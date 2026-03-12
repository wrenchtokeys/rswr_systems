"""
Regression tests for UX-009: Team Settings "Repairs" role badge on owners.

Root cause:
  - Owner-role team members were showing "Repairs" and "Replacements" ability badges
    in Settings → Team, alongside the "Owner" role badge.
  - Owners have all permissions by definition; showing ability badges for them is
    redundant and visually noisy.
  - The "Repairs" icon also used `fa-tools` (described as scissors-like by reviewer).

Fix (owner_settings.html):
  - Wrapped ability badge block in `{% if member.role != 'owner' %}` guard.
  - Changed Repairs badge icon from `fa-tools` to `fa-wrench` for clarity.
  - Ability badges now only render for technician / manager / viewer roles.
"""
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_plan(slug='trial'):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=slug,
        defaults={
            'name': slug.title(),
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    return plan


def _make_tenant_with_owner(name, slug):
    plan = _make_plan()
    user = User.objects.create_user(
        slug, f'{slug}@test.com', 'testpass123',
        first_name='Owner', last_name='User',
    )
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=user,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


def _add_member(tenant, username, role, can_repair=True, can_replace=True):
    """Create a user + TenantMembership + Technician record for the tenant."""
    user = User.objects.create_user(
        username, f'{username}@test.com', 'testpass123',
        first_name='Test', last_name=username.title(),
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role=role)
    tech = Technician.objects.create(
        user=user, tenant=tenant,
        can_repair=can_repair,
        can_replace=can_replace,
        is_active=True,
    )
    return user, tech


@override_settings(**TEST_OVERRIDES)
class OwnerBadgesNotShownForOwnerRoleTest(TestCase):
    """Owner-role members should NOT show ability badges (Repairs / Replacements)."""

    def setUp(self):
        self.owner_user, self.tenant = _make_tenant_with_owner('Badge Co', 'badgeco')
        # Give the owner user a technician record with both abilities
        self.owner_tech = Technician.objects.create(
            user=self.owner_user, tenant=self.tenant,
            can_repair=True, can_replace=True, is_active=True,
        )
        self.client = Client()
        self.client.force_login(self.owner_user)

    def test_settings_page_loads(self):
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)

    def test_owner_role_badge_renders(self):
        """The "Owner" role badge must still appear."""
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Owner')

    def test_ability_badges_not_shown_for_owner_role(self):
        """When user has role=owner, the Repairs/Replacements badges must NOT render.

        Because the page uses a Django template condition, we can't easily distinguish
        which row the badge belongs to when there is only one member.  We verify by
        ensuring the page does not contain the ability-badge markup that would only
        appear for an owner (we add a second owner member and no tech-role members).
        """
        # Add a second owner-role member with can_repair
        second_owner, _ = _add_member(self.tenant, 'owner2badge', 'owner', can_repair=True, can_replace=False)
        resp = self.client.get('/owner/settings/')
        content = resp.content.decode()
        # The template guard `member.role != 'owner'` means no Repairs badge
        # should appear since ALL members in this test are owners.
        # "Repairs" text in the badge div has a specific class pair:
        self.assertNotIn('bg-amber-100 text-amber-800', content)

    def test_wrench_icon_used_not_tools(self):
        """Repairs badge should use fa-wrench icon (not fa-tools)."""
        # Add a technician-role member so the Repairs badge CAN render
        _add_member(self.tenant, 'tech_wrench_test', 'technician', can_repair=True)
        resp = self.client.get('/owner/settings/')
        content = resp.content.decode()
        self.assertIn('fa-wrench', content)
        self.assertNotIn('fa-tools', content)


@override_settings(**TEST_OVERRIDES)
class TechnicianAbilityBadgesStillRenderTest(TestCase):
    """Technician-role members SHOULD still show ability badges."""

    def setUp(self):
        self.owner_user, self.tenant = _make_tenant_with_owner('TechBadge Co', 'techbadgeco')
        self.client = Client()
        self.client.force_login(self.owner_user)

    def test_repairs_badge_shown_for_technician_with_can_repair(self):
        """Technician with can_repair=True must show the Repairs badge."""
        _add_member(self.tenant, 'techrepair', 'technician', can_repair=True, can_replace=False)
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Repairs')
        self.assertContains(resp, 'bg-amber-100 text-amber-800')

    def test_replacements_badge_shown_for_technician_with_can_replace(self):
        """Technician with can_replace=True must show the Replacements badge."""
        _add_member(self.tenant, 'techreplace', 'technician', can_repair=False, can_replace=True)
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Replacements')
        self.assertContains(resp, 'bg-teal-100 text-teal-800')

    def test_no_ability_badges_when_technician_has_neither(self):
        """Technician with both False must show neither badge."""
        _add_member(self.tenant, 'techneither', 'technician', can_repair=False, can_replace=False)
        resp = self.client.get('/owner/settings/')
        # The amber and teal badge classes should not appear
        self.assertNotIn('bg-amber-100 text-amber-800', resp.content.decode())
        self.assertNotIn('bg-teal-100 text-teal-800', resp.content.decode())

    def test_manager_role_shows_ability_badges(self):
        """Manager-role member with can_repair should still show Repairs badge."""
        _add_member(self.tenant, 'mgr_badges', 'manager', can_repair=True, can_replace=True)
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Repairs')
        self.assertContains(resp, 'Replacements')
