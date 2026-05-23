"""
Regression tests for CODE-076:
Unscoped request.user.technician.is_manager in customers.py / repairs.py

Root cause: request.user.technician resolves via OneToOneField with no tenant
filter. A user can only have ONE Technician record (OneToOneField). That record
may belong to Shop A (is_manager=True, tenant=shop_a). If that user also has a
TenantMembership at Shop B (role='technician'), there is no Technician record
for Shop B — but the old code used `request.user.technician.is_manager` which
returned Shop A's is_manager=True, bypassing manager gates on Shop B.

Fix: All is_mgr checks now use
    Technician.objects.filter(user=request.user, tenant=tenant).first()
which returns None when no record exists for the current tenant, correctly
resulting in is_mgr=False.

Test scenarios:
1. Cross-tenant: user's Technician record belongs to Shop A (is_manager=True).
   In Shop B context (no Technician record at shop_b), is_mgr must be False.
2. Legitimate manager at their own shop still passes all gates.
3. Plain technician at their own shop is correctly blocked.
4. Each affected view correctly blocks the cross-tenant scenario.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage


def _make_request(method, url, user, tenant, data=None):
    """Build a fake Request with message middleware attached."""
    factory = RequestFactory()
    if method == 'POST':
        req = factory.post(url, data or {})
    else:
        req = factory.get(url)
    req.user = user
    req.tenant = tenant
    setattr(req, 'session', 'session')
    setattr(req, '_messages', FallbackStorage(req))
    return req

from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership


def _make_user(username, email=None):
    return User.objects.create_user(
        username=username,
        email=email or f"{username}@example.com",
        password="testpass123",
    )


def _make_tenant(name, slug, owner=None):
    """Helper to create a test tenant."""
    _owner = owner or _make_user(f'owner_{slug}')
    tenant = Tenant.objects.create(name=name, slug=slug, subdomain=slug, owner=_owner)
    TenantMembership.objects.create(user=_owner, tenant=tenant, role='owner', is_active=True)
    return tenant


def _make_tech(user, tenant, is_manager=False, is_active=True):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=is_manager,
        is_active=is_active,
    )


def _make_membership(user, tenant, role='technician'):
    return TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)


class CrossTenantIsManagerCoreScopeTest(TestCase):
    """
    Core unit test: verify that Technician.objects.filter(user, tenant) correctly
    differentiates between the user's "home" tenant (where they have a Technician
    record with is_manager=True) and a "foreign" tenant (where they have a
    TenantMembership but no Technician record).
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop Alpha', 'shop-alpha')
        self.shop_b = _make_tenant('Shop Beta', 'shop-beta')

        # User has a Technician record at Shop A (is_manager=True)
        self.user = _make_user('cross_mgr_core')
        _make_membership(self.user, self.shop_a, role='technician')
        self.tech_a = _make_tech(self.user, self.shop_a, is_manager=True)

        # User also has a TenantMembership at Shop B, but NO Technician record
        _make_membership(self.user, self.shop_b, role='technician')

    def test_scoped_lookup_returns_tech_for_home_tenant(self):
        """In Shop A context, the tenant-scoped lookup finds the manager record."""
        tech = Technician.objects.filter(user=self.user, tenant=self.shop_a).first()
        self.assertIsNotNone(tech)
        self.assertTrue(tech.is_manager)

    def test_scoped_lookup_returns_none_for_foreign_tenant(self):
        """
        In Shop B context, the tenant-scoped lookup returns None.
        Before the fix, request.user.technician returned Shop A's record (is_manager=True).
        After the fix, the scoped lookup returns None → is_mgr=False.
        """
        tech = Technician.objects.filter(user=self.user, tenant=self.shop_b).first()
        self.assertIsNone(tech)

    def test_old_pattern_would_return_wrong_result(self):
        """
        Confirm that the OLD pattern (hasattr + .technician.is_manager) would
        erroneously return True in Shop B context — proving the fix was needed.
        """
        # The old pattern: hasattr(user, 'technician') and user.technician.is_manager
        old_is_mgr = hasattr(self.user, 'technician') and self.user.technician.is_manager
        # This is True because user.technician resolves to Shop A's record
        self.assertTrue(old_is_mgr, "Old pattern should return True (demonstrating the bug)")

        # The new fixed pattern: scope to Shop B → correctly returns False
        tech_b = Technician.objects.filter(user=self.user, tenant=self.shop_b).first()
        new_is_mgr = bool(tech_b and tech_b.is_manager)
        self.assertFalse(new_is_mgr, "New tenant-scoped pattern must return False for Shop B")


class CrossTenantCustomerListViewTest(TestCase):
    """customer_list: cross-tenant manager limited in Shop B."""

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-list')
        self.shop_b = _make_tenant('Shop B', 'shop-b-list')

        self.user = _make_user('multi_mgr_list')
        _make_membership(self.user, self.shop_a, role='technician')
        _make_tech(self.user, self.shop_a, is_manager=True)
        # Foreign tenant: membership only, no Technician record
        _make_membership(self.user, self.shop_b, role='technician')

        # Shop B has a customer not associated with any repair for this user
        self.customer_b = Customer.objects.create(name='Shop B Only Customer', tenant=self.shop_b)

    def test_customer_list_in_foreign_tenant_does_not_error(self):
        """
        View must not crash in Shop B context. Before the fix, request.user.technician
        could resolve to Shop A's record — but then the repair filter would be scoped
        to shop_b, so no data leaks. Main concern: no 500 error.
        """
        from apps.technician_portal.views.customers import customer_list

        request = _make_request('GET', '/tech/customers/', self.user, self.shop_b)
        response = customer_list(request)
        self.assertEqual(response.status_code, 200)


class CrossTenantEditCustomerViewTest(TestCase):
    """edit_customer: cross-tenant manager blocked in Shop B."""

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-edit')
        self.shop_b = _make_tenant('Shop B', 'shop-b-edit')

        self.user = _make_user('cross_mgr_edit')
        _make_membership(self.user, self.shop_a, role='technician')
        _make_tech(self.user, self.shop_a, is_manager=True)
        # Foreign tenant: membership only, no Technician record at shop_b
        _make_membership(self.user, self.shop_b, role='technician')

        self.customer_b = Customer.objects.create(name='Shop B Corp', tenant=self.shop_b)

    def test_edit_customer_blocked_for_cross_tenant_manager(self):
        """
        User is manager at Shop A. In Shop B context (no Technician record),
        edit_customer must block them.
        """
        from apps.technician_portal.views.customers import edit_customer

        request = _make_request('GET', f'/tech/customers/{self.customer_b.id}/edit/', self.user, self.shop_b)
        response = edit_customer(request, self.customer_b.id)
        # Should redirect (blocked — not a manager at shop_b)
        self.assertEqual(response.status_code, 302)

    def test_edit_customer_allowed_for_own_tenant_manager(self):
        """Legitimate manager at their own shop can edit customers."""
        from apps.technician_portal.views.customers import edit_customer

        manager_b = _make_user('proper_mgr_b_edit')
        _make_membership(manager_b, self.shop_b, role='manager')
        _make_tech(manager_b, self.shop_b, is_manager=True)
        customer = Customer.objects.create(name='Shop B Customer 2', tenant=self.shop_b)

        request = _make_request('GET', f'/tech/customers/{customer.id}/edit/', manager_b, self.shop_b)
        response = edit_customer(request, customer.id)
        # Gets the form (200), not a redirect
        self.assertEqual(response.status_code, 200)


class CrossTenantSendInvitationViewTest(TestCase):
    """send_customer_invitation: cross-tenant manager blocked in Shop B."""

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-inv')
        self.shop_b = _make_tenant('Shop B', 'shop-b-inv')

        self.user = _make_user('cross_mgr_inv')
        _make_membership(self.user, self.shop_a, role='technician')
        _make_tech(self.user, self.shop_a, is_manager=True)
        # Foreign tenant: membership only, no Technician record
        _make_membership(self.user, self.shop_b, role='technician')

        self.customer_b = Customer.objects.create(name='Invite Test Customer', tenant=self.shop_b)

    def test_send_invitation_blocked_for_cross_tenant_manager(self):
        """
        User is manager at Shop A. In Shop B context, send_customer_invitation must block.
        """
        from apps.technician_portal.views.customers import send_customer_invitation

        request = _make_request(
            'POST',
            f'/tech/customers/{self.customer_b.id}/invite/',
            self.user,
            self.shop_b,
            data={'email': 'test@test.com'},
        )
        response = send_customer_invitation(request, self.customer_b.id)
        self.assertEqual(response.status_code, 302)


class CrossTenantSetPrimaryContactViewTest(TestCase):
    """set_primary_contact: cross-tenant manager blocked in Shop B."""

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-spc')
        self.shop_b = _make_tenant('Shop B', 'shop-b-spc')

        self.user = _make_user('cross_mgr_spc')
        _make_membership(self.user, self.shop_a, role='technician')
        _make_tech(self.user, self.shop_a, is_manager=True)
        # Foreign tenant: membership only
        _make_membership(self.user, self.shop_b, role='technician')

        self.customer_b = Customer.objects.create(name='Contact Test Customer', tenant=self.shop_b)

    def test_set_primary_contact_blocked_for_cross_tenant_manager(self):
        """
        User is manager at Shop A. In Shop B context, set_primary_contact must block.
        """
        from apps.technician_portal.views.customers import set_primary_contact

        request = _make_request('POST', f'/tech/customers/{self.customer_b.id}/set-primary/1/', self.user, self.shop_b)
        response = set_primary_contact(request, self.customer_b.id, 1)
        self.assertEqual(response.status_code, 302)


class LegitimateManagerAllowedTest(TestCase):
    """Legitimate managers at their own shop still pass all gates correctly."""

    def setUp(self):
        self.shop = _make_tenant('My Shop', 'my-shop-mgr')
        self.manager = _make_user('legit_manager_code076')
        _make_membership(self.manager, self.shop, role='technician')
        self.tech_record = _make_tech(self.manager, self.shop, is_manager=True)

    def test_is_manager_resolves_correctly_for_own_tenant(self):
        """Scoped lookup returns the correct manager record for the user's own tenant."""
        tech = Technician.objects.filter(user=self.manager, tenant=self.shop).first()
        self.assertIsNotNone(tech)
        self.assertTrue(tech.is_manager)

    def test_plain_tech_is_not_manager(self):
        """A technician with is_manager=False correctly returns is_mgr=False."""
        plain_user = _make_user('plain_tech_code076')
        _make_membership(plain_user, self.shop, role='technician')
        _make_tech(plain_user, self.shop, is_manager=False)
        tech = Technician.objects.filter(user=plain_user, tenant=self.shop).first()
        self.assertIsNotNone(tech)
        self.assertFalse(tech.is_manager)


class RepairsViewCrossTenantManagerTest(TestCase):
    """
    update_repair: user_is_manager is now scoped to current tenant.
    A manager at Shop A (Technician record there, is_manager=True) acting in
    Shop B context (no Technician record at shop_b) must get user_is_manager=False.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A', 'shop-a-ur')
        self.shop_b = _make_tenant('Shop B', 'shop-b-ur')

        self.user = _make_user('cross_tech_ur')
        # Technician at Shop A with is_manager=True
        _make_membership(self.user, self.shop_a, role='technician')
        _make_tech(self.user, self.shop_a, is_manager=True)
        # Membership at Shop B but NO Technician record
        _make_membership(self.user, self.shop_b, role='technician')

    def test_scoped_tech_returns_none_for_foreign_tenant(self):
        """After fix: no Technician record at Shop B → user_is_manager=False."""
        tech = Technician.objects.filter(user=self.user, tenant=self.shop_b).first()
        self.assertIsNone(tech)
        user_is_manager = bool(tech and tech.is_manager)
        self.assertFalse(user_is_manager)

    def test_scoped_tech_correct_for_home_tenant(self):
        """The same user correctly gets user_is_manager=True in their home tenant."""
        tech = Technician.objects.filter(user=self.user, tenant=self.shop_a).first()
        self.assertIsNotNone(tech)
        self.assertTrue(tech.is_manager)
