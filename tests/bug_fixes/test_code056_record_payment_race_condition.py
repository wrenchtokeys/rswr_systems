"""
Regression tests for CODE-056: TOCTOU race condition in owner_record_payment()

Bug: owner_record_payment() read invoice.amount_due BEFORE the transaction, then
created the Payment inside the transaction. Two concurrent POST requests could both
read the same stale amount_due, both pass validation, and both create payments —
resulting in overpayment (total paid > invoice total).

Example:
  Invoice total = $500, amount_paid = $0, amount_due = $500
  Thread A: reads amount_due = $500, check $400 <= $500 → PASS
  Thread B: reads amount_due = $500, check $400 <= $500 → PASS
  Both commit → amount_paid = $800 on a $500 invoice.

Fix: The amount_due validation now happens INSIDE transaction.atomic() after
acquiring a select_for_update() lock on the Invoice row. The second thread
blocks until the first commits, then re-reads the correct (lower) amount_due
and rejects the overpayment with a clear error message.
"""
import threading
import uuid
from decimal import Decimal

from django.test import TestCase, TransactionTestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.billing.models import Invoice, Payment
from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan


def _uid():
    return uuid.uuid4().hex[:8]


def _make_plan():
    slug = f"plan-{_uid()}"
    return SubscriptionPlan.objects.create(
        name=slug,
        slug=slug,
        monthly_price=Decimal("49.00"),
        annual_price=Decimal("490.00"),
    )


def _make_tenant_with_owner():
    slug = f"shop-{_uid()}"
    plan = _make_plan()
    owner = User.objects.create_user(username=f"owner_{slug}", password="pw")
    tenant = Tenant.objects.create(
        name=f"Shop {slug}",
        slug=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role="owner", is_active=True)
    return tenant, owner


def _make_customer(tenant):
    return Customer.objects.create(
        name=f"Fleet Co {_uid()}",
        tenant=tenant,
        customer_type="FLEET",
    )


def _make_invoice(customer, tenant, total=Decimal("500.00")):
    return Invoice.objects.create(
        customer=customer,
        tenant=tenant,
        invoice_number=f"INV-{_uid()}",
        subtotal=total,
        total=total,
        amount_paid=Decimal("0.00"),
        status="SENT",
    )


# ---------------------------------------------------------------------------
# Unit-level tests (no HTTP, just view logic via Django test client)
# ---------------------------------------------------------------------------

class RecordPaymentValidationTests(TestCase):
    """
    Functional tests: correct validation, success, and error paths for
    owner_record_payment() view. These use TestCase (fast, single-threaded).
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner()
        self.customer = _make_customer(self.tenant)
        self.invoice = _make_invoice(self.customer, self.tenant, total=Decimal("300.00"))
        self.client = Client()
        self.client.force_login(self.owner)
        # Attach tenant to middleware (session-based fallback used by _get_owner_tenant)
        session = self.client.session
        session["tenant_id"] = self.tenant.id
        session.save()

    def _post_payment(self, amount, method="CASH"):
        return self.client.post(
            reverse("owner_record_payment", kwargs={"invoice_id": self.invoice.id}),
            data={
                "amount": str(amount),
                "payment_method": method,
                "payment_date": "2026-03-17",
                "reference_number": "",
                "notes": "",
            },
        )

    def test_valid_payment_recorded(self):
        """Normal payment within amount_due succeeds."""
        resp = self._post_payment(Decimal("100.00"))
        self.assertEqual(resp.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("100.00"))
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)

    def test_exact_amount_due_succeeds(self):
        """Payment equal to amount_due fully pays the invoice."""
        resp = self._post_payment(Decimal("300.00"))
        self.assertEqual(resp.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("300.00"))
        self.assertEqual(self.invoice.status, "PAID")

    def test_overpayment_rejected(self):
        """Payment exceeding amount_due is rejected with a user-visible error."""
        resp = self._post_payment(Decimal("400.00"))
        self.assertEqual(resp.status_code, 302)
        # No payment should have been created
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 0)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("0.00"))

    def test_zero_amount_rejected(self):
        """Zero-amount payment is rejected early (before the transaction)."""
        resp = self._post_payment(Decimal("0.00"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 0)

    def test_paid_invoice_rejects_payment_inside_lock(self):
        """
        If the invoice is already PAID (set concurrently), the locked re-check
        inside the transaction rejects the new payment.
        """
        self.invoice.status = "PAID"
        self.invoice.amount_paid = Decimal("300.00")
        self.invoice.save()
        resp = self._post_payment(Decimal("50.00"))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 0)

    def test_sequential_payments_accumulate_correctly(self):
        """Two sequential payments sum correctly without overpayment."""
        self._post_payment(Decimal("100.00"))
        self._post_payment(Decimal("100.00"))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("200.00"))
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 2)

    def test_second_payment_cannot_exceed_remaining_balance(self):
        """
        After first payment, second payment for the original full amount is rejected
        by the inside-lock check (amount_due is now lower).
        """
        # Record $200
        self._post_payment(Decimal("200.00"))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_due, Decimal("100.00"))
        # Try to record $200 again (would overpay by $100)
        self._post_payment(Decimal("200.00"))
        self.invoice.refresh_from_db()
        # Only the first payment should exist
        self.assertEqual(self.invoice.amount_paid, Decimal("200.00"))
        self.assertEqual(Payment.objects.filter(invoice=self.invoice).count(), 1)


# ---------------------------------------------------------------------------
# Concurrency test (TransactionTestCase — no test-transaction wrapping)
# ---------------------------------------------------------------------------

class RecordPaymentConcurrentRaceTest(TransactionTestCase):
    """
    Threading test: two concurrent payment POSTs on the same invoice must
    not both succeed when together they would exceed amount_due.

    Before the fix: both threads read amount_due = $500, both pass validation,
    both commit → $800 recorded on a $500 invoice.

    After the fix: the second thread acquires the row lock AFTER the first
    commits, re-reads amount_due = $100 (only $100 left), $400 > $100 → rejected.
    """

    def test_concurrent_payments_cannot_overpay(self):
        tenant, owner = _make_tenant_with_owner()
        customer = _make_customer(tenant)
        invoice = _make_invoice(customer, tenant, total=Decimal("500.00"))

        errors = []
        responses = []
        lock = threading.Lock()

        def record_payment(amount):
            client = Client()
            client.force_login(owner)
            session = client.session
            session["tenant_id"] = tenant.id
            session.save()
            try:
                resp = client.post(
                    reverse("owner_record_payment", kwargs={"invoice_id": invoice.id}),
                    data={
                        "amount": str(amount),
                        "payment_method": "CASH",
                        "payment_date": "2026-03-17",
                        "reference_number": "",
                        "notes": "",
                    },
                )
                with lock:
                    responses.append(resp.status_code)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # Both threads attempt to pay $400 on a $500 invoice.
        # Together they total $800 — only one should succeed.
        t1 = threading.Thread(target=record_payment, args=(Decimal("400.00"),))
        t2 = threading.Thread(target=record_payment, args=(Decimal("400.00"),))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertFalse(errors, f"Unexpected thread errors: {errors}")

        invoice.refresh_from_db()
        total_paid = invoice.amount_paid
        total_payments = Payment.objects.filter(invoice=invoice).count()

        # Total paid must never exceed the invoice total
        self.assertLessEqual(
            total_paid,
            invoice.total,
            f"Overpayment detected: amount_paid={total_paid} > invoice.total={invoice.total}",
        )
        # Exactly one payment should have been created (the second was blocked)
        self.assertEqual(
            total_payments,
            1,
            f"Expected 1 payment, got {total_payments} (concurrent overpayment not blocked)",
        )
        self.assertEqual(total_paid, Decimal("400.00"))
