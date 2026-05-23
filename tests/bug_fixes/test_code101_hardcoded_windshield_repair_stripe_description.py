"""
Regression tests for CODE-101:
  Hardcoded "windshield repair(s)" in Stripe checkout session descriptions
  in stripe_service.py (create_checkout_session) and
  connect_service.py (create_connected_checkout_session).

Root cause:
    Both Stripe checkout session builders hardcoded:
        description=f'{invoice.line_items.count()} windshield repair(s) for {invoice.customer.name}'

    This is a SaaS bug — RS Systems is designed for any glass/auto shop,
    not just windshield repair shops. A shop specializing in tinting,
    calibration, or full replacement would have their customers see
    "3 windshield repair(s) for EOS Trucking" on Stripe's hosted checkout
    even if no windshield repairs were performed.

Fix (CODE-101):
    Changed both descriptions to:
        f'{invoice.line_items.count()} service(s) for {invoice.customer.name}'

    "service(s)" is neutral and accurate for any shop type.

Tests verify:
1. StripeService.create_checkout_session: description does NOT contain "windshield"
2. StripeService.create_checkout_session: description contains "service(s)"
3. ConnectService.create_connected_checkout_session: description does NOT contain "windshield"
4. ConnectService.create_connected_checkout_session: description contains "service(s)"
5. Both include the customer name in the description
6. Both include the line item count in the description
7. Regression: single line item uses "1 service(s)" (count is accurate)
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock, call

from django.test import TestCase
from django.contrib.auth.models import User

from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.services.stripe_service import StripeService
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.connect_service import ConnectService
from core.models import Customer


def _make_tenant(name='Test Shop', slug='test-shop'):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='starter',
        defaults={'name': 'Starter', 'monthly_price': 0, 'is_active': True},
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}', password='test123', email=f'owner@{slug}.com'
    )
    tenant = Tenant.objects.create(name=name, slug=slug, owner=owner, plan='starter')
    return tenant


def _make_invoice(tenant, num_line_items=3, amount_due=Decimal('150.00')):
    """Create an invoice with N line items."""
    customer = Customer.objects.create(
        name='EOS Trucking',
        tenant=tenant,
        email='eos@example.com',
    )
    invoice = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number='INV-001',
        status='SENT',
        invoice_date='2026-01-01',
        subtotal=amount_due,
        total=amount_due,
        amount_paid=Decimal('0.00'),
        payment_terms='NET30',
    )
    for i in range(num_line_items):
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f'Service item {i + 1}',
            quantity=1,
            unit_price=amount_due / num_line_items,
            amount=amount_due / num_line_items,
        )
    return invoice, customer


class StripeServiceDescriptionTests(TestCase):
    """Tests for StripeService.create_checkout_session description field."""

    def setUp(self):
        self.tenant = _make_tenant(name='Auto Tint Pro', slug='auto-tint-pro')
        self.invoice, self.customer = _make_invoice(self.tenant, num_line_items=3)

    @patch('apps.billing.services.stripe_service.stripe')
    @patch.object(StripeService, 'is_enabled', new_callable=lambda: property(lambda self: True))
    @patch.object(StripeService, 'get_or_create_customer', return_value='cus_test123')
    def test_description_does_not_contain_windshield(self, mock_get_customer, mock_enabled, mock_stripe):
        """Checkout description should not say 'windshield'."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_test123'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = StripeService()
        service.create_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertNotIn(
            'windshield',
            description.lower(),
            f"Description should not mention 'windshield': got '{description}'"
        )

    @patch('apps.billing.services.stripe_service.stripe')
    @patch.object(StripeService, 'is_enabled', new_callable=lambda: property(lambda self: True))
    @patch.object(StripeService, 'get_or_create_customer', return_value='cus_test123')
    def test_description_contains_service(self, mock_get_customer, mock_enabled, mock_stripe):
        """Checkout description should use 'service(s)' instead of 'windshield repair(s)'."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_test123'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = StripeService()
        service.create_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertIn(
            'service',
            description.lower(),
            f"Description should contain 'service': got '{description}'"
        )

    @patch('apps.billing.services.stripe_service.stripe')
    @patch.object(StripeService, 'is_enabled', new_callable=lambda: property(lambda self: True))
    @patch.object(StripeService, 'get_or_create_customer', return_value='cus_test123')
    def test_description_contains_customer_name(self, mock_get_customer, mock_enabled, mock_stripe):
        """Checkout description should include the customer name."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_test123'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = StripeService()
        service.create_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertIn(
            'EOS Trucking',
            description,
            f"Description should contain customer name: got '{description}'"
        )

    @patch('apps.billing.services.stripe_service.stripe')
    @patch.object(StripeService, 'is_enabled', new_callable=lambda: property(lambda self: True))
    @patch.object(StripeService, 'get_or_create_customer', return_value='cus_test123')
    def test_description_contains_line_item_count(self, mock_get_customer, mock_enabled, mock_stripe):
        """Checkout description should include the line item count."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_test123'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = StripeService()
        service.create_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        # Should include "3" (the number of line items)
        self.assertIn(
            '3',
            description,
            f"Description should contain line item count '3': got '{description}'"
        )


class ConnectServiceDescriptionTests(TestCase):
    """Tests for ConnectService.create_connected_checkout_session description field."""

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='starter',
            defaults={'name': 'Starter', 'monthly_price': 0, 'is_active': True},
        )
        owner = User.objects.create_user(
            username='connect_owner', password='test123', email='connect@testshop.com'
        )
        self.tenant = Tenant.objects.create(
            name='Glass Calibration Pros',
            slug='glass-calibration-pros',
            owner=owner,
            plan='starter',
            stripe_connect_account_id='acct_test123',
            stripe_connect_charges_enabled=True,
        )
        self.invoice, self.customer = _make_invoice(
            self.tenant, num_line_items=2, amount_due=Decimal('200.00')
        )

    @patch('apps.tenants.services.connect_service.stripe')
    def test_connect_description_does_not_contain_windshield(self, mock_stripe):
        """ConnectService checkout description should not say 'windshield'."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_connect_test'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = ConnectService()
        service.create_connected_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertNotIn(
            'windshield',
            description.lower(),
            f"ConnectService description should not mention 'windshield': got '{description}'"
        )

    @patch('apps.tenants.services.connect_service.stripe')
    def test_connect_description_contains_service(self, mock_stripe):
        """ConnectService checkout description should use 'service(s)'."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_connect_test'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = ConnectService()
        service.create_connected_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertIn(
            'service',
            description.lower(),
            f"ConnectService description should contain 'service': got '{description}'"
        )

    @patch('apps.tenants.services.connect_service.stripe')
    def test_connect_description_contains_customer_name(self, mock_stripe):
        """ConnectService checkout description should include customer name."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_connect_test'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = ConnectService()
        service.create_connected_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertIn(
            'EOS Trucking',
            description,
            f"ConnectService description should contain customer name: got '{description}'"
        )

    @patch('apps.tenants.services.connect_service.stripe')
    def test_connect_description_contains_line_item_count(self, mock_stripe):
        """ConnectService checkout description should include line item count."""
        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_connect_test'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = ConnectService()
        service.create_connected_checkout_session(self.invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        # Should include "2" (the number of line items)
        self.assertIn(
            '2',
            description,
            f"ConnectService description should contain line item count '2': got '{description}'"
        )

    @patch('apps.tenants.services.connect_service.stripe')
    def test_single_line_item_count(self, mock_stripe):
        """Description is accurate for single-item invoices too."""
        # Create invoice with exactly 1 line item
        single_item_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-002',
            status='SENT',
            invoice_date='2026-01-01',
            subtotal=Decimal('75.00'),
            total=Decimal('75.00'),
            amount_paid=Decimal('0.00'),
            payment_terms='NET30',
        )
        InvoiceLineItem.objects.create(
            invoice=single_item_invoice,
            description='ADAS calibration',
            quantity=1,
            unit_price=Decimal('75.00'),
            amount=Decimal('75.00'),
        )

        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/test'
        mock_session.id = 'cs_connect_test2'
        mock_stripe.checkout.Session.create.return_value = mock_session

        service = ConnectService()
        service.create_connected_checkout_session(single_item_invoice)

        call_kwargs = mock_stripe.checkout.Session.create.call_args
        line_items = call_kwargs[1]['line_items']
        description = line_items[0]['price_data']['product_data']['description']

        self.assertIn('1', description)
        self.assertNotIn('windshield', description.lower())
        self.assertIn('service', description.lower())
