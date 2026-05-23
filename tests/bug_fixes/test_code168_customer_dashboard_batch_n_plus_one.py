"""
CODE-168: Regression test — customer dashboard PENDING batch repair N+1.

Bug: customer_dashboard() called Repair.get_batch_summary() once per unique
pending batch ID. Each call issued ~4 DB queries:
  1. get_batch_repairs() → SELECT * FROM repair WHERE repair_batch_id=?
  2. .exists()           → SELECT 1 FROM repair WHERE repair_batch_id=? LIMIT 1
  3. .first()            → SELECT * FROM repair WHERE repair_batch_id=? LIMIT 1
  4. iteration           → another pass over the queryset

For a customer with N unique PENDING batches, that is ~4N queries.  This is the
same N+1 class fixed for the technician dashboard in CODE-142, but the customer
dashboard was not updated at that time.

Fix: Collect all pending batch IDs first, bulk-fetch every sibling repair in ONE
query, group in Python by batch_id, then build summaries via
build_batch_summary_from_repairs() — zero additional DB queries per batch.

Tests verify:
1. Dashboard returns 200 OK when customer has pending batch repairs.
2. Batch repairs are correctly grouped in context['batch_repairs'].
3. Individual (non-batched) repairs appear in context['individual_repairs'].
4. Multiple pending batches are all surfaced — not just the first one.
5. Batch summaries contain expected fields (break_count, total_cost, unit_number).
6. An unrelated tenant's batch repair does NOT appear in the context (tenant isolation).
"""

import uuid
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser


class CustomerDashboardBatchPendingN1Test(TestCase):
    """Tests for CODE-168 bulk batch prefetch in customer_dashboard()."""

    def setUp(self):
        # --- Tenant A ---
        self.owner_a = User.objects.create_user(
            username='owner_code168a', email='owner168a@test.com', password='pass'
        )
        self.tenant_a = Tenant.objects.create(
            name='Shop Alpha Code168',
            slug='shop-alpha-code168',
            owner=self.owner_a,
        )
        TenantMembership.objects.create(
            tenant=self.tenant_a, user=self.owner_a, role='owner'
        )
        self.tech_a = Technician.objects.create(
            user=self.owner_a,
            tenant=self.tenant_a,
            is_active=True,
            can_repair=True,
        )
        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a,
            name='Fleet Alpha Code168',
        )
        # Customer portal user
        self.cu_user_a = User.objects.create_user(
            username='cu_code168a', email='cu168a@test.com', password='pass'
        )
        self.customer_user_a = CustomerUser.objects.create(
            user=self.cu_user_a,
            customer=self.customer_a,
            is_primary_contact=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant_a, user=self.cu_user_a, role='viewer'
        )

        # --- Tenant B (isolation test) ---
        self.owner_b = User.objects.create_user(
            username='owner_code168b', email='owner168b@test.com', password='pass'
        )
        self.tenant_b = Tenant.objects.create(
            name='Shop Beta Code168',
            slug='shop-beta-code168',
            owner=self.owner_b,
        )
        TenantMembership.objects.create(
            tenant=self.tenant_b, user=self.owner_b, role='owner'
        )
        self.tech_b = Technician.objects.create(
            user=self.owner_b,
            tenant=self.tenant_b,
            is_active=True,
            can_repair=True,
        )
        self.customer_b = Customer.objects.create(
            tenant=self.tenant_b,
            name='Fleet Beta Code168',
        )

        self.client = Client()

    def _make_pending_batch(self, tenant, tech, customer, unit_number, break_count=3):
        """Create a PENDING batch with `break_count` repairs, return batch_id."""
        batch_id = uuid.uuid4()
        for i in range(1, break_count + 1):
            Repair.objects.create(
                tenant=tenant,
                technician=tech,
                customer=customer,
                unit_number=unit_number,
                damage_type='Chip',
                cost=Decimal('50.00'),
                queue_status='PENDING',
                repair_batch_id=batch_id,
                break_number=i,
                total_breaks_in_batch=break_count,
                service_date=timezone.now(),
            )
        return batch_id

    def _make_pending_single(self, tenant, tech, customer, unit_number):
        """Create a single PENDING (non-batch) repair, return it."""
        return Repair.objects.create(
            tenant=tenant,
            technician=tech,
            customer=customer,
            unit_number=unit_number,
            damage_type='Chip',
            cost=Decimal('50.00'),
            queue_status='PENDING',
            service_date=timezone.now(),
        )

    def _login_as_customer(self, cu_user, tenant):
        self.client.login(username=cu_user.username, password='pass')
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_dashboard_200_with_pending_batch(self):
        """Dashboard renders OK when customer has a pending batch repair."""
        self._make_pending_batch(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-01')
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)

    def test_single_batch_appears_in_batch_repairs_context(self):
        """A single pending batch is surfaced in context['batch_repairs']."""
        batch_id = self._make_pending_batch(
            self.tenant_a, self.tech_a, self.customer_a, 'UNIT-01', break_count=3
        )
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)
        batch_repairs = resp.context['batch_repairs']
        self.assertEqual(len(batch_repairs), 1, "Expected exactly 1 batch summary")
        summary = batch_repairs[0]
        self.assertEqual(summary['break_count'], 3)
        self.assertEqual(summary['unit_number'], 'UNIT-01')
        self.assertEqual(summary['total_cost'], Decimal('150.00'))

    def test_multiple_pending_batches_all_surfaced(self):
        """All pending batches for a customer are returned, not just the first."""
        self._make_pending_batch(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-01', 2)
        self._make_pending_batch(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-02', 3)
        self._make_pending_batch(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-03', 2)
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)
        batch_repairs = resp.context['batch_repairs']
        self.assertEqual(len(batch_repairs), 3, "All 3 batches should appear")

    def test_individual_pending_repairs_separate_from_batches(self):
        """Non-batched PENDING repairs appear in individual_repairs, not batch_repairs."""
        self._make_pending_batch(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-BATCH')
        single = self._make_pending_single(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-SINGLE')
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)
        batch_repairs = resp.context['batch_repairs']
        individual_repairs = resp.context['individual_repairs']
        self.assertEqual(len(batch_repairs), 1, "1 batch")
        self.assertEqual(len(individual_repairs), 1, "1 individual repair")
        self.assertEqual(individual_repairs[0].id, single.id)

    def test_batch_summary_has_required_fields(self):
        """Batch summary dict contains all fields the template needs."""
        self._make_pending_batch(self.tenant_a, self.tech_a, self.customer_a, 'UNIT-01', 2)
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        summary = resp.context['batch_repairs'][0]
        for key in ('batch_id', 'unit_number', 'break_count', 'total_cost',
                    'statuses', 'all_same_status', 'customer', 'service_date'):
            self.assertIn(key, summary, f"Missing key: {key}")

    def test_cross_tenant_batch_not_included(self):
        """A pending batch from Tenant B does NOT appear on Tenant A customer dashboard."""
        # Batch at Shop B
        self._make_pending_batch(self.tenant_b, self.tech_b, self.customer_b, 'UNIT-B')
        # Nothing at Shop A
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['batch_repairs']), 0, "Shop B batch must not leak into Shop A")
        self.assertEqual(len(resp.context['individual_repairs']), 0)

    def test_dashboard_200_no_pending_repairs(self):
        """Dashboard works fine when customer has no pending repairs at all."""
        # No pending repairs — just a completed one
        Repair.objects.create(
            tenant=self.tenant_a,
            technician=self.tech_a,
            customer=self.customer_a,
            unit_number='UNIT-C',
            damage_type='Chip',
            cost=Decimal('50.00'),
            queue_status='COMPLETED',
            service_date=timezone.now(),
        )
        self._login_as_customer(self.cu_user_a, self.tenant_a)
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['batch_repairs']), 0)
        self.assertEqual(len(resp.context['individual_repairs']), 0)
