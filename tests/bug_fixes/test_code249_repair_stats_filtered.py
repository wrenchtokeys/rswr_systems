"""
Regression tests for CODE-249: customer_repairs stats computed on filtered queryset.

Before this fix, the summary statistics (total_repairs, pending_approval, etc.)
on the customer repairs list page were computed AFTER applying the user's
status/unit/date filters.  This meant filtering to e.g. "COMPLETED" would show
pending_approval=0, misleading the customer about how many repairs actually
await their approval.

The fix mirrors the pattern already used in customer_replacements():
stats are computed from the unfiltered base queryset, and filters only apply
to the display list.

Author: Amelia (Bug Hunter)
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser
from core.models import Customer


def _add_middleware(request):
    """Attach session + messages storage to a RequestFactory request."""
    setattr(request, 'session', SessionStore())
    setattr(request, '_messages', FallbackStorage(request))
    return request


class TestRepairStatsUnfilteredAfterFix(TestCase):
    """Stats on the customer repairs page should always reflect global totals."""

    @classmethod
    def setUpTestData(cls):
        owner = User.objects.create_user(
            username='statsowner', password='test1234', email='owner@example.com',
        )
        cls.tenant = Tenant.objects.create(
            name='Stats Test Shop',
            slug='stats-test-shop',
            subdomain='stats-test-shop',
            owner=owner,
            subscription_status='active',
        )
        TenantMembership.objects.create(user=owner, tenant=cls.tenant, role='owner')
        cls.user = User.objects.create_user(
            username='statsuser', password='test1234', email='stats@example.com',
        )
        cls.customer = Customer.objects.create(
            name='Stats Customer', tenant=cls.tenant,
        )
        cls.customer_user = CustomerUser.objects.create(
            user=cls.user, customer=cls.customer,
        )
        TenantMembership.objects.create(
            user=cls.user, tenant=cls.tenant, role='customer',
        )
        cls.tech_user = User.objects.create_user(
            username='statstech', password='test1234',
        )
        cls.technician = Technician.objects.create(
            user=cls.tech_user, tenant=cls.tenant,
        )

        # Create repairs in various statuses:
        # 2 PENDING, 1 APPROVED, 1 IN_PROGRESS, 3 COMPLETED = 7 total
        for status in ('PENDING', 'PENDING', 'APPROVED', 'IN_PROGRESS',
                       'COMPLETED', 'COMPLETED', 'COMPLETED'):
            Repair.objects.create(
                tenant=cls.tenant,
                customer=cls.customer,
                technician=cls.technician,
                unit_number=f'UNIT-{status[:3]}',
                damage_type='Star Break',
                queue_status=status,
                cost=Decimal('50.00') if status == 'COMPLETED' else None,
            )

    def _get_stats(self, **query_params):
        """
        Call customer_repairs view directly and capture context via render patch.
        
        We patch django.shortcuts.render to intercept the context dict before
        it's flattened into an HttpResponse.
        """
        from apps.customer_portal import views as cp_views
        factory = RequestFactory()
        request = factory.get('/app/repairs/', query_params)
        request.user = self.user
        request.tenant = self.tenant
        _add_middleware(request)

        captured = {}
        _original_render = cp_views.render

        def _capture_render(request, template, context=None, **kwargs):
            captured.update(context or {})
            return _original_render(request, template, context, **kwargs)

        with patch.object(cp_views, 'render', side_effect=_capture_render):
            response = cp_views.customer_repairs(request)

        self.assertEqual(response.status_code, 200)
        return captured

    def test_stats_show_global_totals_when_filtered_by_status(self):
        """Filtering by COMPLETED should not zero out pending/in-progress stats."""
        ctx = self._get_stats(status='COMPLETED')
        stats = ctx['stats']

        self.assertEqual(stats['total_repairs'], 7,
                         "total_repairs should count ALL repairs, not just filtered")
        self.assertEqual(stats['pending_approval'], 2,
                         "pending_approval should count ALL pending, not just filtered")
        # in_progress = APPROVED + IN_PROGRESS = 1 + 1 = 2
        self.assertEqual(stats['in_progress'], 2,
                         "in_progress should count ALL APPROVED+IN_PROGRESS, not just filtered")

    def test_stats_show_global_totals_when_searched_by_unit(self):
        """Searching by unit number should not alter stat counts."""
        ctx = self._get_stats(unit_search='UNIT-COM')
        stats = ctx['stats']

        self.assertEqual(stats['total_repairs'], 7)
        self.assertEqual(stats['pending_approval'], 2)

    def test_stats_show_global_totals_when_filtered_by_damage_type(self):
        """Filtering by nonexistent damage type should not alter stat counts."""
        ctx = self._get_stats(damage_type='Bullseye')
        stats = ctx['stats']

        self.assertEqual(stats['total_repairs'], 7)
        self.assertEqual(stats['pending_approval'], 2)

    def test_display_list_still_filtered(self):
        """The actual displayed items should still be filtered by status."""
        ctx = self._get_stats(status='COMPLETED')

        # page_obj items should only contain COMPLETED repairs
        page_obj = ctx['page_obj']
        for item in page_obj:
            if isinstance(item, dict) and item.get('type') == 'individual':
                self.assertEqual(item['repair'].queue_status, 'COMPLETED')
