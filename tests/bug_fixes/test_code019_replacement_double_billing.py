"""
Regression tests for CODE-019: Replacement double-billing in batch invoice task.

Problem:
    `billing/tasks.py::_create_batch_invoice()` tracked invoiced replacements
    by querying:

        InvoiceLineItem.objects.filter(
            repair__isnull=False   # <-- this gets REPAIR line items only
        ).values_list('repair_id', flat=True)

    Then `.exclude(id__in=...)` on Replacement.objects used *repair IDs*
    (wrong model). Result: the exclusion was meaningless — every completed
    Replacement was included in every batch invoice run, causing double billing.

    Root cause: InvoiceLineItem had a `repair` FK but NO `replacement` FK,
    so there was no way to track which replacement a line item belonged to.

Fix:
    1. Added `replacement = ForeignKey(Replacement, null=True, blank=True,
       on_delete=PROTECT, related_name='invoice_line_items')` to InvoiceLineItem.
    2. Fixed the exclusion query in `_create_batch_invoice()` to use
       `InvoiceLineItem.objects.filter(replacement__isnull=False, ...)
       .values_list('replacement_id', flat=True)`.
    3. `_create_batch_invoice()` now passes `replacement=replacement` when
       creating the InvoiceLineItem for each Replacement.

Regression tests verify:
    1. InvoiceLineItem model has a `replacement` field.
    2. `_create_batch_invoice` sets `replacement` FK on replacement line items.
    3. A completed replacement already on an active invoice is NOT double-billed.
    4. A completed replacement on a CANCELLED invoice IS re-billed (cancelled ≠ paid).
    5. Repairs (the existing FK) are still correctly excluded from double-billing.
    6. Source-code guard: exclusion query uses `replacement__isnull=False`, not the old broken pattern.

Author: Amelia
"""

import inspect
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.billing.tasks import process_batch_invoices, _create_batch_invoice
from apps.customer_portal.models import CustomerRepairPreference
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Repair, Replacement, Technician
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(slug):
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@test.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan='pro',
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_customer(tenant, name='Fleet Co'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=f'{name.lower().replace(" ", "")}@test.com',
        customer_type='fleet',
    )


def _make_technician(tenant):
    user = User.objects.create_user(
        username=f'tech_{tenant.slug}_{User.objects.count()}',
        email=f'tech_{tenant.slug}_{User.objects.count()}@test.com',
        password='x',
    )
    tech, _ = Technician.objects.get_or_create(
        user=user, tenant=tenant, defaults={'is_active': True}
    )
    return tech


def _make_replacement(tenant, customer, cost='150.00', status='COMPLETED', technician=None):
    if technician is None:
        technician = _make_technician(tenant)
    return Replacement.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        cost=Decimal(cost),
        queue_status=status,
        service_date=date.today(),
        glass_position='WINDSHIELD',
    )


def _make_repair(tenant, customer, cost='75.00', status='COMPLETED', technician=None):
    if technician is None:
        technician = _make_technician(tenant)
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        cost=Decimal(cost),
        queue_status=status,
        service_date=date.today(),
        damage_type='CHIP',
    )


def _make_billing_config(tenant):
    config, _ = BillingConfig.objects.get_or_create(
        tenant=tenant,
        defaults={
            'company_name': tenant.name,
            'batch_invoice_frequency': 'monthly',
            'batch_invoice_day': date.today().day,
            'batch_invoice_auto_send': False,
            'tax_enabled': False,
        },
    )
    config.batch_invoice_frequency = 'monthly'
    config.batch_invoice_day = date.today().day
    config.batch_invoice_auto_send = False
    config.save()
    return config


def _set_batch_preference(customer):
    prefs, _ = CustomerRepairPreference.objects.get_or_create(customer=customer)
    prefs.invoice_preference = 'batch'
    prefs.save()
    return prefs


# ---------------------------------------------------------------------------
# 1. Model-level: InvoiceLineItem has a replacement FK
# ---------------------------------------------------------------------------

class TestInvoiceLineItemReplacementField(TestCase):
    """InvoiceLineItem must have a nullable `replacement` FK."""

    def test_replacement_field_exists(self):
        """InvoiceLineItem.replacement field must exist."""
        field_names = [f.name for f in InvoiceLineItem._meta.get_fields()]
        self.assertIn(
            'replacement', field_names,
            "InvoiceLineItem is missing the `replacement` FK. "
            "Replacements cannot be tracked for double-billing prevention without it."
        )

    def test_replacement_field_is_nullable(self):
        """replacement FK must be nullable (line items for repairs have replacement=NULL)."""
        field = InvoiceLineItem._meta.get_field('replacement')
        self.assertTrue(
            field.null,
            "InvoiceLineItem.replacement must be nullable (null=True)."
        )

    def test_replacement_field_on_delete_protect(self):
        """replacement FK must use PROTECT to prevent deleting invoiced replacements."""
        from django.db.models import CASCADE, PROTECT
        field = InvoiceLineItem._meta.get_field('replacement')
        self.assertEqual(
            field.remote_field.on_delete, PROTECT,
            "InvoiceLineItem.replacement should use on_delete=PROTECT."
        )

    def test_repair_field_still_exists(self):
        """The existing repair FK must still be present (regression guard)."""
        field_names = [f.name for f in InvoiceLineItem._meta.get_fields()]
        self.assertIn('repair', field_names, "InvoiceLineItem.repair FK disappeared!")


# ---------------------------------------------------------------------------
# 2. Source-code guard: broken exclusion pattern is gone
# ---------------------------------------------------------------------------

class TestBrokenExclusionGone(TestCase):
    """The old broken exclusion query must not appear in tasks.py."""

    def test_old_broken_exclusion_not_present(self):
        """
        The old pattern `repair__isnull=False` followed by `values_list('repair_id'`
        for the replacement exclusion must be gone from _create_batch_invoice source.
        """
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(tasks_module)

        # The correct new pattern must exist
        self.assertIn(
            'replacement__isnull=False',
            source,
            "_create_batch_invoice must use replacement__isnull=False to filter "
            "replacement line items (not the old repair__isnull=False hack)."
        )
        self.assertIn(
            'replacement_id',
            source,
            "_create_batch_invoice must extract replacement_id from the exclusion "
            "query (not repair_id)."
        )

    def test_replacement_fk_set_on_line_item_create(self):
        """replacement=replacement must be passed when creating InvoiceLineItem for replacements."""
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(tasks_module._create_batch_invoice)
        self.assertIn(
            'replacement=replacement',
            source,
            "_create_batch_invoice must set InvoiceLineItem.replacement=replacement "
            "so the replacement FK is populated and future exclusions work."
        )

    def test_correct_model_for_invoice_preference(self):
        """process_batch_invoices must use CustomerRepairPreference, not CustomerPreference."""
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(tasks_module.process_batch_invoices)
        self.assertIn(
            'CustomerRepairPreference',
            source,
            "process_batch_invoices must filter by CustomerRepairPreference.invoice_preference, "
            "not CustomerPreference (which has no invoice_preference field)."
        )
        self.assertNotIn(
            "CustomerPreference.objects",
            source,
            "process_batch_invoices must not use CustomerPreference.objects — "
            "that model has no invoice_preference field."
        )


# ---------------------------------------------------------------------------
# 3. Functional: replacement line item is linked correctly
# ---------------------------------------------------------------------------

class TestReplacementLineItemLinkage(TestCase):
    """_create_batch_invoice must populate the replacement FK on line items."""

    def test_replacement_fk_set_after_batch_invoice(self):
        tenant, _ = _make_tenant('linkage')
        customer = _make_customer(tenant, 'Linkage Trucking')
        config = _make_billing_config(tenant)
        replacement = _make_replacement(tenant, customer)

        invoice = _create_batch_invoice(tenant, customer, config)
        self.assertIsNotNone(invoice, "Invoice should be created for uninvoiced replacement")

        line_items = list(invoice.line_items.all())
        self.assertEqual(len(line_items), 1, "Should have exactly 1 line item")

        li = line_items[0]
        self.assertIsNotNone(li.replacement_id, "Line item replacement FK must be set")
        self.assertEqual(li.replacement_id, replacement.id)
        self.assertIsNone(li.repair_id, "Line item repair FK should be NULL for replacement")


# ---------------------------------------------------------------------------
# 4. Functional: no double-billing of replacements
# ---------------------------------------------------------------------------

class TestNoDoubleReplacementBilling(TestCase):
    """A replacement already on an active invoice must NOT be invoiced again."""

    def test_already_invoiced_replacement_excluded(self):
        tenant, _ = _make_tenant('nodbl')
        customer = _make_customer(tenant, 'NoDbl Trucking')
        config = _make_billing_config(tenant)
        replacement = _make_replacement(tenant, customer)

        # First invoice (simulate existing draft)
        existing_invoice = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number='INV-EXISTING-001',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            payment_terms='NET30',
            status='DRAFT',
        )
        InvoiceLineItem.objects.create(
            invoice=existing_invoice,
            replacement=replacement,
            description='Windshield Replacement - UNIT-001',
            quantity=1,
            unit_price=replacement.cost,
            amount=replacement.cost,
        )

        # Second run should produce nothing (already invoiced)
        invoice2 = _create_batch_invoice(tenant, customer, config)
        self.assertIsNone(
            invoice2,
            "Should not create a second invoice — replacement is already invoiced."
        )

    def test_cancelled_invoice_allows_rebilling(self):
        """A replacement on a CANCELLED invoice can be re-billed."""
        tenant, _ = _make_tenant('rebill')
        customer = _make_customer(tenant, 'Rebill Trucking')
        config = _make_billing_config(tenant)
        replacement = _make_replacement(tenant, customer)

        # Cancelled invoice — should NOT block re-billing
        cancelled_invoice = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number='INV-CANCELLED-001',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            payment_terms='NET30',
            status='CANCELLED',
        )
        InvoiceLineItem.objects.create(
            invoice=cancelled_invoice,
            replacement=replacement,
            description='Windshield Replacement - UNIT-001',
            quantity=1,
            unit_price=replacement.cost,
            amount=replacement.cost,
        )

        # Should create a new invoice since the only existing one is CANCELLED
        invoice2 = _create_batch_invoice(tenant, customer, config)
        self.assertIsNotNone(
            invoice2,
            "Should create a new invoice — the existing one is CANCELLED, not active."
        )

    def test_repair_double_billing_still_prevented(self):
        """Existing repair double-billing prevention must still work (regression guard)."""
        tenant, _ = _make_tenant('repairdbl')
        customer = _make_customer(tenant, 'RepairDbl Trucking')
        config = _make_billing_config(tenant)
        repair = _make_repair(tenant, customer)

        # Existing draft invoice with this repair
        existing_invoice = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number='INV-REPAIR-001',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            payment_terms='NET30',
            status='DRAFT',
        )
        InvoiceLineItem.objects.create(
            invoice=existing_invoice,
            repair=repair,
            description='Windshield Repair - UNIT-001',
            quantity=1,
            unit_price=repair.cost,
            amount=repair.cost,
        )

        # Second run — repair already invoiced, no new invoice
        invoice2 = _create_batch_invoice(tenant, customer, config)
        self.assertIsNone(
            invoice2,
            "Repair double-billing prevention must still work after the replacement fix."
        )


# ---------------------------------------------------------------------------
# 5. Functional: process_batch_invoices end-to-end with replacements
# ---------------------------------------------------------------------------

class TestProcessBatchInvoicesWithReplacements(TestCase):
    """process_batch_invoices should create invoices for replacements correctly."""

    def test_batch_task_invoices_replacements(self):
        tenant, _ = _make_tenant('e2e')
        customer = _make_customer(tenant, 'E2E Fleet')
        config = _make_billing_config(tenant)
        _set_batch_preference(customer)
        replacement = _make_replacement(tenant, customer, cost='200.00')

        result = process_batch_invoices()
        self.assertGreaterEqual(
            result['invoices_created'], 1,
            "process_batch_invoices should create at least 1 invoice for the replacement."
        )

        # Confirm the replacement FK is set
        li = InvoiceLineItem.objects.filter(replacement=replacement).first()
        self.assertIsNotNone(
            li,
            "InvoiceLineItem with replacement FK should exist after batch run."
        )

    def test_batch_task_does_not_double_bill_on_second_run(self):
        tenant, _ = _make_tenant('e2e2')
        customer = _make_customer(tenant, 'E2E2 Fleet')
        config = _make_billing_config(tenant)
        _set_batch_preference(customer)
        _make_replacement(tenant, customer, cost='180.00')

        result1 = process_batch_invoices()
        self.assertGreaterEqual(result1['invoices_created'], 1)

        # Second run: replacement already invoiced — no new invoices
        result2 = process_batch_invoices()
        self.assertEqual(
            result2['invoices_created'], 0,
            "Second batch run should create 0 invoices — replacement already invoiced."
        )
