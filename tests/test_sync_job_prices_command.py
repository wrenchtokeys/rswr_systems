"""
Tests for the sync_job_prices_from_invoices management command — the
back-fill for jobs whose cost drifted from the invoiced amount before the
line-item editor learned to write back (tests/test_simplicity_pass.py
LineItemRepairSyncTests covers the live write-back).
"""

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Customer
from tests.test_simplicity_pass import TEST_OVERRIDES, OwnerClientMixin, make_owner_tenant


@override_settings(**TEST_OVERRIDES)
class SyncJobPricesCommandTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Sync Cmd Shop', 'synccmd@test.com'))
        from apps.technician_portal.models import Repair, Technician
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Penske', customer_type='FLEET',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='U-77', queue_status='COMPLETED',
            service_date=timezone.now(),
        )

    def _make_invoice(self, amount, number='INV-CMD-1', status='SENT', repair=None):
        from apps.billing.models import Invoice, InvoiceLineItem
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number=number, invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status=status, subtotal=amount, discount=Decimal('0.00'), total=amount,
        )
        li = InvoiceLineItem.objects.create(
            invoice=inv, repair=repair or self.repair,
            description='Windshield repair', quantity=1,
            unit_price=amount, discount=Decimal('0.00'), amount=amount,
        )
        return inv, li

    def _run(self, *args):
        out = StringIO()
        call_command('sync_job_prices_from_invoices', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_but_does_not_write(self):
        self._make_invoice(Decimal('60.00'))
        self.repair.refresh_from_db()
        original_cost = self.repair.cost

        out = self._run()
        self.assertIn('Dry run', out)
        self.assertIn('#%d' % self.repair.pk, out)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, original_cost)
        self.assertIsNone(self.repair.cost_override)

    def test_apply_syncs_and_survives_resave(self):
        inv, _ = self._make_invoice(Decimal('60.00'))
        out = self._run('--apply')
        self.assertIn('Synced 1 job', out)

        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))
        self.assertEqual(self.repair.cost_override, Decimal('60.00'))
        self.assertIn(inv.invoice_number, self.repair.override_reason)

        self.repair.save()
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))

    def test_in_sync_job_reports_no_drift(self):
        from apps.technician_portal.models import Repair
        Repair.objects.filter(pk=self.repair.pk).update(cost=Decimal('60.00'))
        self._make_invoice(Decimal('60.00'))
        out = self._run()
        self.assertIn('No drift', out)

    def test_cancelled_and_trashed_invoices_ignored(self):
        inv, _ = self._make_invoice(Decimal('60.00'), number='INV-CANC', status='CANCELLED')
        inv2, _ = self._make_invoice(Decimal('75.00'), number='INV-TRASH')
        type(inv2).all_objects.filter(pk=inv2.pk).update(deleted_at=timezone.now())
        out = self._run('--apply')
        self.assertIn('No drift', out)
        self.repair.refresh_from_db()
        self.assertIsNone(self.repair.cost_override)

    def test_customer_filter_scopes_the_sync(self):
        from apps.technician_portal.models import Repair
        other_customer = Customer.objects.create(
            tenant=self.tenant, name='Ryder', customer_type='FLEET',
        )
        other_repair = Repair.objects.create(
            tenant=self.tenant, customer=other_customer, technician=self.tech,
            unit_number='R-1', queue_status='COMPLETED',
            service_date=timezone.now(),
        )
        self._make_invoice(Decimal('60.00'), number='INV-PENSKE')
        self._make_invoice(Decimal('90.00'), number='INV-RYDER', repair=other_repair)

        out = self._run('--customer', 'penske', '--apply')
        self.assertIn('Synced 1 job', out)
        self.repair.refresh_from_db()
        other_repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))
        self.assertNotEqual(other_repair.cost, Decimal('90.00'))

    def _enable_tax(self, rate='9.750'):
        from apps.billing.models import BillingConfig
        cfg = BillingConfig.get_for_tenant(self.tenant)
        cfg.tax_enabled = True
        cfg.default_tax_rate = Decimal(rate)
        cfg.save()

    def test_stale_tax_detected_even_when_price_matches(self):
        """A job whose cost matches the invoice but whose tax was computed
        from an old price (the pre-fix write-back skipped tax recalc) is
        drift, and --apply corrects the tax fields."""
        from apps.technician_portal.models import Repair
        self._enable_tax()
        # Simulate the repair-182 state: cost synced to $1, tax stuck at $50-era.
        Repair.objects.filter(pk=self.repair.pk).update(
            cost=Decimal('1.00'), cost_override=Decimal('1.00'),
            tax_rate=Decimal('9.750'), tax_amount=Decimal('4.88'),
        )
        self._make_invoice(Decimal('1.00'))

        out = self._run()
        self.assertIn('Dry run', out)
        self.assertIn('tax 4.88 -> 0.10', out)

        out = self._run('--apply')
        self.assertIn('Synced 1 job', out)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('1.00'))
        self.assertEqual(self.repair.tax_amount, Decimal('0.10'))
        self.assertEqual(self.repair.tax_rate, Decimal('9.750'))

    def test_price_sync_updates_tax_together(self):
        """When the cost is back-filled, tax follows the new cost."""
        self._enable_tax()
        self.repair.save()  # tax computed on the original price
        self._make_invoice(Decimal('60.00'))

        self._run('--apply')
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))
        self.assertEqual(self.repair.tax_amount, Decimal('5.85'))

    def test_in_sync_tax_and_price_reports_no_drift(self):
        """Correct cost AND correct tax → nothing to do."""
        from apps.technician_portal.models import Repair
        self._enable_tax()
        Repair.objects.filter(pk=self.repair.pk).update(
            cost=Decimal('60.00'), tax_rate=Decimal('9.750'), tax_amount=Decimal('5.85'),
        )
        self._make_invoice(Decimal('60.00'))
        out = self._run()
        self.assertIn('No drift', out)

    def test_multiple_invoices_last_one_wins(self):
        self._make_invoice(Decimal('50.00'), number='INV-OLD')
        self._make_invoice(Decimal('65.00'), number='INV-NEW')
        out = self._run('--apply')
        self.assertIn('multiple invoices', out)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('65.00'))
        self.assertIn('INV-NEW', self.repair.override_reason)
