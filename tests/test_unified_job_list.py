"""
Unified /tech/jobs/ list (repairs + replacements as one surface).

Covers: visibility matrix across the three service mixes, cross-type
search and type filtering, legacy repair_list/replacement_list redirects,
type-badge gating, and the new technician-level replacement access rules.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse

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


def make_plain_tech(tenant, username, can_replace=False):
    user = User.objects.create_user(username=username, password='pass123!')
    TenantMembership.objects.create(
        user=user, tenant=tenant, role='technician', is_active=True,
    )
    tech = Technician.objects.create(
        user=user, tenant=tenant, phone_number='555-0100',
        expertise='Glass', is_active=True,
        can_repair=True, can_replace=can_replace,
    )
    return user, tech


@override_settings(**TEST_SETTINGS)
class UnifiedJobListTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Both Shop', 'both-owner@test.com', 'both')
        self.customer = Customer.objects.create(name='Acme Fleet', tenant=self.tenant)
        self.other_customer = Customer.objects.create(name='Zebra Trucking', tenant=self.tenant)
        self.owner_tech = Technician.objects.get(user=self.user, tenant=self.tenant)

        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.owner_tech, unit_number='R-1',
            damage_type='Chip', queue_status='APPROVED',
        )
        self.replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.other_customer,
            technician=self.owner_tech, unit_number='Z-9',
            glass_position='WINDSHIELD', queue_status='APPROVED',
        )
        login(self.client, self.user, self.tenant)

    def test_owner_sees_both_types(self):
        resp = self.client.get(reverse('job_list'))
        self.assertEqual(resp.status_code, 200)
        jobs = list(resp.context['page_obj'])
        self.assertEqual({j.service_type for j in jobs}, {'repair', 'replacement'})
        self.assertEqual(resp.context['total_jobs'], 2)

    def test_type_filter_repair(self):
        resp = self.client.get(reverse('job_list'), {'type': 'repair'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual([j.service_type for j in jobs], ['repair'])

    def test_type_filter_replacement(self):
        resp = self.client.get(reverse('job_list'), {'type': 'replacement'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual([j.service_type for j in jobs], ['replacement'])

    def test_customer_search_spans_both_types(self):
        resp = self.client.get(reverse('job_list'), {'customer_search': 'Zebra'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].service_type, 'replacement')

        resp = self.client.get(reverse('job_list'), {'customer_search': 'Acme'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].service_type, 'repair')

    def test_unit_search_spans_both_types(self):
        resp = self.client.get(reverse('job_list'), {'unit_search': 'Z-9'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].service_type, 'replacement')

    def test_status_filter_spans_both_types(self):
        self.repair.queue_status = 'COMPLETED'
        self.repair.save()
        resp = self.client.get(reverse('job_list'), {'status': 'APPROVED'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual([j.service_type for j in jobs], ['replacement'])

    def test_damage_type_filter_implies_repairs(self):
        resp = self.client.get(reverse('job_list'), {'damage_type': 'Chip'})
        jobs = list(resp.context['page_obj'])
        self.assertEqual([j.service_type for j in jobs], ['repair'])
        self.assertEqual(resp.context['type_filter'], 'repair')

    def test_both_shop_shows_type_badges(self):
        resp = self.client.get(reverse('job_list'))
        self.assertContains(resp, '>Replacement</span>')

    def test_stats_count_both_types(self):
        resp = self.client.get(reverse('job_list'))
        self.assertEqual(resp.context['stats']['total_active'], 2)

    def test_plain_tech_sees_only_own_jobs(self):
        tech_user, tech = make_plain_tech(self.tenant, 'plaintech', can_replace=True)
        own_repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=tech, unit_number='R-2', queue_status='IN_PROGRESS',
        )
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.owner_tech, unit_number='R-3', queue_status='REQUESTED',
        )
        client = Client()
        login(client, tech_user, self.tenant)
        resp = client.get(reverse('job_list'))
        self.assertEqual(resp.status_code, 200)
        jobs = list(resp.context['page_obj'])
        self.assertEqual([j.id for j in jobs], [own_repair.id])

    def test_plain_tech_sees_own_replacement(self):
        tech_user, tech = make_plain_tech(self.tenant, 'repltech', can_replace=True)
        own_repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=tech, unit_number='Z-2',
            glass_position='WINDSHIELD', queue_status='IN_PROGRESS',
        )
        client = Client()
        login(client, tech_user, self.tenant)
        resp = client.get(reverse('job_list'))
        jobs = list(resp.context['page_obj'])
        self.assertEqual([j.id for j in jobs], [own_repl.id])
        self.assertEqual(jobs[0].service_type, 'replacement')


@override_settings(**TEST_SETTINGS)
class SingleServiceShopTests(TestCase):

    def test_replacement_only_shop_list_and_no_repair_wording(self):
        user, tenant = make_shop('Repl Shop', 'repl-owner@test.com', 'replacement')
        customer = Customer.objects.create(name='Fleet R', tenant=tenant)
        tech = Technician.objects.get(user=user, tenant=tenant)
        Replacement.objects.create(
            tenant=tenant, customer=customer, technician=tech,
            unit_number='U-1', glass_position='WINDSHIELD', queue_status='APPROVED',
        )
        client = Client()
        login(client, user, tenant)
        resp = client.get(reverse('job_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_jobs'], 1)
        self.assertNotContains(resp, 'New Repair')
        self.assertContains(resp, 'New Replacement')
        # Type column/badges hidden for single-service shops
        self.assertNotContains(resp, '>Type</th>')

    def test_repair_only_shop_hides_replacement_button(self):
        user, tenant = make_shop('Rep Shop', 'rep-owner@test.com', 'repair')
        client = Client()
        login(client, user, tenant)
        resp = client.get(reverse('job_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'New Repair')
        self.assertNotContains(resp, 'New Replacement')


@override_settings(**TEST_SETTINGS)
class LegacyRedirectTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Redirect Shop', 'redir@test.com', 'both')
        login(self.client, self.user, self.tenant)

    def test_repair_list_redirects_to_job_list(self):
        resp = self.client.get(reverse('repair_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('job_list')))

    def test_repair_list_preserves_status_param(self):
        resp = self.client.get(reverse('repair_list'), {'status': 'REQUESTED'})
        self.assertIn('status=REQUESTED', resp.url)

    def test_repair_list_damage_type_forces_repair_type(self):
        resp = self.client.get(reverse('repair_list'), {'damage_type': 'Chip'})
        self.assertIn('type=repair', resp.url)

    def test_replacement_list_redirects_with_type(self):
        resp = self.client.get(reverse('replacement_list'))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith(reverse('job_list')))
        self.assertIn('type=replacement', resp.url)

    def test_replacement_list_drops_empty_status(self):
        resp = self.client.get(reverse('replacement_list'), {'status': ''})
        self.assertNotIn('status=', resp.url)


@override_settings(**TEST_SETTINGS)
class TechnicianReplacementAccessTests(TestCase):
    """Replacements are no longer owner/manager-only."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Access Shop', 'access@test.com', 'replacement')
        self.customer = Customer.objects.create(name='Fleet A', tenant=self.tenant)
        self.tech_user, self.tech = make_plain_tech(
            self.tenant, 'accesstech', can_replace=True
        )
        self.other_user, self.other_tech = make_plain_tech(
            self.tenant, 'othertech', can_replace=True
        )
        self.norepl_user, self.norepl_tech = make_plain_tech(
            self.tenant, 'norepltech', can_replace=False
        )
        self.replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='U-5', glass_position='WINDSHIELD', queue_status='APPROVED',
        )

    def test_assigned_tech_can_view_detail(self):
        login(self.client, self.tech_user, self.tenant)
        resp = self.client.get(reverse('replacement_detail', args=[self.replacement.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_unassigned_tech_cannot_view_detail(self):
        login(self.client, self.other_user, self.tenant)
        resp = self.client.get(reverse('replacement_detail', args=[self.replacement.pk]))
        self.assertEqual(resp.status_code, 302)

    def test_tech_with_can_replace_can_open_create(self):
        login(self.client, self.tech_user, self.tenant)
        resp = self.client.get(reverse('replacement_create'))
        self.assertEqual(resp.status_code, 200)

    def test_tech_without_can_replace_blocked_from_create(self):
        login(self.client, self.norepl_user, self.tenant)
        resp = self.client.get(reverse('replacement_create'))
        self.assertEqual(resp.status_code, 302)

    def test_assigned_tech_can_update_status(self):
        login(self.client, self.tech_user, self.tenant)
        resp = self.client.post(
            reverse('replacement_update_status', args=[self.replacement.pk]),
            {'status': 'IN_PROGRESS'},
        )
        self.assertEqual(resp.status_code, 302)
        self.replacement.refresh_from_db()
        self.assertEqual(self.replacement.queue_status, 'IN_PROGRESS')

    def test_unassigned_tech_cannot_update_status(self):
        login(self.client, self.other_user, self.tenant)
        self.client.post(
            reverse('replacement_update_status', args=[self.replacement.pk]),
            {'status': 'IN_PROGRESS'},
        )
        self.replacement.refresh_from_db()
        self.assertEqual(self.replacement.queue_status, 'APPROVED')

    def test_owner_still_has_full_access(self):
        login(self.client, self.user, self.tenant)
        resp = self.client.get(reverse('replacement_detail', args=[self.replacement.pk]))
        self.assertEqual(resp.status_code, 200)
