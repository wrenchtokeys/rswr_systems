"""
Regression tests for CODE-179:
_send_overdue_reminder() NameError when generate_payment_token is unavailable.

Bug: pay_url was only assigned inside the try block. If generate_payment_token
raises any exception, pay_url is never defined. The send_branded_email call
below then raises NameError, which is caught by the outer try/except and
causes _send_overdue_reminder to return False — silently dropping ALL overdue
reminder emails.

Fix: initialise pay_url = None before the try block so the email is still
sent (without a pay button) even when token generation fails.
"""

from unittest.mock import patch, MagicMock
from decimal import Decimal
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from django.contrib.auth.models import User


class OverdueReminderPayUrlTest(TestCase):
    """Tests that overdue reminder emails are sent even when pay token fails."""

    def setUp(self):
        # Create a minimal tenant + customer + invoice for testing
        self.owner = User.objects.create_user(
            username='code179_owner',
            email='code179_owner@example.com',
            password='testpass123',
        )
        self.tenant = Tenant.objects.create(
            name='CODE-179 Test Shop',
            slug='code179-test-shop',
            owner=self.owner,
            plan='pro',
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
            is_active=True,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Overdue Corp',
            email='overdue@example.com',
        )
        # BillingConfig is created lazily by get_for_tenant
        self.config = BillingConfig.get_for_tenant(self.tenant)
        self.config.overdue_reminder_enabled = True
        self.config.overdue_reminder_days = '7'
        self.config.overdue_reminder_subject = 'Invoice {invoice_number} is overdue'
        self.config.save()

        # Create an overdue invoice
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-CODE179-001',
            invoice_date=date.today() - timedelta(days=37),
            due_date=date.today() - timedelta(days=7),
            status='OVERDUE',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
        )

    @patch('core.email_utils.send_branded_email', return_value=1)
    def test_reminder_sent_when_token_generation_raises_import_error(self, mock_send_email):
        """Even if generate_payment_token raises ImportError, the email is still sent."""
        from apps.billing.tasks import _send_overdue_reminder
        import sys
        # Temporarily make rs_systems.views unimportable so the try block raises ImportError
        with patch.dict(sys.modules, {'rs_systems.views': None}):
            result = _send_overdue_reminder(self.invoice, self.config, days_overdue=7)
        self.assertTrue(result, "Expected _send_overdue_reminder to return True when token import fails")
        mock_send_email.assert_called_once()

    @patch('core.email_utils.send_branded_email', return_value=1)
    def test_reminder_sent_when_token_generation_raises_generic_exception(self, mock_send_email):
        """Even if generate_payment_token raises a generic Exception, the email is still sent."""
        from apps.billing.tasks import _send_overdue_reminder
        import sys
        # Make the module importable but make generate_payment_token raise
        mock_views = MagicMock()
        mock_views.generate_payment_token = MagicMock(side_effect=Exception('unexpected'))
        with patch.dict(sys.modules, {'rs_systems.views': mock_views}):
            result = _send_overdue_reminder(self.invoice, self.config, days_overdue=7)
        self.assertTrue(result)
        mock_send_email.assert_called_once()

    @patch('core.email_utils.send_branded_email', return_value=1)
    def test_reminder_sent_with_pay_button_when_token_succeeds(self, mock_send_email):
        """When token generation succeeds, the pay button URL is passed to send_branded_email."""
        from apps.billing.tasks import _send_overdue_reminder
        import sys
        mock_views = MagicMock()
        mock_views.generate_payment_token = MagicMock(return_value='test-token-abc')
        with patch.dict(sys.modules, {'rs_systems.views': mock_views}):
            result = _send_overdue_reminder(self.invoice, self.config, days_overdue=7)
        self.assertTrue(result)
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        # button_url and button_text should be populated when token is available
        self.assertIn('/pay/', call_kwargs.get('button_url', ''))
        self.assertIsNotNone(call_kwargs.get('button_text'))

    @patch('core.email_utils.send_branded_email', return_value=1)
    def test_reminder_sent_without_pay_button_when_token_fails(self, mock_send_email):
        """When token generation fails, button_url/button_text are None (no pay button)."""
        from apps.billing.tasks import _send_overdue_reminder
        import sys
        mock_views = MagicMock()
        mock_views.generate_payment_token = MagicMock(side_effect=AttributeError('no attr'))
        with patch.dict(sys.modules, {'rs_systems.views': mock_views}):
            result = _send_overdue_reminder(self.invoice, self.config, days_overdue=7)
        self.assertTrue(result)
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertIsNone(call_kwargs.get('button_url'))
        self.assertIsNone(call_kwargs.get('button_text'))

    @patch('core.email_utils.send_branded_email', return_value=1)
    def test_no_nameerror_when_pay_url_not_set(self, mock_send_email):
        """The original bug: NameError when pay_url was not defined. Ensure no NameError is raised."""
        from apps.billing.tasks import _send_overdue_reminder
        import sys
        # Simulate failure: rs_systems.views is unimportable
        with patch.dict(sys.modules, {'rs_systems.views': None}):
            # This should NOT raise NameError
            try:
                _send_overdue_reminder(self.invoice, self.config, days_overdue=7)
            except NameError as e:
                self.fail(f"NameError raised in _send_overdue_reminder: {e}")
