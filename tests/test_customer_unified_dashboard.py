"""
Unified customer dashboard (repairs + replacements).

The customer dashboard used to query only Repair — a replacement shop's
customers saw an empty dashboard no matter how many replacements they had.
Covers the merged recent-services list, replacement pending-approval alert,
combined counters, preserved legacy context keys, empty state, and the
greeting (no "Welcome back" for first-time users, no blank name).
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair, Replacement
from core.models import Customer
from apps.customer_portal.models import CustomerUser


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        owner_username, f'{owner_username}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_SETTINGS)
class UnifiedDashboardTestCase(TestCase):

    def setUp(self):
        self.owner, self.tenant = make_tenant('Duncan Auto Glass', 'dash_owner')
        self.technician = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True, is_manager=True,
        )
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cust_user = User.objects.create_user(
            'dash_contact', 'dash@fleetco.com', 'testpass123',
            first_name='Pat', last_name='Contact',
        )
        CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer, is_primary_contact=True,
        )
        self.client = Client()
        self.client.force_login(self.cust_user)

    def _make_repair(self, status='COMPLETED', unit='R-1'):
        return Repair.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number=unit,
            description='Chip repair',
            queue_status=status,
        )

    def _make_replacement(self, status='REQUESTED', unit='X-1', **kwargs):
        return Replacement.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number=unit,
            glass_position='WINDSHIELD',
            description='Windshield replacement',
            queue_status=status,
            **kwargs,
        )


class RecentServicesTests(UnifiedDashboardTestCase):

    def test_recent_services_merges_both_types(self):
        self._make_repair()
        self._make_replacement()
        response = self.client.get('/app/')
        self.assertEqual(response.status_code, 200)
        recent = response.context['recent_services']
        self.assertEqual(len(recent), 2)
        types = {item.service_type for item in recent}
        self.assertEqual(types, {'repair', 'replacement'})
        # Newest first
        dates = [item.service_date for item in recent]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_replacement_rendered_with_badge_and_link(self):
        replacement = self._make_replacement()
        response = self.client.get('/app/')
        self.assertContains(response, 'REPLACEMENT')
        self.assertContains(
            response, reverse('customer_replacement_detail', args=[replacement.id])
        )

    def test_empty_state_shows_no_services(self):
        response = self.client.get('/app/')
        self.assertContains(response, 'No services yet')
        self.assertContains(response, reverse('customer_request_replacement'))


class PendingApprovalTests(UnifiedDashboardTestCase):

    def test_pending_replacement_in_approval_alert(self):
        replacement = self._make_replacement(
            status='PENDING', parts_cost=Decimal('250.00'), labor_cost=Decimal('150.00'),
        )
        response = self.client.get('/app/')
        pending = response.context['pending_approval_replacements']
        self.assertEqual([r.id for r in pending], [replacement.id])
        self.assertContains(
            response, reverse('customer_replacement_approve', args=[replacement.id])
        )
        self.assertContains(
            response, reverse('customer_replacement_deny', args=[replacement.id])
        )

    def test_pending_services_count_combines_types(self):
        self._make_repair(status='PENDING', unit='R-2')
        self._make_replacement(status='PENDING', unit='X-2')
        response = self.client.get('/app/')
        self.assertEqual(response.context['pending_services_count'], 2)


class CombinedCountersTests(UnifiedDashboardTestCase):

    def test_combined_counters(self):
        self._make_repair(status='COMPLETED', unit='R-1')
        self._make_repair(status='IN_PROGRESS', unit='R-2')
        self._make_replacement(status='COMPLETED', unit='X-1',
                               parts_cost=Decimal('300.00'), labor_cost=Decimal('100.00'))
        self._make_replacement(status='REQUESTED', unit='X-2')
        response = self.client.get('/app/')
        self.assertEqual(response.context['completed_services_count'], 2)
        self.assertEqual(response.context['active_services_count'], 2)

    def test_legacy_repair_keys_unchanged_by_replacements(self):
        """Existing repair-only context keys must not absorb replacement data."""
        self._make_repair(status='COMPLETED', unit='R-1')
        self._make_replacement(status='COMPLETED', unit='X-1',
                               parts_cost=Decimal('300.00'), labor_cost=Decimal('100.00'))
        response = self.client.get('/app/')
        self.assertEqual(response.context['completed_repairs_count'], 1)
        self.assertEqual(response.context['active_repairs_count'], 0)
        self.assertEqual(response.context['stats']['repairs_completed'], 1)
        self.assertEqual(len(response.context['recent_repairs']), 1)


class GreetingTests(UnifiedDashboardTestCase):

    def test_greeting_uses_first_name(self):
        response = self.client.get('/app/')
        self.assertContains(response, 'Welcome, Pat')
        self.assertNotContains(response, 'Welcome back')

    def test_greeting_falls_back_when_first_name_blank(self):
        self.cust_user.first_name = ''
        self.cust_user.last_name = ''
        self.cust_user.save()
        response = self.client.get('/app/')
        self.assertEqual(response.context['display_name'], 'Fleet Co')
        self.assertContains(response, 'Welcome, Fleet Co')
        self.assertNotContains(response, 'Welcome, </h1>')
