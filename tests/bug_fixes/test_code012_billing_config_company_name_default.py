"""
Regression tests for CODE-012: BillingConfig.company_name hardcoded default.

Bug: BillingConfig.company_name field had default='Rockstar Windshield Repair'.
Every new tenant signup created a BillingConfig branded as "Rockstar Windshield Repair"
regardless of the actual shop name.

Fix:
- Field default changed to '' (blank=True)
- get_for_tenant() now auto-populates company_name from tenant.name on creation
- Migration 0015 fixes any existing rows with the old hardcoded value
"""
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from apps.billing.models import BillingConfig
from apps.tenants.models import Tenant, SubscriptionPlan


class BillingConfigCompanyNameDefaultTest(TestCase):
    """BillingConfig.get_for_tenant creates config with correct shop name."""

    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Test Plan', slug='test-plan-code012',
            monthly_price=Decimal('29.99'),
            max_repairs_per_month=100,
            max_technicians=5,
            max_customers=50,
            max_storage_mb=500,
        )
        self._user_counter = 0

    def _make_tenant(self, name):
        self._user_counter += 1
        user = User.objects.create_user(
            f'user_{self._user_counter}',
            f'user{self._user_counter}@test.com',
            'pass'
        )
        slug = name.lower().replace(' ', '-').replace("'", '')
        subdomain = name.lower().replace(' ', '').replace("'", '')[:20]
        return Tenant.objects.create(
            name=name,
            slug=slug,
            subdomain=subdomain,
            owner=user,
            subscription_plan=self.plan,
            is_active=True,
        )

    def test_new_tenant_gets_its_own_name(self):
        """get_for_tenant populates company_name from tenant.name on first call."""
        tenant = self._make_tenant('Acme Glass Co')
        config = BillingConfig.get_for_tenant(tenant)
        self.assertEqual(config.company_name, 'Acme Glass Co')

    def test_new_tenant_never_gets_rockstar_name(self):
        """A brand-new shop must not be branded as Rockstar Windshield Repair."""
        tenant = self._make_tenant('Springfield Glass')
        config = BillingConfig.get_for_tenant(tenant)
        self.assertNotEqual(config.company_name, 'Rockstar Windshield Repair')

    def test_second_call_returns_same_config(self):
        """get_for_tenant is idempotent — second call returns existing record."""
        tenant = self._make_tenant('Dual Glass')
        config1 = BillingConfig.get_for_tenant(tenant)
        config2 = BillingConfig.get_for_tenant(tenant)
        self.assertEqual(config1.pk, config2.pk)

    def test_existing_custom_name_not_overwritten(self):
        """If company_name was already set to a custom value, get_for_tenant must not overwrite it."""
        tenant = self._make_tenant('Custom Shop')
        # Pre-create with a custom name
        BillingConfig.objects.create(tenant=tenant, company_name='My Custom Brand')
        config = BillingConfig.get_for_tenant(tenant)
        self.assertEqual(config.company_name, 'My Custom Brand')

    def test_creation_path_populates_name(self):
        """Creation path (no pre-existing config) auto-populates company_name."""
        tenant = self._make_tenant('Blank Name Shop')
        # No pre-existing config — get_for_tenant creates one and populates name
        config = BillingConfig.get_for_tenant(tenant)
        self.assertTrue(len(config.company_name) > 0)
        self.assertEqual(config.company_name, tenant.name)

    def test_multiple_tenants_get_different_names(self):
        """Different tenants must get different company names."""
        tenant_a = self._make_tenant('Alpha Glass')
        tenant_b = self._make_tenant('Beta Auto Glass')
        config_a = BillingConfig.get_for_tenant(tenant_a)
        config_b = BillingConfig.get_for_tenant(tenant_b)
        self.assertEqual(config_a.company_name, 'Alpha Glass')
        self.assertEqual(config_b.company_name, 'Beta Auto Glass')
        self.assertNotEqual(config_a.company_name, config_b.company_name)

    def test_field_default_is_not_rockstar(self):
        """The model field default must be '' not 'Rockstar Windshield Repair'."""
        field = BillingConfig._meta.get_field('company_name')
        self.assertNotEqual(field.default, 'Rockstar Windshield Repair')
        self.assertEqual(field.default, '')

    def test_field_is_blank_true(self):
        """Field must have blank=True so empty strings are valid at form level."""
        field = BillingConfig._meta.get_field('company_name')
        self.assertTrue(field.blank)
