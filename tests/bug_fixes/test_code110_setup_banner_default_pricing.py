"""
CODE-110 — Regression test: Setup banner ("Finish setting up your shop") persists
for shops whose prices happen to match the defaults ($50/$40/$35/$30/$25).

Root cause: owner_dashboard was computing setup_steps using a pricing_is_default
check.  If an owner's real prices equal the defaults, pricing_is_default=True
and a "Set your repair pricing" step was appended — causing the banner to show
even after the shop was fully configured.

Fix: remove the pricing_is_default check entirely.  _setup_completion() already
treats pricing as always done (sensible defaults exist, we can't tell them from
deliberate choices), so setup_steps should align.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import TaxRate, BillingConfig


class SetupBannerDefaultPricingTest(TestCase):
    """Banner must NOT show when a fully-configured shop charges default prices."""

    def setUp(self):
        self.client = Client()

        # Create owner user
        self.owner = User.objects.create_user(
            username='owner_code110',
            email='owner110@example.com',
            password='testpass123',
            first_name='Test',
            last_name='Owner',
        )

        # Create tenant with all required business info filled in
        self.tenant = Tenant.objects.create(
            name='Test Shop 110',
            slug='test-shop-110',
            plan='professional',
            owner=self.owner,
            business_phone='555-0110',
            business_email='shop110@example.com',
            # Explicitly set default prices — this was the trigger
            repair_price_1=Decimal('50.00'),
            repair_price_2=Decimal('40.00'),
            repair_price_3=Decimal('35.00'),
            repair_price_4=Decimal('30.00'),
            repair_price_5_plus=Decimal('25.00'),
        )

        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
            is_active=True,
        )

        # Add a tax rate so setup_completion.tax = True
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

        # Ensure BillingConfig with default_payment_terms exists
        config = BillingConfig.get_for_tenant(self.tenant)
        config.default_payment_terms = 30
        config.save()

        self.client.force_login(self.owner)

    def test_banner_hidden_when_shop_fully_configured_with_default_prices(self):
        """
        A shop with:
        - business_phone + business_email set
        - prices at defaults ($50/$40/$35/$30/$25)
        - at least one TaxRate
        - BillingConfig with payment terms

        ...should NOT show the 'Finish setting up your shop' banner.
        """
        # Attach the tenant to the request (simulate middleware)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)

        context = response.context

        # setup_steps should be empty (no remaining steps)
        setup_steps = context.get('setup_steps', [])
        pricing_steps = [s for s in setup_steps if 'pricing' in s.get('label', '').lower()]
        self.assertEqual(
            pricing_steps,
            [],
            msg=(
                'Pricing step should NOT appear in setup_steps for a shop using '
                'default prices — we cannot distinguish default from deliberate. '
                f'Got: {setup_steps}'
            ),
        )

    def test_banner_hidden_when_fully_setup(self):
        """
        A fully configured shop should render with empty setup_steps so neither
        setup banner variant is shown.
        """
        from apps.technician_portal.models import Technician
        from core.models import Customer

        # Add a technician
        tech_user = User.objects.create_user(
            username='tech_code110', email='tech110@example.com', password='test'
        )
        tech = Technician.objects.create(
            user=tech_user,
            tenant=self.tenant,
            is_active=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=tech_user,
            role='technician',
            is_active=True,
        )

        # Add a customer
        Customer.objects.create(tenant=self.tenant, name='Test Fleet 110', email='fleet110@example.com')

        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)

        setup_steps = response.context.get('setup_steps', [])
        self.assertEqual(
            setup_steps,
            [],
            msg=f'Expected no setup steps for fully configured shop. Got: {setup_steps}',
        )

    def test_business_info_step_still_shows_when_missing(self):
        """
        If business_phone or business_email is blank, the banner should still show
        the 'Add your business info' step — this must not be broken by the fix.
        """
        self.tenant.business_phone = ''
        self.tenant.save(update_fields=['business_phone'])

        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)

        setup_steps = response.context.get('setup_steps', [])
        labels = [s.get('label', '') for s in setup_steps]
        self.assertIn(
            'Add your business info',
            labels,
            msg=f'Business info step should appear when phone is blank. Got steps: {labels}',
        )
