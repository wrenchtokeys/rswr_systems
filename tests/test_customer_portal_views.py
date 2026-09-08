"""
Customer-portal view coverage (the June plan's standing item: ~16 tests for
30+ views, "add coverage before B3 builds on those views").

Integration tests through the real URL conf: the logged-in customer sees
their own shop's data, the right status guards hold, and another customer's
records are a 404 — the contract the quote pages (B3) inherit.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from apps.billing.models import Invoice
from apps.customer_portal.models import CustomerRepairPreference, CustomerUser
from apps.technician_portal.models import Repair, Replacement, Technician
from core.models import Customer
from tests.test_e2e_today import make_tenant

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


@override_settings(**TEST_SETTINGS)
class CustomerPortalViewTests(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant('Portal Shop', 'portal_owner')
        self.tech = Technician.objects.create(user=self.owner, tenant=self.tenant, is_active=True, is_manager=True)
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant, customer_type='FLEET')
        CustomerRepairPreference.objects.get_or_create(
            customer=self.customer, defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cust_user = User.objects.create_user('portal_contact', 'c@fleetco.com', 'pw',
                                                  first_name='Pat', last_name='Contact')
        CustomerUser.objects.create(user=self.cust_user, customer=self.customer, is_primary_contact=True)
        self.other = Customer.objects.create(name='Other Fleet', tenant=self.tenant, customer_type='FLEET')
        CustomerRepairPreference.objects.get_or_create(
            customer=self.other, defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.client = Client()
        self.client.force_login(self.cust_user)

    def make_repair(self, customer=None, status='PENDING', **kw):
        return Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=customer or self.customer,
            unit_number='12', queue_status=status, damage_type='Chip', **kw,
        )

    def test_dashboard_services_and_invoices_render(self):
        self.make_repair()
        Invoice.objects.create(tenant=self.tenant, customer=self.customer, invoice_number='INV-1',
                               status='SENT', subtotal=Decimal('50'), total=Decimal('50'))
        for url in ('/app/', '/app/services/', '/app/invoices/', '/app/rewards/', '/app/account/settings/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)

    def test_anonymous_is_sent_to_login(self):
        resp = Client().get('/app/services/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'])

    def test_repair_detail_is_scoped_to_the_customer(self):
        mine = self.make_repair()
        theirs = self.make_repair(customer=self.other)
        self.assertEqual(self.client.get(f'/app/repairs/{mine.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/app/repairs/{theirs.id}/').status_code, 404)

    def test_pending_repair_can_be_approved_and_denied_once(self):
        repair = self.make_repair()
        resp = self.client.get(f'/app/repairs/{repair.id}/approve/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(f'/app/repairs/{repair.id}/approve/', {'notes': 'go'})
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')
        # A second answer on a job that is no longer PENDING is refused (CODE-061)
        resp = self.client.post(f'/app/repairs/{repair.id}/deny/', {'reason': 'no'})
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')

    def test_denying_a_pending_repair(self):
        repair = self.make_repair()
        resp = self.client.post(f'/app/repairs/{repair.id}/deny/', {'reason': 'Not now'})
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'DENIED')

    def test_cannot_approve_another_customers_repair(self):
        theirs = self.make_repair(customer=self.other)
        resp = self.client.post(f'/app/repairs/{theirs.id}/approve/', {'notes': ''})
        self.assertEqual(resp.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.queue_status, 'PENDING')

    def test_replacement_detail_and_approval(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='12', queue_status='PENDING', glass_position='WINDSHIELD',
            parts_cost=Decimal('200'), labor_cost=Decimal('100'),
        )
        self.assertEqual(self.client.get(f'/app/replacements/{repl.id}/').status_code, 200)
        resp = self.client.post(f'/app/replacements/{repl.id}/approve/', {'notes': ''})
        self.assertEqual(resp.status_code, 302)
        repl.refresh_from_db()
        self.assertEqual(repl.queue_status, 'APPROVED')

    def test_invoice_detail_is_scoped_and_drafts_are_hidden(self):
        mine = Invoice.objects.create(tenant=self.tenant, customer=self.customer, invoice_number='INV-2',
                                      status='SENT', subtotal=Decimal('50'), total=Decimal('50'))
        draft = Invoice.objects.create(tenant=self.tenant, customer=self.customer, invoice_number='INV-3',
                                       status='DRAFT', subtotal=Decimal('50'), total=Decimal('50'))
        theirs = Invoice.objects.create(tenant=self.tenant, customer=self.other, invoice_number='INV-4',
                                        status='SENT', subtotal=Decimal('50'), total=Decimal('50'))
        self.assertEqual(self.client.get(f'/app/invoices/{mine.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/app/invoices/{theirs.id}/').status_code, 404)
        resp = self.client.get('/app/invoices/')
        self.assertContains(resp, 'INV-2')
        self.assertNotContains(resp, 'INV-3')
        self.assertNotContains(resp, 'INV-4')

    def test_user_with_no_customer_profile_gets_no_data(self):
        # No CustomerUser and no membership: the tenant middleware finds no
        # tenant and the subscription middleware sends them to login
        # (CLAUDE.md, Tenant Isolation). Either way, no portal page renders.
        stranger = User.objects.create_user('stranger', 's@x.com', 'pw')
        client = Client()
        client.force_login(stranger)
        resp = client.get('/app/services/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue('login' in resp['Location'] or 'profile' in resp['Location'])
