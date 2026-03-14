"""
Regression tests for CODE-020: update_team_member() cross-tenant Technician corruption.

Bug:
  apps/saas/views.update_team_member() used:

      tech, created = Technician.objects.get_or_create(user=target.user, ...)
      if not created:
          tech.tenant = tenant  # <-- WRONG: rewrites foreign tenant
          tech.save()

  Technician.user is a OneToOneField, so get_or_create(user=...) returns the
  FIRST matching record regardless of tenant.  If a user is a Technician at
  Shop B and an owner of Shop A promotes them to manager via update_team_member,
  the code fetched Shop B's Technician record, set tech.tenant = Shop A, and
  saved — silently stealing that record from Shop B.

  The deactivation branch had the same issue: it called
  Technician.objects.get(user=target.user) without a tenant filter, so moving a
  user away from tech/manager in Shop A could deactivate their Technician record
  that actually belonged to Shop B.

Fix:
  - Promote path: try Technician.objects.get(user=, tenant=) first; only create
    if no record for THIS tenant; if a foreign record exists, log and skip.
  - Demotion path: Technician.objects.get(user=, tenant=) — scoped.

Note on model constraint:
  Technician.user is a OneToOneField, meaning a User can only have ONE Technician
  record across ALL tenants.  This is a design limitation; the tests here verify
  the view handles the cross-tenant collision gracefully rather than silently
  corrupting the foreign record.
"""

import logging
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial",
        defaults={
            "name": "Trial",
            "monthly_price": Decimal("0.00"),
            "trial_days": 30,
            "is_active": True,
            "display_order": 0,
        },
    )
    return plan


def _make_tenant(name, slug, owner):
    return Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan="trial",
        subscription_plan=_plan(),
    )


def _membership(user, tenant, role="owner"):
    return TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True
    )


def _make_user(username):
    return User.objects.create_user(
        username=username,
        password="pw",
        email=f"{username}@ex.com",
        first_name="Test",
        last_name="User",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class UpdateTeamMemberTenantScopeTests(TestCase):
    """update_team_member() must never touch Technician records from other tenants."""

    def setUp(self):
        # Two independent shops
        self.owner_a = _make_user("owner_a_020")
        self.owner_b = _make_user("owner_b_020")

        self.tenant_a = _make_tenant("Shop A 020", "shop-a-020", self.owner_a)
        self.tenant_b = _make_tenant("Shop B 020", "shop-b-020", self.owner_b)

        _membership(self.owner_a, self.tenant_a, "owner")
        _membership(self.owner_b, self.tenant_b, "owner")

        self.client_a = Client()
        self.client_a.force_login(self.owner_a)

        self.client_b = Client()
        self.client_b.force_login(self.owner_b)

    # ------------------------------------------------------------------
    # Scenario 1: Promote a fresh user (no prior Technician) — normal path
    # ------------------------------------------------------------------

    def test_promote_creates_technician_for_correct_tenant(self):
        """Promoting a brand-new viewer to technician creates a Technician for THIS tenant."""
        new_user = _make_user("newbie_020")
        mem = _membership(new_user, self.tenant_a, "viewer")

        resp = self.client_a.post(
            f"/owner/team/{mem.id}/update/",
            {"role": "technician", "can_repair": "on"},
        )
        self.assertIn(resp.status_code, [200, 302],
                      f"Expected redirect or 200, got {resp.status_code}")

        tech = Technician.objects.filter(user=new_user, tenant=self.tenant_a).first()
        self.assertIsNotNone(tech, "Technician record should be created for Shop A")
        self.assertEqual(tech.tenant, self.tenant_a)

    # ------------------------------------------------------------------
    # Scenario 2: User has Technician at Shop B; Shop A tries to promote
    # ------------------------------------------------------------------

    def test_promote_does_not_steal_foreign_technician_record(self):
        """
        If a user already has a Technician record for Shop B, promoting them
        at Shop A must NOT overwrite that record's tenant field.
        """
        shared_user = _make_user("shared_tech_020")

        # Shop B already has this user as a Technician
        tech_b = Technician.objects.create(
            user=shared_user,
            tenant=self.tenant_b,
            is_active=True,
            is_manager=False,
        )

        # Shop A adds them as a viewer, then owner promotes to technician
        mem_a = _membership(shared_user, self.tenant_a, "viewer")

        self.client_a.post(
            f"/owner/team/{mem_a.id}/update/",
            {"role": "technician", "can_repair": "on"},
        )

        # Shop B's Technician record must be untouched
        tech_b.refresh_from_db()
        self.assertEqual(
            tech_b.tenant, self.tenant_b,
            "Shop B's Technician.tenant must NOT be overwritten to Shop A",
        )
        self.assertTrue(tech_b.is_active, "Shop B's Technician must remain active")

    def test_promote_does_not_change_foreign_tech_is_manager(self):
        """Promoting at Shop A must not flip is_manager on the existing record from Shop B."""
        shared_user = _make_user("shared_mgr_020")

        tech_b = Technician.objects.create(
            user=shared_user,
            tenant=self.tenant_b,
            is_active=True,
            is_manager=False,
        )

        mem_a = _membership(shared_user, self.tenant_a, "viewer")

        self.client_a.post(
            f"/owner/team/{mem_a.id}/update/",
            {"role": "manager"},
        )

        tech_b.refresh_from_db()
        self.assertFalse(
            tech_b.is_manager,
            "Shop B's is_manager must not be changed by Shop A's promote action",
        )
        self.assertEqual(tech_b.tenant, self.tenant_b)

    # ------------------------------------------------------------------
    # Scenario 3: Same-tenant update works correctly
    # ------------------------------------------------------------------

    def test_promote_same_tenant_updates_in_place(self):
        """Updating an existing same-tenant Technician record updates flags in place."""
        user = _make_user("same_tenant_020")
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,
            is_active=True,
            is_manager=False,
            can_repair=True,
            can_replace=False,
        )
        mem = _membership(user, self.tenant_a, "technician")

        resp = self.client_a.post(
            f"/owner/team/{mem.id}/update/",
            {"role": "manager", "can_repair": "on", "can_replace": "on"},
        )
        self.assertIn(resp.status_code, [200, 302])

        tech.refresh_from_db()
        self.assertTrue(tech.is_manager, "is_manager should be updated to True")
        self.assertTrue(tech.can_replace, "can_replace should be updated to True")
        self.assertEqual(tech.tenant, self.tenant_a, "tenant must not change")

    def test_demote_deactivates_same_tenant_technician(self):
        """Moving a technician to viewer deactivates their Technician record for THIS tenant."""
        user = _make_user("demoted_020")
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,
            is_active=True,
            is_manager=False,
        )
        mem = _membership(user, self.tenant_a, "technician")

        self.client_a.post(
            f"/owner/team/{mem.id}/update/",
            {"role": "viewer"},
        )

        tech.refresh_from_db()
        self.assertFalse(tech.is_active, "Shop A's Technician should be deactivated")

    # ------------------------------------------------------------------
    # Scenario 4: Cross-tenant membership ID cannot be updated (URL auth)
    # ------------------------------------------------------------------

    def test_shop_b_cannot_update_shop_a_membership(self):
        """
        A Shop B owner cannot update a TenantMembership belonging to Shop A
        (get_object_or_404 tenant scoping).
        """
        user = _make_user("target_user_020")
        mem_a = _membership(user, self.tenant_a, "technician")

        resp = self.client_b.post(
            f"/owner/team/{mem_a.id}/update/",
            {"role": "viewer"},
        )
        # Should redirect away or 404 — membership doesn't belong to tenant_b
        self.assertIn(resp.status_code, [302, 404])
        # The membership for Shop A must be unchanged
        mem_a.refresh_from_db()
        self.assertEqual(mem_a.role, "technician",
                         "Shop A membership must not be changed by Shop B owner")

    # ------------------------------------------------------------------
    # Scenario 5: Verify the warning log is emitted for cross-tenant collision
    # ------------------------------------------------------------------

    def test_warning_logged_when_foreign_technician_exists(self):
        """
        When a user already has a foreign-tenant Technician record, the view
        must log a warning and skip creation (not raise or silently corrupt).
        """
        shared_user = _make_user("collision_warn_020")

        # User already has a Technician at Shop B
        Technician.objects.create(
            user=shared_user,
            tenant=self.tenant_b,
            is_active=True,
        )

        mem_a = _membership(shared_user, self.tenant_a, "viewer")

        with self.assertLogs("apps.saas.views", level=logging.WARNING) as log_cm:
            self.client_a.post(
                f"/owner/team/{mem_a.id}/update/",
                {"role": "technician", "can_repair": "on"},
            )

        # At least one warning about the collision should be present
        warning_found = any(
            "already has a Technician record" in msg for msg in log_cm.output
        )
        self.assertTrue(
            warning_found,
            "Expected a WARNING log about cross-tenant Technician collision, "
            f"but got: {log_cm.output}",
        )
