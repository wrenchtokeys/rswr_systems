"""
Quick job + invoice flow (PR3 of the Jobs overhaul).

Covers: /tech/jobs/new/ quick create (completed checkbox, price mapping,
approval-preference refusal), Save & Send Invoice (happy path, no-email path,
send-failure path), the Complete & Send Invoice endpoints (batch handling,
double-invoice guard), and the owner_send_invoice delegation.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.billing.models import Invoice, InvoiceLineItem
from apps.customer_portal.models import CustomerRepairPreference
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Repair, Replacement
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

SEND_EMAIL = 'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email'


def make_shop(business_name, email, services='replacement'):
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
class QuickJobCreateTests(TestCase):
    """Dad scenario: replacement-only shop, one short form."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Dad Glass', 'dad@test.com', 'replacement')
        self.customer = Customer.objects.create(
            name='Smith Trucking', tenant=self.tenant, email='smith@test.com',
        )
        login(self.client, self.user, self.tenant)

    def _post(self, **overrides):
        data = {
            'service_type': 'replacement',
            'customer': self.customer.id,
            'unit_number': 'T-100',
            'work_done': 'Windshield replacement',
            'price': '425.00',
            'already_completed': 'on',
        }
        data.update(overrides)
        return self.client.post(reverse('job_create'), data)

    def test_quick_create_completed_replacement(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.queue_status, 'COMPLETED')
        self.assertEqual(repl.cost, Decimal('425.00'))
        self.assertEqual(repl.customer, self.customer)
        self.assertIsNotNone(repl.technician)

    def test_quick_create_without_completed_stays_approved(self):
        resp = self._post(already_completed='')
        self.assertEqual(resp.status_code, 302)
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.queue_status, 'APPROVED')

    def test_replacement_requires_price(self):
        resp = self._post(price='')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enter a price')
        self.assertEqual(Replacement.objects.count(), 0)

    def test_approval_required_customer_blocks_completion(self):
        CustomerRepairPreference.objects.create(
            customer=self.customer, field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.queue_status, 'PENDING')  # saved but not completed

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_save_and_send_creates_and_sends_invoice(self, mock_send):
        resp = self._post(save_and_send='1')
        self.assertEqual(resp.status_code, 302)
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.queue_status, 'COMPLETED')
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.status, 'SENT')
        self.assertTrue(mock_send.called)
        self.assertTrue(resp.url.startswith('/owner/invoices/'))

    @patch(SEND_EMAIL, return_value=(False, 'smtp down'))
    def test_send_failure_leaves_draft(self, mock_send):
        self._post(save_and_send='1')
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.status, 'DRAFT')

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_no_email_customer_leaves_draft(self, mock_send):
        self.customer.email = ''
        self.customer.save()
        resp = self._post(save_and_send='1')
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.status, 'DRAFT')
        self.assertFalse(mock_send.called)
        self.assertTrue(resp.url.startswith('/owner/invoices/'))

    def test_repair_type_rejected_for_replacement_shop(self):
        resp = self._post(service_type='repair')
        self.assertEqual(resp.status_code, 200)  # re-rendered with error
        self.assertEqual(Repair.objects.count(), 0)
        self.assertEqual(Replacement.objects.count(), 0)

    def test_replacement_details_persist(self):
        self._post(glass_position='WINDSHIELD', glass_type='OEM', nags_number='FW04567')
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.glass_position, 'WINDSHIELD')
        self.assertEqual(repl.glass_type, 'OEM')
        self.assertEqual(repl.nags_number, 'FW04567')

    def test_form_page_shows_replacement_details_only(self):
        resp = self.client.get(reverse('job_create'))
        self.assertContains(resp, 'Glass position')
        self.assertNotContains(resp, 'windshieldDiagram')


@override_settings(**TEST_SETTINGS)
class QuickJobRepairPricingTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Chip Shop', 'chip@test.com', 'repair')
        self.customer = Customer.objects.create(
            name='Acme Fleet', tenant=self.tenant, email='acme@test.com',
        )
        login(self.client, self.user, self.tenant)

    def test_blank_price_auto_prices_repair(self):
        resp = self.client.post(reverse('job_create'), {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-1',
            'work_done': 'Chip repair',
            'price': '',
            'already_completed': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.queue_status, 'COMPLETED')
        self.assertGreater(repair.cost, 0)  # progressive price book kicked in

    def test_price_override_wins(self):
        self.client.post(reverse('job_create'), {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-2',
            'price': '99.00',
            'already_completed': 'on',
        })
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.cost, Decimal('99.00'))

    def test_repair_details_persist(self):
        self.client.post(reverse('job_create'), {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-3',
            'price': '',
            'damage_type': 'Chip',
            'damage_location_x': '25.5',
            'damage_location_y': '60.0',
        })
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertEqual(repair.damage_type, 'Chip')
        self.assertEqual(repair.damage_location_x, 25.5)
        self.assertEqual(repair.damage_location_y, 60.0)

    def test_form_page_shows_windshield_diagram(self):
        resp = self.client.get(reverse('job_create'))
        self.assertContains(resp, 'windshieldDiagram')
        self.assertContains(resp, 'Damage type')


@override_settings(**TEST_SETTINGS)
class CompleteAndInvoiceTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Both Shop', 'bothqi@test.com', 'both')
        self.customer = Customer.objects.create(
            name='Fleet Q', tenant=self.tenant, email='fleetq@test.com',
        )
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        login(self.client, self.user, self.tenant)

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_complete_and_invoice_replacement(self, mock_send):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-1', glass_position='WINDSHIELD',
            queue_status='APPROVED', cost_override=Decimal('500.00'),
        )
        resp = self.client.post(
            reverse('replacement_complete_and_invoice', args=[repl.pk]))
        self.assertEqual(resp.status_code, 302)
        repl.refresh_from_db()
        self.assertEqual(repl.queue_status, 'COMPLETED')
        invoice = Invoice.objects.get(customer=self.customer)
        self.assertEqual(invoice.status, 'SENT')

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_complete_and_invoice_repair_batch_invoices_all_siblings(self, mock_send):
        import uuid
        batch_id = uuid.uuid4()
        r1 = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='B-1', queue_status='COMPLETED',
            repair_batch_id=batch_id, break_number=1, total_breaks_in_batch=2,
        )
        r2 = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='B-1', queue_status='COMPLETED',
            repair_batch_id=batch_id, break_number=2, total_breaks_in_batch=2,
        )
        resp = self.client.post(
            reverse('repair_complete_and_invoice', args=[r1.id]))
        self.assertEqual(resp.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer)
        invoiced_repairs = set(
            InvoiceLineItem.objects.filter(invoice=invoice)
            .values_list('repair_id', flat=True)
        )
        self.assertEqual(invoiced_repairs, {r1.id, r2.id})

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_double_invoice_guard_reuses_existing(self, mock_send):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-2', glass_position='WINDSHIELD',
            queue_status='APPROVED', cost_override=Decimal('300.00'),
        )
        url = reverse('replacement_complete_and_invoice', args=[repl.pk])
        self.client.post(url)
        self.assertEqual(Invoice.objects.filter(customer=self.customer).count(), 1)
        # Second click must not create a second invoice
        self.client.post(url)
        self.assertEqual(Invoice.objects.filter(customer=self.customer).count(), 1)

    def test_plain_tech_without_invoice_access_blocked(self):
        from django.contrib.auth.models import User
        from apps.tenants.models import TenantMembership
        tech_user = User.objects.create_user('qitech', password='pass123!')
        TenantMembership.objects.create(
            user=tech_user, tenant=self.tenant, role='technician', is_active=True,
        )
        tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True, can_replace=True,
        )
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=tech,
            unit_number='Z-3', glass_position='WINDSHIELD',
            queue_status='APPROVED', cost_override=Decimal('100.00'),
        )
        client = Client()
        login(client, tech_user, self.tenant)
        client.post(reverse('replacement_complete_and_invoice', args=[repl.pk]))
        repl.refresh_from_db()
        self.assertEqual(repl.queue_status, 'APPROVED')  # nothing happened
        self.assertEqual(Invoice.objects.count(), 0)


@override_settings(**TEST_SETTINGS)
class OwnerSendInvoiceDelegationTests(TestCase):
    """owner_send_invoice now delegates to InvoiceSendService — same behavior."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Send Shop', 'send@test.com', 'replacement')
        self.customer = Customer.objects.create(
            name='Send Fleet', tenant=self.tenant, email='sendfleet@test.com',
        )
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        login(self.client, self.user, self.tenant)
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='S-1', glass_position='WINDSHIELD',
            queue_status='APPROVED', cost_override=Decimal('200.00'),
        )
        repl.queue_status = 'COMPLETED'
        repl.save()
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        self.invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            customer=self.customer, services=[repl],
        )

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_send_marks_sent_on_success(self, mock_send):
        resp = self.client.post(
            reverse('owner_send_invoice', args=[self.invoice.id]))
        self.assertEqual(resp.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')

    @patch(SEND_EMAIL, return_value=(False, 'boom'))
    def test_send_failure_stays_draft(self, mock_send):
        self.client.post(reverse('owner_send_invoice', args=[self.invoice.id]))
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'DRAFT')

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_inline_email_capture(self, mock_send):
        self.customer.email = ''
        self.customer.save()
        self.client.post(
            reverse('owner_send_invoice', args=[self.invoice.id]),
            {'email': 'captured@test.com'},
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'captured@test.com')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')
