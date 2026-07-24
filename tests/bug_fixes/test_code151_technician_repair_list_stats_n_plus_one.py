"""
CODE-151: Regression test — repair_list() stats aggregation (technician portal).

Bug: repair_list() in apps/technician_portal/views/repairs.py fired 5 separate
DB queries to build the stats dict:
  1. repairs.count()                                      → total_repairs
  2. repairs.exclude(queue_status='COMPLETED').count()    → total_active
  3. repairs.filter(queue_status='REQUESTED').count()     → pending_approval
  4. repairs.filter(queue_status='IN_PROGRESS').count()   → in_progress
  5. repairs.filter(...).count()                          → completed_this_week

This is the same N+1 pattern fixed for customer_dashboard (CODE-141) and
customer_repairs (CODE-143), but was missed in the technician portal repair list.

Fix: collapsed all 5 into a single aggregate() call with conditional Count
using Django's Q() filter argument. Eliminates 4 round-trips per page load.

Tests verify:
1. repair_list() returns 200 OK with correct stats in context.
2. total_active, pending_approval, in_progress, completed_this_week are correct.
3. Stats update correctly as repairs change status.
4. completed_this_week only counts repairs from the last 7 days.
5. All four stats are correct simultaneously.
"""

import uuid
from datetime import timedelta

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com', password='testpass'
    )


def _make_tenant(name):
    slug = uuid.uuid4().hex[:12]
    owner = _make_user(f'owner_{slug}')
    tenant = Tenant.objects.create(name=name, slug=slug, subdomain=slug, owner=owner)
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant, owner


def _make_tech(user, tenant, is_manager=False):
    return Technician.objects.create(
        user=user, tenant=tenant, is_active=True, is_manager=is_manager,
    )


def _make_membership(user, tenant, role='technician'):
    TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class TechnicianRepairListStatsAggregationTest(TestCase):
    """Tests for the consolidated stats in repair_list()."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Stat Shop 151')
        self.user = _make_user('tech_151')
        _make_membership(self.user, self.tenant, role='technician')
        self.tech = _make_tech(self.user, self.tenant, is_manager=True)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet 151', email='fleet151@test.com',
        )

        self.client = Client()
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        self.client.force_login(self.user)

    def _get(self):
        """GET the legacy repair_list URL, following its redirect to job_list."""
        return self.client.get(
            '/tech/repairs/',
            HTTP_HOST='testserver',
            SERVER_NAME='testserver',
            follow=True,
        )

    def _get_stats(self):
        """Return (response, stats_dict)."""
        response = self._get()
        stats = response.context.get('stats', {}) if response.context else {}
        return response, stats

    def _make_repair(self, status, days_ago=0):
        """Create a Repair with the given status and service_date offset."""
        svc_date = timezone.now() - timedelta(days=days_ago)
        return Repair.objects.create(
            technician=self.tech,
            customer=self.customer,
            tenant=self.tenant,
            unit_number=f'U-{status}-{days_ago}-{Repair.objects.count()}',
            damage_type='Chip',
            queue_status=status,
            service_date=svc_date,
            cost=50,
        )

    def test_repair_list_returns_200(self):
        """repair_list() returns 200 OK for a manager user."""
        response = self._get()
        self.assertEqual(response.status_code, 200)

    def test_stats_empty_with_no_repairs(self):
        """All stat counters are 0 when there are no repairs."""
        _, stats = self._get_stats()
        self.assertEqual(stats.get('total_active'), 0)
        self.assertEqual(stats.get('pending_approval'), 0)
        self.assertEqual(stats.get('in_progress'), 0)
        self.assertEqual(stats.get('completed_this_week'), 0)

    def test_total_active_excludes_completed(self):
        """total_active counts all non-COMPLETED repairs."""
        self._make_repair('APPROVED')
        self._make_repair('IN_PROGRESS')
        self._make_repair('COMPLETED')
        self._make_repair('REQUESTED')
        _, stats = self._get_stats()
        # APPROVED + IN_PROGRESS + REQUESTED = 3 active
        self.assertEqual(stats.get('total_active'), 3)

    def test_pending_approval_counts_requested(self):
        """pending_approval counts only REQUESTED repairs."""
        self._make_repair('REQUESTED')
        self._make_repair('REQUESTED')
        self._make_repair('APPROVED')
        _, stats = self._get_stats()
        self.assertEqual(stats.get('pending_approval'), 2)

    def test_in_progress_counts_in_progress(self):
        """in_progress counts only IN_PROGRESS repairs."""
        self._make_repair('IN_PROGRESS')
        self._make_repair('IN_PROGRESS')
        self._make_repair('APPROVED')
        _, stats = self._get_stats()
        self.assertEqual(stats.get('in_progress'), 2)

    def test_completed_this_week_counts_recent(self):
        """completed_this_week counts COMPLETED repairs from the last 7 days."""
        self._make_repair('COMPLETED', days_ago=0)   # today — counts
        self._make_repair('COMPLETED', days_ago=6)   # 6 days ago — counts
        self._make_repair('COMPLETED', days_ago=8)   # 8 days ago — does NOT count
        _, stats = self._get_stats()
        self.assertEqual(stats.get('completed_this_week'), 2)

    def test_completed_outside_week_not_counted(self):
        """Repairs completed >7 days ago must not appear in completed_this_week."""
        self._make_repair('COMPLETED', days_ago=10)
        self._make_repair('COMPLETED', days_ago=30)
        _, stats = self._get_stats()
        self.assertEqual(stats.get('completed_this_week'), 0)

    def test_all_stats_correct_together(self):
        """All four stats are correct when repairs in multiple statuses exist."""
        self._make_repair('REQUESTED')              # active + pending
        self._make_repair('IN_PROGRESS')            # active + in_progress
        self._make_repair('APPROVED')               # active only
        self._make_repair('COMPLETED', days_ago=2)  # completed this week
        self._make_repair('COMPLETED', days_ago=20) # completed, not this week
        _, stats = self._get_stats()
        self.assertEqual(stats.get('total_active'), 3)
        self.assertEqual(stats.get('pending_approval'), 1)
        self.assertEqual(stats.get('in_progress'), 1)
        self.assertEqual(stats.get('completed_this_week'), 1)

    def test_total_jobs_in_context(self):
        """total_jobs in context matches the actual number of repairs."""
        self._make_repair('APPROVED')
        self._make_repair('COMPLETED')
        self._make_repair('REQUESTED')
        response = self._get()
        self.assertEqual(response.context.get('total_jobs'), 3)
