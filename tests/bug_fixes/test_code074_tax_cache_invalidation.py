"""
Regression tests for CODE-074:
  owner_settings_view (tax form) and owner_toggle_tax both called
  cache.delete('billing_config_tax') — the old global singleton key.

Root cause:
    tax_service.py uses tenant-scoped cache keys: f'billing_config_tax_{tenant.pk}'
    (changed when BillingConfig became per-tenant). The two call sites in
    saas/views.py were never updated to match.

    After saving tax settings or toggling tax enabled/disabled:
      - The old global key was deleted (had no effect — nothing stored there).
      - The real tenant-scoped key was NOT deleted.
      - TaxService._get_billing_config() returned the stale cached copy
        for up to 5 minutes, so a shop owner toggling tax off would still
        have tax applied to new repairs/invoices during the cache window.

Fix (CODE-074):
    Changed both cache.delete calls to use f'billing_config_tax_{tenant.pk}'.

Tests verify:
    1. After toggling tax via owner_toggle_tax, the tenant-scoped cache key
       is cleared (not present) — confirmed by seeding the cache first.
    2. After saving tax settings via owner_settings_view (billing form),
       the tenant-scoped cache key is cleared.
    3. A DIFFERENT tenant's cache key is NOT cleared (isolation).
    4. Toggling tax from enabled → disabled updates BillingConfig.tax_enabled.
    5. Toggling tax from disabled → enabled updates BillingConfig.tax_enabled.
    6. After toggle, TaxService reflects the updated value (not stale cache).
    7. After settings save, TaxService reflects the updated rate (not stale cache).
    8. Non-POST request to owner_toggle_tax redirects without clearing cache.
"""

import uuid

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.billing.models import BillingConfig
from apps.billing.services.tax_service import TaxService
from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership


def _make_tenant_and_owner(username_suffix=""):
    """Helper: create a Tenant + owner user + BillingConfig."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name="starter",
        defaults={
            "monthly_price": 0,
            "annual_price": 0,
            "max_technicians": 5,
            "max_customers": 50,
        },
    )
    # Tenant requires owner FK — create user first with a placeholder, then update
    temp_user = User.objects.create_user(
        username=f"temp_{username_suffix}_{uuid.uuid4().hex[:6]}",
        password="pass",
    )
    tenant = Tenant.objects.create(
        name=f"Test Shop {username_suffix}",
        subdomain=f"test-shop-{username_suffix}-{uuid.uuid4().hex[:6]}",
        subscription_plan=plan,
        subscription_status="active",
        owner=temp_user,
    )
    user = User.objects.create_user(
        username=f"owner_{username_suffix}_{uuid.uuid4().hex[:6]}",
        password="pass",
        email=f"owner_{username_suffix}@example.com",
    )
    tenant.owner = user
    tenant.save(update_fields=["owner"])
    TenantMembership.objects.create(
        user=user,
        tenant=tenant,
        role="owner",
        is_active=True,
    )
    config = BillingConfig.get_for_tenant(tenant)
    config.tax_enabled = True
    config.default_tax_rate = 9.5
    config.save()
    return tenant, user, config


class TaxCacheInvalidationToggleTests(TestCase):
    """Tests for owner_toggle_tax cache invalidation (CODE-074)."""

    def setUp(self):
        self.tenant, self.user, self.config = _make_tenant_and_owner("toggle")
        self.client.login(username=self.user.username, password="pass")

    def tearDown(self):
        cache.delete(f"billing_config_tax_{self.tenant.pk}")

    def _seed_cache(self, tenant=None):
        """Put a stale value into the tenant-scoped cache key."""
        t = tenant or self.tenant
        cache.set(f"billing_config_tax_{t.pk}", "STALE", 300)

    # --- Test 1: toggle clears tenant-scoped cache key ---
    def test_toggle_clears_tenant_cache_key(self):
        """After toggle, tenant-scoped cache key is gone."""
        self._seed_cache()
        self.assertIsNotNone(cache.get(f"billing_config_tax_{self.tenant.pk}"))

        response = self.client.post("/owner/tax-rates/toggle/")
        self.assertIn(response.status_code, [200, 302])

        self.assertIsNone(
            cache.get(f"billing_config_tax_{self.tenant.pk}"),
            "Tenant-scoped cache key should be cleared after toggle",
        )

    # --- Test 2: toggle does NOT clear a different tenant's cache ---
    def test_toggle_does_not_clear_other_tenant_cache(self):
        """Cache invalidation is scoped to current tenant only."""
        other_tenant, other_user, _ = _make_tenant_and_owner("other")
        self._seed_cache(other_tenant)

        self.client.post("/owner/tax-rates/toggle/")

        self.assertIsNotNone(
            cache.get(f"billing_config_tax_{other_tenant.pk}"),
            "Other tenant's cache key should NOT be touched",
        )
        # Cleanup
        cache.delete(f"billing_config_tax_{other_tenant.pk}")

    # --- Test 3: toggle enabled → disabled ---
    def test_toggle_enabled_to_disabled(self):
        """Toggle from enabled saves disabled status."""
        self.config.tax_enabled = True
        self.config.save()

        self.client.post("/owner/tax-rates/toggle/")

        self.config.refresh_from_db()
        self.assertFalse(self.config.tax_enabled)

    # --- Test 4: toggle disabled → enabled ---
    def test_toggle_disabled_to_enabled(self):
        """Toggle from disabled saves enabled status."""
        self.config.tax_enabled = False
        self.config.save()

        self.client.post("/owner/tax-rates/toggle/")

        self.config.refresh_from_db()
        self.assertTrue(self.config.tax_enabled)

    # --- Test 5: TaxService reflects updated value after toggle ---
    def test_tax_service_reflects_toggle(self):
        """After toggling off, TaxService reports tax_enabled=False (not cached stale)."""
        # Enable and warm the cache
        self.config.tax_enabled = True
        self.config.save()
        svc = TaxService(tenant=self.tenant)
        svc._get_billing_config()  # warm cache

        # Now toggle off — this should clear the tenant-scoped key
        self.client.post("/owner/tax-rates/toggle/")

        # Fresh TaxService call should see disabled
        svc2 = TaxService(tenant=self.tenant)
        cfg = svc2._get_billing_config()
        self.assertFalse(cfg.tax_enabled, "TaxService should load fresh config (not stale cache) after toggle")

    # --- Test 6: non-POST request does NOT clear cache ---
    def test_get_request_no_cache_clear(self):
        """GET to toggle endpoint redirects without clearing cache."""
        self._seed_cache()

        self.client.get("/owner/tax-rates/toggle/")

        self.assertIsNotNone(
            cache.get(f"billing_config_tax_{self.tenant.pk}"),
            "GET request should not clear cache (only POST does the toggle)",
        )


class TaxCacheInvalidationSettingsTests(TestCase):
    """Tests for owner_settings_view billing form cache invalidation (CODE-074)."""

    def setUp(self):
        self.tenant, self.user, self.config = _make_tenant_and_owner("settings")
        self.client.login(username=self.user.username, password="pass")

    def tearDown(self):
        cache.delete(f"billing_config_tax_{self.tenant.pk}")

    def _seed_cache(self):
        cache.set(f"billing_config_tax_{self.tenant.pk}", "STALE", 300)

    def _post_billing_form(self, overrides=None):
        """POST to owner_settings_view with the billing_location sub-form."""
        data = {
            "form_type": "billing_location",
            "company_city": "Little Rock",
            "company_state": "AR",
            "company_zip": "72201",
            "state_tax_rate": "6.500",
            "county_tax_rate": "1.000",
            "city_tax_rate": "0.500",
            "special_tax_rate": "0",
        }
        if overrides:
            data.update(overrides)
        return self.client.post("/owner/settings/", data)

    # --- Test 7: settings billing form clears tenant-scoped cache ---
    def test_billing_form_clears_tenant_cache_key(self):
        """After saving billing settings, tenant-scoped cache key is cleared."""
        self._seed_cache()
        self.assertIsNotNone(cache.get(f"billing_config_tax_{self.tenant.pk}"))

        self._post_billing_form()

        self.assertIsNone(
            cache.get(f"billing_config_tax_{self.tenant.pk}"),
            "Tenant-scoped cache key should be cleared after billing form save",
        )

    # --- Test 8: TaxService reflects updated rate after settings save ---
    def test_tax_service_reflects_settings_save(self):
        """After saving new rates via the tax_settings form, TaxService
        returns the updated rate (not stale cache). The billing_location form
        is address-only now, so rate changes go through tax_settings."""
        # Warm cache with old rate
        self.config.default_tax_rate = 5.0
        self.config.state_tax_rate = 5.0
        self.config.save()
        svc = TaxService(tenant=self.tenant)
        svc._get_billing_config()  # warm cache

        # Save new rates via the tax settings form
        self.client.post("/owner/settings/", {
            "form_type": "tax_settings",
            "charges_tax": "yes",
            "tax_rate_percent": "",
            "state_tax_rate": "6.500",
            "county_tax_rate": "1.500",
            "city_tax_rate": "0.500",
            "special_tax_rate": "0",
        })

        # Fresh TaxService should get new total (8.5%)
        svc2 = TaxService(tenant=self.tenant)
        cfg = svc2._get_billing_config()
        self.assertAlmostEqual(
            float(cfg.default_tax_rate), 8.5, places=1,
            msg="TaxService should return fresh config with updated rate after settings save",
        )
