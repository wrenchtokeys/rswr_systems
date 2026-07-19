"""
CODE-143: Regression test — customer_repairs() stats aggregation.

Bug: customer_repairs() fired 5 separate DB queries to build the stats dict:
  1. repairs.count()                                     → total_repairs
  2. repairs.filter(queue_status='PENDING').count()      → pending_approval
  3. repairs.filter(queue_status__in=[...]).count()      → in_progress
  4. repairs.filter(queue_status='COMPLETED', ...).count() → completed_this_month
  5. repairs.filter(queue_status='COMPLETED').aggregate(Sum('cost')) → total_cost

Fix: collapsed all 5 into a single aggregate() call with conditional Count/Sum
using Django's Q() filter argument. Eliminates 4 round-trips per repairs list load.

Tests verify:
1. Repairs list returns 200 OK with correct stats.
2. pending_approval, in_progress, completed_this_month, total_cost are correct.
3. Stats work with active status filters applied.
4. total_cost uses Decimal, not zero for COMPLETED repairs.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser


class CustomerRepairsListStatsAggregationTest(TestCase):
    """Tests for the consolidated stats aggregation (moved into customer_services)."""

    def setUp(self):
        self.owner_user = User.objects.create_user(
            username='owner_code143', email='owner143@test.com', password='pass'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 143',
            slug='test-shop-code143',
            subdomain='test-shop-code143',
            plan='trial',
            owner=self.owner_user,
        )
        TenantMembership.objects.create(
            user=self.owner_user,
            tenant=self.tenant,
            role='owner',
            is_active=True,
        )

        self.technician = Technician.objects.create(
            user=self.owner_user,
            tenant=self.tenant,
            is_active=True,
        )

        # Customer user for portal access
        self.customer_user_account = User.objects.create_user(
            username='customer_code143', email='customer143@test.com', password='pass'
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Fleet Co 143',
            email='fleet143@test.com',
            customer_type='FLEET',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cu = CustomerUser.objects.create(
            user=self.customer_user_account,
            customer=self.customer,
            is_primary_contact=True,
        )
        TenantMembership.objects.create(
            user=self.customer_user_account,
            tenant=self.tenant,
            role='viewer',
            is_active=True,
        )

        # Create repairs with various statuses
        now = timezone.now()
        this_month_start = now.date().replace(day=1)

        self.repair_pending = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-P',
            damage_type='CHIP',
            queue_status='PENDING',
            cost=Decimal('25.00'),
            service_date=now,
        )
        self.repair_approved = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-A',
            damage_type='CHIP',
            queue_status='APPROVED',
            cost=Decimal('30.00'),
            service_date=now,
        )
        self.repair_in_progress = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-IP',
            damage_type='CRACK',
            queue_status='IN_PROGRESS',
            cost=Decimal('35.00'),
            service_date=now,
        )
        self.repair_completed_this_month = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-CM',
            damage_type='CHIP',
            queue_status='COMPLETED',
            cost=Decimal('50.00'),
            service_date=now,
        )
        self.repair_denied = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-D',
            damage_type='CHIP',
            queue_status='DENIED',
            cost=Decimal('0.00'),
            service_date=now,
        )

        self.client = Client()
        self.client.force_login(self.customer_user_account)
        # Set the tenant in session
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_repairs_list_returns_200(self):
        """GET /customer/repairs/ returns 200 OK."""
        response = self.client.get('/app/services/?type=repair')
        self.assertEqual(response.status_code, 200)

    def test_stats_pending_approval_count(self):
        """pending_approval matches PENDING repair count."""
        response = self.client.get('/app/services/?type=repair')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        self.assertEqual(stats['needs_approval'], 1)

    def test_stats_in_progress_count(self):
        """in_progress matches APPROVED + IN_PROGRESS count."""
        response = self.client.get('/app/services/?type=repair')
        stats = response.context['stats']
        self.assertEqual(stats['in_progress'], 2)  # APPROVED + IN_PROGRESS

    def test_stats_completed_this_month(self):
        """completed_this_month counts only COMPLETED repairs in the current month."""
        response = self.client.get('/app/services/?type=repair')
        stats = response.context['stats']
        self.assertEqual(stats['completed_this_month'], 1)

    def test_stats_total_cost_only_completed(self):
        """total_cost sums only COMPLETED repair costs."""
        response = self.client.get('/app/services/?type=repair')
        stats = response.context['stats']
        self.assertEqual(stats['total_cost'], Decimal('50.00'))

    def test_stats_total_repairs(self):
        """total_repairs counts all repairs for the customer."""
        response = self.client.get('/app/services/?type=repair')
        stats = response.context['stats']
        self.assertEqual(stats['repairs_total'], 5)

    def test_stats_with_status_filter(self):
        """Stats stay GLOBAL when a status filter is applied (CODE-249 behavior)."""
        response = self.client.get('/app/services/?type=repair&status=COMPLETED')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        # Stats come from the unfiltered base queryset (CODE-249),
        # so filtering the display list must not change them.
        self.assertEqual(stats['repairs_total'], 5)
        self.assertEqual(stats['needs_approval'], 1)
        self.assertEqual(stats['total_cost'], Decimal('50.00'))

    def test_total_cost_global_when_filtered_to_pending(self):
        """total_cost stays GLOBAL when the list is filtered (CODE-249 behavior)."""
        response = self.client.get('/app/services/?type=repair&status=PENDING')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        # One COMPLETED $50 repair exists; the PENDING display filter must not hide it.
        self.assertEqual(stats['total_cost'], Decimal('50.00'))

    def test_stats_keys_all_present(self):
        """All expected stats keys are present in context."""
        response = self.client.get('/app/services/?type=repair')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        expected_keys = ['repairs_total', 'needs_approval', 'in_progress',
                         'completed_this_month', 'total_cost']
        for key in expected_keys:
            self.assertIn(key, stats, f"Missing stats key: {key}")
