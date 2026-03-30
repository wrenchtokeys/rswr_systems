"""
Regression tests for CODE-167: RepairAdmin.delete_queryset() missing — default
'Delete selected' action bypasses invoiced-repair guard and UnitRepairCount decrement.

Bug: RepairAdmin had a custom bulk_delete_repairs action that correctly:
  1. Skipped repairs linked to active invoices (DRAFT/SENT/PARTIAL/PAID)
  2. Decremented UnitRepairCount for deleted COMPLETED repairs

But it did NOT override delete_queryset(). Django's default admin 'Delete selected'
action calls delete_queryset() → QuerySet.delete(), which:
  - Deletes invoiced repairs (would crash on DB PROTECT or corrupt billing data)
  - Leaves UnitRepairCount inflated (progressive-pricing corruption)

Fix: Added delete_queryset() override to RepairAdmin that mirrors bulk_delete_repairs:
skips invoiced repairs linked to active invoices (DRAFT/SENT/PARTIAL/PAID) and
decrements UnitRepairCount before deletion.

(CODE-167)
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User

from apps.technician_portal.admin import RepairAdmin
from apps.technician_portal.models import Repair, Technician, Customer, UnitRepairCount
from apps.billing.models import Invoice, InvoiceLineItem
from apps.tenants.models import Tenant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username, email=None):
    return User.objects.create_user(
        username=username,
        email=email or f"{username}@example.com",
        password="testpass",
    )


def _make_tenant(name, owner=None):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=owner,
    )


def _make_customer(tenant, name="Fleet Co"):
    return Customer.objects.create(tenant=tenant, name=name)


def _make_technician(tenant, user):
    return Technician.objects.create(
        tenant=tenant,
        user=user,
        is_active=True,
        can_repair=True,
    )


def _make_repair(tenant, customer, technician, unit_number="T-001", status="COMPLETED"):
    """Create a Repair bypassing Repair.save() pricing logic via all_objects."""
    return Repair.all_objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number=unit_number,
        queue_status=status,
        cost=45.00,
    )


def _make_invoice(tenant, customer, status="SENT"):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f"INV-167-{Invoice.objects.count()}-{status}",
        status=status,
        subtotal=45.00,
        total=45.00,
    )


def _make_line_item(invoice, repair):
    return InvoiceLineItem.objects.create(
        invoice=invoice,
        repair=repair,
        description="Windshield repair",
        quantity=1,
        unit_price=45.00,
        amount=45.00,
    )


def _set_unit_repair_count(tenant, customer, unit_number, count):
    """Set UnitRepairCount.repair_count, creating or updating as needed."""
    urc, created = UnitRepairCount.objects.get_or_create(
        tenant=tenant,
        customer=customer,
        unit_number=unit_number,
        defaults={'repair_count': count},
    )
    if not created:
        urc.repair_count = count
        urc.save()
    return urc


def _make_request(user):
    factory = RequestFactory()
    request = factory.post("/")
    request.user = user
    from django.contrib.messages.storage.cookie import CookieStorage
    request._messages = CookieStorage(request)
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class DeleteQuerysetInvoicedRepairSkipTest(TestCase):
    """delete_queryset skips repairs on active invoices (DRAFT/SENT/PARTIAL/PAID)."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RepairAdmin(Repair, self.site)

        self.owner = _make_user("owner167a")
        self.tenant = _make_tenant("Tenant167A", owner=self.owner)
        self.customer = _make_customer(self.tenant)
        tech_user = _make_user("tech167a")
        self.tech = _make_technician(self.tenant, tech_user)

        self.invoiced_repair = _make_repair(self.tenant, self.customer, self.tech, "T-001", "COMPLETED")
        self.free_repair = _make_repair(self.tenant, self.customer, self.tech, "T-002", "COMPLETED")

        invoice = _make_invoice(self.tenant, self.customer, "SENT")
        _make_line_item(invoice, self.invoiced_repair)

    def test_invoiced_repair_not_deleted(self):
        """delete_queryset must not delete repairs linked to active invoices."""
        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id__in=[self.invoiced_repair.id, self.free_repair.id])
        self.admin.delete_queryset(request, qs)

        self.assertTrue(
            Repair.all_objects.filter(id=self.invoiced_repair.id).exists(),
            "Invoiced repair should NOT be deleted by delete_queryset"
        )

    def test_non_invoiced_repair_is_deleted(self):
        """delete_queryset deletes repairs that are not invoiced."""
        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id__in=[self.invoiced_repair.id, self.free_repair.id])
        self.admin.delete_queryset(request, qs)

        self.assertFalse(
            Repair.all_objects.filter(id=self.free_repair.id).exists(),
            "Non-invoiced repair SHOULD be deleted by delete_queryset"
        )

    def test_draft_invoice_repair_also_skipped(self):
        """DRAFT-status invoice repairs are also protected."""
        draft_repair = _make_repair(self.tenant, self.customer, self.tech, "T-003", "COMPLETED")
        draft_invoice = _make_invoice(self.tenant, self.customer, "DRAFT")
        _make_line_item(draft_invoice, draft_repair)

        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id=draft_repair.id)
        self.admin.delete_queryset(request, qs)

        self.assertTrue(
            Repair.all_objects.filter(id=draft_repair.id).exists(),
            "Repair on DRAFT invoice should NOT be deleted"
        )


class DeleteQuerysetUnitRepairCountDecrementTest(TestCase):
    """delete_queryset decrements UnitRepairCount for deleted COMPLETED repairs."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RepairAdmin(Repair, self.site)

        self.owner = _make_user("owner167b")
        self.tenant = _make_tenant("Tenant167B", owner=self.owner)
        self.customer = _make_customer(self.tenant)
        tech_user = _make_user("tech167b")
        self.tech = _make_technician(self.tenant, tech_user)

        self.repair1 = _make_repair(self.tenant, self.customer, self.tech, "T-001", "COMPLETED")
        self.repair2 = _make_repair(self.tenant, self.customer, self.tech, "T-001", "COMPLETED")

        # Override UnitRepairCount to 3 (Repair.save() may have created/set it)
        _set_unit_repair_count(self.tenant, self.customer, "T-001", 3)

    def test_unit_repair_count_decremented(self):
        """delete_queryset decrements repair_count for each deleted COMPLETED repair."""
        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id__in=[self.repair1.id, self.repair2.id])
        self.admin.delete_queryset(request, qs)

        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number="T-001"
        )
        self.assertEqual(urc.repair_count, 1,
                         "Deleting 2 COMPLETED repairs should drop repair_count from 3 to 1")

    def test_unit_repair_count_clamped_at_zero(self):
        """delete_queryset clamps repair_count at 0, not negative."""
        # Override to 1 — deleting 2 repairs should clamp at 0
        _set_unit_repair_count(self.tenant, self.customer, "T-001", 1)

        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id__in=[self.repair1.id, self.repair2.id])
        self.admin.delete_queryset(request, qs)

        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number="T-001"
        )
        self.assertEqual(urc.repair_count, 0,
                         "repair_count should clamp at 0, not go negative")


class DeleteQuerysetNonCompletedRepairsTest(TestCase):
    """delete_queryset does not change UnitRepairCount for non-COMPLETED repairs."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RepairAdmin(Repair, self.site)

        self.owner = _make_user("owner167c")
        self.tenant = _make_tenant("Tenant167C", owner=self.owner)
        self.customer = _make_customer(self.tenant)
        tech_user = _make_user("tech167c")
        self.tech = _make_technician(self.tenant, tech_user)

        self.pending_repair = _make_repair(self.tenant, self.customer, self.tech, "T-001", "PENDING")
        self.in_progress = _make_repair(self.tenant, self.customer, self.tech, "T-002", "IN_PROGRESS")

        _set_unit_repair_count(self.tenant, self.customer, "T-001", 2)

    def test_no_decrement_for_pending_repairs(self):
        """Only COMPLETED repairs affect UnitRepairCount; PENDING/IN_PROGRESS do not."""
        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id__in=[self.pending_repair.id, self.in_progress.id])
        self.admin.delete_queryset(request, qs)

        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number="T-001"
        )
        self.assertEqual(urc.repair_count, 2,
                         "Deleting non-COMPLETED repairs should not change repair_count")


class DeleteQuerysetMissingUnitRepairCountTest(TestCase):
    """delete_queryset handles missing UnitRepairCount gracefully (no DoesNotExist crash)."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RepairAdmin(Repair, self.site)

        self.owner = _make_user("owner167e")
        self.tenant = _make_tenant("Tenant167E", owner=self.owner)
        self.customer = _make_customer(self.tenant)
        tech_user = _make_user("tech167e")
        self.tech = _make_technician(self.tenant, tech_user)

        # Create repair with PENDING status so Repair.save() doesn't auto-create UnitRepairCount
        self.repair = _make_repair(self.tenant, self.customer, self.tech, "T-999", "PENDING")
        # Manually update to COMPLETED without triggering save() hooks
        Repair.all_objects.filter(id=self.repair.id).update(queue_status='COMPLETED')
        # Ensure no UnitRepairCount exists for this unit
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number="T-999"
        ).delete()

    def test_no_crash_when_unit_repair_count_missing(self):
        """delete_queryset does not crash if UnitRepairCount doesn't exist."""
        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(id=self.repair.id)
        # Should not raise
        try:
            self.admin.delete_queryset(request, qs)
        except Exception as e:
            self.fail(f"delete_queryset raised unexpectedly: {e}")

        self.assertFalse(
            Repair.all_objects.filter(id=self.repair.id).exists(),
            "Repair should still be deleted even if UnitRepairCount is missing"
        )


class DeleteQuerysetMultipleStatusInvoicesTest(TestCase):
    """delete_queryset correctly handles repairs on invoices of different statuses."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RepairAdmin(Repair, self.site)

        self.owner = _make_user("owner167f")
        self.tenant = _make_tenant("Tenant167F", owner=self.owner)
        self.customer = _make_customer(self.tenant)
        tech_user = _make_user("tech167f")
        self.tech = _make_technician(self.tenant, tech_user)

        # Repair on PAID invoice — should be skipped
        self.paid_repair = _make_repair(self.tenant, self.customer, self.tech, "T-100", "COMPLETED")
        paid_invoice = _make_invoice(self.tenant, self.customer, "PAID")
        _make_line_item(paid_invoice, self.paid_repair)

        # Repair on PARTIAL invoice — should be skipped
        self.partial_repair = _make_repair(self.tenant, self.customer, self.tech, "T-101", "COMPLETED")
        partial_invoice = _make_invoice(self.tenant, self.customer, "PARTIAL")
        _make_line_item(partial_invoice, self.partial_repair)

        # Free repair — should be deleted
        self.free_repair = _make_repair(self.tenant, self.customer, self.tech, "T-102", "COMPLETED")

    def test_paid_and_partial_repairs_protected(self):
        """Repairs on PAID and PARTIAL invoices are both skipped."""
        request = _make_request(self.owner)
        qs = Repair.all_objects.filter(
            id__in=[self.paid_repair.id, self.partial_repair.id, self.free_repair.id]
        )
        self.admin.delete_queryset(request, qs)

        self.assertTrue(Repair.all_objects.filter(id=self.paid_repair.id).exists(),
                        "PAID invoice repair should not be deleted")
        self.assertTrue(Repair.all_objects.filter(id=self.partial_repair.id).exists(),
                        "PARTIAL invoice repair should not be deleted")
        self.assertFalse(Repair.all_objects.filter(id=self.free_repair.id).exists(),
                         "Non-invoiced repair should be deleted")
