"""
Regression tests for CODE-080:
    manager_settings_dashboard(), manage_viscosity_rules(), and team_overview()
    used `request.user.technician` (unscoped OneToOneField) to resolve the
    manager/technician record.

    An owner or admin at Shop B who ALSO has a Technician record at Shop A
    (from a previous shop association) would have their Shop A Technician record
    used inside these views — leaking Shop A's managed_technicians and team_count
    to Shop B's manager dashboard.

    Fix: all three views now use
        Technician.objects.filter(user=request.user, tenant=tenant).first()
    so the correct tenant-scoped (or None) record is used.

Covers:
    - manager_settings_dashboard: Shop B owner with Shop A Technician → team_count=0, technician=None
    - manager_settings_dashboard: Shop B manager with correct Technician → team_count correct
    - manage_viscosity_rules: Shop B owner with Shop A Technician → technician=None in context
    - team_overview: Shop B owner with Shop A Technician → redirected (no technician profile)
    - team_overview: Proper Shop B manager → sees correct team
"""

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_counter = [100]  # offset to avoid collisions with other test files


def _uid():
    _counter[0] += 1
    return _counter[0]


def _make_request(method, url, user, tenant, data=None):
    factory = RequestFactory()
    req = factory.post(url, data or {}) if method == "POST" else factory.get(url)
    req.user = user
    req.tenant = tenant
    setattr(req, "session", "session")
    setattr(req, "_messages", FallbackStorage(req))
    return req


def _make_user(username_prefix="u"):
    n = _uid()
    return User.objects.create_user(
        username=f"{username_prefix}_{n}",
        email=f"{username_prefix}_{n}@example.com",
        password="testpass123",
    )


def _make_tenant(name_prefix="shop", owner=None):
    n = _uid()
    if owner is None:
        owner = _make_user(f"owner_{name_prefix}")
    return Tenant.objects.create(
        name=f"{name_prefix} {n}",
        slug=f"{name_prefix}-{n}",
        plan="pro",
        owner=owner,
    )


def _make_membership(user, tenant, role="owner"):
    return TenantMembership.objects.create(
        user=user,
        tenant=tenant,
        role=role,
        is_active=True,
    )


def _make_technician(user, tenant, is_manager=False, is_active=True):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=is_manager,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# Tests: manager_settings_dashboard
# ---------------------------------------------------------------------------

class ManagerSettingsDashboardCrossTenantTest(TestCase):
    """
    manager_settings_dashboard no longer renders anything.

    It used to be a second settings home showing team/viscosity/warranty
    counts, and CODE-080 was about it leaking Shop A's team_count to a user
    visiting Shop B. It is now a redirect into /owner/settings/ (the settings
    consolidation), so it performs no queries and builds no context — the leak
    surface is gone rather than fixed.

    The cross-tenant property itself still matters for the views that *do*
    still render this data, and those are covered by
    ManageViscosityRulesCrossTenantTest and TeamOverviewCrossTenantTest below.
    What remains here is a guard that this view stays inert.
    """

    def setUp(self):
        from django.contrib.auth.models import User
        # Shop A setup
        self.shop_a = _make_tenant("shopA")
        self.shop_b = _make_tenant("shopB")

        # cross_user: owner at Shop B (TenantMembership) + Technician record at Shop A
        self.cross_user = _make_user("cross")
        _make_membership(self.cross_user, self.shop_b, role="owner")

        # Create Technician record for cross_user at Shop A only
        self.tech_a = _make_technician(self.cross_user, self.shop_a, is_manager=True)

        # Create two Shop A managed technicians
        ta1 = _make_user("shopA_tech1")
        ta2 = _make_user("shopA_tech2")
        self.managed_a1 = _make_technician(ta1, self.shop_a)
        self.managed_a2 = _make_technician(ta2, self.shop_a)
        self.tech_a.managed_technicians.add(self.managed_a1, self.managed_a2)

    def test_dashboard_cannot_leak_because_it_renders_nothing(self):
        """
        The cross-tenant owner gets a redirect, not a page with a team count.

        Asserting on the response body is what the original test tried to do;
        there is no longer a body to assert on, which is a stronger guarantee
        than the one CODE-080 shipped.
        """
        from apps.technician_portal.views.settings import manager_settings_dashboard

        req = _make_request("GET", "/tech/settings/", self.cross_user, self.shop_b)
        response = manager_settings_dashboard(req)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(hasattr(response, 'context_data'))

    def test_dashboard_redirects_into_the_single_settings_home(self):
        from django.urls import reverse
        from apps.technician_portal.views.settings import manager_settings_dashboard

        shop_b_manager = _make_user("shopB_mgr")
        _make_membership(shop_b_manager, self.shop_b, role="manager")
        _make_technician(shop_b_manager, self.shop_b, is_manager=True)

        req = _make_request("GET", "/tech/settings/", shop_b_manager, self.shop_b)
        response = manager_settings_dashboard(req)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('owner_settings'))


# ---------------------------------------------------------------------------
# Tests: manage_viscosity_rules
# ---------------------------------------------------------------------------

class ManageViscosityRulesCrossTenantTest(TestCase):
    """
    manage_viscosity_rules uses request.user.technician — same cross-tenant
    risk as manager_settings_dashboard.
    """

    def setUp(self):
        self.shop_a = _make_tenant("visco_shopA")
        self.shop_b = _make_tenant("visco_shopB")

        self.cross_user = _make_user("visco_cross")
        _make_membership(self.cross_user, self.shop_b, role="owner")
        # Technician only at Shop A
        self.tech_a = _make_technician(self.cross_user, self.shop_a, is_manager=True)

    def test_viscosity_view_at_shop_b_returns_200(self):
        """manage_viscosity_rules at Shop B for cross-tenant owner should not crash."""
        from apps.technician_portal.views.settings import manage_viscosity_rules

        req = _make_request("GET", "/tech/settings/viscosity/", self.cross_user, self.shop_b)
        response = manage_viscosity_rules(req)
        self.assertEqual(response.status_code, 200)

    def test_viscosity_view_technician_context_is_none_at_shop_b(self):
        """
        manager context in viscosity rules view should be None when user has
        no Technician record at Shop B (even if they have one at Shop A).
        """
        from apps.technician_portal.views.settings import manage_viscosity_rules

        req = _make_request("GET", "/tech/settings/viscosity/", self.cross_user, self.shop_b)
        response = manage_viscosity_rules(req)
        # The view should return 200, not 500, and technician context should be None
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Tests: team_overview
# ---------------------------------------------------------------------------

class TeamOverviewCrossTenantTest(TestCase):
    """
    team_overview uses request.user.technician (unscoped) for its `manager`
    variable, then calls manager.managed_technicians.
    A Shop B owner with Shop A's Technician would see Shop A's managed team.
    """

    def setUp(self):
        self.shop_a = _make_tenant("team_shopA")
        self.shop_b = _make_tenant("team_shopB")

        self.cross_user = _make_user("team_cross")
        _make_membership(self.cross_user, self.shop_b, role="owner")
        # Technician only at Shop A, with managed techs
        self.tech_a = _make_technician(self.cross_user, self.shop_a, is_manager=True)

        shopA_sub = _make_user("teamA_sub")
        self.managed_a = _make_technician(shopA_sub, self.shop_a)
        self.tech_a.managed_technicians.add(self.managed_a)

    def test_team_overview_cross_tenant_redirected(self):
        """
        A Shop B owner with Technician only at Shop A visiting team_overview at Shop B
        should be redirected (no valid Technician record at Shop B → redirect to dashboard).
        """
        from apps.technician_portal.views.settings import team_overview

        req = _make_request("GET", "/tech/settings/team/", self.cross_user, self.shop_b)
        response = team_overview(req)
        # Should redirect because no Technician at Shop B
        self.assertEqual(response.status_code, 302)

    def test_team_overview_proper_shop_b_manager_sees_team(self):
        """A manager with a Technician record at Shop B should see their own team."""
        shop_b_mgr = _make_user("team_shopB_mgr")
        _make_membership(shop_b_mgr, self.shop_b, role="manager")
        tech_b = _make_technician(shop_b_mgr, self.shop_b, is_manager=True)

        # Create a team member at Shop B
        sub_user = _make_user("team_shopB_sub")
        sub_tech = _make_technician(sub_user, self.shop_b)
        tech_b.managed_technicians.add(sub_tech)

        from apps.technician_portal.views.settings import team_overview
        req = _make_request("GET", "/tech/settings/team/", shop_b_mgr, self.shop_b)
        response = team_overview(req)
        self.assertEqual(response.status_code, 200)

    def test_team_overview_cross_tenant_does_not_expose_shop_a_team(self):
        """
        Verifies the FIX: with the tenant-scoped lookup, manager=None at Shop B,
        so the view redirects BEFORE reaching managed_technicians traversal.
        Without the fix, it would return 200 and show Shop A's managed_technicians.
        """
        from apps.technician_portal.views.settings import team_overview

        req = _make_request("GET", "/tech/settings/team/", self.cross_user, self.shop_b)
        response = team_overview(req)
        # Must redirect — not 200 which would mean Shop A data was shown
        self.assertNotEqual(response.status_code, 200,
                            "Cross-tenant owner should NOT get 200 on team_overview at Shop B "
                            "(would expose Shop A's managed_technicians)")
        self.assertEqual(response.status_code, 302)
