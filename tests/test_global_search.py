"""
Global search: /tech/search/

Search is a new way to reach records, so the thing worth testing hardest is
that it is not a new way to reach records you shouldn't see. It reuses
_visible_jobs() and can_access() rather than writing fresh rules, and these
tests pin that: a plain tech searching a unit number must not surface another
tech's job, and no query may cross a tenant boundary.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from apps.billing.models import Invoice
from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class GlobalSearchTests(TestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user('owner_gs', password='pw', email='owner@gs.test')
        self.shop = Tenant.objects.create(
            name='Search Shop', slug='search-shop', plan='trial',
            is_active=True, owner=self.owner_user,
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')
        self.owner_tech = Technician.objects.create(
            tenant=self.shop, user=self.owner_user,
            is_active=True, is_manager=True, can_repair=True,
        )

        self.tech_user = User.objects.create_user('tech_gs', password='pw', email='tech@gs.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.tech_user, role='technician')
        self.tech = Technician.objects.create(
            tenant=self.shop, user=self.tech_user,
            is_active=True, is_manager=False, can_repair=True,
        )

        self.other_user = User.objects.create_user('other_gs', password='pw', email='other@gs.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.other_user, role='technician')
        self.other_tech = Technician.objects.create(
            tenant=self.shop, user=self.other_user,
            is_active=True, is_manager=False, can_repair=True,
        )

        self.customer = Customer.objects.create(
            tenant=self.shop, name='Bluebird Haulage', phone='5015550123',
        )

        self.my_repair = Repair.objects.create(
            tenant=self.shop, customer=self.customer, technician=self.tech,
            unit_number='TRUCK-42', queue_status='APPROVED', cost=Decimal('50'),
        )
        self.other_repair = Repair.objects.create(
            tenant=self.shop, customer=self.customer, technician=self.other_tech,
            unit_number='TRUCK-99', queue_status='APPROVED', cost=Decimal('50'),
        )

        # A second shop that must never appear in the first shop's results.
        self.rival_owner = User.objects.create_user('rival_gs', password='pw', email='rival@gs.test')
        self.rival = Tenant.objects.create(
            name='Rival Shop', slug='rival-shop', plan='trial',
            is_active=True, owner=self.rival_owner,
        )
        TenantMembership.objects.create(tenant=self.rival, user=self.rival_owner, role='owner')
        self.rival_customer = Customer.objects.create(
            tenant=self.rival, name='Bluebird Rival Fleet', phone='5015559999',
        )
        rival_tech = Technician.objects.create(
            tenant=self.rival, user=self.rival_owner,
            is_active=True, is_manager=True, can_repair=True,
        )
        Repair.objects.create(
            tenant=self.rival, customer=self.rival_customer, technician=rival_tech,
            unit_number='TRUCK-42', queue_status='APPROVED', cost=Decimal('50'),
        )

        self.client = Client()

    def _login(self, user):
        self.client.logout()
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def _search(self, q, follow=False):
        return self.client.get(reverse('global_search'), {'q': q}, follow=follow)

    # Assertions go through the context, not the rendered HTML: the navbar
    # search box echoes the query back on every results page, so a plain
    # assertContains/assertNotContains on the search term is meaningless.
    def _job_ids(self, response):
        return {job.id for job, _kind in response.context['jobs']}

    def _customer_names(self, response):
        return {c.name for c in response.context['customers']}

    def _invoice_numbers(self, response):
        return {i.invoice_number for i in response.context['invoices']}

    # --- scoping -----------------------------------------------------------

    def test_plain_tech_does_not_see_another_techs_job(self):
        # Two of their own, so the result set is a page rather than a
        # single-hit redirect straight to the record.
        mine_too = Repair.objects.create(
            tenant=self.shop, customer=self.customer, technician=self.tech,
            unit_number='TRUCK-43', queue_status='APPROVED', cost=Decimal('50'),
        )
        self._login(self.tech_user)
        response = self._search('TRUCK')
        self.assertEqual(
            {self.my_repair.id, mine_too.id}, self._job_ids(response),
            "Search must not surface a job the tech cannot open from the job list",
        )

    def test_owner_sees_all_jobs_in_their_shop(self):
        self._login(self.owner_user)
        response = self._search('TRUCK')
        self.assertEqual(
            {self.my_repair.id, self.other_repair.id},
            self._job_ids(response),
        )

    def test_search_never_crosses_tenants(self):
        """Both shops have a TRUCK-42 and a customer matching 'Bluebird'."""
        self._login(self.owner_user)
        response = self._search('Bluebird')
        self.assertEqual({'Bluebird Haulage'}, self._customer_names(response))
        for job, _kind in response.context['jobs']:
            self.assertEqual(job.tenant_id, self.shop.id)

    # --- behaviour ---------------------------------------------------------

    def test_matches_customer_by_name(self):
        self._login(self.owner_user)
        response = self._search('Bluebird')
        self.assertIn('Bluebird Haulage', self._customer_names(response))

    def test_matches_customer_by_phone(self):
        self._login(self.owner_user)
        response = self._search('5550123', follow=True)
        # Only the customer matches, so this jumps straight to their page.
        self.assertRedirects(
            response,
            reverse('customer_detail', kwargs={'customer_id': self.customer.id}),
        )

    def test_matches_invoice_by_number(self):
        for suffix in ('0042', '0043'):
            Invoice.objects.create(
                tenant=self.shop, customer=self.customer,
                invoice_number=f'INV-2026-{suffix}', subtotal=Decimal('50'),
                total=Decimal('50'), status='SENT',
            )
        self._login(self.owner_user)
        response = self._search('INV-2026')
        self.assertEqual(
            {'INV-2026-0042', 'INV-2026-0043'}, self._invoice_numbers(response)
        )

    def test_single_hit_jumps_straight_to_the_record(self):
        """One obvious destination shouldn't cost an extra tap."""
        self._login(self.tech_user)
        response = self._search('TRUCK-42')
        self.assertRedirects(
            response,
            reverse('repair_detail', kwargs={'repair_id': self.my_repair.id}),
        )

    def test_no_matches_renders_an_empty_state(self):
        self._login(self.owner_user)
        response = self._search('zzz-nothing-matches-zzz')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No jobs, customers or invoices matched')

    def test_blank_query_falls_back_to_the_job_list(self):
        self._login(self.owner_user)
        response = self.client.get(reverse('global_search'), {'q': '   '})
        self.assertRedirects(response, reverse('job_list'))

    def test_plain_tech_gets_no_invoice_section(self):
        Invoice.objects.create(
            tenant=self.shop, customer=self.customer,
            invoice_number='INV-HIDDEN-1', subtotal=Decimal('50'),
            total=Decimal('50'), status='SENT',
        )
        self._login(self.tech_user)
        response = self._search('INV-HIDDEN-1')
        self.assertEqual(
            [], response.context['invoices'],
            "A technician has no invoices access, so search must not expose them",
        )
