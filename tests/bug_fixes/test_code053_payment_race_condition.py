"""
Regression tests for CODE-053: Race condition in Payment._update_invoice_totals()

Bug: Payment.save() → _update_invoice_totals() read invoice.payments.aggregate(SUM)
and wrote back invoice.amount_paid without any row-level lock. Two concurrent
payments on the same invoice would both read the same stale aggregate and the
last write would lose one payment, leaving amount_paid under-counted.

Fix: _update_invoice_totals() now wraps the read-aggregate-write in
transaction.atomic() + select_for_update() on the Invoice row, serialising
concurrent saves.

CODE-127: TransactionTestCase.serialized_rollback = True must be set on all
TransactionTestCase classes to prevent them from flushing migration-seeded
NotificationTemplate rows, which would cause subsequent TestCase runs to emit
spurious 'Template not found' errors from notification signals.
"""
import threading
import uuid
from decimal import Decimal

from django.test import TransactionTestCase, TestCase
from django.contrib.auth.models import User

from apps.billing.models import Invoice, Payment
from core.models.notification_template import NotificationTemplate
from apps.customer_portal.models import Customer
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


def _make_tenant():
    slug = f"race-{_uid()}"
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
    return Customer.objects.create(name=f"Customer {_uid()}", tenant=tenant)


def _make_invoice(tenant, customer, total=Decimal("200.00"), status="SENT"):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f"RACE-{_uid()}",
        status=status,
        invoice_date="2026-01-01",
        subtotal=total,
        total=total,
        amount_paid=Decimal("0.00"),
        payment_terms="COD",
    )


class PaymentRaceConditionTestCase(TransactionTestCase):
    """
    TransactionTestCase is required so that database transactions are actually
    committed — regular TestCase wraps everything in one outer transaction that
    prevents select_for_update from working across threads.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.invoice = _make_invoice(self.tenant, self.customer)

    def test_single_payment_updates_amount_paid(self):
        """Baseline: a single payment correctly updates invoice.amount_paid."""
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("100.00"),
            payment_method="CASH",
            recorded_by=self.owner,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("100.00"))

    def test_two_sequential_payments_correct_total(self):
        """Two sequential payments produce the correct total."""
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("75.00"),
            payment_method="CASH",
            recorded_by=self.owner,
        )
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("125.00"),
            payment_method="CHECK",
            recorded_by=self.owner,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("200.00"))
        self.assertEqual(self.invoice.status, "PAID")

    def test_concurrent_payments_do_not_lose_data(self):
        """
        Two threads record payments concurrently. Without the select_for_update
        lock, one payment's write could overwrite the other's and
        amount_paid would be under-counted (100 instead of 200).

        With the fix, both payments are serialised via the row lock and the
        final amount_paid must equal 100 + 100 = 200.
        """
        errors = []

        def record_payment():
            try:
                Payment.objects.create(
                    invoice=self.invoice,
                    amount=Decimal("100.00"),
                    payment_method="CASH",
                    recorded_by=self.owner,
                )
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=record_payment)
        t2 = threading.Thread(target=record_payment)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")

        self.invoice.refresh_from_db()
        # Both payments must be counted
        self.assertEqual(self.invoice.amount_paid, Decimal("200.00"))
        self.assertEqual(
            Payment.objects.filter(invoice=self.invoice).count(),
            2,
            "Both payment records must exist",
        )

    def test_invoice_status_transitions_to_paid(self):
        """Invoice transitions to PAID when amount_paid >= total."""
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("200.00"),
            payment_method="CASH",
            recorded_by=self.owner,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, "PAID")

    def test_invoice_status_partial_when_partially_paid(self):
        """Invoice transitions to PARTIAL when partially paid."""
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("50.00"),
            payment_method="CASH",
            recorded_by=self.owner,
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal("50.00"))
        self.assertEqual(self.invoice.status, "PARTIAL")

    def test_update_invoice_totals_uses_select_for_update(self):
        """
        Verify the implementation actually calls select_for_update() on the
        Invoice row.  We patch Invoice.objects to confirm the method is invoked.
        """
        from unittest.mock import patch

        original_select = Invoice.objects.select_for_update

        called = []

        def tracking_select_for_update(*args, **kwargs):
            called.append(True)
            return original_select(*args, **kwargs)

        with patch.object(Invoice.objects, "select_for_update", side_effect=tracking_select_for_update):
            Payment.objects.create(
                invoice=self.invoice,
                amount=Decimal("10.00"),
                payment_method="OTHER",
                recorded_by=self.owner,
            )

        self.assertTrue(
            len(called) > 0,
            "select_for_update() was not called — race condition fix not active",
        )


class NotificationTemplatesSurviveTransactionCaseFlushTest(TestCase):
    """
    CODE-127: Verify that migration-seeded NotificationTemplate rows are
    present after a TransactionTestCase has run.

    TransactionTestCase flushes the DB between tests.  Without
    ``serialized_rollback = True``, the migration-seeded templates are
    destroyed, and subsequent signal calls log ERROR 'Template not found'.
    This test confirms the templates are visible to regular TestCase runs.
    """

    REQUIRED_TEMPLATES = [
        'repair_assigned',
        'repair_approved',
        'repair_denied',
        'repair_pending_approval',
        'repair_completed',
        'repair_in_progress',
        'repair_reassigned_away',
        'repair_request_received',
        'repair_request_submitted',
        'batch_approved',
    ]

    def test_seeded_notification_templates_are_present(self):
        """All migration-seeded NotificationTemplates must be active after suite runs."""
        for name in self.REQUIRED_TEMPLATES:
            self.assertTrue(
                NotificationTemplate.objects.filter(name=name, active=True).exists(),
                f"NotificationTemplate '{name}' is missing or inactive. "
                f"TransactionTestCase may have flushed migration-seeded data. "
                f"Ensure all TransactionTestCase subclasses set serialized_rollback = True. "
                f"(CODE-127)"
            )
