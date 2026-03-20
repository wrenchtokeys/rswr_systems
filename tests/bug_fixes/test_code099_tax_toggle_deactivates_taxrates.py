"""
CODE-099 regression tests: owner_toggle_tax() and owner_setup_save_tax() must
sync TaxRate.is_active when tax is disabled/enabled.

Root cause:
    TaxService.is_tax_enabled() for tenant-aware paths checks
        TaxRate.objects.filter(tenant=tenant, is_active=True).exists()
    It does NOT consult BillingConfig.tax_enabled.  Before this fix:
    - owner_toggle_tax() only flipped BillingConfig.tax_enabled.
    - owner_setup_save_tax() with tax_enabled=False left existing active
      TaxRate records untouched.
    In both cases, tax kept being charged even after the owner "disabled" it.

Fixes:
    1. owner_toggle_tax():   deactivate all TaxRates on disable; reactivate on enable.
    2. owner_setup_save_tax(): deactivate all TaxRates when tax_enabled=False is saved.
                               Reactivate (or create) TaxRate when tax_enabled=True with rates.
"""

from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.billing.models import TaxRate, BillingConfig
from apps.billing.services.tax_service import TaxService
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()


def _make_tenant_owner(slug):
    user = User.objects.create_user(
        username=f"owner_{slug}",
        email=f"owner_{slug}@test.com",
        password="password",
    )
    tenant = Tenant.objects.create(name=f"Shop {slug}", slug=slug, is_active=True, owner=user)
    TenantMembership.objects.create(
        user=user, tenant=tenant, role="owner", is_active=True
    )
    BillingConfig.objects.create(tenant=tenant, tax_enabled=True)
    return tenant, user


class OwnerToggleTaxDeactivatesRatesTest(TestCase):
    """owner_toggle_tax() must deactivate TaxRates when disabling tax."""

    def setUp(self):
        self.tenant, self.user = _make_tenant_owner("toggle1")
        self.client.force_login(self.user)
        # Add an active TaxRate
        self.rate = TaxRate.objects.create(
            tenant=self.tenant,
            city="Little Rock",
            state="AR",
            state_rate=Decimal("6.5"),
            city_rate=Decimal("1.0"),
            is_active=True,
        )

    def test_toggle_off_deactivates_taxrates(self):
        """Disabling tax via toggle should deactivate all TaxRate records."""
        # tax is currently enabled in BillingConfig
        response = self.client.post("/owner/tax-rates/toggle/")
        # Should redirect (302)
        self.assertIn(response.status_code, [301, 302])

        self.rate.refresh_from_db()
        self.assertFalse(self.rate.is_active, "TaxRate should be deactivated after toggle off")

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled, "BillingConfig.tax_enabled should be False")

    def test_toggle_off_makes_is_tax_enabled_return_false(self):
        """After toggle off, TaxService.is_tax_enabled() must return False."""
        self.client.post("/owner/tax-rates/toggle/")
        svc = TaxService(tenant=self.tenant)
        self.assertFalse(svc.is_tax_enabled(tenant=self.tenant))

    def test_toggle_on_reactivates_taxrates(self):
        """Re-enabling tax should reactivate all TaxRate records for the tenant."""
        # Start with tax disabled and rate deactivated
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = False
        config.save()
        self.rate.is_active = False
        self.rate.save()

        # Now toggle on
        self.client.post("/owner/tax-rates/toggle/")

        self.rate.refresh_from_db()
        self.assertTrue(self.rate.is_active, "TaxRate should be reactivated after toggle on")

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled, "BillingConfig.tax_enabled should be True")

    def test_toggle_off_does_not_affect_other_tenant_taxrates(self):
        """Deactivating tax for tenant A must not touch tenant B's TaxRates."""
        tenant_b, user_b = _make_tenant_owner("toggle_b")
        rate_b = TaxRate.objects.create(
            tenant=tenant_b,
            city="Fayetteville",
            state="AR",
            state_rate=Decimal("6.5"),
            is_active=True,
        )

        self.client.post("/owner/tax-rates/toggle/")

        rate_b.refresh_from_db()
        self.assertTrue(rate_b.is_active, "Other tenant's TaxRate should be unaffected")

    def test_toggle_off_no_taxrates_still_updates_billing_config(self):
        """Toggle off with no existing TaxRates should still update BillingConfig."""
        self.rate.delete()
        self.client.post("/owner/tax-rates/toggle/")
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)


class OwnerSetupSaveTaxDeactivatesRatesTest(TestCase):
    """owner_setup_save_tax() must deactivate TaxRates when tax_enabled=False."""

    def setUp(self):
        self.tenant, self.user = _make_tenant_owner("setup1")
        self.client.force_login(self.user)
        self.rate = TaxRate.objects.create(
            tenant=self.tenant,
            city="Jonesboro",
            state="AR",
            state_rate=Decimal("6.5"),
            is_active=True,
        )

    def _post_setup_tax(self, **kwargs):
        data = {
            "tax_enabled": "0",
            "state_rate": "0",
            "county_rate": "0",
            "city_rate": "0",
            "special_rate": "0",
            "city": "",
            "state": "AR",
        }
        data.update(kwargs)
        return self.client.post("/owner/setup/save/tax/", data)

    def test_setup_save_tax_disabled_deactivates_taxrates(self):
        """Saving setup with tax_enabled=False should deactivate all TaxRates."""
        response = self._post_setup_tax(tax_enabled="0")
        self.assertEqual(response.status_code, 200)

        self.rate.refresh_from_db()
        self.assertFalse(self.rate.is_active)

    def test_setup_save_tax_disabled_makes_is_tax_enabled_false(self):
        """After save with disabled, TaxService must report tax is off."""
        self._post_setup_tax(tax_enabled="0")
        svc = TaxService(tenant=self.tenant)
        self.assertFalse(svc.is_tax_enabled(tenant=self.tenant))

    def test_setup_save_tax_enabled_creates_taxrate(self):
        """Saving setup with tax_enabled=1 and valid rates should create/activate a TaxRate."""
        # Delete existing rate first
        self.rate.delete()

        response = self._post_setup_tax(
            tax_enabled="1",
            state_rate="6.5",
            county_rate="1.0",
            city_rate="0.5",
            special_rate="0",
            city="Little Rock",
            state="AR",
        )
        self.assertEqual(response.status_code, 200)

        rates = TaxRate.objects.filter(tenant=self.tenant, is_active=True)
        self.assertEqual(rates.count(), 1)
        rate = rates.first()
        self.assertEqual(rate.city, "Little Rock")
        self.assertEqual(rate.state_rate, Decimal("6.5"))
        self.assertTrue(rate.is_active)

    def test_setup_save_tax_enabled_reactivates_deactivated_rate(self):
        """Re-enabling with same city/state should reactivate existing deactivated rate."""
        self.rate.is_active = False
        self.rate.city = "Jonesboro"
        self.rate.state = "AR"
        self.rate.save()

        response = self._post_setup_tax(
            tax_enabled="1",
            state_rate="6.5",
            county_rate="0",
            city_rate="1.0",
            special_rate="0",
            city="Jonesboro",
            state="AR",
        )
        self.assertEqual(response.status_code, 200)

        self.rate.refresh_from_db()
        self.assertTrue(self.rate.is_active)

    def test_setup_save_tax_disabled_does_not_affect_other_tenant(self):
        """Disabling tax for tenant A must not affect tenant B's TaxRates."""
        tenant_b, _ = _make_tenant_owner("setup_b")
        rate_b = TaxRate.objects.create(
            tenant=tenant_b,
            city="Conway",
            state="AR",
            state_rate=Decimal("6.5"),
            is_active=True,
        )

        self._post_setup_tax(tax_enabled="0")

        rate_b.refresh_from_db()
        self.assertTrue(rate_b.is_active, "Other tenant's rate must be unaffected")
