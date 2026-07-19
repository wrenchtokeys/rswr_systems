"""
Tests for replacement invoicing.

Covers:
- InvoiceTrackingService.create_invoice_from_services with replacements
  (single, mixed with repairs), double-billing guard, CANCELLED frees work
- get_uninvoiced_replacements filtering
- Auto-invoice on Replacement completion (per_ticket preference)
- Billing API: uninvoiced list (service_type rows), create with
  replacement_ids, dismiss replacements
- Replacement-only PDF rendered from the tracked record
- Owner invoices page "ready to invoice" widget includes replacements
"""

import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.billing.models import Invoice, InvoiceLineItem, TaxRate
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.customer_portal.models import CustomerRepairPreference
from apps.technician_portal.models import Repair, Replacement
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


def make_tenant_with_owner(business_name='Invoice Test Shop', email='invowner@test.com',
                           first_name='Inv', last_name='Owner'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name=first_name, last_name=last_name,
    )


def make_replacement(tenant, customer, technician=None, status='COMPLETED', **kwargs):
    defaults = dict(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='R-100',
        glass_position='WINDSHIELD',
        parts_cost=Decimal('250.00'),
        labor_cost=Decimal('150.00'),
        queue_status=status,
    )
    defaults.update(kwargs)
    return Replacement.objects.create(**defaults)


def make_repair(tenant, customer, technician=None, status='COMPLETED', **kwargs):
    defaults = dict(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='U-100',
        damage_type='chip',
        queue_status=status,
        cost=Decimal('50.00'),
    )
    defaults.update(kwargs)
    return Repair.objects.create(**defaults)


class ReplacementInvoicingBase(TestCase):
    def make_replacement(self, **kwargs):
        kwargs.setdefault('technician', self.technician)
        return make_replacement(self.tenant, self.customer, **kwargs)

    def make_repair(self, **kwargs):
        kwargs.setdefault('technician', self.technician)
        return make_repair(self.tenant, self.customer, **kwargs)

    def setUp(self):
        result = make_tenant_with_owner()
        self.user = result['user']
        self.tenant = result['tenant']
        from apps.technician_portal.models import Technician
        self.technician = Technician.objects.get(tenant=self.tenant, user=self.user)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', email='fleet@test.com',
        )
        TaxRate.objects.create(
            tenant=self.tenant, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )
        self.tracking = InvoiceTrackingService(tenant=self.tenant)

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()


class CreateInvoiceFromServicesTests(ReplacementInvoicingBase):
    def test_single_replacement_invoice(self):
        replacement = self.make_replacement()
        invoice = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement],
        )
        self.assertEqual(invoice.status, 'DRAFT')
        line_items = list(invoice.line_items.all())
        self.assertEqual(len(line_items), 1)
        li = line_items[0]
        self.assertEqual(li.replacement_id, replacement.id)
        self.assertIsNone(li.repair_id)
        self.assertEqual(li.unit_price, Decimal('400.00'))  # parts + labor
        self.assertEqual(li.amount, Decimal('400.00'))
        self.assertIn('Windshield Replacement', li.description)
        self.assertEqual(invoice.subtotal, Decimal('400.00'))

    def test_mixed_repair_and_replacement_invoice(self):
        repair = self.make_repair()
        replacement = self.make_replacement()
        invoice = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[repair, replacement],
        )
        self.assertEqual(invoice.line_items.count(), 2)
        self.assertEqual(
            invoice.line_items.filter(replacement=replacement).count(), 1)
        self.assertEqual(invoice.line_items.filter(repair=repair).count(), 1)
        self.assertEqual(invoice.subtotal, Decimal('450.00'))

    def test_double_billing_guard(self):
        replacement = self.make_replacement()
        self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement])
        with self.assertRaises(ValueError):
            self.tracking.create_invoice_from_services(
                customer=self.customer, services=[replacement])

    def test_cancelled_invoice_frees_replacement(self):
        replacement = self.make_replacement()
        invoice = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement])
        invoice.status = 'CANCELLED'
        invoice.save(update_fields=['status'])
        second = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement])
        self.assertIsNotNone(second.id)

    def test_delegator_still_works_for_repairs(self):
        repair = self.make_repair()
        invoice = self.tracking.create_invoice_from_repairs(
            customer=self.customer, repairs=[repair])
        self.assertEqual(invoice.line_items.count(), 1)
        self.assertEqual(invoice.line_items.first().repair_id, repair.id)


class GetUninvoicedReplacementsTests(ReplacementInvoicingBase):
    def test_returns_completed_uninvoiced_only(self):
        completed = self.make_replacement()
        self.make_replacement(status='IN_PROGRESS',
                         unit_number='R-101')
        skipped = self.make_replacement(unit_number='R-102')
        skipped.skip_invoicing = True
        skipped.save()

        ids = set(self.tracking.get_uninvoiced_replacements(self.customer)
                  .values_list('id', flat=True))
        self.assertEqual(ids, {completed.id})

    def test_excludes_replacements_on_active_invoices(self):
        replacement = self.make_replacement()
        invoice = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement])
        self.assertEqual(
            self.tracking.get_uninvoiced_replacements(self.customer).count(), 0)
        # CANCELLED invoices don't count
        invoice.status = 'CANCELLED'
        invoice.save(update_fields=['status'])
        self.assertEqual(
            self.tracking.get_uninvoiced_replacements(self.customer).count(), 1)


class AutoInvoiceReplacementTests(ReplacementInvoicingBase):
    def setUp(self):
        super().setUp()
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            invoice_preference='per_ticket',
        )

    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._send_invoice_email', return_value=False)
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._create_payment_link', return_value=None)
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._save_to_s3', return_value='invoices/1/test.pdf')
    def test_completing_replacement_creates_tracked_invoice(self, mock_s3, _mock_link, _mock_email):
        replacement = self.make_replacement(status='IN_PROGRESS')
        self.assertEqual(Invoice.objects.count(), 0)
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        self.assertEqual(Invoice.objects.count(), 1)
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.tenant, self.tenant)
        self.assertEqual(invoice.customer, self.customer)
        li = invoice.line_items.get()
        self.assertEqual(li.replacement_id, replacement.id)
        self.assertTrue(mock_s3.called)
        # Not emailed (auto_email_invoices off) → stays DRAFT
        self.assertEqual(invoice.status, 'DRAFT')
        self.assertEqual(invoice.s3_key, 'invoices/1/test.pdf')

    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._send_invoice_email', return_value=False)
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._create_payment_link', return_value=None)
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._save_to_s3', return_value='invoices/1/test.pdf')
    def test_replacement_pk_never_bills_unrelated_repair(self, *_mocks):
        """Old bug: Replacement PK passed as repair_id could invoice an
        unrelated Repair sharing the same integer PK."""
        replacement = self.make_replacement(status='IN_PROGRESS')
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        invoice = Invoice.objects.get()
        self.assertEqual(invoice.line_items.filter(repair__isnull=False).count(), 0)
        self.assertEqual(
            invoice.line_items.filter(replacement=replacement).count(), 1)


class BillingApiReplacementTests(ReplacementInvoicingBase):
    def test_uninvoiced_endpoint_includes_replacements(self):
        self.login()
        self.make_repair()
        self.make_replacement()
        resp = self.client.get(
            f'/api/billing/customers/{self.customer.id}/uninvoiced/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        rows = data['uninvoiced_repairs']
        self.assertEqual(len(rows), 2)
        types = {row['service_type'] for row in rows}
        self.assertEqual(types, {'repair', 'replacement'})
        repl_row = next(r for r in rows if r['service_type'] == 'replacement')
        self.assertEqual(repl_row['cost'], 400.0)
        self.assertIn('Replacement', repl_row['damage_type'])
        self.assertEqual(data['total_value'], 450.0)

    def test_create_invoice_with_replacement_ids(self):
        self.login()
        replacement = self.make_replacement()
        resp = self.client.post(
            f'/api/billing/invoices/create/{self.customer.id}/',
            data=json.dumps({'replacement_ids': [replacement.id]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data['success'])
        invoice = Invoice.objects.get(id=data['invoice']['id'])
        self.assertEqual(invoice.line_items.get().replacement_id, replacement.id)

    def test_create_invoice_all_uninvoiced_includes_replacements(self):
        self.login()
        self.make_repair()
        self.make_replacement()
        resp = self.client.post(
            f'/api/billing/invoices/create/{self.customer.id}/',
            data=json.dumps({'all_uninvoiced': True}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        invoice = Invoice.objects.get(id=resp.json()['invoice']['id'])
        self.assertEqual(invoice.line_items.count(), 2)

    def test_dismiss_replacements(self):
        self.login()
        replacement = self.make_replacement()
        resp = self.client.post(
            f'/api/billing/customers/{self.customer.id}/uninvoiced/dismiss/',
            data=json.dumps({'replacement_ids': [replacement.id]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['dismissed_count'], 1)
        replacement.refresh_from_db()
        self.assertTrue(replacement.skip_invoicing)
        self.assertEqual(
            self.tracking.get_uninvoiced_replacements(self.customer).count(), 0)

    def test_dismiss_all_covers_replacements(self):
        self.login()
        self.make_repair()
        self.make_replacement()
        resp = self.client.post(
            f'/api/billing/customers/{self.customer.id}/uninvoiced/dismiss/',
            data=json.dumps({'all': True}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['dismissed_count'], 2)


class ReplacementInvoicePdfTests(ReplacementInvoicingBase):
    def test_replacement_only_pdf_renders_from_record(self):
        from apps.billing.services.invoice_service import InvoiceService
        replacement = self.make_replacement()
        invoice = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement])
        pdf_bytes, invoice_data = InvoiceService(
            tenant=self.tenant).generate_invoice_from_record(invoice)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertEqual(len(invoice_data.line_items), 1)


class OwnerInvoiceWidgetTests(ReplacementInvoicingBase):
    def test_widget_counts_replacements(self):
        self.login()
        self.make_repair()
        self.make_replacement()
        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        widget = resp.context['uninvoiced_customers']
        self.assertEqual(len(widget), 1)
        self.assertEqual(widget[0]['customer'].id, self.customer.id)
        self.assertEqual(widget[0]['count'], 2)
        self.assertEqual(widget[0]['total'], Decimal('450.00'))

    def test_generate_invoice_from_replacement_button_flow(self):
        self.login()
        replacement = self.make_replacement()
        resp = self.client.post(
            f'/owner/invoices/generate-from-replacement/{replacement.id}/')
        self.assertEqual(resp.status_code, 302)
        invoice = Invoice.objects.get()
        self.assertIn(f'/owner/invoices/{invoice.id}/', resp.url)
        self.assertEqual(invoice.line_items.get().replacement_id, replacement.id)

    def test_replacement_detail_shows_invoice_state(self):
        self.login()
        replacement = self.make_replacement()
        resp = self.client.get(f'/tech/replacement/{replacement.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['is_invoiced'])
        invoice = self.tracking.create_invoice_from_services(
            customer=self.customer, services=[replacement])
        resp = self.client.get(f'/tech/replacement/{replacement.id}/')
        self.assertTrue(resp.context['is_invoiced'])
        self.assertEqual(resp.context['existing_invoice'].id, invoice.id)
