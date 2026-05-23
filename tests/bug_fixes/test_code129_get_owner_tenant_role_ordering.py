"""
CODE-129: _get_owner_tenant() used .order_by('role') — alphabetical, not priority.

Bug:
- _get_owner_tenant() in apps/saas/views.py is called with no tenant context when
  the tenant middleware fails to resolve a tenant from the request.
- The fallback branch filtered TenantMembership to role__in=['owner', 'manager']
  and called .order_by('role') to pick the "best" membership.
- Alphabetical ordering puts 'manager' before 'owner' (m < o).
- A user who is an **owner** at Shop A AND a **manager** at Shop B would get the
  manager-at-Shop-B membership returned instead of the owner-at-Shop-A one.
- This means the owner dashboard would silently show Shop B data instead of Shop A.

Fix (CODE-129):
- Replace .order_by('role') with an annotated priority ordering (owner=0, manager=1),
  consistent with the priority logic already used in common.auth._get_membership.

Tests:
1. Single-owner user → returns owner membership (unchanged, regression guard).
2. Single-manager user → returns manager membership.
3. Owner at Shop A + manager at Shop B → returns OWNER (Shop A), not manager (Shop B).
4. Manager at Shop A + owner at Shop B → returns OWNER (Shop B), not manager (Shop A).
5. Viewer/technician user → returns (None, None).
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership


def _make_request(user):
    """Authenticated request with NO tenant context (tests the fallback branch)."""
    factory = RequestFactory()
    request = factory.get('/owner/')
    request.user = user
    # Deliberately do NOT set request.tenant — tests the no-tenant fallback branch.
    return request


class GetOwnerTenantRoleOrderingTest(TestCase):
    """Regression tests for CODE-129: _get_owner_tenant() role priority ordering."""

    def setUp(self):
        from apps.saas.views import _get_owner_tenant
        self._get_owner_tenant = _get_owner_tenant

        # Shop A — our "primary" shop
        self.owner_a = User.objects.create_user(
            username='owner_a_129', email='owner_a_129@example.com', password='pass'
        )
        self.shop_a = Tenant.objects.create(
            name='Shop A 129', slug='shop-a-129', plan='starter', is_active=True,
            owner=self.owner_a,
        )

        # Shop B — secondary shop
        self.owner_b = User.objects.create_user(
            username='owner_b_129', email='owner_b_129@example.com', password='pass'
        )
        self.shop_b = Tenant.objects.create(
            name='Shop B 129', slug='shop-b-129', plan='starter', is_active=True,
            owner=self.owner_b,
        )

        # Multi-shop user (the bug target)
        self.multi_user = User.objects.create_user(
            username='multi_129', email='multi_129@example.com', password='pass'
        )

    # -----------------------------------------------------------------
    # 1. Single owner — baseline regression guard
    # -----------------------------------------------------------------
    def test_single_owner_returns_correct_membership(self):
        TenantMembership.objects.create(
            user=self.owner_a, tenant=self.shop_a, role='owner', is_active=True,
        )
        request = _make_request(self.owner_a)
        tenant, membership = self._get_owner_tenant(request)
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant, self.shop_a)
        self.assertEqual(membership.role, 'owner')

    # -----------------------------------------------------------------
    # 2. Single manager — should work fine
    # -----------------------------------------------------------------
    def test_single_manager_returns_correct_membership(self):
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_a, role='manager', is_active=True,
        )
        request = _make_request(self.multi_user)
        tenant, membership = self._get_owner_tenant(request)
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant, self.shop_a)
        self.assertEqual(membership.role, 'manager')

    # -----------------------------------------------------------------
    # 3. Owner at Shop A + manager at Shop B → must return OWNER (Shop A)
    #    This is the core regression: alphabetical order would return 'manager'.
    # -----------------------------------------------------------------
    def test_owner_beats_manager_in_fallback_branch(self):
        """CODE-129 core: owner role must win over manager in alphabetical order."""
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_a, role='owner', is_active=True,
        )
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_b, role='manager', is_active=True,
        )
        request = _make_request(self.multi_user)
        tenant, membership = self._get_owner_tenant(request)
        self.assertIsNotNone(tenant, "Expected a tenant to be returned")
        self.assertEqual(membership.role, 'owner',
            "Expected owner role to win over manager (alphabetical order would "
            "return 'manager' first — CODE-129 regression)")
        self.assertEqual(tenant, self.shop_a,
            "Expected Shop A (where user is owner) not Shop B (where manager)")

    # -----------------------------------------------------------------
    # 4. Manager at Shop A + owner at Shop B → must return OWNER (Shop B)
    # -----------------------------------------------------------------
    def test_owner_beats_manager_regardless_of_insert_order(self):
        """Owner always wins even when manager membership was inserted first."""
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_a, role='manager', is_active=True,
        )
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_b, role='owner', is_active=True,
        )
        request = _make_request(self.multi_user)
        tenant, membership = self._get_owner_tenant(request)
        self.assertIsNotNone(tenant)
        self.assertEqual(membership.role, 'owner')
        self.assertEqual(tenant, self.shop_b)

    # -----------------------------------------------------------------
    # 5. Viewer / technician → (None, None)
    # -----------------------------------------------------------------
    def test_viewer_returns_none(self):
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_a, role='viewer', is_active=True,
        )
        request = _make_request(self.multi_user)
        tenant, membership = self._get_owner_tenant(request)
        self.assertIsNone(tenant)
        self.assertIsNone(membership)

    def test_technician_returns_none(self):
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_a, role='technician', is_active=True,
        )
        request = _make_request(self.multi_user)
        tenant, membership = self._get_owner_tenant(request)
        self.assertIsNone(tenant)
        self.assertIsNone(membership)

    # -----------------------------------------------------------------
    # 6. Inactive memberships are ignored
    # -----------------------------------------------------------------
    def test_inactive_memberships_are_ignored(self):
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_a, role='owner', is_active=False,
        )
        TenantMembership.objects.create(
            user=self.multi_user, tenant=self.shop_b, role='manager', is_active=True,
        )
        request = _make_request(self.multi_user)
        tenant, membership = self._get_owner_tenant(request)
        # Only the active manager membership should be returned
        self.assertIsNotNone(tenant)
        self.assertEqual(membership.role, 'manager')
        self.assertEqual(tenant, self.shop_b)
