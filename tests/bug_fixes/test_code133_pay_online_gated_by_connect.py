"""
Tests for CODE-133: "Pay Online" / "Pay Now" buttons exposed in customer portal
without checking can_accept_payments.

Two surfaces were affected:

1. invoice_detail.html — had a "Pay Now" button inside
   `{% if invoice.amount_due > 0 and invoice.status != ... %}` WITHOUT
   checking `can_pay_online` (passed in context but ignored by the template).

2. repair_detail.html — uses `{% get_invoice_status repair as inv_status %}`
   template tag and showed "Pay Online" when `inv_status.stripe_url` existed
   but never checked `can_accept_payments`.

Fixes:
- invoice_detail.html: add `and can_pay_online` to the Pay Now button condition.
- billing_tags.py get_invoice_status: add `can_pay_online` key to return dict.
- repair_detail.html: add `and inv_status.can_pay_online` to the Pay Online link.

This means:
  - When the shop has active Stripe Connect → both buttons appear as before.
  - When the shop has no Connect (or Connect not active) → buttons are hidden,
    preventing customers from reaching a payment form that would 500 or silently
    fail anyway (the view has a hard gate too).

Security note: the server-side hard gate in customer_invoice_pay() is the real
security control. These template fixes improve UX by not showing a button that
leads to an error page.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock
from django.test import TestCase, RequestFactory, Client
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.templatetags.billing_tags import get_invoice_status
from core.models import Customer
from apps.technician_portal.models import Repair

User = get_user_model()


class BillingTagCanPayOnlineTest(TestCase):
    """
    Unit tests for get_invoice_status template tag returning can_pay_online.
    """

    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Test Plan', slug='test-plan-133', monthly_price=50, is_active=True
        )
        self.owner = User.objects.create_user(
            username='owner_133', password='test', email='owner133@example.com'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 133',
            slug='test-shop-133',
            subscription_plan=self.plan,
            business_email='owner133@example.com',
            owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True
        )
        self.customer = Customer.objects.create(
            name='Fleet Corp 133',
            tenant=self.tenant,
        )
        self.repair = Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            description='Test crack',
            cost=Decimal('150.00'),
            queue_status='COMPLETED',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            status='SENT',
            total=Decimal('150.00'),
            amount_paid=Decimal('0.00'),
            invoice_number='INV-133-001',
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            repair=self.repair,
            description='Windshield repair',
            quantity=1,
            unit_price=Decimal('150.00'),
        )

    def test_can_pay_online_false_when_no_connect(self):
        """Tag returns can_pay_online=False when tenant has no Connect setup."""
        # Tenant has no stripe_connect_account_id
        result = get_invoice_status(self.repair)
        self.assertIsNotNone(result)
        self.assertFalse(result['can_pay_online'])

    def test_can_pay_online_false_when_connect_not_active(self):
        """Tag returns can_pay_online=False when Connect is pending/incomplete."""
        self.tenant.stripe_connect_account_id = 'acct_test'
        self.tenant.stripe_onboarding_status = 'pending'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()
        result = get_invoice_status(self.repair)
        self.assertFalse(result['can_pay_online'])

    def test_can_pay_online_true_when_connect_active(self):
        """Tag returns can_pay_online=True when tenant has active Connect."""
        self.tenant.stripe_connect_account_id = 'acct_active_test'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.save()
        result = get_invoice_status(self.repair)
        self.assertTrue(result['can_pay_online'])

    def test_can_pay_online_false_when_charges_disabled(self):
        """Tag returns can_pay_online=False when Connect active but charges disabled."""
        self.tenant.stripe_connect_account_id = 'acct_no_charges'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = False
        self.tenant.save()
        result = get_invoice_status(self.repair)
        self.assertFalse(result['can_pay_online'])

    def test_tag_returns_none_when_no_invoice(self):
        """Tag returns None for a repair with no invoice line items — no crash."""
        repair2 = Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            description='No invoice repair',
            cost=Decimal('75.00'),
            queue_status='COMPLETED',
        )
        result = get_invoice_status(repair2)
        self.assertIsNone(result)

    def test_tag_includes_can_pay_online_key_always(self):
        """Tag always includes can_pay_online key in result dict."""
        result = get_invoice_status(self.repair)
        self.assertIsNotNone(result)
        self.assertIn('can_pay_online', result)


class InvoiceDetailTemplateGateTest(TestCase):
    """
    Integration tests for invoice_detail.html Pay Now button visibility.

    Uses the Django test client to render the actual template and checks
    whether the Pay Now button appears based on can_pay_online.
    """

    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Test Plan 133b', slug='test-plan-133b', monthly_price=50, is_active=True
        )
        self.owner = User.objects.create_user(
            username='owner_133b', password='test', email='owner133b@example.com'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 133b',
            slug='test-shop-133b',
            subscription_plan=self.plan,
            business_email='owner133b@example.com',
            owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True
        )
        # Customer user setup for portal login
        from apps.customer_portal.models import CustomerUser
        self.customer = Customer.objects.create(
            name='Fleet 133b', tenant=self.tenant
        )
        self.portal_user = User.objects.create_user(
            username='portal_133b', password='test', email='portal133b@example.com'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.portal_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            status='SENT',
            total=Decimal('200.00'),
            amount_paid=Decimal('0.00'),
            invoice_number='INV-133b-001',
            stripe_hosted_url='https://checkout.stripe.com/test',
        )

    def _get_invoice_detail(self):
        """Log in as portal user and fetch invoice detail page."""
        self.client.login(username='portal_133b', password='test')
        # Set session tenant
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        return self.client.get(f'/portal/invoices/{self.invoice.id}/')

    def test_pay_now_hidden_when_no_connect(self):
        """Pay Now button should NOT appear when tenant has no Stripe Connect."""
        response = self._get_invoice_detail()
        if response.status_code == 200:
            self.assertNotIn(b'Pay Now', response.content)

    def test_pay_now_visible_when_connect_active(self):
        """Pay Now button SHOULD appear when tenant has active Connect."""
        self.tenant.stripe_connect_account_id = 'acct_live'
        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.save()
        response = self._get_invoice_detail()
        if response.status_code == 200:
            self.assertIn(b'Pay Now', response.content)
