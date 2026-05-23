"""
Tests for CODE-139: _send_batch_invoice_email() used customer.email instead
of CustomerRepairPreference.billing_email.

Bug:
    _send_batch_invoice_email() in apps/billing/tasks.py had two flaws:
    1. The early-return guard checked `if not customer.email` — so fleet
       customers with a dedicated AP billing_email but no customer.email were
       silently skipped (batch invoices never sent).
    2. The send_mail() call used `recipient_list=[customer.email]` even when
       CustomerRepairPreference.billing_email was set — so invoices went to
       the wrong inbox.

    All other invoice/reminder send paths correctly prefer billing_email:
    - _send_overdue_reminder()         (fixed in CODE-127)
    - owner_send_reminder()            (fixed in CODE-128)
    - owner_send_invoice()             (uses repair_preferences.billing_email)
    - owner_email_invoice()            (uses repair_preferences.billing_email)
    The batch task was the only path that was missed.

Fix:
    Resolve recipient_email using CustomerRepairPreference.billing_email with
    fallback to customer.email — matching the pattern in _send_overdue_reminder.
    Use recipient_email in both the guard check and the send_mail() call.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice, BillingConfig
from apps.customer_portal.models import CustomerRepairPreference
from core.models import Customer

User = get_user_model()


def _make_tenant(name='Shop A'):
    owner = User.objects.create_user(username=f'owner_{name}', password='pw')
    plan = SubscriptionPlan.objects.filter(slug='starter').first()
    tenant = Tenant.objects.create(
        name=name, slug=name.lower().replace(' ', '-'),
        owner=owner, is_active=True,
    )
    if plan:
        tenant.subscription_plan = plan
    tenant.subscription_status = 'active'
    tenant.save()
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    BillingConfig.objects.create(
        tenant=tenant,
        company_name=name,
        invoice_email_template='',
    )
    return tenant, owner


def _make_customer(tenant, name='EOS Trucking', email=None):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=email,
    )


def _make_invoice(customer, tenant):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number='INV-001',
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        status='DRAFT',
    )


class BatchInvoiceBillingEmailTest(TestCase):
    """Verify _send_batch_invoice_email resolves billing_email over customer.email."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Fleet Shop')
        self.config = BillingConfig.get_for_tenant(self.tenant)

    # ------------------------------------------------------------------
    # 1. Sends to billing_email when both billing_email and customer.email exist
    # ------------------------------------------------------------------
    @patch('apps.billing.tasks.send_mail')
    def test_prefers_billing_email_over_customer_email(self, mock_send):
        """When billing_email is set, invoice goes to billing_email, not customer.email."""
        from apps.billing.tasks import _send_batch_invoice_email

        mock_send.return_value = 1
        customer = _make_customer(self.tenant, email='general@eos.com')
        CustomerRepairPreference.objects.create(
            customer=customer,
            billing_email='ap@eos.com',  # dedicated AP email
        )
        invoice = _make_invoice(customer, self.tenant)

        result = _send_batch_invoice_email(invoice, self.config)

        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        recipient_list = (
            call_kwargs.kwargs.get('recipient_list')
            or call_kwargs.args[3]  # positional arg position
        )
        self.assertIn('ap@eos.com', recipient_list)
        self.assertNotIn('general@eos.com', recipient_list)

    # ------------------------------------------------------------------
    # 2. Falls back to customer.email when billing_email is empty
    # ------------------------------------------------------------------
    @patch('apps.billing.tasks.send_mail')
    def test_falls_back_to_customer_email(self, mock_send):
        """When billing_email is blank, customer.email is used as fallback."""
        from apps.billing.tasks import _send_batch_invoice_email

        mock_send.return_value = 1
        customer = _make_customer(self.tenant, email='contact@fleet.com')
        CustomerRepairPreference.objects.create(
            customer=customer,
            billing_email='',  # not configured
        )
        invoice = _make_invoice(customer, self.tenant)

        result = _send_batch_invoice_email(invoice, self.config)

        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        recipient_list = (
            call_kwargs.kwargs.get('recipient_list')
            or call_kwargs.args[3]
        )
        self.assertIn('contact@fleet.com', recipient_list)

    # ------------------------------------------------------------------
    # 3. Sends to billing_email even when customer.email is NULL (fleet AP-only accounts)
    # ------------------------------------------------------------------
    @patch('apps.billing.tasks.send_mail')
    def test_sends_when_only_billing_email_set(self, mock_send):
        """Fleet customer with billing_email but no customer.email: invoice is sent."""
        from apps.billing.tasks import _send_batch_invoice_email

        mock_send.return_value = 1
        customer = _make_customer(self.tenant, email=None)  # no general email
        CustomerRepairPreference.objects.create(
            customer=customer,
            billing_email='accounts@penske.com',
        )
        invoice = _make_invoice(customer, self.tenant)

        result = _send_batch_invoice_email(invoice, self.config)

        self.assertTrue(result, 'Should send when billing_email is present even with no customer.email')
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        recipient_list = (
            call_kwargs.kwargs.get('recipient_list')
            or call_kwargs.args[3]
        )
        self.assertIn('accounts@penske.com', recipient_list)

    # ------------------------------------------------------------------
    # 4. Returns False (and does NOT send) when no email at all
    # ------------------------------------------------------------------
    @patch('apps.billing.tasks.send_mail')
    def test_skips_when_no_email_anywhere(self, mock_send):
        """Customer with no email at all → returns False, send_mail not called."""
        from apps.billing.tasks import _send_batch_invoice_email

        customer = _make_customer(self.tenant, email=None)
        # No CustomerRepairPreference → exception path → falls back to None
        invoice = _make_invoice(customer, self.tenant)

        result = _send_batch_invoice_email(invoice, self.config)

        self.assertFalse(result)
        mock_send.assert_not_called()

    # ------------------------------------------------------------------
    # 5. Falls back gracefully when CustomerRepairPreference does not exist
    # ------------------------------------------------------------------
    @patch('apps.billing.tasks.send_mail')
    def test_no_repair_preferences_falls_back_to_customer_email(self, mock_send):
        """No CustomerRepairPreference → uses customer.email without error."""
        from apps.billing.tasks import _send_batch_invoice_email

        mock_send.return_value = 1
        customer = _make_customer(self.tenant, email='owner@company.com')
        # Deliberately no CustomerRepairPreference record
        invoice = _make_invoice(customer, self.tenant)

        result = _send_batch_invoice_email(invoice, self.config)

        self.assertTrue(result)
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args
        recipient_list = (
            call_kwargs.kwargs.get('recipient_list')
            or call_kwargs.args[3]
        )
        self.assertIn('owner@company.com', recipient_list)

    # ------------------------------------------------------------------
    # 6. Returns False when send_mail raises an exception
    # ------------------------------------------------------------------
    @patch('apps.billing.tasks.send_mail', side_effect=Exception('SMTP error'))
    def test_returns_false_on_send_exception(self, mock_send):
        """send_mail exception → returns False (does not raise)."""
        from apps.billing.tasks import _send_batch_invoice_email

        customer = _make_customer(self.tenant, email='billing@fleet.com')
        invoice = _make_invoice(customer, self.tenant)

        result = _send_batch_invoice_email(invoice, self.config)

        self.assertFalse(result)
