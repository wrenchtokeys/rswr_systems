"""
CODE-101: owner_settings_view fetched 349+ shared (null-tenant) TaxRate rows
on every /owner/settings/ GET, but owner_settings.html never rendered them.

Regression test:
- Confirms the settings page loads without error (no missing context crash)
- Confirms tax_rates is NOT in the response context (dead variable removed)
- Confirms tax_enabled and billing_config ARE in context (still needed)
- Confirms shared null-tenant rates can't leak into settings page context
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import TaxRate, BillingConfig


class SettingsDeadTaxRateQueryTest(TestCase):
    """
    Verify that owner_settings_view no longer fetches 349+ shared TaxRate rows.
    """

    def setUp(self):
        self.client = Client()

        # Create owner user first (Tenant.owner is a required FK)
        self.owner = User.objects.create_user(
            username='owner_101',
            email='owner101@example.com',
            password='testpass123',
            first_name='Owner',
            last_name='One',
        )

        # Create tenant with owner
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-101',
            plan='trial',
            owner=self.owner,
        )

        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
            is_active=True,
        )

        # Create 10 shared (null-tenant) TaxRate rows — simulates production state
        for i in range(10):
            TaxRate.objects.create(
                tenant=None,
                city=f'SharedCity{i}',
                state='AR',
                state_rate=Decimal('6.500'),
            )

        # Create 2 tenant-owned TaxRate rows
        TaxRate.objects.create(
            tenant=self.tenant,
            city='MyCity',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )
        TaxRate.objects.create(
            tenant=self.tenant,
            city='MyCity2',
            state='AR',
            state_rate=Decimal('9.000'),
            is_active=True,
        )

        # Billing config
        BillingConfig.get_for_tenant(self.tenant)

        # Log in and set tenant session
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _get_settings(self, tab='general'):
        return self.client.get(f'/owner/settings/?tab={tab}')

    def test_settings_page_loads_without_error(self):
        """GET /owner/settings/ must return 200."""
        response = self._get_settings()
        self.assertEqual(response.status_code, 200)

    def test_tax_rates_not_in_context(self):
        """tax_rates must NOT be passed to owner_settings.html (dead variable removed)."""
        response = self._get_settings(tab='billing')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('tax_rates', response.context,
            "tax_rates was added back to settings context — it's a dead variable "
            "that loads 349+ shared rows but is never rendered by owner_settings.html")

    def test_tax_enabled_still_in_context(self):
        """tax_enabled must still be in context (used by the template)."""
        response = self._get_settings(tab='billing')
        self.assertIn('tax_enabled', response.context)

    def test_billing_config_still_in_context(self):
        """billing_config must still be in context (used by the template)."""
        response = self._get_settings(tab='billing')
        self.assertIn('billing_config', response.context)

    def test_other_essential_context_vars_present(self):
        """Ensure removing tax_rates didn't accidentally remove other context vars."""
        response = self._get_settings()
        for var in ['tenant', 'membership', 'members', 'shop_join_url',
                    'customers', 'active_tab', 'reminder_day_choices',
                    'active_reminder_days', 'batch_month_days']:
            self.assertIn(var, response.context,
                f"'{var}' missing from settings context after CODE-101 fix")

    def test_null_tenant_rates_not_leaked_to_settings(self):
        """
        Shared null-tenant TaxRate rows must not be accessible from owner_settings context.
        Previously they were in tax_rates — verify that even if tax_rates reappears,
        it must not contain null-tenant rows.
        """
        response = self._get_settings(tab='billing')
        # If tax_rates were ever added back, verify null-tenant rows are excluded
        tax_rates = response.context.get('tax_rates', None) if response.context else None
        if tax_rates is not None:
            # Must only show this tenant's rows
            for rate in tax_rates:
                self.assertEqual(rate.tenant_id, self.tenant.id,
                    f"Shared null-tenant TaxRate '{rate.city}' leaked into settings context")
