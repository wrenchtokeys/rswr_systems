"""
CODE-128: owner_send_reminder() used customer.email for guard and success message.

Bug:
- owner_send_reminder() checked `if not invoice.customer.email:` to block reminders.
- A fleet customer who has ONLY a billing_email on CustomerRepairPreference (no
  customer.email) would get "No email address found" error and the reminder would
  never be sent — even though ReminderService.send_reminder() could deliver it.
- The success message showed `invoice.customer.email` instead of the actual
  recipient address, so the owner saw the wrong email in their confirmation toast.

Fix:
- Resolve recipient email before the guard: prefer prefs.billing_email or customer.email
- Check the resolved address (not customer.email directly) for the no-email guard
- Show resolved address in the success message so owner sees where it actually went
"""

from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, BillingConfig
from core.models import Customer
from apps.customer_portal.models import CustomerRepairPreference


def _make_request_with_messages(user, tenant, data=None):
    """Helper: authenticated POST request with tenant + message middleware."""
    factory = RequestFactory()
    request = factory.post('/owner/invoices/1/reminder/', data or {})
    request.user = user
    request.tenant = tenant
    setattr(request, 'session', {})
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)
    return request


class OwnerSendReminderBillingEmailTest(TestCase):
    """Tests for CODE-128: owner_send_reminder billing_email guard and success message."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_code128', email='owner128@example.com', password='pass'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 128', slug='test-shop-128', plan='starter', is_active=True,
            owner=self.owner,
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True,
        )
        self.customer_with_email = Customer.objects.create(
            tenant=self.tenant, name='Regular Fleet', email='fleet@example.com',
        )
        # billing_only: no customer.email — use None to avoid unique constraint on ''
        self.customer_billing_only = Customer.objects.create(
            tenant=self.tenant, name='AP-Only Fleet', email=None,
        )
        # no_email: will be cleared in the specific test
        self.customer_no_email = Customer.objects.create(
            tenant=self.tenant, name='No Email Fleet', email='placeholder128@example.com',
        )
        BillingConfig.get_for_tenant(self.tenant)

        today = timezone.now().date()
        self.invoice_sent = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer_with_email,
            invoice_number='INV-128-001',
            invoice_date=today - timezone.timedelta(days=10),
            due_date=today + timezone.timedelta(days=5),
            total=300.00,
            amount_paid=0.00,
            status='SENT',
        )
        self.invoice_billing_only = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer_billing_only,
            invoice_number='INV-128-002',
            invoice_date=today - timezone.timedelta(days=10),
            due_date=today + timezone.timedelta(days=5),
            total=200.00,
            amount_paid=0.00,
            status='SENT',
        )
        self.invoice_no_email = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer_no_email,
            invoice_number='INV-128-003',
            invoice_date=today - timezone.timedelta(days=10),
            due_date=today + timezone.timedelta(days=5),
            total=100.00,
            amount_paid=0.00,
            status='SENT',
        )

    # -------------------------------------------------------------------------
    # Customer with only customer.email (no billing_email) — baseline
    # -------------------------------------------------------------------------

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_sends_reminder_to_customer_email(self, mock_send):
        """Reminder is sent to customer.email when no billing_email exists."""
        mock_send.return_value = {'success': True}
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, self.invoice_sent.id)

        mock_send.assert_called_once()
        msgs = list(request._messages)
        self.assertTrue(
            any('fleet@example.com' in str(m) for m in msgs),
            f"Expected fleet@example.com in messages, got: {[str(m) for m in msgs]}"
        )

    # -------------------------------------------------------------------------
    # Customer with billing_email only (no customer.email)
    # -------------------------------------------------------------------------

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_sends_reminder_to_billing_email_when_no_customer_email(self, mock_send):
        """
        BUG: customer.email is empty but billing_email is set.
        Pre-fix: guard checked customer.email → blocked with 'No email address found'.
        Post-fix: guard checks resolved address (billing_email) → reminder goes through.
        """
        CustomerRepairPreference.objects.create(
            customer=self.customer_billing_only,
            billing_email='ap@apfleet.com',
        )
        mock_send.return_value = {'success': True}
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, self.invoice_billing_only.id)

        # Should NOT block with 'No email address found'
        msgs = list(request._messages)
        msg_texts = [str(m) for m in msgs]
        self.assertFalse(
            any('No email address found' in t for t in msg_texts),
            f"Should not block when billing_email is set, got: {msg_texts}"
        )
        # ReminderService.send_reminder() should have been called
        mock_send.assert_called_once()

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_success_message_shows_billing_email_not_customer_email(self, mock_send):
        """
        BUG: success message used invoice.customer.email.
        Post-fix: message shows the actual recipient (billing_email when set).
        """
        CustomerRepairPreference.objects.create(
            customer=self.customer_with_email,
            billing_email='accounts-payable@fleet.com',
        )
        mock_send.return_value = {'success': True}
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, self.invoice_sent.id)

        msgs = list(request._messages)
        msg_texts = [str(m) for m in msgs]
        # Should mention billing_email
        self.assertTrue(
            any('accounts-payable@fleet.com' in t for t in msg_texts),
            f"Expected billing email in message, got: {msg_texts}"
        )
        # Should NOT show the old customer.email in the success message
        self.assertFalse(
            any('fleet@example.com' in t for t in msg_texts),
            f"Should show billing_email, not customer.email, got: {msg_texts}"
        )

    # -------------------------------------------------------------------------
    # Customer with neither email (should still block with clear error)
    # -------------------------------------------------------------------------

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_blocks_when_no_email_at_all(self, mock_send):
        """When both customer.email and billing_email are empty, show error."""
        # Clear the placeholder email
        self.customer_no_email.email = ''
        self.customer_no_email.save()
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, self.invoice_no_email.id)

        msgs = list(request._messages)
        msg_texts = [str(m) for m in msgs]
        self.assertTrue(
            any('No email address found' in t for t in msg_texts),
            f"Expected 'No email' message, got: {msg_texts}"
        )
        mock_send.assert_not_called()

    # -------------------------------------------------------------------------
    # Status guards still work
    # -------------------------------------------------------------------------

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_blocks_paid_invoice(self, mock_send):
        """Cannot send reminder for PAID invoice."""
        paid_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer_with_email,
            invoice_number='INV-128-PAID',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total=100.00,
            amount_paid=100.00,
            status='PAID',
        )
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, paid_invoice.id)

        mock_send.assert_not_called()
        msgs = list(request._messages)
        self.assertTrue(any('paid' in str(m).lower() for m in msgs))

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_blocks_draft_invoice(self, mock_send):
        """Cannot send reminder for DRAFT invoice."""
        draft_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer_with_email,
            invoice_number='INV-128-DRAFT',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            total=100.00,
            amount_paid=0.00,
            status='DRAFT',
        )
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, draft_invoice.id)

        mock_send.assert_not_called()

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_handles_reminder_service_failure(self, mock_send):
        """When ReminderService returns failure, show error message."""
        mock_send.return_value = {'success': False, 'error': 'SMTP error'}
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, self.invoice_sent.id)

        msgs = list(request._messages)
        msg_texts = [str(m) for m in msgs]
        self.assertTrue(
            any('Failed' in t or 'SMTP' in t for t in msg_texts),
            f"Expected failure message, got: {msg_texts}"
        )

    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_billing_email_takes_priority_over_customer_email(self, mock_send):
        """When both customer.email and billing_email are set, billing_email wins."""
        CustomerRepairPreference.objects.create(
            customer=self.customer_with_email,
            billing_email='billing@fleet-ap.com',
        )
        mock_send.return_value = {'success': True}
        request = _make_request_with_messages(self.owner, self.tenant)

        from apps.saas.views import owner_send_reminder
        owner_send_reminder(request, self.invoice_sent.id)

        msgs = list(request._messages)
        msg_texts = [str(m) for m in msgs]
        # billing_email should appear in success
        self.assertTrue(
            any('billing@fleet-ap.com' in t for t in msg_texts),
            f"Expected billing email in message, got: {msg_texts}"
        )
        # customer.email should NOT appear
        self.assertFalse(
            any('fleet@example.com' in t for t in msg_texts),
            f"Should show billing_email, not customer.email, got: {msg_texts}"
        )
