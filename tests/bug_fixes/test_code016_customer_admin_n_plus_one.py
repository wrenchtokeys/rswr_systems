"""
Regression tests for CODE-016: N+1 query in CustomerAdmin.get_primary_contact().

Problem:
    CustomerAdmin.get_primary_contact() called
    CustomerUser.objects.filter(customer=obj, is_primary_contact=True).first()
    for EVERY row in the changelist — issuing N extra SELECT statements for
    a page with N customers.

Fix:
    CustomerAdmin.get_queryset() now prefetches CustomerUser rows with
    is_primary_contact=True via Prefetch(..., to_attr='_primary_contacts').
    get_primary_contact() reads from obj._primary_contacts (the prefetch
    cache) rather than issuing a new query per row.

These tests verify:
1. The prefetch attribute is present on queryset objects.
2. get_primary_contact() returns the correct name/email when a primary
   contact exists.
3. get_primary_contact() returns "No primary contact" when none exists.
4. The admin changelist executes a fixed (small) number of queries
   regardless of customer page size — specifically, the total query count
   does NOT grow linearly with the number of customers.

Author: Amelia
"""

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.technician_portal.admin import CustomerAdmin
from apps.tenants.models import Tenant, TenantMembership
from apps.customer_portal.models import CustomerUser
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser(username='su_code016'):
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'is_staff': True, 'is_superuser': True}
    )
    user.set_password('x')
    user.save()
    return user


def _make_tenant(name='CODE016Shop'):
    owner, _ = User.objects.get_or_create(
        username=f'owner_c016_{name}',
        defaults={'password': 'x'}
    )
    tenant, _ = Tenant.objects.get_or_create(
        slug=f'code016-{name.lower().replace(" ", "-")}',
        defaults={'name': name, 'owner': owner, 'is_active': True}
    )
    return tenant


def _make_customer(tenant, name='ACME Corp'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=f'contact@{name.replace(" ", "").lower()}.example.com',
    )


def _make_customer_user(customer, username, is_primary=True):
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            'first_name': 'Test',
            'last_name': 'User',
            'email': f'{username}@example.com',
        }
    )
    cu, _ = CustomerUser.objects.get_or_create(
        user=user,
        customer=customer,
        defaults={'is_primary_contact': is_primary},
    )
    return cu


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(
    LOCAL_DATABASE_URL='postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test'
)
class CustomerAdminPrimaryContactTests(TestCase):
    """CustomerAdmin.get_primary_contact() uses the prefetch cache, not N queries."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = CustomerAdmin(Customer, self.site)
        self.superuser = _make_superuser()
        self.factory = RequestFactory()
        self.tenant = _make_tenant()

    def _make_request(self):
        request = self.factory.get('/admin/technician_portal/customer/')
        request.user = self.superuser
        request.tenant = self.tenant
        return request

    def test_prefetch_attribute_present_on_queryset(self):
        """get_queryset() should attach _primary_contacts to every Customer object."""
        customer = _make_customer(self.tenant, 'PrefetchTest Corp')
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        self.assertTrue(
            hasattr(obj, '_primary_contacts'),
            "_primary_contacts prefetch attribute missing from queryset object"
        )

    def test_get_primary_contact_with_primary_contact(self):
        """Returns 'Full Name (email)' when a primary contact exists."""
        customer = _make_customer(self.tenant, 'HasContact Corp')
        cu = _make_customer_user(customer, 'code016_primary_cu', is_primary=True)
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        result = self.admin.get_primary_contact(obj)
        self.assertIn(cu.user.get_full_name(), result)
        self.assertIn(cu.user.email, result)

    def test_get_primary_contact_without_primary_contact(self):
        """Returns 'No primary contact' when no CustomerUser with is_primary_contact=True."""
        customer = _make_customer(self.tenant, 'NoContact Corp')
        # Create a non-primary CustomerUser to ensure the filter is correct
        _make_customer_user(customer, 'code016_nonprimary_cu', is_primary=False)
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        result = self.admin.get_primary_contact(obj)
        self.assertEqual(result, 'No primary contact')

    def test_get_primary_contact_no_customer_users(self):
        """Returns 'No primary contact' when the customer has no CustomerUsers at all."""
        customer = _make_customer(self.tenant, 'EmptyContact Corp')
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        result = self.admin.get_primary_contact(obj)
        self.assertEqual(result, 'No primary contact')

    def test_query_count_does_not_grow_linearly_with_customers(self):
        """
        The total number of SQL queries for get_primary_contact() across N
        customers should be constant (prefetched), not O(N).

        Strategy: create 5 customers and verify that fetching get_primary_contact
        for all of them, after calling get_queryset(), issues no additional
        queries beyond the initial prefetch.
        """
        customers = []
        for i in range(5):
            c = _make_customer(self.tenant, f'QueryCountTest {i}')
            if i % 2 == 0:
                # Give half the customers a primary contact
                _make_customer_user(c, f'code016_qc_cu_{i}', is_primary=True)
            customers.append(c)

        request = self._make_request()
        qs = self.admin.get_queryset(request).filter(
            id__in=[c.id for c in customers]
        )

        # Force queryset evaluation + prefetch
        customer_list = list(qs)

        # Any calls to get_primary_contact() after this point should NOT
        # issue any additional queries — they read from _primary_contacts.
        with CaptureQueriesContext(connection) as ctx:
            for obj in customer_list:
                self.admin.get_primary_contact(obj)

        self.assertEqual(
            len(ctx.captured_queries), 0,
            f"Expected 0 extra queries after prefetch, but got "
            f"{len(ctx.captured_queries)}: {[q['sql'][:120] for q in ctx.captured_queries]}"
        )

    def test_only_primary_contacts_are_prefetched(self):
        """
        Non-primary CustomerUser rows should NOT appear in _primary_contacts.
        The Prefetch queryset filters is_primary_contact=True.
        """
        customer = _make_customer(self.tenant, 'FilterTest Corp')
        _make_customer_user(customer, 'code016_nonprim_filter', is_primary=False)
        primary_cu = _make_customer_user(customer, 'code016_prim_filter', is_primary=True)

        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)

        self.assertEqual(len(obj._primary_contacts), 1)
        self.assertEqual(obj._primary_contacts[0].id, primary_cu.id)
