"""
Unified technician dashboard (PR2 of the Jobs overhaul).

Covers: Today's Queue merging repairs + replacements with priority ordering,
the single customer-requests card spanning both types, legacy context keys
staying populated, and summary/admin stats counting replacements.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings

from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Repair, Replacement
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_shop(business_name, email, services='both'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'),
            'trial_days': 30, 'display_order': 0, 'is_active': True,
        },
    )
    result = create_tenant_with_owner(
        business_name=business_name,
        email=email,
        password='testpass123!',
        first_name='Test',
        last_name='Owner',
        services_offered=services,
    )
    return result['user'], result['tenant']


def login(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


@override_settings(**TEST_SETTINGS)
class UnifiedDashboardTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Dash Shop', 'dash@test.com', 'both')
        self.customer = Customer.objects.create(name='Dash Fleet', tenant=self.tenant)
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        login(self.client, self.user, self.tenant)

    def test_todays_queue_merges_and_orders_by_priority(self):
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='R-1', queue_status='APPROVED',
        )
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-1', glass_position='WINDSHIELD',
            queue_status='IN_PROGRESS',
        )
        resp = self.client.get('/tech/')
        self.assertEqual(resp.status_code, 200)
        queue = resp.context['todays_queue']
        self.assertEqual(len(queue), 2)
        # IN_PROGRESS (priority 0) outranks APPROVED (priority 1)
        self.assertEqual(queue[0].service_type, 'replacement')
        self.assertEqual(queue[1].service_type, 'repair')

    def test_customer_requests_card_spans_both_types(self):
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='R-2', queue_status='REQUESTED',
        )
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-2', glass_position='WINDSHIELD',
            queue_status='REQUESTED',
        )
        resp = self.client.get('/tech/')
        requests = resp.context['customer_requests']
        self.assertEqual({r.service_type for r in requests}, {'repair', 'replacement'})
        # Legacy per-type keys stay populated
        self.assertEqual(len(resp.context['customer_requested_repairs']), 1)
        self.assertEqual(len(resp.context['customer_requested_replacements']), 1)
        self.assertContains(resp, 'Customer Requests - Attention Required')

    def test_summary_stats_include_replacements(self):
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-3', glass_position='WINDSHIELD',
            queue_status='IN_PROGRESS',
        )
        resp = self.client.get('/tech/')
        stats = resp.context['summary_stats']
        self.assertEqual(stats['individual_in_progress'], 1)
        self.assertEqual(stats['total_active_work'], 1)

    def test_admin_data_counts_both_types(self):
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='R-4', queue_status='APPROVED',
        )
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-4', glass_position='WINDSHIELD',
            queue_status='APPROVED',
        )
        resp = self.client.get('/tech/')
        admin_data = resp.context['admin_data']
        self.assertEqual(admin_data['total_jobs'], 2)
        self.assertEqual(admin_data['total_repairs'], 1)  # legacy key intact

    def test_replacement_only_shop_queue_has_no_repair_wording(self):
        user, tenant = make_shop('Repl Dash', 'repldash@test.com', 'replacement')
        customer = Customer.objects.create(name='Fleet RD', tenant=tenant)
        tech = Technician.objects.get(user=user, tenant=tenant)
        Replacement.objects.create(
            tenant=tenant, customer=customer, technician=tech,
            unit_number='Z-5', glass_position='WINDSHIELD',
            queue_status='APPROVED',
        )
        client = Client()
        login(client, user, tenant)
        resp = client.get('/tech/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Fleet RD')
        self.assertNotContains(resp, 'New Repair')
        self.assertNotContains(resp, 'Multi-Break Entry')
        self.assertContains(resp, 'New Replacement')
