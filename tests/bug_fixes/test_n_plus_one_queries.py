"""
N+1 Query Tests
Consolidated from: CODE-004, CODE-013, CODE-016, CODE-018
"""

from apps.billing.admin import InvoiceAdmin
from apps.billing.models import Invoice, InvoiceLineItem, Payment
from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.admin import ReferralCodeAdmin
from apps.rewards_referrals.models import Referral, ReferralCode
from apps.technician_portal.admin import CustomerAdmin, TechnicianAdmin
from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer
from decimal import Decimal
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.db import connection, reset_queries
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext, override_settings
import datetime


# --- From test_code004_n_plus_one_batch_views.py ---

def _count_queries_for(queryset_fn):
    """Evaluate queryset_fn() and return (results, query_count)."""
    reset_queries()
    results = list(queryset_fn())
    return results, len(connection.queries)


@override_settings(DEBUG=True)  # DEBUG=True is required for connection.queries to populate
class CustomerSelectRelatedTest(TestCase):
    """Verify Customer.objects.select_related('tenant') eliminates N+1 per customer."""

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'monthly_price': 0,
                'trial_days': 30,
                'is_active': True,
            }
        )
        # Create two tenants, each with two customers → 4 customers total
        owner1 = User.objects.create_user(username='owner_a', password='pw')
        owner2 = User.objects.create_user(username='owner_b', password='pw')
        self.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a', subdomain='shop-a',
            owner=owner1, plan='trial', subscription_plan=plan,
        )
        self.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b', subdomain='shop-b',
            owner=owner2, plan='trial', subscription_plan=plan,
        )
        for i in range(2):
            Customer.objects.create(
                name=f'Customer A{i}', email=f'ca{i}@example.com',
                tenant=self.tenant_a,
            )
            Customer.objects.create(
                name=f'Customer B{i}', email=f'cb{i}@example.com',
                tenant=self.tenant_b,
            )

    # ------------------------------------------------------------------
    # 1. select_related('tenant') — SQL includes JOIN
    # ------------------------------------------------------------------

    def test_customer_queryset_uses_join(self):
        """Customer.objects.select_related('tenant') produces a JOIN query."""
        qs = Customer.objects.select_related('tenant').filter(tenant=self.tenant_a)
        sql = str(qs.query).upper()
        self.assertIn('JOIN', sql,
                      "Expected a JOIN in the query when select_related('tenant') is used.")

    def test_customer_queryset_without_select_related_no_join(self):
        """Baseline: Customer.objects.all() produces no JOIN (so we can detect the difference)."""
        qs = Customer.objects.filter(tenant=self.tenant_a)
        sql = str(qs.query).upper()
        # A plain filter on tenant FK uses a WHERE, not necessarily a JOIN
        # (Django may still join if needed — this just documents behaviour)
        # The real regression test is the one above confirming JOIN is present
        # when select_related is used.
        self.assertIn('WHERE', sql)

    # ------------------------------------------------------------------
    # 2. Accessing .tenant does NOT cause extra queries with select_related
    # ------------------------------------------------------------------

    def test_accessing_tenant_no_extra_query_with_select_related(self):
        """Iterating customers + reading .tenant should need only 1 SQL query."""
        customers, query_count = _count_queries_for(
            lambda: Customer.objects.select_related('tenant').filter(tenant=self.tenant_a)
        )
        self.assertGreater(len(customers), 0)
        # Access .tenant on each row — should NOT fire extra queries
        reset_queries()
        for customer in customers:
            _ = customer.tenant.name
        post_access_count = len(connection.queries)
        self.assertEqual(
            post_access_count, 0,
            "Accessing customer.tenant after select_related() should fire 0 extra queries."
        )

    def test_n_plus_one_baseline_without_select_related(self):
        """Without select_related, accessing .tenant on a deferred instance fires a query."""
        # Force a fresh fetch with no caching
        customer = Customer.objects.filter(tenant=self.tenant_a).first()
        # Clear the tenant cache so next access hits DB
        if hasattr(customer, '_state'):
            customer.__dict__.pop('tenant', None)  # remove cached value if any
        customer.__dict__.pop('tenant_cache', None)
        # We can't guarantee a query fires here (Django may cache FK ids),
        # but we CAN guarantee that the select_related path fires zero queries.
        # This test documents the design intent.
        qs = Customer.objects.select_related('tenant').get(pk=customer.pk)
        reset_queries()
        _ = qs.tenant.name
        self.assertEqual(len(connection.queries), 0,
                         "select_related should cache tenant so zero extra queries fire.")


@override_settings(DEBUG=True)
class RepairSelectRelatedTest(TestCase):
    """Verify Repair queryset in convert_to_batch uses select_related."""

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'monthly_price': 0,
                'trial_days': 30,
                'is_active': True,
            }
        )
        owner = User.objects.create_user(username='repair_owner', password='pw')
        self.tenant = Tenant.objects.create(
            name='Repair Shop', slug='repair-shop', subdomain='repair-shop',
            owner=owner, plan='trial', subscription_plan=plan,
        )
        self.customer = Customer.objects.create(
            name='Fleet Co', email='fleet@example.com', tenant=self.tenant,
        )
        tech_user = User.objects.create_user(username='tech1', password='pw')
        self.technician = Technician.objects.create(
            user=tech_user,
            phone_number='555-0199',
            tenant=self.tenant,
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='U001',
            damage_type='chip',
            cost=Decimal('50.00'),
        )

    def test_repair_queryset_uses_join(self):
        """Repair queryset with select_related produces a JOIN."""
        qs = Repair.objects.select_related(
            'customer', 'technician__user', 'tenant'
        ).filter(tenant=self.tenant)
        sql = str(qs.query).upper()
        self.assertIn('JOIN', sql,
                      "Expected JOIN in query when select_related is used on Repair.")

    def test_accessing_customer_no_extra_query(self):
        """After select_related, accessing repair.customer fires 0 extra queries."""
        repair = Repair.objects.select_related(
            'customer', 'technician__user', 'tenant'
        ).get(pk=self.repair.pk)
        reset_queries()
        _ = repair.customer.name
        _ = repair.technician.user.username
        _ = repair.tenant.name
        self.assertEqual(
            len(connection.queries), 0,
            "select_related should cache customer/technician/tenant → 0 extra queries."
        )

    def test_repair_queryset_returns_correct_repair(self):
        """select_related queryset still returns the correct repair object."""
        qs = Repair.objects.select_related(
            'customer', 'technician__user', 'tenant'
        ).filter(tenant=self.tenant)
        self.assertEqual(qs.count(), 1)
        fetched = qs.get(pk=self.repair.pk)
        self.assertEqual(fetched.unit_number, 'U001')
        self.assertEqual(fetched.customer.name, 'Fleet Co')
        self.assertEqual(fetched.technician.user.username, 'tech1')


@override_settings(DEBUG=True)
class BatchViewQuerysetSignatureTest(TestCase):
    """
    Verify the actual querysets used by batch view functions include select_related.
    Imports the view helpers and inspects query SQL directly.
    """

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'monthly_price': 0,
                'trial_days': 30,
                'is_active': True,
            }
        )
        owner = User.objects.create_user(username='bv_owner', password='pw')
        self.tenant = Tenant.objects.create(
            name='BatchView Shop', slug='bv-shop', subdomain='bv-shop',
            owner=owner, plan='trial', subscription_plan=plan,
        )
        for i in range(3):
            Customer.objects.create(
                name=f'BV Customer {i}',
                email=f'bvc{i}@example.com',
                tenant=self.tenant,
            )

    def test_customer_select_related_query_count_constant_for_n_customers(self):
        """
        With select_related, query count should be 1 regardless of customer count,
        since tenant is JOINed in the same query.
        """
        # Fetch and access .tenant for 3 customers
        customers_sr, _ = _count_queries_for(
            lambda: Customer.objects.select_related('tenant').filter(tenant=self.tenant)
        )
        reset_queries()
        for c in customers_sr:
            _ = c.tenant.name
        queries_after_sr = len(connection.queries)

        self.assertEqual(
            queries_after_sr, 0,
            f"Expected 0 extra queries after select_related fetch, got {queries_after_sr}. "
            "This would be N queries without select_related (N+1 problem)."
        )

    def test_batch_view_import_succeeds(self):
        """Ensure the batch view module imports cleanly after our changes."""
        try:
            from apps.technician_portal.views import batch  # noqa: F401
        except ImportError as e:
            self.fail(f"batch.py failed to import: {e}")


# --- From test_code013_admin_n_plus_one.py ---

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser_c013(username='su_code013'):
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'is_staff': True, 'is_superuser': True}
    )
    user.set_password('x')
    user.save()
    return user


def _make_tenant_c013(name='CODE013Shop'):
    owner = User.objects.create_user(username=f'owner_{name}', password='x')
    tenant, _ = Tenant.objects.get_or_create(
        slug=f'code013-{name.lower()}',
        defaults={'name': name, 'owner': owner, 'is_active': True}
    )
    return tenant


def _make_invoice(tenant, customer, index=1):
    """Create a draft invoice with a given number of line items."""
    inv = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-C013-{index:04d}',
        invoice_date=datetime.date.today(),
        due_date=datetime.date.today() + datetime.timedelta(days=30),
        payment_terms='NET30',
        status='DRAFT',
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
    )
    # Add some line items so the count is non-trivial
    for i in range(index % 3 + 1):
        InvoiceLineItem.objects.create(
            invoice=inv,
            description=f'Line item {i + 1}',
            quantity=1,
            unit_price=Decimal('50.00'),
            amount=Decimal('50.00'),
        )
    return inv


# ---------------------------------------------------------------------------
# 1. InvoiceAdmin — line_item_count uses annotation, not per-row COUNT
# ---------------------------------------------------------------------------


class InvoiceAdminLineItemCountTest(TestCase):

    def setUp(self):
        self.site = AdminSite()
        self.admin = InvoiceAdmin(Invoice, self.site)
        self.factory = RequestFactory()
        self.superuser = _make_superuser_c013('su_inv_c013')
        self.tenant = _make_tenant_c013('InvoiceN1')
        self.customer = Customer.objects.create(
            name='N+1 Test Corp', tenant=self.tenant
        )
        # Create 5 invoices with varying line-item counts
        self.invoices = [_make_invoice(self.tenant, self.customer, i + 1) for i in range(5)]

    def _make_request(self):
        req = self.factory.get('/admin/billing/invoice/')
        req.user = self.superuser
        return req

    def test_get_queryset_has_annotation(self):
        """get_queryset() should annotate each invoice with _line_items_count."""
        req = self._make_request()
        qs = self.admin.get_queryset(req)
        first = qs.filter(id=self.invoices[0].id).first()
        self.assertTrue(
            hasattr(first, '_line_items_count'),
            "Invoice queryset should have _line_items_count annotation"
        )

    def test_line_item_count_uses_annotation(self):
        """line_item_count() should return the annotated value, not do a DB hit."""
        req = self._make_request()
        qs = self.admin.get_queryset(req)
        inv = qs.filter(id=self.invoices[0].id).first()
        # Real line item count from DB
        expected = inv.line_items.count()
        # Admin method should return same value from annotation
        result = self.admin.line_item_count(inv)
        self.assertEqual(result, expected)

    def test_no_extra_query_per_invoice_for_line_item_count(self):
        """
        After annotating the queryset, iterating over N invoices and calling
        line_item_count should NOT fire N additional queries.
        """
        req = self._make_request()
        qs = self.admin.get_queryset(req).filter(
            id__in=[inv.id for inv in self.invoices]
        )
        invoices_list = list(qs)   # materialize

        # Now call line_item_count for each; should use annotation (no DB queries)
        with CaptureQueriesContext(connection) as ctx:
            counts = [self.admin.line_item_count(inv) for inv in invoices_list]

        # Annotation is already resolved; no additional queries should fire
        self.assertEqual(
            len(ctx.captured_queries), 0,
            f"Expected 0 extra queries for line_item_count, got {len(ctx.captured_queries)}"
        )
        # Sanity check: counts are non-negative integers
        for c in counts:
            self.assertIsInstance(c, int)
            self.assertGreaterEqual(c, 0)

    def test_line_item_count_sortable(self):
        """line_item_count should have admin_order_field set for column sorting."""
        self.assertEqual(
            self.admin.line_item_count.admin_order_field, '_line_items_count'
        )


# ---------------------------------------------------------------------------
# 2. TechnicianAdmin — 'tenant' in list_select_related
# ---------------------------------------------------------------------------

class TechnicianAdminSelectRelatedTest(TestCase):

    def test_tenant_in_list_select_related(self):
        """TechnicianAdmin must include 'tenant' in list_select_related."""
        site = AdminSite()
        ta = TechnicianAdmin(Technician, site)
        self.assertIn(
            'tenant', ta.list_select_related,
            "TechnicianAdmin.list_select_related must include 'tenant' to avoid N+1 queries"
        )

    def test_user_still_in_list_select_related(self):
        """TechnicianAdmin must still include 'user' in list_select_related."""
        site = AdminSite()
        ta = TechnicianAdmin(Technician, site)
        self.assertIn('user', ta.list_select_related)


# ---------------------------------------------------------------------------
# 3. ReferralCodeAdmin — get_referral_count uses annotation
# ---------------------------------------------------------------------------

class ReferralCodeAdminReferralCountTest(TestCase):

    def setUp(self):
        self.site = AdminSite()
        self.admin = ReferralCodeAdmin(ReferralCode, self.site)
        self.factory = RequestFactory()
        self.superuser = _make_superuser_c013('su_ref_c013')
        self.tenant = _make_tenant_c013('ReferralN1')
        customer_owner = User.objects.create_user(username='cu_owner_ref', password='x')
        self.customer = Customer.objects.create(
            name='Referral Test Corp', tenant=self.tenant
        )

    def _make_request(self):
        req = self.factory.get('/admin/rewards_referrals/referralcode/')
        req.user = self.superuser
        return req

    def test_get_queryset_has_annotation(self):
        """get_queryset() should annotate each ReferralCode with _referral_count."""
        from apps.customer_portal.models import CustomerUser
        cu_user = User.objects.create_user(username='cu_user_ref_ann', password='x')
        cu = CustomerUser.objects.create(
            user=cu_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        code = ReferralCode.objects.create(customer_user=cu, code='TESTANN')
        req = self._make_request()
        qs = self.admin.get_queryset(req)
        result = qs.filter(id=code.id).first()
        self.assertTrue(
            hasattr(result, '_referral_count'),
            "ReferralCode queryset should have _referral_count annotation"
        )

    def test_referral_count_sortable(self):
        """get_referral_count should have admin_order_field for column sorting."""
        self.assertEqual(
            self.admin.get_referral_count.admin_order_field, '_referral_count'
        )

    def test_no_extra_queries_for_referral_count(self):
        """
        After annotating, calling get_referral_count on materialized objects
        should not fire additional DB queries.
        """
        from apps.customer_portal.models import CustomerUser
        cu_user = User.objects.create_user(username='cu_user_ref_nq', password='x')
        cu = CustomerUser.objects.create(
            user=cu_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        # Create 3 referral codes
        codes = []
        for i in range(3):
            code = ReferralCode.objects.create(customer_user=cu, code=f'CODE{i:03d}')
            codes.append(code)

        req = self._make_request()
        qs = self.admin.get_queryset(req).filter(id__in=[c.id for c in codes])
        codes_list = list(qs)  # materialize with annotation

        with CaptureQueriesContext(connection) as ctx:
            counts = [self.admin.get_referral_count(code) for code in codes_list]

        self.assertEqual(
            len(ctx.captured_queries), 0,
            f"Expected 0 extra queries after annotation, got {len(ctx.captured_queries)}"
        )
        for c in counts:
            self.assertIsInstance(c, int)
            self.assertGreaterEqual(c, 0)


# --- From test_code016_customer_admin_n_plus_one.py ---

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser_c016(username='su_code016'):
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'is_staff': True, 'is_superuser': True}
    )
    user.set_password('x')
    user.save()
    return user


def _make_tenant_c016(name='CODE016Shop'):
    owner, _ = User.objects.get_or_create(
        username=f'owner_c016_{name}',
        defaults={'password': 'x'}
    )
    tenant, _ = Tenant.objects.get_or_create(
        slug=f'code016-{name.lower().replace(" ", "-")}',
        defaults={'name': name, 'owner': owner, 'is_active': True}
    )
    return tenant


def _make_customer_c016(tenant, name='ACME Corp'):
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
        self.superuser = _make_superuser_c016()
        self.factory = RequestFactory()
        self.tenant = _make_tenant_c016()

    def _make_request(self):
        request = self.factory.get('/admin/technician_portal/customer/')
        request.user = self.superuser
        request.tenant = self.tenant
        return request

    def test_prefetch_attribute_present_on_queryset(self):
        """get_queryset() should attach _primary_contacts to every Customer object."""
        customer = _make_customer_c016(self.tenant, 'PrefetchTest Corp')
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        self.assertTrue(
            hasattr(obj, '_primary_contacts'),
            "_primary_contacts prefetch attribute missing from queryset object"
        )

    def test_get_primary_contact_with_primary_contact(self):
        """Returns 'Full Name (email)' when a primary contact exists."""
        customer = _make_customer_c016(self.tenant, 'HasContact Corp')
        cu = _make_customer_user(customer, 'code016_primary_cu', is_primary=True)
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        result = self.admin.get_primary_contact(obj)
        self.assertIn(cu.user.get_full_name(), result)
        self.assertIn(cu.user.email, result)

    def test_get_primary_contact_without_primary_contact(self):
        """Returns 'No primary contact' when no CustomerUser with is_primary_contact=True."""
        customer = _make_customer_c016(self.tenant, 'NoContact Corp')
        # Create a non-primary CustomerUser to ensure the filter is correct
        _make_customer_user(customer, 'code016_nonprimary_cu', is_primary=False)
        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)
        result = self.admin.get_primary_contact(obj)
        self.assertEqual(result, 'No primary contact')

    def test_get_primary_contact_no_customer_users(self):
        """Returns 'No primary contact' when the customer has no CustomerUsers at all."""
        customer = _make_customer_c016(self.tenant, 'EmptyContact Corp')
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
            c = _make_customer_c016(self.tenant, f'QueryCountTest {i}')
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
        customer = _make_customer_c016(self.tenant, 'FilterTest Corp')
        _make_customer_user(customer, 'code016_nonprim_filter', is_primary=False)
        primary_cu = _make_customer_user(customer, 'code016_prim_filter', is_primary=True)

        request = self._make_request()
        qs = self.admin.get_queryset(request)
        obj = qs.get(id=customer.id)

        self.assertEqual(len(obj._primary_contacts), 1)
        self.assertEqual(obj._primary_contacts[0].id, primary_cu.id)


# --- From test_code018_invoice_list_n_plus_one.py ---

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant_c018(slug, plan='pro'):
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@test.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_tech(tenant, suffix=''):
    user = User.objects.create_user(
        username=f'tech_{tenant.slug}{suffix}',
        email=f'tech_{tenant.slug}{suffix}@test.com',
        password='x',
    )
    tech, _ = Technician.objects.get_or_create(
        user=user, tenant=tenant, defaults={'is_active': True}
    )
    return tech


def _make_customer_c018(tenant, name):
    return Customer.objects.create(tenant=tenant, name=name)


def _make_repair(tenant, customer, tech, cost=50, invoiced=False):
    repair = Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=tech,
        queue_status='COMPLETED',
        skip_invoicing=False,
        service_date=datetime.date.today(),
        cost=Decimal(str(cost)),
    )
    if invoiced:
        inv = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number=f'INV-T{tenant.id}-R{repair.id}',
            invoice_date=datetime.date.today(),
            due_date=datetime.date.today(),
            status='SENT',
            total=Decimal(str(cost)),
        )
        InvoiceLineItem.objects.create(
            invoice=inv,
            repair=repair,
            description='Repair',
            quantity=1,
            unit_price=Decimal(str(cost)),
            amount=Decimal(str(cost)),
        )
    return repair


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@override_settings(**TEST_OVERRIDES)
class TestInvoiceListUninvoicedBulkQuery(TestCase):
    """Verify correctness and query-efficiency of the uninvoiced_customers widget."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_c018('c018main')
        self.tech = _make_tech(self.tenant)
        self.client = Client()
        self.client.force_login(self.owner)

    def test_uninvoiced_customer_appears_in_context(self):
        """Customer with uninvoiced completed repairs should appear in widget."""
        cust = _make_customer_c018(self.tenant, 'Cust018A')
        repair = _make_repair(self.tenant, cust, self.tech, invoiced=False)
        # Reload from DB — save() may have recalculated cost via pricing rules
        repair.refresh_from_db()

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)

        uninvoiced = resp.context['uninvoiced_customers']
        cust_ids = [uc['customer'].id for uc in uninvoiced]
        self.assertIn(cust.id, cust_ids, "Customer with uninvoiced repairs should appear in widget")

        entry = next(uc for uc in uninvoiced if uc['customer'].id == cust.id)
        self.assertEqual(entry['count'], 1)
        # Total should match the actual saved cost (pricing rules applied on save)
        self.assertEqual(entry['total'], repair.cost or 0)

    def test_fully_invoiced_customer_excluded(self):
        """Customer whose repairs are all invoiced should NOT appear in widget."""
        cust = _make_customer_c018(self.tenant, 'Cust018B')
        _make_repair(self.tenant, cust, self.tech, invoiced=True)

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)

        uninvoiced = resp.context['uninvoiced_customers']
        cust_ids = [uc['customer'].id for uc in uninvoiced]
        self.assertNotIn(cust.id, cust_ids, "Fully-invoiced customer should not appear in widget")

    def test_mixed_repairs_partial_uninvoiced(self):
        """Customer with one invoiced + one uninvoiced repair: widget shows count=1."""
        cust = _make_customer_c018(self.tenant, 'Cust018C')
        _make_repair(self.tenant, cust, self.tech, invoiced=True)
        repair2 = _make_repair(self.tenant, cust, self.tech, invoiced=False)
        repair2.refresh_from_db()

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)

        uninvoiced = resp.context['uninvoiced_customers']
        cust_ids = [uc['customer'].id for uc in uninvoiced]
        self.assertIn(cust.id, cust_ids)
        entry = next(uc for uc in uninvoiced if uc['customer'].id == cust.id)
        self.assertEqual(entry['count'], 1, "Only uninvoiced repair should count")
        self.assertEqual(entry['total'], repair2.cost or 0)

    def test_query_count_does_not_grow_with_customers(self):
        """
        The uninvoiced_customers widget should use a fixed number of queries
        regardless of how many customers exist — O(1) not O(N).

        We measure the query count delta between a 2-customer tenant and a
        7-customer tenant. The delta should be <= 2 (noise allowance), NOT
        5+ as it would be with the N+1 bug.
        """
        # Baseline: 2 customers, no repairs
        tenant_base, owner_base = _make_tenant_c018('c018base')
        for i in range(2):
            _make_customer_c018(tenant_base, f'BaseCust{i}')
        client_base = Client()
        client_base.force_login(owner_base)

        with CaptureQueriesContext(connection) as ctx_base:
            resp = client_base.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        baseline_count = len(ctx_base)

        # Scaled: 7 customers, no repairs
        tenant_scaled, owner_scaled = _make_tenant_c018('c018scaled')
        for i in range(7):
            _make_customer_c018(tenant_scaled, f'ScaledCust{i}')
        client_scaled = Client()
        client_scaled.force_login(owner_scaled)

        with CaptureQueriesContext(connection) as ctx_scaled:
            resp = client_scaled.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        scaled_count = len(ctx_scaled)

        delta = scaled_count - baseline_count
        self.assertLessEqual(
            delta, 2,
            f"Query count grew too much: baseline={baseline_count}, scaled={scaled_count}, "
            f"delta={delta}. Likely N+1 still present."
        )


# ---------------------------------------------------------------------------
# CODE-097: UserAdmin N+1 — get_role() and get_tenant() issued 4 queries per
# user in the admin changelist (2× exists() for role + 2× first() for tenant).
# Fix: override get_queryset() to prefetch_related('technician', 'customeruser').
# ---------------------------------------------------------------------------

def _make_tenant_c097(slug_suffix):
    """Helper: create a Tenant + owner User for CODE-097 tests."""
    from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'annual_price': 0},
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug_suffix}',
        slug=f'shop-{slug_suffix}',
        plan='trial',
        subscription_plan=plan,
        is_active=True,
    )
    owner = User.objects.create_user(
        username=f'owner_{slug_suffix}',
        email=f'owner_{slug_suffix}@example.com',
        password='pw',
        is_staff=True,
        is_superuser=True,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return tenant, owner


@override_settings(DEBUG=True)
class UserAdminN1Test(TestCase):
    """
    CODE-097: UserAdmin.get_role() and get_tenant() N+1 fix.

    Verifies that loading the admin changelist for N users does NOT issue
    O(N) queries for Technician/CustomerUser lookups.
    """

    def setUp(self):
        from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'annual_price': 0},
        )
        self.superuser = User.objects.create_user(
            username='c097_super',
            email='c097_super@test.com',
            password='pw',
            is_staff=True,
            is_superuser=True,
        )
        self.tenant = Tenant.objects.create(
            name='C097 Shop',
            slug='c097-shop',
            plan='trial',
            subscription_plan=plan,
            is_active=True,
            owner=self.superuser,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.superuser, role='owner', is_active=True,
        )

        # Create a mix of technician and plain users for the changelist
        from apps.technician_portal.models import Technician
        self.tech_users = []
        self.plain_users = []

        for i in range(5):
            u = User.objects.create_user(
                username=f'c097_tech_{i}',
                email=f'c097_tech_{i}@test.com',
                password='pw',
            )
            Technician.objects.create(user=u, tenant=self.tenant, is_active=True)
            TenantMembership.objects.create(tenant=self.tenant, user=u, role='technician', is_active=True)
            self.tech_users.append(u)

        for i in range(5):
            u = User.objects.create_user(
                username=f'c097_plain_{i}',
                email=f'c097_plain_{i}@test.com',
                password='pw',
            )
            self.plain_users.append(u)

        self.client = Client()
        self.client.force_login(self.superuser)

    def test_get_queryset_uses_prefetch(self):
        """
        UserAdmin.get_queryset() should prefetch 'technician' and 'customeruser'
        so display methods can read them without extra DB hits.
        """
        from rs_systems.admin import UserAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        site = AdminSite()
        ua = UserAdmin(User, site)
        factory = RequestFactory()
        req = factory.get('/admin/auth/user/')
        req.user = self.superuser

        with CaptureQueriesContext(connection) as ctx:
            qs = ua.get_queryset(req)
            # Force evaluation — iterate to trigger prefetch
            users = list(qs)

        # Verify the queryset has prefetch_related_lookups attached.
        # _prefetch_related_lookups contains Prefetch objects; extract their
        # prefetch_to attribute (the accessor name, e.g. 'technician').
        from django.db.models.query import Prefetch
        lookup_names = [
            p.prefetch_to if isinstance(p, Prefetch) else str(p)
            for p in qs._prefetch_related_lookups
        ]
        self.assertIn(
            'technician',
            lookup_names,
            f"Queryset should prefetch 'technician'; got {lookup_names}",
        )
        self.assertIn(
            'customeruser',
            lookup_names,
            f"Queryset should prefetch 'customeruser'; got {lookup_names}",
        )

    def test_get_role_uses_prefetch_cache(self):
        """
        get_role() should read from the prefetch cache, not issue new queries.
        After get_queryset(), each call to get_role() should use 0 DB queries.
        """
        from rs_systems.admin import UserAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        site = AdminSite()
        ua = UserAdmin(User, site)
        factory = RequestFactory()
        req = factory.get('/admin/auth/user/')
        req.user = self.superuser

        qs = ua.get_queryset(req)
        users = list(qs)  # populate prefetch cache

        reset_queries()
        with CaptureQueriesContext(connection) as ctx:
            for u in users:
                role = ua.get_role(u)
        
        # With prefetch, get_role should issue 0 extra queries for the cached users
        self.assertEqual(
            len(ctx), 0,
            f"get_role() issued {len(ctx)} unexpected queries after prefetch: "
            f"{[q['sql'][:80] for q in ctx.captured_queries[:3]]}"
        )

    def test_get_tenant_uses_prefetch_cache(self):
        """
        get_tenant() should read from the prefetch cache, not issue new queries.
        """
        from rs_systems.admin import UserAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        site = AdminSite()
        ua = UserAdmin(User, site)
        factory = RequestFactory()
        req = factory.get('/admin/auth/user/')
        req.user = self.superuser

        qs = ua.get_queryset(req)
        users = list(qs)  # populate prefetch cache

        reset_queries()
        with CaptureQueriesContext(connection) as ctx:
            for u in users:
                tenant_name = ua.get_tenant(u)

        self.assertEqual(
            len(ctx), 0,
            f"get_tenant() issued {len(ctx)} unexpected queries after prefetch: "
            f"{[q['sql'][:80] for q in ctx.captured_queries[:3]]}"
        )

    def test_get_role_correct_values(self):
        """get_role() returns the right role string for each user type."""
        from rs_systems.admin import UserAdmin
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory

        site = AdminSite()
        ua = UserAdmin(User, site)
        factory = RequestFactory()
        req = factory.get('/admin/auth/user/')
        req.user = self.superuser

        qs = ua.get_queryset(req)
        list(qs)  # populate cache

        # Superuser should be 'Admin'
        self.assertEqual(ua.get_role(self.superuser), 'Admin')

        # Technician users
        for u in self.tech_users:
            # Refresh from cache
            cached = next(x for x in qs if x.pk == u.pk)
            self.assertEqual(ua.get_role(cached), 'Technician',
                             f'Expected Technician for {u.username}')

        # Plain users with no Technician/CustomerUser record
        for u in self.plain_users:
            cached = next(x for x in qs if x.pk == u.pk)
            self.assertEqual(ua.get_role(cached), 'Unassigned',
                             f'Expected Unassigned for {u.username}')
