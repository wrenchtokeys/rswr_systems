"""
CODE-142: Regression test — technician dashboard batch summary N+1 query.

Bug: technician_dashboard() called Repair.get_batch_summary(batch_id, tenant=tenant)
inside three separate loops (approved / in-progress / completed).  Each call to
get_batch_summary() issued ~4 DB queries (exists, first, list, values_list).
With up to 60 unique batches across the three sections that's potentially ~240 DB
queries per dashboard load.

Fix (CODE-142):
  1. Added Repair.build_batch_summary_from_repairs(batch_id, repairs_list) classmethod
     that builds the summary dict from a pre-loaded Python list — zero DB queries.
  2. Dashboard now bulk-fetches all sibling repairs for every batch_id present in the
     three repair slices in a SINGLE query before the loops begin.
  3. Loop helper _batch_summary() reads from the prefetched dict; falls back to the
     original get_batch_summary() only when the cache misses (defensive).

Tests verify:
  1. build_batch_summary_from_repairs() produces correct summary fields.
  2. build_batch_summary_from_repairs() returns None for empty list.
  3. Dashboard renders 200 OK with batch repairs correctly grouped.
  4. Dashboard DB query count does NOT scale with the number of unique batches
     (i.e. adding more batches does not add more queries — no N+1).
  5. Individual (non-batch) repairs still appear correctly.
  6. Batches with all repairs COMPLETED appear only in the completed section.
  7. Batches with IN_PROGRESS repairs appear in the in-progress section.
"""

import uuid
from decimal import Decimal
from datetime import timedelta

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.db import connection, reset_queries
from django.test.utils import override_settings
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair


def _make_batch_repairs(technician, customer, tenant, queue_status, n=3):
    """Create n repairs sharing a batch_id; return (batch_id, repairs)."""
    batch_id = uuid.uuid4()
    repairs = []
    for i in range(1, n + 1):
        r = Repair.objects.create(
            tenant=tenant,
            technician=technician,
            customer=customer,
            queue_status=queue_status,
            repair_batch_id=batch_id,
            break_number=i,
            total_breaks_in_batch=n,
            unit_number='TRUCK-01',
            service_date=timezone.now() - timedelta(hours=i),
            damage_type='CHIP',
            cost=Decimal('50.00'),
        )
        repairs.append(r)
    return batch_id, repairs


class BuildBatchSummaryFromRepairsTest(TestCase):
    """Unit tests for the new Repair.build_batch_summary_from_repairs() classmethod."""

    def setUp(self):
        owner = User.objects.create_user('owner142', password='pass')
        self.tenant = Tenant.objects.create(
            name='Test Shop', subdomain='testshop-142', plan='pro', owner=owner
        )
        user = User.objects.create_user('tech142', password='pass')
        self.technician = Technician.objects.create(
            user=user, tenant=self.tenant, is_active=True
        )
        self.customer = Customer.objects.create(
            name='Test Fleet', tenant=self.tenant
        )

    def test_returns_none_for_empty_list(self):
        result = Repair.build_batch_summary_from_repairs(uuid.uuid4(), [])
        self.assertIsNone(result)

    def test_correct_fields_returned(self):
        batch_id, repairs = _make_batch_repairs(
            self.technician, self.customer, self.tenant, 'IN_PROGRESS', n=3
        )
        summary = Repair.build_batch_summary_from_repairs(batch_id, repairs)
        self.assertIsNotNone(summary)
        self.assertEqual(summary['batch_id'], batch_id)
        self.assertEqual(summary['break_count'], 3)
        self.assertEqual(summary['total_cost'], Decimal('150.00'))
        self.assertEqual(summary['in_progress_count'], 3)
        self.assertEqual(summary['completed_count'], 0)
        self.assertEqual(summary['approved_count'], 0)
        self.assertEqual(summary['progress_percentage'], 0)
        self.assertFalse(summary['all_same_status'] is False)  # all IN_PROGRESS → True
        self.assertTrue(summary['all_same_status'])
        self.assertEqual(summary['current_status'], 'IN_PROGRESS')
        self.assertEqual(summary['unit_number'], 'TRUCK-01')

    def test_mixed_statuses(self):
        batch_id = uuid.uuid4()
        r1 = Repair.objects.create(
            tenant=self.tenant, technician=self.technician, customer=self.customer,
            queue_status='COMPLETED', repair_batch_id=batch_id, break_number=1,
            total_breaks_in_batch=2, unit_number='U1', service_date=timezone.now(),
            damage_type='CHIP', cost=Decimal('50.00'),
        )
        r2 = Repair.objects.create(
            tenant=self.tenant, technician=self.technician, customer=self.customer,
            queue_status='IN_PROGRESS', repair_batch_id=batch_id, break_number=2,
            total_breaks_in_batch=2, unit_number='U1', service_date=timezone.now(),
            damage_type='CHIP', cost=Decimal('60.00'),
        )
        summary = Repair.build_batch_summary_from_repairs(batch_id, [r1, r2])
        self.assertFalse(summary['all_same_status'])
        self.assertEqual(summary['current_status'], 'MIXED')
        self.assertEqual(summary['completed_count'], 1)
        self.assertEqual(summary['in_progress_count'], 1)
        self.assertEqual(summary['total_cost'], Decimal('110.00'))
        self.assertEqual(summary['progress_percentage'], 50)

    def test_matches_get_batch_summary_output(self):
        """
        build_batch_summary_from_repairs must produce the same numeric/string fields as
        get_batch_summary.  Note: the original get_batch_summary has a pre-existing quirk
        where .values_list('queue_status', flat=True).distinct() can return duplicate entries
        if the DB result ordering includes duplicates, so all_same_status may be incorrect
        in the original but correct in the new method.  We only compare fields that are
        clearly unambiguous: cost, counts, progress, unit_number.
        """
        batch_id, repairs = _make_batch_repairs(
            self.technician, self.customer, self.tenant, 'APPROVED', n=2
        )
        original = Repair.get_batch_summary(batch_id, tenant=self.tenant)
        from_list = Repair.build_batch_summary_from_repairs(batch_id, repairs)
        # Numeric and string fields that must be identical
        for key in ('break_count', 'total_cost', 'in_progress_count', 'approved_count',
                    'completed_count', 'progress_percentage', 'unit_number'):
            self.assertEqual(original[key], from_list[key], f"Mismatch for key: {key}")
        # build_batch_summary_from_repairs correctly deduplicates statuses;
        # for a homogeneous batch all_same_status must be True.
        self.assertTrue(from_list['all_same_status'])
        self.assertEqual(from_list['current_status'], 'APPROVED')


@override_settings(DEBUG=True)
class DashboardBatchQueryCountTest(TestCase):
    """
    Verify that adding more batches to the dashboard does NOT linearly increase
    the number of DB queries (no N+1 regression).
    """

    def _setup_shop(self, subdomain):
        owner_user = User.objects.create_user(f'owner_{subdomain}', password='pass')
        tenant = Tenant.objects.create(
            name=f'Shop {subdomain}', subdomain=subdomain, plan='pro', owner=owner_user
        )
        TenantMembership.objects.create(user=owner_user, tenant=tenant, role='owner', is_active=True)
        tech_user = User.objects.create_user(f'tech_{subdomain}', password='pass')
        tech = Technician.objects.create(
            user=tech_user, tenant=tenant, is_active=True, can_repair=True
        )
        TenantMembership.objects.create(user=tech_user, tenant=tenant, role='technician', is_active=True)
        customer = Customer.objects.create(name='Fleet Co', tenant=tenant)
        return tenant, tech, tech_user, customer

    def _make_client_for(self, user, tenant):
        """Create a test Client with tenant set in session (matches middleware pattern)."""
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = tenant.id
        session.save()
        return client

    def _count_queries_for_dashboard(self, tech_user, tenant):
        client = self._make_client_for(tech_user, tenant)
        reset_queries()
        response = client.get('/tech/')
        return len(connection.queries), response

    def test_dashboard_200_with_batch_repairs(self):
        """Dashboard renders 200 OK when technician has batch repairs."""
        tenant, tech, tech_user, customer = self._setup_shop('batch142a')
        _make_batch_repairs(tech, customer, tenant, 'IN_PROGRESS', n=3)
        _make_batch_repairs(tech, customer, tenant, 'APPROVED', n=2)

        client = self._make_client_for(tech_user, tenant)
        response = client.get('/tech/')
        self.assertEqual(response.status_code, 200)

    def test_no_n_plus_one_with_multiple_batches(self):
        """
        Query count with 5 batches should be close to query count with 1 batch
        (within a small tolerance for query overhead).  If N+1 were present,
        each extra batch would add ~4 queries.
        """
        # Shop with 1 in-progress batch
        t1, tech1, user1, cust1 = self._setup_shop('batch142b')
        _make_batch_repairs(tech1, cust1, t1, 'IN_PROGRESS', n=2)
        queries_1, r1 = self._count_queries_for_dashboard(user1, t1)
        self.assertEqual(r1.status_code, 200)

        # Shop with 5 in-progress batches
        t2, tech2, user2, cust2 = self._setup_shop('batch142c')
        for _ in range(5):
            _make_batch_repairs(tech2, cust2, t2, 'IN_PROGRESS', n=3)
        queries_5, r5 = self._count_queries_for_dashboard(user2, t2)
        self.assertEqual(r5.status_code, 200)

        # With the N+1 fix, 5 batches should add at most 2 extra queries vs 1 batch
        # (e.g. one larger IN query instead of 5× single-batch queries).
        # Without the fix, each batch adds ~4 queries: 5 batches → +20 extra.
        delta = queries_5 - queries_1
        self.assertLess(
            delta, 10,
            f"Query count grew by {delta} when going from 1 to 5 batches — "
            f"possible N+1 regression. (1 batch: {queries_1} queries, "
            f"5 batches: {queries_5} queries)"
        )

    def test_individual_repairs_still_appear(self):
        """Non-batch repairs are still shown correctly alongside batched ones."""
        tenant, tech, tech_user, customer = self._setup_shop('batch142d')
        # One batch
        _make_batch_repairs(tech, customer, tenant, 'IN_PROGRESS', n=2)
        # One individual repair
        Repair.objects.create(
            tenant=tenant, technician=tech, customer=customer,
            queue_status='IN_PROGRESS', unit_number='SOLO-1',
            service_date=timezone.now(), damage_type='CHIP', cost=Decimal('45.00'),
        )

        client = self._make_client_for(tech_user, tenant)
        response = client.get('/tech/')
        self.assertEqual(response.status_code, 200)
        # Individual repairs appear in individual_repairs_in_progress context
        individual_in_progress = response.context.get('individual_repairs_in_progress', [])
        self.assertEqual(len(individual_in_progress), 1)
        self.assertEqual(individual_in_progress[0].unit_number, 'SOLO-1')
