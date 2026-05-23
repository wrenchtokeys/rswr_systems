"""
CODE-127: Automated overdue reminders ignored billing_email from CustomerRepairPreference.

Bug:
- _send_overdue_reminder() in billing/tasks.py always sent to customer.email
- ReminderService.send_reminder() and send_payment_confirmation() also used customer.email
- All manual invoice-send paths (saas/views.py) correctly prefer billing_email first
- Fleet customers who configured a dedicated AP billing email never received automated reminders there

Fix:
- _send_overdue_reminder: resolve recipient_email via billing_email or customer.email
- ReminderService.send_reminder: same fallback pattern
- ReminderService.send_payment_confirmation: same fallback pattern
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice, BillingConfig
from core.models import Customer
from apps.customer_portal.models import CustomerRepairPreference


class TestOverdueReminderBillingEmail(TestCase):
    """Test that automated reminders use billing_email when set."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_code127', email='owner127@example.com', password='testpass'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop', slug='test-shop-code127', plan='starter', is_active=True,
            owner=self.owner,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Fleet Co',
            customer_type='FLEET',
            email='fleet-contact@example.com',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-CODE127-001',
            invoice_date=timezone.now().date() - timezone.timedelta(days=40),
            due_date=timezone.now().date() - timezone.timedelta(days=10),
            total=500.00,
            amount_paid=0.00,
            status='OVERDUE',
        )
        self.config = BillingConfig.get_for_tenant(self.tenant)
        self.config.overdue_reminder_enabled = True
        self.config.overdue_reminder_days = '10'
        self.config.overdue_reminder_subject = 'Reminder: Invoice #{invoice_number} is overdue'
        self.config.save()

    # -------------------------------------------------------------------------
    # billing/tasks.py _send_overdue_reminder
    # -------------------------------------------------------------------------

    @patch('apps.billing.tasks.send_mail')
    def test_sends_to_customer_email_when_no_billing_email(self, mock_send):
        """Without billing_email set, reminder goes to customer.email."""
        from apps.billing.tasks import _send_overdue_reminder
        # No CustomerRepairPreference exists
        result = _send_overdue_reminder(self.invoice, self.config, 10)
        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        self.assertIn('fleet-contact@example.com', call_kwargs[1].get('recipient_list', call_kwargs[0][3] if len(call_kwargs[0]) > 3 else []))

    @patch('apps.billing.tasks.send_mail')
    def test_sends_to_billing_email_when_set(self, mock_send):
        """When billing_email is set on CustomerRepairPreference, reminder goes there."""
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            billing_email='ap-department@fleetco.com',
        )
        from apps.billing.tasks import _send_overdue_reminder
        result = _send_overdue_reminder(self.invoice, self.config, 10)
        self.assertTrue(result)
        mock_send.assert_called_once()
        # Extract recipient_list from call
        call_kwargs = mock_send.call_args
        recipient_list = call_kwargs[1].get('recipient_list') or (call_kwargs[0][3] if len(call_kwargs[0]) > 3 else [])
        self.assertIn('ap-department@fleetco.com', recipient_list)
        self.assertNotIn('fleet-contact@example.com', recipient_list)

    @patch('apps.billing.tasks.send_mail')
    def test_falls_back_to_customer_email_when_billing_email_blank(self, mock_send):
        """When billing_email is blank (not None), falls back to customer.email."""
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            billing_email=None,  # None means "use customer.email"
        )
        from apps.billing.tasks import _send_overdue_reminder
        result = _send_overdue_reminder(self.invoice, self.config, 10)
        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        recipient_list = call_kwargs[1].get('recipient_list') or (call_kwargs[0][3] if len(call_kwargs[0]) > 3 else [])
        self.assertIn('fleet-contact@example.com', recipient_list)

    @patch('apps.billing.tasks.send_mail')
    def test_returns_false_when_no_email_at_all(self, mock_send):
        """Returns False (no send) when customer has no email and no billing_email."""
        self.customer.email = ''
        self.customer.save()
        from apps.billing.tasks import _send_overdue_reminder
        result = _send_overdue_reminder(self.invoice, self.config, 10)
        self.assertFalse(result)
        mock_send.assert_not_called()

    # -------------------------------------------------------------------------
    # billing/services/reminder_service.py ReminderService.send_reminder
    # -------------------------------------------------------------------------

    @patch('apps.billing.services.reminder_service.ReminderService._send_email')
    def test_reminder_service_sends_to_billing_email(self, mock_send_email):
        """ReminderService.send_reminder uses billing_email when set."""
        mock_send_email.return_value = True
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            billing_email='billing@fleetco.com',
        )
        from apps.billing.services.reminder_service import ReminderService
        svc = ReminderService(tenant=self.tenant)
        result = svc.send_reminder(self.invoice, reminder_type='overdue')
        self.assertTrue(result.get('success'))
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args
        self.assertEqual(call_kwargs[1].get('to_email') or call_kwargs[0][0], 'billing@fleetco.com')

    @patch('apps.billing.services.reminder_service.ReminderService._send_email')
    def test_reminder_service_falls_back_to_customer_email(self, mock_send_email):
        """ReminderService.send_reminder falls back to customer.email when no billing_email."""
        mock_send_email.return_value = True
        # No CustomerRepairPreference
        from apps.billing.services.reminder_service import ReminderService
        svc = ReminderService(tenant=self.tenant)
        result = svc.send_reminder(self.invoice, reminder_type='overdue')
        self.assertTrue(result.get('success'))
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args
        self.assertEqual(call_kwargs[1].get('to_email') or call_kwargs[0][0], 'fleet-contact@example.com')

    # -------------------------------------------------------------------------
    # billing/services/reminder_service.py ReminderService.send_payment_confirmation
    # -------------------------------------------------------------------------

    @patch('apps.billing.services.reminder_service.ReminderService._send_email')
    def test_payment_confirmation_sends_to_billing_email(self, mock_send_email):
        """ReminderService.send_payment_confirmation uses billing_email when set."""
        mock_send_email.return_value = True
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            billing_email='billing@fleetco.com',
        )
        from apps.billing.services.reminder_service import ReminderService
        from apps.billing.models import Payment
        payment = MagicMock()
        payment.amount = 200.00
        payment.get_payment_method_display.return_value = 'Check'
        payment.payment_date = timezone.now().date()
        svc = ReminderService(tenant=self.tenant)
        result = svc.send_payment_confirmation(self.invoice, payment)
        self.assertTrue(result.get('success'))
        call_kwargs = mock_send_email.call_args
        self.assertEqual(call_kwargs[1].get('to_email') or call_kwargs[0][0], 'billing@fleetco.com')

    @patch('apps.billing.services.reminder_service.ReminderService._send_email')
    def test_payment_confirmation_falls_back_to_customer_email(self, mock_send_email):
        """ReminderService.send_payment_confirmation falls back to customer.email."""
        mock_send_email.return_value = True
        payment = MagicMock()
        payment.amount = 200.00
        payment.get_payment_method_display.return_value = 'Cash'
        payment.payment_date = timezone.now().date()
        from apps.billing.services.reminder_service import ReminderService
        svc = ReminderService(tenant=self.tenant)
        result = svc.send_payment_confirmation(self.invoice, payment)
        self.assertTrue(result.get('success'))
        call_kwargs = mock_send_email.call_args
        self.assertEqual(call_kwargs[1].get('to_email') or call_kwargs[0][0], 'fleet-contact@example.com')
