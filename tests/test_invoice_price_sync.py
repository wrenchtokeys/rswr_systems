"""
Job → invoice price sync (apps/billing/services/invoice_sync.py).

The invoice → job direction is covered by
tests/test_simplicity_pass.py LineItemRepairSyncTests; these tests cover
the reverse: editing a job's price updates its line on live invoices,
paid invoices are never touched, and RepairForm locks the price fields
for jobs on a paid invoice.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Customer
from tests.test_simplicity_pass import TEST_OVERRIDES, OwnerClientMixin, make_owner_tenant


@override_settings(**TEST_OVERRIDES)
class JobToInvoiceSyncTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Fwd Sync Shop', 'fwdsync@test.com'))
        from apps.technician_portal.models import Repair, Technician
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Penske', customer_type='FLEET',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='U-1', queue_status='COMPLETED',
            service_date=timezone.now(),
        )

    def _make_invoice(self, amount, status='SENT', number='INV-FWD-1', repair=None,
                      replacement=None):
        from apps.billing.models import Invoice, InvoiceLineItem
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number=number, invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status=status, subtotal=amount, discount=Decimal('0.00'), total=amount,
        )
        li = InvoiceLineItem.objects.create(
            invoice=inv, repair=repair or (None if replacement else self.repair),
            replacement=replacement,
            description='Windshield repair', quantity=1,
            unit_price=amount, discount=Decimal('0.00'), amount=amount,
        )
        return inv, li

    def test_repair_price_edit_updates_live_invoice(self):
        inv, li = self._make_invoice(Decimal('50.00'))
        self.repair.cost_override = Decimal('65.00')
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(li.unit_price, Decimal('65.00'))
        self.assertEqual(li.amount, Decimal('65.00'))
        self.assertEqual(inv.subtotal, Decimal('65.00'))
        self.assertEqual(inv.total, Decimal('65.00'))

    def test_paid_invoice_is_never_touched(self):
        inv, li = self._make_invoice(Decimal('50.00'), status='PAID')
        self.repair.cost_override = Decimal('65.00')
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(li.amount, Decimal('50.00'))
        self.assertEqual(inv.total, Decimal('50.00'))

    def test_in_sync_line_presentation_preserved(self):
        """A line whose charged amount already matches keeps its unit-price/
        discount presentation (progressive-pricing display)."""
        from apps.billing.models import InvoiceLineItem
        inv, li = self._make_invoice(Decimal('35.00'))
        # Progressive-style presentation: base $50, discount $15, charged $35
        InvoiceLineItem.objects.filter(pk=li.pk).update(
            unit_price=Decimal('50.00'), discount=Decimal('15.00'),
        )
        from apps.technician_portal.models import Repair
        Repair.objects.filter(pk=self.repair.pk).update(cost=Decimal('35.00'))
        self.repair.refresh_from_db()

        self.repair.save()
        li.refresh_from_db()
        self.assertEqual(li.unit_price, Decimal('50.00'))
        self.assertEqual(li.discount, Decimal('15.00'))

    def test_replacement_price_edit_updates_live_invoice(self):
        from apps.technician_portal.models import Replacement
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='U-2', queue_status='COMPLETED',
            service_date=timezone.now(),
            parts_cost=Decimal('200.00'), labor_cost=Decimal('100.00'),
        )
        inv, li = self._make_invoice(
            Decimal('300.00'), number='INV-FWD-R', replacement=replacement,
        )
        replacement.cost_override = Decimal('350.00')
        replacement.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertEqual(li.amount, Decimal('350.00'))
        self.assertEqual(inv.total, Decimal('350.00'))

    def test_repair_form_locks_price_on_paid_invoice(self):
        from apps.technician_portal.forms import RepairForm
        self._make_invoice(Decimal('50.00'), status='PAID')
        form = RepairForm(instance=self.repair, user=self.user, tenant=self.tenant)
        self.assertNotIn('cost_override', form.fields)
        self.assertNotIn('override_reason', form.fields)
        self.assertEqual(form.price_locked_invoice, 'INV-FWD-1')

    def test_repair_form_keeps_price_fields_on_sent_invoice(self):
        from apps.technician_portal.forms import RepairForm
        self._make_invoice(Decimal('50.00'), status='SENT')
        form = RepairForm(instance=self.repair, user=self.user, tenant=self.tenant)
        self.assertIn('cost_override', form.fields)
        self.assertIsNone(form.price_locked_invoice)


@override_settings(**TEST_OVERRIDES)
class JobToInvoiceTaxSyncTests(OwnerClientMixin, TestCase):
    """Taxable-status half of the job→invoice sync.

    Marking a customer tax-exempt (or the job no_tax) and re-saving the job
    must reach its line on a live invoice — the field alternative was
    deleting the job and invoice and recreating both. The invoice's tax RATE
    stays frozen at creation; only which lines it applies to changes.
    """

    def setUp(self):
        self.login_owner(make_owner_tenant('Tax Sync Shop', 'taxsync@test.com'))
        from apps.technician_portal.models import Repair, Technician
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Jane Driver', customer_type='RETAIL',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Silver Camry', queue_status='COMPLETED',
            service_date=timezone.now(),
        )
        Repair.objects.filter(pk=self.repair.pk).update(cost=Decimal('50.00'))
        self.repair.refresh_from_db()

    def _make_taxed_invoice(self, status='SENT', tax_rate=Decimal('6.500'),
                            taxable=True, number='INV-TAX-1'):
        from apps.billing.models import Invoice, InvoiceLineItem
        subtotal = Decimal('50.00')
        tax_amount = (subtotal * tax_rate / Decimal('100')).quantize(Decimal('0.01')) if taxable else Decimal('0.00')
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number=number, invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status=status, subtotal=subtotal, discount=Decimal('0.00'),
            tax_rate=tax_rate, tax_amount=tax_amount,
            total=subtotal + tax_amount,
        )
        li = InvoiceLineItem.objects.create(
            invoice=inv, repair=self.repair,
            description='Windshield repair', quantity=1,
            unit_price=subtotal, discount=Decimal('0.00'), amount=subtotal,
            taxable=taxable,
        )
        return inv, li

    def test_tax_exempt_flip_reaches_live_invoice(self):
        inv, li = self._make_taxed_invoice()
        self.assertEqual(inv.total, Decimal('53.25'))

        self.customer.tax_exempt = True
        self.customer.save(update_fields=['tax_exempt'])
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertFalse(li.taxable)
        self.assertEqual(inv.tax_amount, Decimal('0.00'))
        self.assertEqual(inv.total, Decimal('50.00'))
        # The rate is frozen at creation — only its application changed.
        self.assertEqual(inv.tax_rate, Decimal('6.500'))

    def test_unexempting_restores_tax_at_frozen_rate(self):
        inv, li = self._make_taxed_invoice()
        self.customer.tax_exempt = True
        self.customer.save(update_fields=['tax_exempt'])
        self.repair.save()

        self.customer.tax_exempt = False
        self.customer.save(update_fields=['tax_exempt'])
        self.repair.refresh_from_db()
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertTrue(li.taxable)
        self.assertEqual(inv.tax_amount, Decimal('3.25'))
        self.assertEqual(inv.total, Decimal('53.25'))

    def test_paid_invoice_tax_is_never_touched(self):
        inv, li = self._make_taxed_invoice(status='PAID')
        self.customer.tax_exempt = True
        self.customer.save(update_fields=['tax_exempt'])
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertTrue(li.taxable)
        self.assertEqual(inv.tax_amount, Decimal('3.25'))
        self.assertEqual(inv.total, Decimal('53.25'))

    def test_no_tax_flag_propagates_like_exemption(self):
        inv, li = self._make_taxed_invoice()
        self.repair.no_tax = True
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertFalse(li.taxable)
        self.assertEqual(inv.tax_amount, Decimal('0.00'))
        self.assertEqual(inv.total, Decimal('50.00'))

    def test_exempt_at_creation_invoice_keeps_frozen_zero_rate(self):
        """Un-exempting can't retroactively sprout tax on an invoice created
        while the customer was exempt: its rate was frozen at zero."""
        inv, li = self._make_taxed_invoice(tax_rate=Decimal('0.000'), taxable=False)
        self.repair.save()

        li.refresh_from_db()
        inv.refresh_from_db()
        self.assertTrue(li.taxable)  # status synced to the non-exempt job...
        self.assertEqual(inv.tax_amount, Decimal('0.00'))  # ...at the frozen zero rate
        self.assertEqual(inv.total, Decimal('50.00'))
