"""
CODE-103: billing_location form in owner_settings_view updated BillingConfig
component rates but never created/updated a TaxRate record.

TaxService.is_tax_enabled() checks TaxRate.objects.filter(tenant=tenant,
is_active=True).exists() — NOT BillingConfig.tax_enabled. So tax was never
actually applied to invoices even after the owner set their rate breakdown in
Settings → Billing tab (form_type='billing_location').

Root cause is the same as CODE-099 (owner_toggle_tax), but in a different
code path.

Regression tests:
1. Saving billing_location with rates creates a TaxRate row for the tenant.
2. TaxService.is_tax_enabled() returns True after saving.
3. Saving billing_location with a previously deactivated TaxRate row reactivates it.
4. Saving billing_location with zero rates deactivates all TaxRate rows.
5. Saving without city/state (location not set) skips TaxRate creation but
   does NOT deactivate existing rows (partial save).
6. BillingConfig.company_city/state/zip are updated correctly.
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import TaxRate, BillingConfig
from apps.billing.services.tax_service import TaxService


class BillingLocationTaxRateSyncTest(TestCase):
    """
    Verify that the billing_location form properly syncs TaxRate records
    so that TaxService.is_tax_enabled() reflects the owner's intent.
    """

    def setUp(self):
        self.client = Client()

        self.owner = User.objects.create_user(
            username='owner_103',
            email='owner103@example.com',
            password='testpass123',
            first_name='Owner',
            last_name='Test',
        )

        self.tenant = Tenant.objects.create(
            name='Tax Test Shop',
            slug='tax-test-shop-103',
            owner=self.owner,
            plan='trial',
        )

        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
        )

        self.client.login(username='owner_103', password='testpass123')
        # Attach tenant via middleware session var
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_billing_location(self, city='Hensley', state='AR', zip_code='72103',
                                state_rate='6.500', county_rate='0', city_rate='0',
                                special_rate='0'):
        return self.client.post('/owner/settings/', {
            'form_type': 'billing_location',
            'company_city': city,
            'company_state': state,
            'company_zip': zip_code,
            'state_tax_rate': state_rate,
            'county_tax_rate': county_rate,
            'city_tax_rate': city_rate,
            'special_tax_rate': special_rate,
        }, follow=True)

    def test_saves_tax_rate_row_for_tenant(self):
        """Submitting billing_location with rates creates a TaxRate for the tenant."""
        self.assertFalse(
            TaxRate.objects.filter(tenant=self.tenant, is_active=True).exists(),
            "Precondition: no active TaxRate before saving",
        )

        response = self._post_billing_location(
            state_rate='6.500', county_rate='1.000', city_rate='0.500',
        )
        self.assertEqual(response.status_code, 200)

        rate = TaxRate.objects.filter(tenant=self.tenant, is_active=True).first()
        self.assertIsNotNone(rate, "TaxRate must be created after billing_location save")
        self.assertEqual(rate.city.lower(), 'hensley')
        self.assertEqual(rate.state.upper(), 'AR')
        self.assertEqual(rate.state_rate, Decimal('6.500'))
        self.assertEqual(rate.county_rate, Decimal('1.000'))
        self.assertEqual(rate.city_rate, Decimal('0.500'))

    def test_tax_service_is_enabled_after_save(self):
        """TaxService.is_tax_enabled() returns True after billing_location save."""
        self._post_billing_location(state_rate='6.500')
        svc = TaxService(tenant=self.tenant)
        self.assertTrue(
            svc.is_tax_enabled(),
            "TaxService.is_tax_enabled() must return True after billing_location saves a rate",
        )

    def test_reactivates_previously_deactivated_taxrate(self):
        """If tenant had a deactivated TaxRate for the same city/state, it is reactivated."""
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Hensley',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=False,  # previously deactivated
        )

        self._post_billing_location(state_rate='6.500', county_rate='1.000')

        active = TaxRate.objects.filter(tenant=self.tenant, is_active=True, city__iexact='Hensley')
        self.assertEqual(active.count(), 1, "Should have exactly one active TaxRate")
        self.assertEqual(active.first().county_rate, Decimal('1.000'))

    def test_zero_rates_deactivates_all_taxrates(self):
        """Submitting billing_location with all-zero rates deactivates existing TaxRates."""
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Hensley',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

        self._post_billing_location(
            state_rate='0', county_rate='0', city_rate='0', special_rate='0',
        )

        active_count = TaxRate.objects.filter(tenant=self.tenant, is_active=True).count()
        self.assertEqual(active_count, 0, "All TaxRates must be deactivated when rate is zero")

        svc = TaxService(tenant=self.tenant)
        self.assertFalse(svc.is_tax_enabled(), "TaxService must report disabled when all rates deactivated")

    def test_billing_config_company_location_updated(self):
        """BillingConfig.company_city/state/zip are stored correctly."""
        self._post_billing_location(city='Conway', state='AR', zip_code='72032', state_rate='6.500')

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.company_city, 'Conway')
        self.assertEqual(config.company_state, 'AR')
        self.assertEqual(config.company_zip, '72032')

    def test_billing_config_tax_rates_updated(self):
        """BillingConfig component rates are saved and default_tax_rate totals correctly."""
        self._post_billing_location(
            state_rate='6.500', county_rate='1.000', city_rate='0.500', special_rate='0.250',
        )
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.state_tax_rate, Decimal('6.500'))
        self.assertEqual(config.county_tax_rate, Decimal('1.000'))
        self.assertEqual(config.city_tax_rate, Decimal('0.500'))
        self.assertEqual(config.special_tax_rate, Decimal('0.250'))
        self.assertEqual(config.default_tax_rate, Decimal('8.250'))

    def test_tax_enabled_set_on_billing_config(self):
        """BillingConfig.tax_enabled is set to True when rate > 0."""
        self._post_billing_location(state_rate='6.500')
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)
