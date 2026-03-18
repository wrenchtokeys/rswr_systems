"""
Regression tests for CODE-077:
Unscoped request.user.technician.is_manager in repair_list / repair_detail

Root cause: repair_list used `request.user.technician` (OneToOneField, no
tenant filter) to decide whether to show REQUESTED repairs to the user.  A user
who is a manager at Shop A (Technician.tenant=Shop A, is_manager=True) but only
a plain technician at Shop B (TenantMembership only, no Technician record at
Shop B) would see Shop B's REQUESTED repairs because the old code resolved
`request.user.technician.is_manager` to Shop A's record.

Same issue applied to repair_detail: the permission check used
`technician.is_manager` resolved from `request.user.technician`, allowing a
cross-tenant manager to view REQUESTED repairs at Shop B.

Fix (mirrors CODE-076 / CODE-077):
    technician = Technician.objects.filter(user=request.user, tenant=tenant).first()
Both repair_list and repair_detail now use this scoped lookup before checking
is_manager.

Test scenarios:
1. Cross-tenant: user's Technician belongs to Shop A (is_manager=True). In
   Shop B context (no Technician record) they must NOT see REQUESTED repairs.
2. Legitimate manager at their own shop still sees REQUESTED repairs.
3. Plain technician at their shop does NOT see REQUESTED repairs.
4. repair_detail blocks cross-tenant manager from viewing a REQUESTED repair at Shop B.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(method, url, user, tenant, data=None):
    factory = RequestFactory()
    req = factory.post(url, data or {}) if method == 'POST' else factory.get(url)
    req.user = user
    req.tenant = tenant
    setattr(req, 'session', 'session')
    setattr(req, '_messages', FallbackStorage(req))
    return req


def _make_user(username):
    return User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password='testpass123',
    )


def _make_tenant(name, slug):
    owner = _make_user(f'owner_{slug}')
    tenant = Tenant.objects.create(name=name, slug=slug, subdomain=slug, owner=owner)
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant


def _make_tech(user, tenant, is_manager=False, is_active=True):
    return Technician.objects.create(
        user=user, tenant=tenant, is_manager=is_manager, is_active=is_active,
    )


def _make_membership(user, tenant, role='technician'):
    return TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True,
    )


def _make_repair(customer, tenant, status='REQUESTED', technician=None):
    return Repair.objects.create(
        customer=customer,
        tenant=tenant,
        technician=technician,
        unit_number='U-001',
        damage_type='CHIP',
        queue_status=status,
    )


# ---------------------------------------------------------------------------
# Unit: scoped lookup behaviour
# ---------------------------------------------------------------------------

class ScopedLookupTest(TestCase):
    """Verify the tenant-scoped Technician lookup used by the fix."""

    def setUp(self):
        self.shop_a = _make_tenant('Alpha', 'alpha-077')
        self.shop_b = _make_tenant('Beta', 'beta-077')
        self.user = _make_user('scoped_user_077')
        _make_membership(self.user, self.shop_a, role='technician')
        _make_tech(self.user, self.shop_a, is_manager=True)
        _make_membership(self.user, self.shop_b, role='technician')
        # NO Technician record at shop_b

    def test_scoped_returns_tech_at_home_tenant(self):
        tech = Technician.objects.filter(user=self.user, tenant=self.shop_a).first()
        self.assertIsNotNone(tech)
        self.assertTrue(tech.is_manager)

    def test_scoped_returns_none_at_foreign_tenant(self):
        tech = Technician.objects.filter(user=self.user, tenant=self.shop_b).first()
        self.assertIsNone(tech)
        self.assertFalse(bool(tech and tech.is_manager))

    def test_old_pattern_demonstrates_the_bug(self):
        """Old OneToOne pattern resolves to Shop A record — proves the bug existed."""
        old_mgr = hasattr(self.user, 'technician') and self.user.technician.is_manager
        self.assertTrue(old_mgr, "Old pattern returns True (demonstrates the bug)")
        # New pattern correctly returns False in Shop B context
        tech_b = Technician.objects.filter(user=self.user, tenant=self.shop_b).first()
        self.assertFalse(bool(tech_b and tech_b.is_manager))


# ---------------------------------------------------------------------------
# repair_list: cross-tenant manager blocked
# ---------------------------------------------------------------------------

class RepairListCrossTenantManagerTest(TestCase):
    """
    repair_list: user is manager at Shop A, plain technician at Shop B.
    Before fix: they could see REQUESTED repairs at Shop B.
    After fix:  they are redirected away (no Technician record at Shop B).
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-rlist')
        self.shop_b = _make_tenant('Shop B', 'shop-b-rlist')

        self.cross_user = _make_user('cross_mgr_rlist')
        _make_membership(self.cross_user, self.shop_a, role='technician')
        _make_tech(self.cross_user, self.shop_a, is_manager=True)
        _make_membership(self.cross_user, self.shop_b, role='technician')
        # NO Technician record at shop_b

        self.customer_b = Customer.objects.create(name='Shop B Fleet', tenant=self.shop_b)
        _make_repair(self.customer_b, self.shop_b, status='REQUESTED')

    def test_cross_tenant_manager_redirected_at_shop_b(self):
        """
        With the fix, the view detects no Technician record at Shop B and
        redirects instead of showing the repair list (which would include
        REQUESTED repairs the user should not see).
        """
        from apps.technician_portal.views.repairs import repair_list

        req = _make_request('GET', '/tech/repairs/', self.cross_user, self.shop_b)
        response = repair_list(req)
        # Should redirect because no Technician record at shop_b
        self.assertEqual(response.status_code, 302)


class RepairListLegitManagerTest(TestCase):
    """Legitimate manager at their own shop still sees REQUESTED repairs."""

    def setUp(self):
        self.shop = _make_tenant('Own Shop', 'own-shop-rlist')
        self.manager = _make_user('legit_mgr_rlist')
        _make_membership(self.manager, self.shop, role='technician')
        _make_tech(self.manager, self.shop, is_manager=True)
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.shop)
        _make_repair(self.customer, self.shop, status='REQUESTED')

    def test_legit_manager_sees_repair_list(self):
        from apps.technician_portal.views.repairs import repair_list

        req = _make_request('GET', '/tech/repairs/', self.manager, self.shop)
        response = repair_list(req)
        self.assertEqual(response.status_code, 200)


class RepairListPlainTechTest(TestCase):
    """Plain technician (is_manager=False) does NOT see REQUESTED repairs."""

    def setUp(self):
        self.shop = _make_tenant('Plain Shop', 'plain-shop-rlist')
        self.tech_user = _make_user('plain_tech_rlist')
        _make_membership(self.tech_user, self.shop, role='technician')
        self.tech = _make_tech(self.tech_user, self.shop, is_manager=False)
        self.customer = Customer.objects.create(name='Fleet Plain', tenant=self.shop)
        # Own repair (non-requested)
        _make_repair(self.customer, self.shop, status='APPROVED', technician=self.tech)
        # Requested repair (should be invisible to plain tech)
        _make_repair(self.customer, self.shop, status='REQUESTED')

    def test_plain_tech_sees_own_repairs_only(self):
        from apps.technician_portal.views.repairs import repair_list

        req = _make_request('GET', '/tech/repairs/', self.tech_user, self.shop)
        response = repair_list(req)
        self.assertEqual(response.status_code, 200)
        # The response should contain the plain tech's own repair but not REQUESTED
        content = response.content.decode()
        # Check that REQUESTED repairs are not visible; the approved repair should appear
        self.assertNotIn('REQUESTED', content.upper().replace('queue_status', ''))


# ---------------------------------------------------------------------------
# repair_detail: cross-tenant manager blocked on REQUESTED repair
# ---------------------------------------------------------------------------

class RepairDetailCrossTenantManagerTest(TestCase):
    """
    repair_detail: user is manager at Shop A, plain technician at Shop B.
    Viewing a REQUESTED repair at Shop B should redirect (not 200).
    Before fix: technician resolved to Shop A manager record → allowed through.
    After fix:  tenant-scoped lookup returns None → redirected.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-rdetail')
        self.shop_b = _make_tenant('Shop B', 'shop-b-rdetail')

        self.cross_user = _make_user('cross_mgr_rdetail')
        _make_membership(self.cross_user, self.shop_a, role='technician')
        _make_tech(self.cross_user, self.shop_a, is_manager=True)
        _make_membership(self.cross_user, self.shop_b, role='technician')
        # NO Technician record at shop_b

        self.customer_b = Customer.objects.create(name='Shop B Detail Fleet', tenant=self.shop_b)
        self.repair_b = _make_repair(self.customer_b, self.shop_b, status='REQUESTED')

    def test_cross_tenant_manager_blocked_on_shop_b_requested_repair(self):
        """
        After fix: no Technician record at Shop B → technician=None → redirect.
        """
        from apps.technician_portal.views.repairs import repair_detail

        req = _make_request('GET', f'/tech/repairs/{self.repair_b.id}/', self.cross_user, self.shop_b)
        response = repair_detail(req, self.repair_b.id)
        self.assertEqual(response.status_code, 302)


class RepairDetailLegitManagerTest(TestCase):
    """Legitimate manager at their own shop can view REQUESTED repairs."""

    def setUp(self):
        self.shop = _make_tenant('My Shop', 'my-shop-rdetail')
        self.manager = _make_user('legit_mgr_rdetail')
        _make_membership(self.manager, self.shop, role='technician')
        _make_tech(self.manager, self.shop, is_manager=True)
        self.customer = Customer.objects.create(name='Fleet Detail', tenant=self.shop)
        self.repair = _make_repair(self.customer, self.shop, status='REQUESTED')

    def test_legit_manager_can_view_requested_repair(self):
        from apps.technician_portal.views.repairs import repair_detail

        req = _make_request('GET', f'/tech/repairs/{self.repair.id}/', self.manager, self.shop)
        response = repair_detail(req, self.repair.id)
        self.assertEqual(response.status_code, 200)
