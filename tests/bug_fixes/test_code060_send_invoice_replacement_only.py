"""
Regression tests for CODE-060:
  owner_send_invoice() silently skipped email for replacement-only invoices
  while still marking the invoice SENT.

Root cause:
    owner_send_invoice() gated the send_invoice_email() call on:
        if repair_ids:
            ...send email...
        else:
            logger.warning(...)   # silently skipped!
    But the invoice was already marked SENT BEFORE this check.  Any invoice
    whose line items have only replacement FKs (no repair FK) — i.e. windshield
    replacement batch invoices created by billing/tasks.py — would:
      1. Be permanently marked SENT (owner can't undo without manual DB edit)
      2. Never deliver an email to the customer
      3. Show an ambiguous "marked as sent" success message to the owner

    owner_email_invoice() (the resend path) already handled this correctly
    by passing `repair_ids if repair_ids else None`.  owner_send_invoice()
    was inconsistent.

Fix:
    Replace `if repair_ids: ... else: logger.warning(...)` with a single
    send_invoice_email(..., repair_ids=repair_ids if repair_ids else None).
    This matches owner_email_invoice() and the service's own fallback logic.

Tests verify:
1. Repair-only invoice: send_invoice_email called with repair_ids list.
2. Replacement-only invoice: send_invoice_email called with repair_ids=None
   (not skipped).
3. Mixed invoice: send_invoice_email called with the repair IDs only
   (same as before — replacement line items have no repair id to pass).
4. Invoice is marked SENT when the email succeeds.
5. Failed email leaves the invoice DRAFT (CODE-112: only mark SENT on delivery).
6. send_invoice_email not called when invoice has no recipient email.
"""

from decimal import Decimal
from datetime import date
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice, InvoiceLineItem
from apps.technician_portal.models import Technician

from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(name="TestShop60"):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial",
        defaults={
            "name": "Trial",
            "monthly_price": 0,
            "annual_price": 0,
            "max_customers": 50,
            "max_technicians": 5,
        }
    )
    return Tenant.objects.create(
        name=name, slug=name.lower().replace(" ", "-"),
        owner=User.objects.create_user(
            username=f"owner_{name.lower().replace(' ', '_')}",
            password="testpass",
            email=f"owner_{name.lower().replace(' ', '_')}@example.com",
        ),
        subscription_plan=plan,
        is_active=True,
    )


def _make_owner_client(tenant):
    client = Client()
    client.force_login(tenant.owner)
    TenantMembership.objects.get_or_create(
        user=tenant.owner,
        tenant=tenant,
        defaults={"role": "owner", "is_active": True},
    )
    return client


def _make_customer(tenant, name="Fleet Co", email="fleet@example.com"):
    return Customer.objects.create(
        tenant=tenant, name=name, email=email, phone="555-0100",
    )


def _make_technician(tenant):
    user = User.objects.create_user(
        username=f"tech_{tenant.slug}_{User.objects.count()}",
        password="testpass",
        email=f"tech_{User.objects.count()}@example.com",
    )
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_active=True,
    )


def _make_invoice(tenant, customer, status="DRAFT"):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number="INV-60-001",
        invoice_date=date.today(),
        due_date=date.today(),
        status=status,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class SendInvoiceReplacementOnlyTests(TestCase):
    """
    owner_send_invoice() must call send_invoice_email() even when the invoice
    has no repair line items (replacement-only invoice).
    """

    def setUp(self):
        self.tenant = _make_tenant("ShopSendTest60")
        self.customer = _make_customer(self.tenant)
        self.technician = _make_technician(self.tenant)
        self.client = _make_owner_client(self.tenant)
        # Ensure the session picks up the tenant
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_send(self, invoice_id):
        return self.client.post(
            reverse('owner_send_invoice', kwargs={'invoice_id': invoice_id}),
            follow=False,
        )

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_repair_only_invoice_calls_email_with_repair_ids(self, mock_send):
        """Repair-only invoice: send_invoice_email called with the repair IDs."""
        from apps.technician_portal.models import Repair
        mock_send.return_value = (True, "ok")

        invoice = _make_invoice(self.tenant, self.customer)
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            unit_number="U1", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("50.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, repair=repair,
            description="Repair", quantity=1,
            unit_price=Decimal("50.00"), amount=Decimal("50.00"),
        )

        self._post_send(invoice.id)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        # Since A4, owner_send_invoice passes the Invoice record itself and
        # the service renders the invoice's OWN line items (repair-backed
        # ones included) — the repair_ids plumbing this test originally
        # asserted is gone. The CODE-060 invariant (email is attempted, not
        # silently skipped) is unchanged.
        self.assertEqual(call_kwargs.get('invoice'), invoice)

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_replacement_only_invoice_calls_email_with_none(self, mock_send):
        """
        Replacement-only invoice: send_invoice_email must still be called
        (with repair_ids=None, not skipped entirely).
        """
        from apps.technician_portal.models import Replacement
        mock_send.return_value = (True, "ok")

        invoice = _make_invoice(self.tenant, self.customer)
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            unit_number="U2", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("100.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, replacement=replacement,
            description="Replacement", quantity=1,
            unit_price=Decimal("100.00"), amount=Decimal("100.00"),
        )

        self._post_send(invoice.id)

        # CRITICAL: email service must be called — not silently skipped
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        # repair_ids should be None (fallback to time-window scan)
        self.assertIsNone(call_kwargs.get('repair_ids'))

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_replacement_only_invoice_marked_sent_after_email_attempt(self, mock_send):
        """Invoice is marked SENT even if email succeeds (and vice versa)."""
        from apps.technician_portal.models import Replacement
        mock_send.return_value = (True, "ok")

        invoice = _make_invoice(self.tenant, self.customer)
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            unit_number="U3", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("100.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, replacement=replacement,
            description="Replacement", quantity=1,
            unit_price=Decimal("100.00"), amount=Decimal("100.00"),
        )

        self._post_send(invoice.id)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_invoice_stays_draft_when_email_fails(self, mock_send):
        """
        CODE-112 semantics: if send_invoice_email() returns (False, ...),
        the invoice stays DRAFT so the owner knows it never went out and
        can retry. (This test originally asserted the retired pre-CODE-112
        behavior of marking SENT regardless.)
        """
        from apps.technician_portal.models import Replacement
        mock_send.return_value = (False, "smtp error")

        invoice = _make_invoice(self.tenant, self.customer)
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            unit_number="U4", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("100.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, replacement=replacement,
            description="Replacement", quantity=1,
            unit_price=Decimal("100.00"), amount=Decimal("100.00"),
        )

        self._post_send(invoice.id)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'DRAFT',
                         "Invoice must stay DRAFT when email delivery fails (CODE-112)")

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_mixed_invoice_calls_email_with_repair_ids_only(self, mock_send):
        """
        Mixed invoice (repairs + replacements): send_invoice_email called
        with only the repair IDs (replacements have no repair_id to pass).
        """
        from apps.technician_portal.models import Repair, Replacement
        mock_send.return_value = (True, "ok")

        invoice = _make_invoice(self.tenant, self.customer)

        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            unit_number="U5", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("50.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, repair=repair,
            description="Repair", quantity=1,
            unit_price=Decimal("50.00"), amount=Decimal("50.00"),
        )

        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            unit_number="U5", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("50.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, replacement=replacement,
            description="Replacement", quantity=1,
            unit_price=Decimal("50.00"), amount=Decimal("50.00"),
        )

        self._post_send(invoice.id)

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        # Since A4 the whole Invoice record is passed; the service renders
        # ALL of the invoice's own line items (repair + replacement) — see
        # test_repair_only_invoice_calls_email_with_repair_ids.
        self.assertEqual(call_kwargs.get('invoice'), invoice)

    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_no_email_when_no_recipient(self, mock_send):
        """
        If the customer has no email, send_invoice_email should NOT be called
        (no address to send to).
        """
        from apps.technician_portal.models import Replacement
        # Customer with no email
        no_email_customer = Customer.objects.create(
            tenant=self.tenant, name="No Email Co", email="",
        )
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=no_email_customer,
            invoice_number="INV-60-NO-EMAIL",
            invoice_date=date.today(),
            due_date=date.today(),
            status="DRAFT",
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
        )
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=no_email_customer,
            unit_number="U6", queue_status="COMPLETED",
            technician=self.technician,
            cost=Decimal("100.00"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, replacement=replacement,
            description="Replacement", quantity=1,
            unit_price=Decimal("100.00"), amount=Decimal("100.00"),
        )

        self._post_send(invoice.id)

        # send_invoice_email should not be called (no recipient email)
        mock_send.assert_not_called()
