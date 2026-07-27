"""
CODE-103 (rewritten for the tax overhaul): the billing_location form used to
parse rates, auto-enable tax, and sync TaxRate rows — which silently enabled a
prefilled 6.5% Arkansas rate when an owner merely saved their shop address.

New contract:
- form_type='billing_location' saves the ADDRESS ONLY. It never touches
  tax_enabled, tax_configured, BillingConfig rates, or TaxRate rows.
- form_type='tax_settings' is the only path that configures tax: it sets
  tax_configured=True, tax_enabled per the yes/no answer, stores the rate,
  and upserts the tenant's single TaxRate row.
- BillingConfig.tax_enabled is the single source of truth for
  TaxService.is_tax_enabled(); TaxRate rows only hold rates.
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import TaxRate, BillingConfig
from apps.billing.services.tax_service import TaxService


class TaxSettingsFormTest(TestCase):
    """Address saves never touch tax; the tax_settings form owns tax setup."""

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
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_address(self, city='Hensley', state='AR', zip_code='72103'):
        return self.client.post('/owner/settings/', {
            'form_type': 'billing_location',
            'company_address': '123 Main St',
            'company_city': city,
            'company_state': state,
            'company_zip': zip_code,
        }, follow=True)

    def _post_tax(self, charges_tax='yes', rate='8.25', **components):
        data = {
            'form_type': 'tax_settings',
            'charges_tax': charges_tax,
            'tax_rate_percent': rate,
        }
        data.update(components)
        return self.client.post('/owner/settings/', data, follow=True)

    # ── Address form is tax-inert ────────────────────────────────────────

    def test_address_save_never_enables_tax(self):
        response = self._post_address()
        self.assertEqual(response.status_code, 200)

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)
        self.assertFalse(config.tax_configured)
        self.assertFalse(
            TaxRate.objects.filter(tenant=self.tenant).exists(),
            "Saving the shop address must not create a TaxRate row",
        )
        self.assertFalse(TaxService(tenant=self.tenant).is_tax_enabled())

    def test_address_save_stores_location(self):
        self._post_address(city='Conway', state='AR', zip_code='72032')
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.company_city, 'Conway')
        self.assertEqual(config.company_state, 'AR')
        self.assertEqual(config.company_zip, '72032')

    def test_address_save_does_not_disturb_configured_tax(self):
        """Re-saving the address leaves an already-configured tax setup alone."""
        self._post_tax(charges_tax='yes', rate='8.25')
        self._post_address(city='Conway')

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)
        self.assertTrue(config.tax_configured)
        self.assertEqual(config.default_tax_rate, Decimal('8.25'))

    # ── tax_settings: the explicit yes/no answer ─────────────────────────

    def test_answer_yes_enables_tax_and_stores_rate(self):
        self._post_tax(charges_tax='yes', rate='8.25')

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)
        self.assertTrue(config.tax_configured)
        self.assertEqual(config.default_tax_rate, Decimal('8.25'))
        self.assertTrue(TaxService(tenant=self.tenant).is_tax_enabled())

    def test_answer_yes_upserts_single_taxrate_row(self):
        self._post_address()  # store city/state first
        self._post_tax(charges_tax='yes', rate='8.25')

        rows = TaxRate.objects.filter(tenant=self.tenant)
        self.assertEqual(rows.count(), 1)
        row = rows.first()
        self.assertTrue(row.is_active)
        self.assertEqual(row.total_rate, Decimal('8.250'))
        self.assertEqual(row.city, 'Hensley')

        # Saving again updates in place — no duplicate rows
        self._post_tax(charges_tax='yes', rate='9.00')
        self.assertEqual(TaxRate.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(
            TaxRate.objects.get(tenant=self.tenant).total_rate, Decimal('9.000'))

    def test_answer_no_disables_tax_and_marks_configured(self):
        self._post_tax(charges_tax='no', rate='')

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)
        self.assertTrue(config.tax_configured)
        self.assertFalse(TaxService(tenant=self.tenant).is_tax_enabled())

    def test_answer_no_wins_even_with_active_taxrate_rows(self):
        """TaxRate rows no longer control whether tax applies."""
        TaxRate.objects.create(
            tenant=self.tenant, city='Hensley', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )
        self._post_tax(charges_tax='no', rate='')

        self.assertFalse(TaxService(tenant=self.tenant).is_tax_enabled())
        result = TaxService(tenant=self.tenant).calculate_tax(subtotal=Decimal('100'))
        self.assertEqual(result['amount'], Decimal('0.00'))

    def test_component_breakdown_wins_over_single_rate(self):
        self._post_tax(
            charges_tax='yes', rate='5.00',
            state_tax_rate='6.500', county_tax_rate='1.000',
            city_tax_rate='0.500', special_tax_rate='0.250',
        )
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.default_tax_rate, Decimal('8.250'))
        self.assertEqual(config.state_tax_rate, Decimal('6.500'))
        self.assertEqual(config.county_tax_rate, Decimal('1.000'))

    def test_rate_validation_rejects_out_of_bounds(self):
        for bad_rate in ('0', '-1', '31', 'abc'):
            self._post_tax(charges_tax='yes', rate=bad_rate)
            config = BillingConfig.get_for_tenant(self.tenant)
            self.assertFalse(
                config.tax_configured,
                f"Rate {bad_rate!r} must be rejected without configuring tax",
            )

    def test_calculate_tax_falls_back_to_config_rates_without_row(self):
        """tax_enabled + no TaxRate row → config component rates apply."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = True
        config.tax_configured = True
        config.state_tax_rate = Decimal('7.000')
        config.default_tax_rate = Decimal('7.000')
        config.save()

        result = TaxService(tenant=self.tenant).calculate_tax(subtotal=Decimal('100.00'))
        self.assertEqual(result['rate'], Decimal('7.000'))
        self.assertEqual(result['amount'], Decimal('7.00'))
