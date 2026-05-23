"""
CODE-258: purge_deleted_records deletes line items from active invoices

When purging soft-deleted repairs, the command previously deleted ALL
InvoiceLineItems referencing those repairs — including line items on active
(non-soft-deleted) invoices.  This corrupted the active invoice's financial
data: line items would vanish from a SENT or PAID invoice, breaking the
total/subtotal relationship and the audit trail.

Fix: Exclude soft-deleted repairs from purging if they are still referenced
by line items on active (non-soft-deleted) invoices.  Only delete line items
on invoices that are themselves being purged or are already soft-deleted.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from apps.technician_portal.models import Repair, Customer, Technician
from apps.tenants.models import Tenant
from django.contrib.auth.models import User


class PurgeActiveInvoiceProtectionTest(TestCase):
    """Verify purge_deleted_records does not corrupt active invoices."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('owner', 'owner@test.com', 'pass')
        cls.tenant = Tenant.objects.create(name='Test Shop', slug='test-shop', owner=cls.owner)
        cls.tech_user = User.objects.create_user('tech', 'tech@test.com', 'pass')
        cls.tech = Technician.objects.create(user=cls.tech_user, tenant=cls.tenant, is_active=True)
        cls.customer = Customer.objects.create(name='Test Customer', tenant=cls.tenant)

    def _create_repair(self, unit_number='U001', soft_deleted=False, days_ago=60):
        """Helper to create a repair, optionally soft-deleted."""
        repair = Repair.objects.create(
            tenant=self.tenant,
            technician=self.tech,
            customer=self.customer,
            unit_number=unit_number,
            damage_type='CHIP',
            queue_status='COMPLETED',
            cost=Decimal('25.00'),
        )
        if soft_deleted:
            cutoff = timezone.now() - timedelta(days=days_ago)
            Repair.all_objects.filter(pk=repair.pk).update(deleted_at=cutoff)
            repair.refresh_from_db()
        return repair

    def _create_invoice(self, status='PAID', soft_deleted=False, days_ago=60):
        """Helper to create an invoice."""
        invoice = Invoice.all_objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=f'INV-{Invoice.all_objects.count() + 1}',
            status=status,
            subtotal=Decimal('25.00'),
            total=Decimal('25.00'),
        )
        if soft_deleted:
            cutoff = timezone.now() - timedelta(days=days_ago)
            Invoice.all_objects.filter(pk=invoice.pk).update(deleted_at=cutoff)
            invoice.refresh_from_db()
        return invoice

    def _run_purge(self, apply=True, days=30):
        """Run the purge_deleted_records command and return stdout."""
        from django.core.management import call_command
        out = StringIO()
        call_command('purge_deleted_records', apply=apply, days=days, stdout=out)
        return out.getvalue()

    def test_repair_on_active_invoice_not_purged(self):
        """
        A soft-deleted repair referenced by a line item on an active invoice
        must NOT be purged. The line item on the active invoice must survive.
        """
        repair = self._create_repair(soft_deleted=True, days_ago=60)
        active_invoice = self._create_invoice(status='PAID', soft_deleted=False)
        line_item = InvoiceLineItem.objects.create(
            invoice=active_invoice,
            repair=repair,
            description='Repair #1',
            quantity=1,
            unit_price=Decimal('25.00'),
            amount=Decimal('25.00'),
        )

        output = self._run_purge(apply=True, days=30)

        # The repair should still exist (skipped due to active invoice reference)
        self.assertTrue(
            Repair.all_objects.filter(pk=repair.pk).exists(),
            'Repair referenced by active invoice was incorrectly purged',
        )
        # The line item on the active invoice should still exist
        self.assertTrue(
            InvoiceLineItem.objects.filter(pk=line_item.pk).exists(),
            'Line item on active invoice was incorrectly deleted',
        )
        # The active invoice should be untouched
        self.assertTrue(
            Invoice.all_objects.filter(pk=active_invoice.pk).exists(),
            'Active invoice was incorrectly purged',
        )
        self.assertIn('skipped', output.lower())

    def test_repair_on_soft_deleted_invoice_is_purged(self):
        """
        A soft-deleted repair referenced only by line items on also-soft-deleted
        invoices should be purged along with those invoices and line items.
        """
        repair = self._create_repair(soft_deleted=True, days_ago=60)
        deleted_invoice = self._create_invoice(status='PAID', soft_deleted=True, days_ago=60)
        InvoiceLineItem.objects.create(
            invoice=deleted_invoice,
            repair=repair,
            description='Repair #1',
            quantity=1,
            unit_price=Decimal('25.00'),
            amount=Decimal('25.00'),
        )

        self._run_purge(apply=True, days=30)

        # Both should be purged
        self.assertFalse(
            Repair.all_objects.filter(pk=repair.pk).exists(),
            'Soft-deleted repair with only soft-deleted invoice refs was not purged',
        )
        self.assertFalse(
            Invoice.all_objects.filter(pk=deleted_invoice.pk).exists(),
            'Soft-deleted invoice was not purged',
        )
        self.assertEqual(InvoiceLineItem.objects.count(), 0, 'Line items were not cleaned up')

    def test_repair_with_no_invoice_refs_is_purged(self):
        """
        A soft-deleted repair with no invoice line item references should be
        purged normally.
        """
        repair = self._create_repair(soft_deleted=True, days_ago=60)

        self._run_purge(apply=True, days=30)

        self.assertFalse(
            Repair.all_objects.filter(pk=repair.pk).exists(),
            'Orphan soft-deleted repair was not purged',
        )

    def test_mixed_scenario_selective_purge(self):
        """
        Two soft-deleted repairs: one referenced by an active invoice, one not.
        Only the unreferenced one should be purged.
        """
        repair_safe = self._create_repair(unit_number='SAFE', soft_deleted=True, days_ago=60)
        repair_blocked = self._create_repair(unit_number='BLOCKED', soft_deleted=True, days_ago=60)

        active_invoice = self._create_invoice(status='SENT', soft_deleted=False)
        line_item = InvoiceLineItem.objects.create(
            invoice=active_invoice,
            repair=repair_blocked,
            description='Blocked repair',
            quantity=1,
            unit_price=Decimal('25.00'),
            amount=Decimal('25.00'),
        )

        self._run_purge(apply=True, days=30)

        # Safe repair should be purged
        self.assertFalse(
            Repair.all_objects.filter(pk=repair_safe.pk).exists(),
            'Unreferenced repair was not purged',
        )
        # Blocked repair and its line item should survive
        self.assertTrue(
            Repair.all_objects.filter(pk=repair_blocked.pk).exists(),
            'Repair referenced by active invoice was incorrectly purged',
        )
        self.assertTrue(
            InvoiceLineItem.objects.filter(pk=line_item.pk).exists(),
            'Line item on active invoice was incorrectly deleted',
        )

    def test_dry_run_does_not_delete(self):
        """Dry run should report but not delete anything."""
        repair = self._create_repair(soft_deleted=True, days_ago=60)

        output = self._run_purge(apply=False, days=30)

        self.assertTrue(
            Repair.all_objects.filter(pk=repair.pk).exists(),
            'Dry run deleted a repair',
        )
        self.assertIn('dry run', output.lower())

    def test_recently_deleted_not_purged(self):
        """Repairs soft-deleted less than --days ago should not be purged."""
        repair = self._create_repair(soft_deleted=True, days_ago=10)

        self._run_purge(apply=True, days=30)

        self.assertTrue(
            Repair.all_objects.filter(pk=repair.pk).exists(),
            'Recently soft-deleted repair was purged prematurely',
        )
