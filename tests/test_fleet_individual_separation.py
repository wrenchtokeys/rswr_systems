"""
Fleet vs Individual separation tests.

Covers: the customer search API (tenant-scoped, history summaries), the
duplicate-suggest flow on the quick job form, the FLEET-only name constraint,
individual job history on the customer detail page, and the customer list
type filter/badges.
"""

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


def make_shop(name, email):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name=name, email=email,
        password='testpass123!', first_name=name.split()[0], last_name='Owner',
    )
    return result['user'], result['tenant']


class CustomerSearchApiTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_shop('Search Shop', 'owner@search.test')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        self.fleet = Customer.objects.create(
            tenant=self.tenant, name='Acme Trucking', customer_type='FLEET')
        self.jane = Customer.objects.create(
            tenant=self.tenant, name='Jane Doe', customer_type='RETAIL',
            phone='(555) 123-4567')
        self.walkin = Customer.objects.create(
            tenant=self.tenant, name='Walk-in Willy', customer_type='WALK_IN')

    def _get(self, **params):
        return self.client.get(reverse('customer_search_api'), params)

    def test_individual_search_excludes_fleet(self):
        data = self._get(type='individual', q='').json()
        names = [r['name'] for r in data['results']]
        self.assertIn('Jane Doe', names)
        self.assertIn('Walk-in Willy', names)  # WALK_IN collapses into Individual
        self.assertNotIn('Acme Trucking', names)

    def test_fleet_search_excludes_individuals(self):
        data = self._get(type='fleet', q='').json()
        names = [r['name'] for r in data['results']]
        self.assertEqual(names, ['Acme Trucking'])

    def test_search_by_phone_digits(self):
        data = self._get(type='individual', q='5551234').json()
        names = [r['name'] for r in data['results']]
        self.assertEqual(names, ['Jane Doe'])

    def test_history_summary_included(self):
        tech = Technician.objects.filter(tenant=self.tenant).first()
        Repair.objects.create(
            tenant=self.tenant, customer=self.jane, technician=tech,
            queue_status='COMPLETED', cost_override=Decimal('50.00'),
            vehicle_make='Honda', vehicle_model='Civic',
        )
        data = self._get(type='individual', q='Jane').json()
        self.assertIn('1 previous job', data['results'][0]['summary'])

    def test_tenant_isolation(self):
        """Shop B's individuals never appear in Shop A's search."""
        _user_b, tenant_b = make_shop('Other Shop', 'owner@other.test')
        Customer.objects.create(
            tenant=tenant_b, name='Jane Doe', customer_type='RETAIL')

        data = self._get(type='individual', q='Jane').json()
        ids = [r['id'] for r in data['results']]
        self.assertEqual(ids, [self.jane.id])


class QuickJobDuplicateSuggestTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_shop('Dup Shop', 'owner@dup.test')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post(self, **overrides):
        data = {
            'service_type': 'repair',
            'new_customer_name': 'John Smith',
            'new_customer_phone': '555-999-8888',
            'unit_number': '2020 Toyota Camry',
            'work_done': 'Chip repair',
            'price': '50.00',
            'already_completed': 'on',
        }
        data.update(overrides)
        return self.client.post(reverse('job_create'), data)

    def test_first_individual_creates_directly(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        cust = Customer.objects.get(tenant=self.tenant, name='John Smith')
        self.assertEqual(cust.customer_type, 'RETAIL')

    def test_email_captured_on_inline_create(self):
        self._post(new_customer_email='john@smith.test')
        cust = Customer.objects.get(tenant=self.tenant, name='John Smith')
        self.assertEqual(cust.email, 'john@smith.test')

    def test_duplicate_shows_suggestion_not_error(self):
        self._post()
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already a customer')
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant, name='John Smith').count(), 1)
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 1)

    def test_suggestion_includes_history(self):
        self._post()
        resp = self._post()
        self.assertContains(resp, 'previous job')

    def test_confirmed_creates_second_person(self):
        self._post()
        resp = self._post(confirmed_new_customer='1')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant, name='John Smith').count(), 2)
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 2)

    def test_phone_match_with_different_name_suggests(self):
        self._post()
        resp = self._post(new_customer_name='Jonathan Smith')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already a customer')


class IndividualHistoryPageTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_shop('History Shop', 'owner@history.test')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        self.tech = Technician.objects.filter(tenant=self.tenant).first()

    def test_individual_detail_shows_job_history(self):
        jane = Customer.objects.create(
            tenant=self.tenant, name='Jane Doe', customer_type='RETAIL')
        Repair.objects.create(
            tenant=self.tenant, customer=jane, technician=self.tech,
            queue_status='COMPLETED', cost_override=Decimal('50.00'),
            vehicle_make='Honda', vehicle_model='Civic',
        )
        resp = self.client.get(reverse('customer_detail', args=[jane.id]))
        self.assertContains(resp, 'Job History')
        self.assertContains(resp, 'Honda')
        self.assertNotContains(resp, 'No repairs recorded')

    def test_fleet_detail_still_shows_units(self):
        fleet = Customer.objects.create(
            tenant=self.tenant, name='Acme Trucking', customer_type='FLEET')
        Repair.objects.create(
            tenant=self.tenant, customer=fleet, technician=self.tech,
            queue_status='COMPLETED', cost_override=Decimal('50.00'),
            unit_number='T-1045',
        )
        resp = self.client.get(reverse('customer_detail', args=[fleet.id]))
        self.assertContains(resp, 'Units')
        self.assertContains(resp, 'T-1045')


class CustomerListFilterTests(TestCase):
    def setUp(self):
        self.user, self.tenant = make_shop('List Shop', 'owner@list.test')
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        Customer.objects.create(
            tenant=self.tenant, name='Acme Trucking', customer_type='FLEET')
        Customer.objects.create(
            tenant=self.tenant, name='Jane Doe', customer_type='RETAIL')

    def test_type_filter_fleet(self):
        resp = self.client.get(reverse('technician_customers'), {'type': 'fleet'})
        self.assertContains(resp, 'Acme Trucking')
        self.assertNotContains(resp, 'Jane Doe')

    def test_type_filter_individual(self):
        resp = self.client.get(reverse('technician_customers'), {'type': 'individual'})
        self.assertContains(resp, 'Jane Doe')
        self.assertNotContains(resp, 'Acme Trucking')

    def test_no_filter_shows_both_with_badges(self):
        resp = self.client.get(reverse('technician_customers'))
        self.assertContains(resp, 'Acme Trucking')
        self.assertContains(resp, 'Jane Doe')
        self.assertContains(resp, 'Individual')
