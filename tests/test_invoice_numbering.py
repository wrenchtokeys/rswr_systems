"""
Tests for simple sequential invoice numbering.

Invoice numbers are "{prefix}-{counter}" per tenant (e.g. INV-1001), with
the counter stored on BillingConfig.next_invoice_number and allocated
atomically via BillingConfig.allocate_invoice_number. Owners configure the
prefix and next number in Settings → Billing (form_type='invoice_numbering').
"""

from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, TaxRate
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.billing.tasks import _generate_invoice_number
from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


def make_tenant_with_owner(business_name='Numbering Shop', email='numowner@test.com',
                           first_name='Num', last_name='Owner'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name=first_name, last_name=last_name,
    )


class InvoiceNumberingBase(TestCase):
    def setUp(self):
        result = make_tenant_with_owner()
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(tenant=self.tenant, user=self.user)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', email='fleet@test.com',
        )
        TaxRate.objects.create(
            tenant=self.tenant, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )

    def make_repair(self, **kwargs):
        defaults = dict(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='U-100', damage_type='Chip', queue_status='COMPLETED',
            cost=Decimal('50.00'),
        )
        defaults.update(kwargs)
        return Repair.objects.create(**defaults)

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()


class AllocateInvoiceNumberTests(InvoiceNumberingBase):
    def test_default_sequence_starts_at_1001(self):
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'INV-1001')
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'INV-1002')
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.next_invoice_number, 1003)

    def test_custom_prefix_and_start(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.invoice_number_prefix = 'RWR'
        config.next_invoice_number = 5480
        config.save(update_fields=['invoice_number_prefix', 'next_invoice_number'])
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'RWR-5480')
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'RWR-5481')

    def test_blank_prefix_falls_back_to_inv(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.invoice_number_prefix = '   '
        config.save(update_fields=['invoice_number_prefix'])
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'INV-1001')

    def test_skips_numbers_already_taken(self):
        # Owner reset the counter below invoices that already exist.
        for n in (1001, 1002):
            Invoice.objects.create(
                tenant=self.tenant, invoice_number=f'INV-{n}',
                customer=self.customer, invoice_date=timezone.localdate(),
                due_date=timezone.localdate(), status='DRAFT',
            )
        config = BillingConfig.get_for_tenant(self.tenant)
        config.next_invoice_number = 1001
        config.save(update_fields=['next_invoice_number'])
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'INV-1003')
        self.assertEqual(BillingConfig.get_for_tenant(self.tenant).next_invoice_number, 1004)

    def test_soft_deleted_invoice_still_occupies_its_number(self):
        inv = Invoice.objects.create(
            tenant=self.tenant, invoice_number='INV-1001',
            customer=self.customer, invoice_date=timezone.localdate(),
            due_date=timezone.localdate(), status='DRAFT',
        )
        inv.deleted_at = timezone.now()  # soft delete (how the trash views do it)
        inv.save(update_fields=['deleted_at'])
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'INV-1002')

    def test_tenants_have_independent_sequences(self):
        other = make_tenant_with_owner(
            business_name='Other Shop', email='othernum@test.com',
            first_name='Other', last_name='Owner',
        )['tenant']
        self.assertEqual(BillingConfig.allocate_invoice_number(self.tenant), 'INV-1001')
        self.assertEqual(BillingConfig.allocate_invoice_number(other), 'INV-1001')


class InvoiceCreationUsesSequenceTests(InvoiceNumberingBase):
    def test_tracking_service_assigns_sequential_numbers(self):
        tracking = InvoiceTrackingService(tenant=self.tenant)
        inv1 = tracking.create_invoice_from_services(
            customer=self.customer, services=[self.make_repair()],
        )
        inv2 = tracking.create_invoice_from_services(
            customer=self.customer, services=[self.make_repair(unit_number='U-101')],
        )
        self.assertEqual(inv1.invoice_number, 'INV-1001')
        self.assertEqual(inv2.invoice_number, 'INV-1002')

    def test_batch_task_helper_uses_sequence(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(_generate_invoice_number(self.tenant, config), 'INV-1001')


class InvoiceNumberingSettingsTests(InvoiceNumberingBase):
    URL = '/owner/settings/'

    def post_settings(self, **data):
        payload = {'form_type': 'invoice_numbering'}
        payload.update(data)
        return self.client.post(self.URL, payload)

    def test_owner_can_set_prefix_and_next_number(self):
        self.login()
        resp = self.post_settings(invoice_number_prefix='RWR', next_invoice_number='5480')
        self.assertEqual(resp.status_code, 302)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.invoice_number_prefix, 'RWR')
        self.assertEqual(config.next_invoice_number, 5480)

    def test_blank_prefix_saves_as_inv(self):
        self.login()
        self.post_settings(invoice_number_prefix='', next_invoice_number='1001')
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.invoice_number_prefix, 'INV')

    def test_invalid_number_rejected(self):
        self.login()
        self.post_settings(invoice_number_prefix='INV', next_invoice_number='abc')
        self.assertEqual(BillingConfig.get_for_tenant(self.tenant).next_invoice_number, 1001)
        self.post_settings(invoice_number_prefix='INV', next_invoice_number='0')
        self.assertEqual(BillingConfig.get_for_tenant(self.tenant).next_invoice_number, 1001)

    def test_settings_page_shows_numbering_card(self):
        self.login()
        resp = self.client.get(self.URL + '?tab=billing')
        self.assertContains(resp, 'Invoice Numbers')
        self.assertContains(resp, 'invoice_numbering')
