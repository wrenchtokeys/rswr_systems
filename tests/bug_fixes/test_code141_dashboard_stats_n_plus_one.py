"""
CODE-141: Regression test — customer dashboard stats aggregation.

Bug: customer_dashboard() fired 7 separate DB queries (6 COUNTs + 1 SUM) to build
the repair stats dict. Each status query hit the repairs table individually:
  1. .exclude(status='COMPLETED').exclude(status='DENIED').count()   → active_repairs
  2. .filter(status='COMPLETED').count()                              → completed_repairs
  3. .filter(status='PENDING').count()                                → pending_approval
  4. .filter(status='COMPLETED').aggregate(sum=Sum('cost'))           → total_spent
  5. .filter(status='REQUESTED').count()                             → repairs_requested
  6. .filter(status='APPROVED').count()                              → repairs_approved
  7. .filter(status='IN_PROGRESS').count()                           → repairs_in_progress
  8. .filter(status='DENIED').count()                                → repairs_denied

Fix: collapsed all 7 into a single aggregate() call with conditional Count/Sum using
Django's Q() filter argument. Eliminates 6 round-trips per dashboard load (CODE-141).

Tests verify:
1. Dashboard returns 200 OK with correct status counts in context.
2. All status values (REQUESTED, PENDING, APPROVED, IN_PROGRESS, COMPLETED, DENIED)
   are counted correctly from the single aggregate call.
3. total_spent only counts COMPLETED repair costs.
4. active_repairs = REQUESTED + PENDING + APPROVED + IN_PROGRESS (excludes COMPLETED/DENIED).
5. Context keys are all present (no regressions from consolidation).
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser


class CustomerDashboardStatsAggregationTest(TestCase):
    """Tests for the consolidated repair stats in customer_dashboard()."""

    def setUp(self):
        # Owner + technician
        self.owner_user = User.objects.create_user(
            username='owner_code141', email='owner141@test.com', password='pass'
        )

        # Tenant (owner required — not-null FK)
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-code141',
            subdomain='test-shop-code141',
            plan='trial',
            owner=self.owner_user,
        )

        self.technician = Technician.objects.create(
            user=self.owner_user,
            tenant=self.tenant,
            is_active=True,
        )

        # Customer
        self.customer = Customer.objects.create(
            name='Fleet Corp 141',
            tenant=self.tenant,
        )

        # CustomerUser
        self.customer_user_account = User.objects.create_user(
            username='fleet_code141', email='fleet141@test.com', password='fleet141pass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.customer_user_account,
            customer=self.customer,
            is_primary_contact=True,
        )

        # Create repairs in various statuses
        def _repair(status, cost=None):
            return Repair.objects.create(
                tenant=self.tenant,
                customer=self.customer,
                technician=self.technician,
                unit_number='U-141',
                queue_status=status,
                service_date=timezone.now(),
                cost=Decimal(cost) if cost else Decimal('50.00'),
            )

        self.repair_requested = _repair('REQUESTED', 55.00)
        self.repair_pending   = _repair('PENDING', 45.00)
        self.repair_approved  = _repair('APPROVED', 60.00)
        self.repair_in_prog   = _repair('IN_PROGRESS', 70.00)
        self.repair_completed = _repair('COMPLETED', 80.00)
        self.repair_denied    = _repair('DENIED', 40.00)

        self.client = Client()
        self.client.login(username='fleet_code141', password='fleet141pass')
        # Set tenant in session so middleware resolves it
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _get_dashboard(self):
        response = self.client.get('/app/dashboard/')
        self.assertEqual(response.status_code, 200, f'Dashboard returned {response.status_code}')
        return response

    def test_dashboard_returns_200(self):
        """Dashboard page loads without errors."""
        self._get_dashboard()

    def test_completed_repairs_count(self):
        """repairs_completed in stats == number of COMPLETED repairs."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['repairs_completed'], 1)

    def test_pending_repair_count(self):
        """repairs_pending in stats == number of PENDING repairs."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['repairs_pending'], 1)

    def test_requested_repair_count(self):
        """repairs_requested in stats == number of REQUESTED repairs."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['repairs_requested'], 1)

    def test_approved_repair_count(self):
        """repairs_approved in stats == number of APPROVED repairs."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['repairs_approved'], 1)

    def test_in_progress_repair_count(self):
        """repairs_in_progress in stats == number of IN_PROGRESS repairs."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['repairs_in_progress'], 1)

    def test_denied_repair_count(self):
        """repairs_denied in stats == number of DENIED repairs."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['repairs_denied'], 1)

    def test_active_repairs_excludes_completed_and_denied(self):
        """active_repairs = REQUESTED + PENDING + APPROVED + IN_PROGRESS."""
        response = self._get_dashboard()
        stats = response.context['stats']
        # We have 1 of each: REQUESTED, PENDING, APPROVED, IN_PROGRESS = 4
        self.assertEqual(stats['active_repairs'], 4)

    def test_total_spent_only_counts_completed(self):
        """total_spent only sums cost of COMPLETED repairs."""
        # Repair.save() overrides cost based on pricing tiers, so fetch the
        # actual computed cost from DB instead of comparing to the input value.
        self.repair_completed.refresh_from_db()
        expected_total = self.repair_completed.cost

        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['total_spent'], expected_total)

    def test_all_context_keys_present(self):
        """All required stats context keys are present after the refactor."""
        response = self._get_dashboard()
        stats = response.context['stats']
        required_keys = [
            'active_repairs', 'completed_repairs', 'pending_approval', 'total_spent',
            'repairs_requested', 'repairs_pending', 'repairs_approved',
            'repairs_in_progress', 'repairs_completed', 'repairs_denied',
        ]
        for key in required_keys:
            self.assertIn(key, stats, f'Missing stats key: {key}')

    def test_pending_approval_equals_pending_count(self):
        """pending_approval in stats matches repairs_pending (aliases for same value)."""
        response = self._get_dashboard()
        stats = response.context['stats']
        self.assertEqual(stats['pending_approval'], stats['repairs_pending'])

    def test_no_cross_tenant_leakage(self):
        """Stats only count repairs belonging to the customer's tenant."""
        # Create a second tenant with its own repair to verify no cross-tenant bleed
        other_owner = User.objects.create_user(
            username='other_tech141', email='other141@test.com', password='pass'
        )
        other_tenant = Tenant.objects.create(
            name='Other Shop 141', slug='other-shop-141', subdomain='other-141',
            plan='trial', owner=other_owner,
        )
        other_customer = Customer.objects.create(
            name='Other Customer', tenant=other_tenant
        )
        other_tech = Technician.objects.create(
            user=other_owner, tenant=other_tenant, is_active=True
        )
        # This repair belongs to other_tenant — should NOT appear in our stats
        Repair.objects.create(
            tenant=other_tenant,
            customer=other_customer,
            technician=other_tech,
            unit_number='U-OTHER',
            queue_status='COMPLETED',
            service_date=timezone.now(),
            cost=Decimal('999.00'),
        )

        # Get the actual cost of our completed repair (Repair.save() overrides based on pricing tiers)
        self.repair_completed.refresh_from_db()
        expected_completed_cost = self.repair_completed.cost

        response = self._get_dashboard()
        stats = response.context['stats']
        # Only our one COMPLETED repair should be counted
        self.assertEqual(stats['repairs_completed'], 1)
        self.assertEqual(stats['total_spent'], expected_completed_cost)
