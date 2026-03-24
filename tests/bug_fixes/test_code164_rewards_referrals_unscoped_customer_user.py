"""
Regression tests for CODE-164: get_customer_user() in rewards_referrals/views.py
was not tenant-scoped, which allowed the wrong shop's CustomerUser to be returned
when a user visited another shop's reward/referral pages.

Background: CustomerUser.user is a OneToOneField, so a user has at most ONE
CustomerUser globally. However, tenant-scoping is still critical: a customer at
Shop A who navigates to Shop B's URL would get their Shop A CustomerUser from the
unscoped lookup, and all downstream reward/referral operations would silently use
Shop A's data (wrong points balance, wrong options) while appearing to be at Shop B.

This is the same validation pattern added in CODE-102 / CODE-162 for the customer
portal's _get_customer_user_for_tenant() helper.

Fix: Added customer__tenant=tenant scope to the filter, returning None when the
user's CustomerUser belongs to a different tenant than the current request.

Behaviour tested:
1. get_customer_user returns the CustomerUser when the tenant matches.
2. get_customer_user returns None when the user has no CustomerUser at all.
3. get_customer_user returns None when the user's CustomerUser belongs to a
   DIFFERENT tenant (the cross-tenant access prevention case).
4. Falls back to unscoped lookup when there is no tenant context.
5. Does not raise DoesNotExist — always returns None on miss.
6. Returns a CustomerUser with select_related customer__tenant pre-loaded.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.technician_portal.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant
from apps.rewards_referrals.views import get_customer_user


def _make_owner(tag):
    return User.objects.create_user(
        username=f"owner_{tag}",
        email=f"owner_{tag}@example.com",
        password="ownerpass164",
    )


def _make_tenant(name, owner=None):
    if owner is None:
        owner = _make_owner(name[:8].replace(" ", "").lower())
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=owner,
    )


def _make_user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass164",
    )


def _make_customer(tenant, name="Fleet Co"):
    return Customer.objects.create(name=name, tenant=tenant)


def _make_customer_user(user, customer):
    return CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=True,
    )


class GetCustomerUserTenantScopeTest(TestCase):
    """Unit tests for get_customer_user() tenant scoping."""

    def setUp(self):
        self.factory = RequestFactory()
        # Two separate shops with separate owners
        self.owner_a = _make_owner("ta164")
        self.owner_b = _make_owner("tb164")
        self.tenant_a = _make_tenant("Shop A 164", owner=self.owner_a)
        self.tenant_b = _make_tenant("Shop B 164", owner=self.owner_b)

        # One user who has a CustomerUser at Shop A (not Shop B)
        self.user = _make_user("cu164_single")
        self.customer_a = _make_customer(self.tenant_a, "Customer at A")
        self.cu_a = _make_customer_user(self.user, self.customer_a)

    def _make_request(self, tenant):
        request = self.factory.get("/rewards/")
        request.user = self.user
        request.tenant = tenant
        return request

    def test_returns_customer_user_for_correct_tenant(self):
        """
        get_customer_user returns the CustomerUser when request.tenant matches.
        """
        request = self._make_request(self.tenant_a)
        result = get_customer_user(request)
        self.assertIsNotNone(result, "Should find CustomerUser for correct tenant")
        self.assertEqual(result.id, self.cu_a.id)
        self.assertEqual(result.customer.tenant_id, self.tenant_a.id)

    def test_returns_none_when_tenant_does_not_match(self):
        """
        Core invariant: get_customer_user returns None when the user's CustomerUser
        belongs to a different tenant than request.tenant.

        Without this check, a customer from Shop A visiting Shop B's rewards page
        would get their Shop A CustomerUser back, causing reward/referral views to
        silently operate on Shop A's data while appearing to be at Shop B.
        """
        request = self._make_request(self.tenant_b)
        result = get_customer_user(request)
        self.assertIsNone(
            result,
            "Must return None when CustomerUser tenant doesn't match request.tenant",
        )

    def test_returns_none_for_user_with_no_customer_user(self):
        """get_customer_user returns None when the user has no CustomerUser at all."""
        new_user = _make_user("cu164_new")
        request = self._make_request(self.tenant_a)
        request.user = new_user
        result = get_customer_user(request)
        self.assertIsNone(result)

    def test_does_not_raise_on_miss(self):
        """get_customer_user never raises DoesNotExist — uses .first() semantics."""
        new_user = _make_user("cu164_noraise")
        request = self._make_request(self.tenant_b)
        request.user = new_user
        # Should not raise any exception
        try:
            result = get_customer_user(request)
        except Exception as e:
            self.fail(f"get_customer_user raised unexpectedly: {e}")
        self.assertIsNone(result)

    def test_falls_back_to_unscoped_when_no_tenant_context(self):
        """
        Without request.tenant, falls back to unscoped lookup (for tests/admin).
        Should return the user's CustomerUser without raising.
        """
        request = self.factory.get("/rewards/")
        request.user = self.user
        # Explicitly NO tenant attribute — simulates test/admin context
        result = get_customer_user(request)
        self.assertIsNotNone(result)
        self.assertEqual(result.id, self.cu_a.id)

    def test_result_has_customer_tenant_preloaded(self):
        """
        get_customer_user includes select_related('customer__tenant') so downstream
        code can access customer.tenant without an extra query.
        """
        request = self._make_request(self.tenant_a)
        result = get_customer_user(request)
        self.assertIsNotNone(result)
        # This should not trigger a DB query (already select_related)
        with self.assertNumQueries(0):
            _ = result.customer.tenant.id


class GetCustomerUserCrossTenantAccessTest(TestCase):
    """
    Targeted test for the cross-tenant data exposure scenario.

    Scenario: user registered at Shop A navigates to Shop B's rewards page.
    Before fix: get_customer_user() returned the Shop A CustomerUser.
    After fix: get_customer_user() returns None for Shop B.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.owner_a = _make_owner("xta164")
        self.owner_b = _make_owner("xtb164")
        self.tenant_a = _make_tenant("Cross Shop A 164", owner=self.owner_a)
        self.tenant_b = _make_tenant("Cross Shop B 164", owner=self.owner_b)

        self.user = _make_user("cu164_cross")
        self.customer_a = _make_customer(self.tenant_a, "Cross Customer A")
        self.cu_a = _make_customer_user(self.user, self.customer_a)

    def test_cross_tenant_navigation_returns_none(self):
        """
        A user enrolled at Shop A visiting Shop B's rewards page must get None,
        not Shop A's CustomerUser. This is the root fix of CODE-164.
        """
        # Simulate the request arriving for Shop B
        request = self.factory.get("/rewards/")
        request.user = self.user
        request.tenant = self.tenant_b  # Shop B's rewards page

        result = get_customer_user(request)

        self.assertIsNone(
            result,
            "Cross-tenant access must return None — user's CustomerUser is at a different shop",
        )

    def test_same_tenant_access_works_normally(self):
        """
        Accessing Shop A's rewards page as a Shop A customer still works.
        """
        request = self.factory.get("/rewards/")
        request.user = self.user
        request.tenant = self.tenant_a  # Shop A's rewards page

        result = get_customer_user(request)

        self.assertIsNotNone(result)
        self.assertEqual(result.id, self.cu_a.id)
