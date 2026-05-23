"""
Regression tests for CODE-098:
  owner_send_invoice() in apps/saas/views.py was stamping status='SENT' + sent_at
  BEFORE attempting email delivery. If SMTP was down or the customer had no email,
  the invoice showed 'SENT' in the owner dashboard but the customer never received it.

  This is the fourth recurrence of the SENT-before-email pattern:
    CODE-094 — AutoInvoiceService
    CODE-095 — _create_batch_invoice() in tasks.py
    CODE-096 — InvoiceTrackingService.create_invoice_from_repairs()
    CODE-098 — owner_send_invoice() view (this fix)

  Fix:
    - Attempt email delivery first (before saving status change).
    - Only after email attempt: stamp status='SENT' + sent_at regardless of email
      result (owner manually triggered this, so we always mark sent).
    - If email failed → show messages.warning so owner knows to follow up.
    - If email succeeded → show messages.success.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.technician_portal.models import Repair, Technician
from apps.billing.models import Invoice, InvoiceLineItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(name='Send Invoice Shop'):
    owner = User.objects.create_user(
        username=f'owner_si_{User.objects.count()}',
        email=f'owner_si_{User.objects.count()}@example.com',
        password='testpass123',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=f'send-inv-{Tenant.objects.count()}',
        plan='trial',
        owner=owner,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_customer(tenant, email='customer@example.com'):
    return Customer.objects.create(
        tenant=tenant,
        name='Test Fleet',
        email=email,
    )


def _make_technician(tenant):
    u = User.objects.create_user(
        username=f'tech_si_{User.objects.count()}',
        email=f'tech_si_{User.objects.count()}@example.com',
        password='pass',
    )
    return Technician.objects.create(tenant=tenant, user=u, is_active=True)


def _make_draft_invoice(tenant, customer):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-TEST-{Invoice.objects.count():04d}',
        invoice_date=timezone.now().date(),
        subtotal=Decimal('100.00'),
        tax_amount=Decimal('0.00'),
        total=Decimal('100.00'),
        amount_paid=Decimal('0.00'),
        status='DRAFT',
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class OwnerSendInvoiceEmailOrderTest(TestCase):
    """
    CODE-098: owner_send_invoice() must NOT stamp status SENT before email attempt.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.client = Client()
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_send(self, invoice_id):
        return self.client.post(
            reverse('owner_send_invoice', kwargs={'invoice_id': invoice_id}),
            follow=True,
        )

    def test_invoice_marked_sent_even_when_email_fails(self):
        """
        When email delivery fails, the invoice must still be marked SENT
        (owner manually triggered the action), but a warning message is shown.
        """
        invoice = _make_draft_invoice(self.tenant, self.customer)

        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
            return_value=(False, 'SMTP connection refused'),
        ):
            response = self._post_send(invoice.id)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT', "Invoice should be SENT even when email fails (manual trigger)")
        self.assertIsNotNone(invoice.sent_at)

        # Should show a warning, not a success, so owner knows email failed
        messages = list(response.context['messages'])
        has_warning = any(
            'warning' in m.tags or 'email delivery failed' in m.message.lower()
            or 'email' in m.message.lower()
            for m in messages
        )
        self.assertTrue(has_warning, f"Expected warning about email failure, got: {[m.message for m in messages]}")

    def test_invoice_marked_sent_with_success_when_email_succeeds(self):
        """
        When email delivery succeeds, the invoice is marked SENT and a success
        message is shown.
        """
        invoice = _make_draft_invoice(self.tenant, self.customer)

        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
            return_value=(True, 'Sent OK'),
        ):
            response = self._post_send(invoice.id)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')
        self.assertIsNotNone(invoice.sent_at)

        messages = list(response.context['messages'])
        has_success = any('success' in m.tags for m in messages)
        self.assertTrue(has_success, f"Expected success message, got: {[m.message for m in messages]}")

    def test_cannot_resend_already_sent_invoice(self):
        """
        owner_send_invoice() must reject non-DRAFT invoices with an error.
        """
        invoice = _make_draft_invoice(self.tenant, self.customer)
        invoice.status = 'SENT'
        invoice.sent_at = timezone.now()
        invoice.save()

        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        ) as mock_email:
            self._post_send(invoice.id)

        mock_email.assert_not_called()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')  # unchanged

    def test_email_not_called_on_non_draft_invoice(self):
        """
        Email service must never be called when the invoice is not DRAFT.
        Guard against double-send scenarios.
        """
        invoice = _make_draft_invoice(self.tenant, self.customer)
        invoice.status = 'OVERDUE'
        invoice.save()

        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        ) as mock_email:
            response = self._post_send(invoice.id)

        mock_email.assert_not_called()

    def test_invoice_from_different_tenant_returns_404(self):
        """
        owner_send_invoice() must scope invoice lookup to the owner's tenant.
        A different shop's invoice should return 404.
        """
        other_tenant, other_owner = _make_tenant('Other Shop')
        other_customer = _make_customer(other_tenant, email='other@example.com')
        other_invoice = _make_draft_invoice(other_tenant, other_customer)

        response = self.client.post(
            reverse('owner_send_invoice', kwargs={'invoice_id': other_invoice.id}),
            follow=True,
        )
        # Should 404 (can't access another tenant's invoice)
        self.assertEqual(response.status_code, 404)
        other_invoice.refresh_from_db()
        self.assertEqual(other_invoice.status, 'DRAFT', "Cross-tenant invoice must not be modified")
