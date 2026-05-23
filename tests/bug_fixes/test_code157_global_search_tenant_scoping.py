"""
CODE-157: Admin global search not tenant-scoped for non-superuser staff.

Bug: _global_search_view in rs_systems/admin.py queried Customers, Repairs,
Invoices, and Users without any tenant restriction.  A staff user from Shop A
(with Django admin access via is_staff=True) could discover records from Shop B
simply by entering a search term.

Fix: Non-superuser staff now receive results scoped to their own tenant(s)
via TenantMembership.  Superusers retain full visibility.

Tests:
1. Superuser sees results from all tenants.
2. Non-superuser staff from Tenant A sees only Tenant A's customers.
3. Non-superuser staff from Tenant A does NOT see Tenant B's customers.
4. Non-superuser staff from Tenant A sees only Tenant A's repairs.
5. Non-superuser staff from Tenant A does NOT see Tenant B's repairs.
6. Non-superuser staff from Tenant A sees only Tenant A's invoices.
7. Non-superuser staff from Tenant A does NOT see Tenant B's invoices.
8. Non-superuser staff sees only users from their tenant (technicians/customers).
9. Non-superuser staff does NOT see users from another tenant.
10. Empty query returns no results (no accidental data dumps).
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User


def _make_user(username, email, is_staff=False, is_superuser=False):
    u = User.objects.create_user(username=username, email=email, password='Test1234!')
    if is_staff:
        u.is_staff = True
        u.save()
    if is_superuser:
        u.is_staff = True
        u.is_superuser = True
        u.save()
    return u


class GlobalSearchTenantScopingTests(TestCase):
    """Non-superuser staff see only their own tenant's data in global search."""

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
        from apps.technician_portal.models import Technician, Repair
        from apps.billing.models import Invoice, InvoiceLineItem
        from core.models import Customer
        from django.utils import timezone

        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='search-scope-test', defaults={
                'name': 'Search Scope Test', 'monthly_price': Decimal('0'), 'trial_days': 14
            }
        )

        # Two tenants, each with their own staff user
        cls.owner_a = _make_user('search_owner_a', 'owner_a@search.test', is_staff=True)
        cls.owner_b = _make_user('search_owner_b', 'owner_b@search.test', is_staff=False)
        cls.superuser = _make_user('search_super', 'super@search.test', is_superuser=True)

        cls.tenant_a = Tenant.objects.create(
            name='SearchAlpha Corp', slug='search-alpha-corp', owner=cls.owner_a
        )
        cls.tenant_b = Tenant.objects.create(
            name='SearchBeta LLC', slug='search-beta-llc', owner=cls.owner_b
        )

        # Grant owner_a admin staff + TenantMembership
        TenantMembership.objects.create(
            tenant=cls.tenant_a, user=cls.owner_a, role='owner', is_active=True
        )

        # Customers with a distinctive search term
        cls.cust_a = Customer.objects.create(
            name='AlphaFleet Customer', email='fleet@alpha.test', tenant=cls.tenant_a
        )
        cls.cust_b = Customer.objects.create(
            name='BetaFleet Customer', email='fleet@beta.test', tenant=cls.tenant_b
        )

        # Technicians for each tenant
        cls.tech_a = Technician.objects.create(
            user=cls.owner_a, tenant=cls.tenant_a, expertise='General'
        )
        tech_b_user = _make_user('search_tech_b', 'tech_b@search.test')
        cls.tech_b = Technician.objects.create(
            user=tech_b_user, tenant=cls.tenant_b, expertise='General'
        )

        # Repairs
        cls.repair_a = Repair.objects.create(
            customer=cls.cust_a, tenant=cls.tenant_a, technician=cls.tech_a,
            unit_number='SEARCH-UNIT-A', cost=Decimal('50'), queue_status='COMPLETED'
        )
        cls.repair_b = Repair.objects.create(
            customer=cls.cust_b, tenant=cls.tenant_b, technician=cls.tech_b,
            unit_number='SEARCH-UNIT-B', cost=Decimal('75'), queue_status='COMPLETED'
        )

        # Invoices (need invoice_number — use a simple unique prefix)
        today = timezone.now().date()
        cls.invoice_a = Invoice.objects.create(
            customer=cls.cust_a, tenant=cls.tenant_a,
            invoice_number='SRCH-A-001', status='SENT',
            invoice_date=today, due_date=today,
            subtotal=Decimal('50'), total=Decimal('50'), amount_paid=Decimal('0'),
        )
        cls.invoice_b = Invoice.objects.create(
            customer=cls.cust_b, tenant=cls.tenant_b,
            invoice_number='SRCH-B-001', status='SENT',
            invoice_date=today, due_date=today,
            subtotal=Decimal('75'), total=Decimal('75'), amount_paid=Decimal('0'),
        )

    def setUp(self):
        self.client = Client()
        self.search_url = '/admin/search/'

    def _search(self, user, query):
        """Log in as user and perform admin global search. Returns response."""
        self.client.force_login(user)
        return self.client.get(self.search_url, {'q': query})

    def _result_ids(self, response, key):
        """Extract PKs from search results context."""
        results = response.context.get('results', {})
        objs = results.get(key, [])
        return {obj.pk for obj in objs}

    # -------------------------------------------------------------------------
    # Superuser tests
    # -------------------------------------------------------------------------

    def test_superuser_sees_customers_from_all_tenants(self):
        resp = self._search(self.superuser, 'Fleet')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'customers')
        self.assertIn(self.cust_a.pk, ids, 'Superuser should see Tenant A customer')
        self.assertIn(self.cust_b.pk, ids, 'Superuser should see Tenant B customer')

    def test_superuser_sees_repairs_from_all_tenants(self):
        resp = self._search(self.superuser, 'SEARCH-UNIT')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'repairs')
        self.assertIn(self.repair_a.pk, ids, 'Superuser should see Tenant A repair')
        self.assertIn(self.repair_b.pk, ids, 'Superuser should see Tenant B repair')

    def test_superuser_sees_invoices_from_all_tenants(self):
        resp = self._search(self.superuser, 'SRCH-')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'invoices')
        self.assertIn(self.invoice_a.pk, ids, 'Superuser should see Tenant A invoice')
        self.assertIn(self.invoice_b.pk, ids, 'Superuser should see Tenant B invoice')

    # -------------------------------------------------------------------------
    # Non-superuser staff (tenant A) tests
    # -------------------------------------------------------------------------

    def test_staff_sees_own_tenant_customer(self):
        resp = self._search(self.owner_a, 'Fleet')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'customers')
        self.assertIn(self.cust_a.pk, ids, 'Staff A should see their own customer')

    def test_staff_cannot_see_other_tenant_customer(self):
        resp = self._search(self.owner_a, 'Fleet')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'customers')
        self.assertNotIn(self.cust_b.pk, ids, 'Staff A must NOT see Tenant B customer')

    def test_staff_sees_own_tenant_repair(self):
        resp = self._search(self.owner_a, 'SEARCH-UNIT')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'repairs')
        self.assertIn(self.repair_a.pk, ids, 'Staff A should see their own repair')

    def test_staff_cannot_see_other_tenant_repair(self):
        resp = self._search(self.owner_a, 'SEARCH-UNIT')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'repairs')
        self.assertNotIn(self.repair_b.pk, ids, 'Staff A must NOT see Tenant B repair')

    def test_staff_sees_own_tenant_invoice(self):
        resp = self._search(self.owner_a, 'SRCH-')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'invoices')
        self.assertIn(self.invoice_a.pk, ids, 'Staff A should see their own invoice')

    def test_staff_cannot_see_other_tenant_invoice(self):
        resp = self._search(self.owner_a, 'SRCH-')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'invoices')
        self.assertNotIn(self.invoice_b.pk, ids, 'Staff A must NOT see Tenant B invoice')

    def test_staff_sees_own_tenant_users(self):
        resp = self._search(self.owner_a, 'search_owner_a')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'users')
        self.assertIn(self.owner_a.pk, ids, 'Staff A should see themselves in user search')

    def test_staff_cannot_see_other_tenant_users(self):
        resp = self._search(self.owner_a, 'search_tech_b')
        self.assertEqual(resp.status_code, 200)
        ids = self._result_ids(resp, 'users')
        self.assertNotIn(self.tech_b.user.pk, ids, 'Staff A must NOT see Tenant B technician user')

    def test_empty_query_returns_no_results(self):
        resp = self._search(self.owner_a, '')
        self.assertEqual(resp.status_code, 200)
        results = resp.context.get('results', {})
        self.assertEqual(results, {}, 'Empty query should return empty results dict')
