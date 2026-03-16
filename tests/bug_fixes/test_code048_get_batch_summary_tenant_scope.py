"""
Regression tests for CODE-048: get_batch_repairs() / get_batch_summary() missing tenant scope.

Bug:
    Repair.get_batch_repairs(batch_id) had no tenant parameter.  Any code that called
    get_batch_summary(batch_id) could retrieve batch data belonging to a different
    tenant by guessing (or knowing) the UUID of the batch.

    Key vulnerable callers:
      - technician_batch_detail: admin/owner path set can_view=True without verifying
        the batch belonged to the current tenant → cross-tenant IDOR for admins.
      - customer_batch_detail/approve/deny: post-fetch `batch_summary['customer'] != customer`
        check relied on application logic rather than the DB query.

Fix:
    Added optional `tenant` parameter to get_batch_repairs() and get_batch_summary().
    When tenant is provided, the queryset is filtered by `tenant=tenant` so cross-tenant
    batch UUIDs return no results (batch_summary returns None → 404 / redirect).
    All callers in views and templates now pass tenant=<request.tenant | customer.tenant>.
"""
import uuid
from datetime import date

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name, plan):
    slug_base = name.lower().replace(' ', '-')
    suffix = Tenant.objects.count()
    owner = User.objects.create_user(
        username=f'owner_{slug_base}_{suffix}',
        password='pw',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=f'{slug_base}-{suffix}',
        subdomain=f'{slug_base}-{suffix}',
        owner=owner,
        plan='trial',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant, owner


def _make_technician(tenant, username_suffix=''):
    user = User.objects.create_user(
        username=f'tech_{tenant.slug}_{username_suffix}_{Technician.objects.count()}',
        password='pw',
    )
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        is_active=True,
        can_repair=True,
    )
    TenantMembership.objects.create(user=user, tenant=tenant, role='technician', is_active=True)
    return tech


def _make_customer(tenant):
    return Customer.objects.create(
        tenant=tenant,
        name=f'Customer {Customer.objects.count()}',
    )


def _make_batch_repairs(tenant, customer, technician, n_breaks=2):
    """Create n_breaks repairs sharing a batch UUID."""
    batch_id = uuid.uuid4()
    repairs = []
    for i in range(1, n_breaks + 1):
        r = Repair.objects.create(
            tenant=tenant,
            customer=customer,
            technician=technician,
            unit_number='UNIT-001',
            service_date=date.today(),
            damage_type='CHIP',
            queue_status='PENDING',
            cost=50,
            repair_batch_id=batch_id,
            break_number=i,
            total_breaks_in_batch=n_breaks,
            is_multi_break_estimate=False,
        )
        repairs.append(r)
    return batch_id, repairs


# ---------------------------------------------------------------------------
# Tests: model-level
# ---------------------------------------------------------------------------

class GetBatchRepairsTenantScopeTest(TestCase):
    """Repair.get_batch_repairs() tenant param must restrict results."""

    def setUp(self):
        plan = _make_plan()
        self.tenant_a, _ = _make_tenant('Shop A', plan)
        self.tenant_b, _ = _make_tenant('Shop B', plan)
        self.tech_a = _make_technician(self.tenant_a, 'a')
        self.tech_b = _make_technician(self.tenant_b, 'b')
        self.customer_a = _make_customer(self.tenant_a)
        self.customer_b = _make_customer(self.tenant_b)

        self.batch_id_a, self.repairs_a = _make_batch_repairs(
            self.tenant_a, self.customer_a, self.tech_a, n_breaks=2
        )
        self.batch_id_b, self.repairs_b = _make_batch_repairs(
            self.tenant_b, self.customer_b, self.tech_b, n_breaks=3
        )

    def test_no_tenant_returns_all_batches(self):
        """Without tenant param the method returns all matching repairs (original behaviour)."""
        qs = Repair.get_batch_repairs(self.batch_id_a)
        self.assertEqual(qs.count(), 2)

    def test_correct_tenant_returns_batch(self):
        """Passing the correct tenant returns the batch normally."""
        qs = Repair.get_batch_repairs(self.batch_id_a, tenant=self.tenant_a)
        self.assertEqual(qs.count(), 2)

    def test_wrong_tenant_returns_empty(self):
        """Passing a different tenant returns no repairs — cross-tenant IDOR blocked."""
        qs = Repair.get_batch_repairs(self.batch_id_a, tenant=self.tenant_b)
        self.assertEqual(qs.count(), 0, "Batch A repairs must not be visible to tenant B")

    def test_batch_summary_wrong_tenant_returns_none(self):
        """get_batch_summary with wrong tenant returns None (→ 404 in views)."""
        summary = Repair.get_batch_summary(self.batch_id_a, tenant=self.tenant_b)
        self.assertIsNone(summary, "get_batch_summary with wrong tenant must return None")

    def test_batch_summary_correct_tenant_returns_data(self):
        """get_batch_summary with correct tenant returns the summary dict."""
        summary = Repair.get_batch_summary(self.batch_id_a, tenant=self.tenant_a)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['break_count'], 2)
        self.assertEqual(summary['customer'], self.customer_a)

    def test_batch_summary_no_tenant_still_works(self):
        """Without tenant param, get_batch_summary still returns data (backward compat)."""
        summary = Repair.get_batch_summary(self.batch_id_b)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['break_count'], 3)


# ---------------------------------------------------------------------------
# Tests: technician portal view — cross-tenant admin IDOR
# ---------------------------------------------------------------------------

class TechnicianBatchDetailCrossTenantTest(TestCase):
    """technician_batch_detail must not let Shop A admin see Shop B's batch."""

    def setUp(self):
        plan = _make_plan()
        self.tenant_a, self.owner_a = _make_tenant('Shop A BHT', plan)
        self.tenant_b, self.owner_b = _make_tenant('Shop B BHT', plan)
        self.tech_b = _make_technician(self.tenant_b, 'tb')
        self.customer_b = _make_customer(self.tenant_b)
        self.batch_id_b, _ = _make_batch_repairs(
            self.tenant_b, self.customer_b, self.tech_b, n_breaks=2
        )

    def test_admin_from_shop_a_cannot_access_shop_b_batch_via_model(self):
        """
        Model-level: get_batch_summary scoped to tenant_a must return None for a
        batch that belongs to tenant_b — even for a Shop A admin/owner.
        This is the key invariant that technician_batch_detail now enforces.
        """
        # tenant_a admin perspective — uses their own tenant for scoping
        summary = Repair.get_batch_summary(self.batch_id_b, tenant=self.tenant_a)
        self.assertIsNone(
            summary,
            "Shop A admin scoping to tenant_a must get None for Shop B's batch"
        )

    def test_admin_from_shop_b_can_access_shop_b_batch(self):
        """Shop B owner with correct tenant can see their own batch."""
        summary = Repair.get_batch_summary(self.batch_id_b, tenant=self.tenant_b)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['break_count'], 2)


# ---------------------------------------------------------------------------
# Tests: customer portal batch views — tenant scope
# ---------------------------------------------------------------------------

class CustomerBatchTenantScopeTest(TestCase):
    """customer_batch_detail/approve/deny must pass tenant to get_batch_summary."""

    def setUp(self):
        from apps.customer_portal.models import CustomerUser
        plan = _make_plan()
        self.tenant_a, _ = _make_tenant('Shop C', plan)
        self.tenant_b, _ = _make_tenant('Shop D', plan)
        self.tech_a = _make_technician(self.tenant_a, 'csa')
        self.tech_b = _make_technician(self.tenant_b, 'csb')
        self.customer_a = _make_customer(self.tenant_a)
        self.customer_b = _make_customer(self.tenant_b)

        # Create a CustomerUser for Shop A
        cu_user = User.objects.create_user(username='cu_a_bhtest', password='pw')
        self.cu_a = CustomerUser.objects.create(
            user=cu_user,
            customer=self.customer_a,
            is_primary_contact=True,
        )

        self.batch_id_b, _ = _make_batch_repairs(
            self.tenant_b, self.customer_b, self.tech_b, n_breaks=2
        )

    def test_get_batch_summary_with_customer_tenant_blocks_cross_tenant(self):
        """
        Simulate what customer_batch_detail does:
        fetch batch summary scoped to customer.tenant.
        A Shop A customer must NOT be able to retrieve Shop B's batch.
        """
        customer = self.customer_a
        summary = Repair.get_batch_summary(self.batch_id_b, tenant=customer.tenant)
        self.assertIsNone(summary, "Shop A customer must not see Shop B's batch")

    def test_get_batch_summary_with_same_tenant_succeeds(self):
        """A customer querying their own shop's batch gets data."""
        batch_id_a, _ = _make_batch_repairs(
            self.tenant_a, self.customer_a, self.tech_a, n_breaks=3
        )
        summary = Repair.get_batch_summary(batch_id_a, tenant=self.customer_a.tenant)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['customer'], self.customer_a)
