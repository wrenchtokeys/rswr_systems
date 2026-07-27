"""
CODE-099 (rewritten for the tax overhaul).

The original bug: TaxService decided "is tax enabled" from TaxRate rows, so
owner_toggle_tax()/owner_setup_save_tax() had to hand-sync TaxRate.is_active
with BillingConfig.tax_enabled — and forgot to.

The overhaul removes the dual source of truth: BillingConfig.tax_enabled IS
the answer, TaxRate rows only hold rates. These tests pin the new contract:
- Toggling tax off/on flips config.tax_enabled, marks tax_configured, and
  is immediately reflected by TaxService — WITHOUT touching TaxRate rows.
- owner_setup_save_tax saves the flag + rates; disabling doesn't need to
  deactivate anything for tax to actually stop.
- Everything stays tenant-scoped.
"""

from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model

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


class OwnerToggleTaxTest(TestCase):
    """owner_toggle_tax() flips the config flag — the single source of truth."""

    def setUp(self):
        self.tenant, self.user = _make_tenant_owner("toggle1")
        self.client.force_login(self.user)
        self.rate = TaxRate.objects.create(
            tenant=self.tenant,
            city="Little Rock",
            state="AR",
            state_rate=Decimal("6.5"),
            city_rate=Decimal("1.0"),
            is_active=True,
        )

    def test_toggle_off_disables_tax_without_touching_rates(self):
        response = self.client.post("/owner/tax-rates/toggle/")
        self.assertIn(response.status_code, [301, 302])

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)
        self.assertTrue(config.tax_configured, "answering the toggle counts as configuring")

        # TaxRate rows are rate storage only — they stay as they were
        self.rate.refresh_from_db()
        self.assertTrue(self.rate.is_active)

    def test_toggle_off_makes_is_tax_enabled_return_false(self):
        """Tax genuinely stops when the flag flips — active rows or not."""
        self.client.post("/owner/tax-rates/toggle/")
        svc = TaxService(tenant=self.tenant)
        self.assertFalse(svc.is_tax_enabled(tenant=self.tenant))
        result = svc.calculate_tax(subtotal=Decimal("100.00"))
        self.assertEqual(result["amount"], Decimal("0.00"))

    def test_toggle_on_enables_tax(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = False
        config.save()

        self.client.post("/owner/tax-rates/toggle/")

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)
        svc = TaxService(tenant=self.tenant)
        self.assertTrue(svc.is_tax_enabled(tenant=self.tenant))
        # Rate comes from the tenant's TaxRate row
        result = svc.calculate_tax(subtotal=Decimal("100.00"))
        self.assertEqual(result["rate"], Decimal("7.500"))

    def test_toggle_is_tenant_scoped(self):
        """Toggling tenant A must not change tenant B's tax state."""
        tenant_b, _user_b = _make_tenant_owner("toggle_b")

        self.client.post("/owner/tax-rates/toggle/")

        config_b = BillingConfig.get_for_tenant(tenant_b)
        self.assertTrue(config_b.tax_enabled, "Other tenant's config must be unaffected")

    def test_toggle_off_no_taxrates_still_updates_billing_config(self):
        self.rate.delete()
        self.client.post("/owner/tax-rates/toggle/")
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)


class OwnerSetupSaveTaxTest(TestCase):
    """owner_setup_save_tax() saves the flag + rates under the new contract."""

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

    def test_setup_save_tax_disabled_stops_tax(self):
        """Saving tax_enabled=0 stops tax via the config flag alone."""
        response = self._post_setup_tax(tax_enabled="0")
        self.assertEqual(response.status_code, 200)

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)
        self.assertTrue(config.tax_configured)

        svc = TaxService(tenant=self.tenant)
        self.assertFalse(svc.is_tax_enabled(tenant=self.tenant))
        # The rate row is untouched — it's just storage now
        self.rate.refresh_from_db()
        self.assertTrue(self.rate.is_active)

    def test_setup_save_tax_enabled_creates_taxrate(self):
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

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.tax_enabled)
        self.assertTrue(config.tax_configured)

    def test_setup_save_tax_enabled_updates_existing_rate_in_place(self):
        """Re-saving updates the tenant's single row — no duplicates."""
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

        self.assertEqual(TaxRate.objects.filter(tenant=self.tenant).count(), 1)
        self.rate.refresh_from_db()
        self.assertTrue(self.rate.is_active)
        self.assertEqual(self.rate.city_rate, Decimal("1.0"))

    def test_setup_save_tax_disabled_does_not_affect_other_tenant(self):
        tenant_b, _ = _make_tenant_owner("setup_b")
        rate_b = TaxRate.objects.create(
            tenant=tenant_b,
            city="Conway",
            state="AR",
            state_rate=Decimal("6.5"),
            is_active=True,
        )

        self._post_setup_tax(tax_enabled="0")

        config_b = BillingConfig.get_for_tenant(tenant_b)
        self.assertTrue(config_b.tax_enabled, "Other tenant's config must be unaffected")
        rate_b.refresh_from_db()
        self.assertTrue(rate_b.is_active)
