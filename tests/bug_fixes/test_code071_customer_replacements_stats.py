"""
Tests for CODE-071: customer_replacements() stats bug.

Bug: stats['total'] used the filtered queryset (after status_filter applied) instead
of the unfiltered base queryset. When filtering by status (e.g., "Completed"), the
"Total" stat card showed the count of filtered replacements, not all replacements.
Also: 4 separate COUNT queries fired instead of 1 aggregated query.

Fix: Compute stats from base_replacements (unfiltered) using a single aggregated
query with conditional COUNT expressions. Apply status_filter to the display
queryset separately, after stats are computed.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Replacement
from core.models import Customer
from apps.customer_portal.models import CustomerUser


class CustomerReplacementsStatsTestCase(TestCase):
    """Tests for the customer_replacements view stats calculation."""

    def setUp(self):
        # Shop owner (must be created before tenant due to owner FK)
        self.owner = User.objects.create_user('stats_owner', 'owner@stats.com', 'pw123456')

        # Tenant
        self.tenant = Tenant.objects.create(name='Stats Shop', slug='stats-shop', is_active=True, owner=self.owner)
        TenantMembership.objects.create(tenant=self.tenant, user=self.owner, role='owner', is_active=True)

        # Technician
        self.tech_user = User.objects.create_user('stats_tech', 'tech@stats.com', 'pw123456')
        TenantMembership.objects.create(tenant=self.tenant, user=self.tech_user, role='technician', is_active=True)
        self.tech = Technician.objects.create(tenant=self.tenant, user=self.tech_user, is_active=True)

        # Customer
        self.customer = Customer.objects.create(tenant=self.tenant, name='Stats Fleet', email='fleet@stats.com')

        # Customer user (portal user)
        self.portal_user = User.objects.create_user('stats_portal', 'portal@stats.com', 'pw123456')
        TenantMembership.objects.create(tenant=self.tenant, user=self.portal_user, role='viewer', is_active=True)
        self.customer_user = CustomerUser.objects.create(
            user=self.portal_user,
            customer=self.customer,
            is_primary_contact=True,
        )

        # Create replacements with various statuses
        # 2 PENDING
        for i in range(2):
            Replacement.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number=f'U{i}', queue_status='PENDING', service_date=timezone.now().date(),
                glass_position="WINDSHIELD",
            )
        # 3 COMPLETED
        for i in range(3):
            Replacement.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number=f'C{i}', queue_status='COMPLETED', service_date=timezone.now().date(),
                glass_position="WINDSHIELD",
            )
        # 1 IN_PROGRESS
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='IP1', queue_status='IN_PROGRESS', service_date=timezone.now().date(),
            glass_position="WINDSHIELD",
        )
        # 1 APPROVED
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='A1', queue_status='APPROVED', service_date=timezone.now().date(),
            glass_position="WINDSHIELD",
        )
        # 1 DENIED
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='D1', queue_status='DENIED', service_date=timezone.now().date(),
            glass_position="WINDSHIELD",
        )

        self.client = Client()
        self.client.force_login(self.portal_user)
        self.client.session['tenant_id'] = self.tenant.id

    def test_stats_without_filter_are_correct(self):
        """Total should be 8 (2+3+1+1+1), pending=2, in_progress=2, completed=3."""
        response = self.client.get('/app/replacements/')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        self.assertEqual(stats['total'], 8, f"Expected total=8, got {stats['total']}")
        self.assertEqual(stats['pending'], 2, f"Expected pending=2, got {stats['pending']}")
        # in_progress = APPROVED + IN_PROGRESS = 1 + 1 = 2
        self.assertEqual(stats['in_progress'], 2, f"Expected in_progress=2, got {stats['in_progress']}")
        self.assertEqual(stats['completed'], 3, f"Expected completed=3, got {stats['completed']}")

    def test_stats_unchanged_when_filter_applied(self):
        """
        BUG: Before the fix, stats['total'] showed the filtered count, not the global total.
        After the fix, stats remain global totals even when a status filter is active.
        """
        # Filter by COMPLETED (3 replacements)
        response = self.client.get('/app/replacements/?status=COMPLETED')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        # Total should still be 8, not 3
        self.assertEqual(stats['total'], 8, f"BUG: total changed to {stats['total']} when filtering by COMPLETED (should be 8)")
        self.assertEqual(stats['pending'], 2)
        self.assertEqual(stats['in_progress'], 2)
        self.assertEqual(stats['completed'], 3)

    def test_filter_only_affects_page_obj(self):
        """The display list (page_obj) is filtered; stats are not."""
        response = self.client.get('/app/replacements/?status=PENDING')
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        # page_obj should only contain PENDING replacements
        for replacement in page_obj:
            self.assertEqual(
                replacement.queue_status, 'PENDING',
                f"page_obj contained non-PENDING replacement: {replacement.queue_status}"
            )
        # Stats should still be global
        stats = response.context['stats']
        self.assertEqual(stats['total'], 8)

    def test_filter_by_in_progress_shows_only_in_progress(self):
        """Filter by IN_PROGRESS shows only IN_PROGRESS replacements in the list."""
        response = self.client.get('/app/replacements/?status=IN_PROGRESS')
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        statuses = [r.queue_status for r in page_obj]
        self.assertIn('IN_PROGRESS', statuses)
        for s in statuses:
            self.assertEqual(s, 'IN_PROGRESS')
        # Stats are global
        stats = response.context['stats']
        self.assertEqual(stats['total'], 8)

    def test_empty_filter_returns_all(self):
        """Empty filter (no ?status) returns all replacements in page_obj."""
        response = self.client.get('/app/replacements/')
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        self.assertEqual(page_obj.paginator.count, 8)

    def test_stats_use_single_db_query(self):
        """Stats should be computed in a single aggregate query, not 4 separate COUNTs."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            self.client.get('/app/replacements/')

        # Find queries that are COUNTs against the replacement table
        count_queries = [
            q['sql'] for q in ctx.captured_queries
            if 'COUNT' in q['sql'].upper() and 'replacement' in q['sql'].lower()
        ]
        # Before the fix: 4 separate COUNTs. After: 1 aggregate query.
        self.assertLessEqual(
            len(count_queries), 2,
            f"Expected ≤2 COUNT queries against replacement table, got {len(count_queries)}:\n"
            + "\n".join(count_queries)
        )

    def test_stats_with_no_replacements(self):
        """All stats should be 0 when no replacements exist for this customer."""
        other_customer = Customer.objects.create(
            tenant=self.tenant, name='Empty Fleet', email='empty@test.com',
        )
        empty_portal_user = User.objects.create_user('empty_portal', 'empty@portal.com', 'pw123456')
        TenantMembership.objects.create(tenant=self.tenant, user=empty_portal_user, role='viewer', is_active=True)
        CustomerUser.objects.create(user=empty_portal_user, customer=other_customer, is_primary_contact=True)

        client = Client()
        client.force_login(empty_portal_user)

        response = client.get('/app/replacements/')
        self.assertEqual(response.status_code, 200)
        stats = response.context['stats']
        self.assertEqual(stats['total'], 0)
        self.assertEqual(stats['pending'], 0)
        self.assertEqual(stats['in_progress'], 0)
        self.assertEqual(stats['completed'], 0)

    def test_cross_tenant_replacements_not_counted(self):
        """Replacements from another tenant's customers are NOT included in stats."""
        other_owner = User.objects.create_user('other_owner2', 'other_owner2@shop.com', 'pw123456')
        other_tenant = Tenant.objects.create(name='Other Shop', slug='other-shop', is_active=True, owner=other_owner)
        other_customer = Customer.objects.create(tenant=other_tenant, name='Other Fleet')
        other_tech_user = User.objects.create_user('other_tech2', 'other_t2@shop.com', 'pw123456')
        other_tech = Technician.objects.create(tenant=other_tenant, user=other_tech_user, is_active=True)

        # Create replacements for a different tenant's customer
        Replacement.objects.create(
            tenant=other_tenant, customer=other_customer, technician=other_tech,
            unit_number='X1', queue_status='COMPLETED', service_date=timezone.now().date(),
            glass_position="WINDSHIELD",
        )

        # Our tenant still has 3 completed, not 4
        response = self.client.get('/app/replacements/')
        stats = response.context['stats']
        self.assertEqual(stats['completed'], 3, "Should not count other tenant's replacements")
        self.assertEqual(stats['total'], 8)
