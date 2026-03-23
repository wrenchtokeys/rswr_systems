"""
Regression tests for CODE-161: bulk_delete_repairs admin action fails to
decrement UnitRepairCount.repair_count when deleting COMPLETED repairs.

Bug: RepairAdmin.bulk_delete_repairs() called safe_to_delete.delete() (QuerySet
bulk delete) after filtering out invoiced repairs. It never decremented
UnitRepairCount.repair_count for the deleted COMPLETED repairs, leaving inflated
counts that cause incorrect progressive pricing on future repairs.

Fix: Tally COMPLETED repairs per (tenant, customer, unit_number) before deletion,
then decrement UnitRepairCount.repair_count (clamped to 0) after the delete.
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.cookie import CookieStorage
from unittest.mock import patch, MagicMock

from apps.technician_portal.admin import RepairAdmin
from apps.technician_portal.models import Repair, Technician, Customer, UnitRepairCount
from apps.tenants.models import Tenant


def _make_tenant(name="TestTenant161", owner=None):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=owner,
    )


def _make_user(username, email=None):
    return User.objects.create_user(
        username=username,
        email=email or f"{username}@example.com",
        password="testpass",
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
    """Create a Repair directly via QuerySet to skip Repair.save() pricing logic."""
    return Repair.all_objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number=unit_number,
        queue_status=status,
        cost=45.00,
    )


class BulkDeleteRepairsUnitRepairCountTest(TestCase):
    """Tests for CODE-161: UnitRepairCount decremented on bulk_delete_repairs."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RepairAdmin(Repair, self.site)
        self.factory = RequestFactory()

        self.owner = _make_user("owner161")
        self.tenant = _make_tenant(owner=self.owner)

        self.technician_user = _make_user("tech161")
        self.customer = _make_customer(self.tenant)
        self.technician = _make_technician(self.tenant, self.technician_user)

        # Superuser for admin actions
        self.superuser = _make_user("su161")
        self.superuser.is_staff = True
        self.superuser.is_superuser = True
        self.superuser.save()

    def _make_request(self):
        request = self.factory.post("/admin/")
        request.user = self.superuser
        # Django admin actions call message_user, which requires the messages
        # middleware storage backend to be set up on the request.
        setattr(request, '_messages', CookieStorage(request))
        return request

    def test_completed_repairs_decrement_unit_repair_count(self):
        """
        Deleting 2 COMPLETED repairs decrements UnitRepairCount by 2.

        Note: _make_repair uses Repair.all_objects.create() which calls
        Repair.save(), which increments UnitRepairCount for COMPLETED repairs.
        We force URC to a known baseline via update() after repair creation.
        """
        unit = "U-001"
        r1 = _make_repair(self.tenant, self.customer, self.technician, unit, "COMPLETED")
        r2 = _make_repair(self.tenant, self.customer, self.technician, unit, "COMPLETED")
        # Force URC to known value (5) regardless of what save() produced
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        ).update(repair_count=5)
        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        )

        qs = Repair.all_objects.filter(pk__in=[r1.pk, r2.pk])
        self.admin.bulk_delete_repairs(self._make_request(), qs)

        urc.refresh_from_db()
        self.assertEqual(urc.repair_count, 3)  # 5 - 2 = 3

    def test_non_completed_repairs_do_not_decrement(self):
        """
        Deleting non-COMPLETED repairs (PENDING, IN_PROGRESS) leaves
        UnitRepairCount unchanged — they never incremented it.
        """
        unit = "U-002"
        r1 = _make_repair(self.tenant, self.customer, self.technician, unit, "PENDING")
        r2 = _make_repair(self.tenant, self.customer, self.technician, unit, "IN_PROGRESS")
        # Force URC to a known value after repair creation
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        ).update(repair_count=2)
        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        )

        qs = Repair.all_objects.filter(pk__in=[r1.pk, r2.pk])
        self.admin.bulk_delete_repairs(self._make_request(), qs)

        urc.refresh_from_db()
        self.assertEqual(urc.repair_count, 2)  # Unchanged — PENDING/IN_PROGRESS don't affect URC

    def test_repair_count_clamped_at_zero(self):
        """
        Deleting more COMPLETED repairs than the count shows does not produce
        a negative repair_count; it clamps to 0.

        We simulate an out-of-sync state (count=1 but deleting 2 repairs)
        by forcing the URC count down after creation.
        """
        unit = "U-003"
        r1 = _make_repair(self.tenant, self.customer, self.technician, unit, "COMPLETED")
        r2 = _make_repair(self.tenant, self.customer, self.technician, unit, "COMPLETED")
        # Force count to 1 to simulate under-count / out-of-sync state
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        ).update(repair_count=1)
        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        )

        qs = Repair.all_objects.filter(pk__in=[r1.pk, r2.pk])
        self.admin.bulk_delete_repairs(self._make_request(), qs)

        urc.refresh_from_db()
        self.assertEqual(urc.repair_count, 0)  # Clamped at 0, not -1

    def test_missing_unit_repair_count_does_not_crash(self):
        """
        If UnitRepairCount doesn't exist for a deleted repair's unit,
        the action silently skips the decrement and doesn't raise.
        """
        unit = "U-MISSING"
        # No UnitRepairCount row for this unit
        r1 = _make_repair(self.tenant, self.customer, self.technician, unit, "COMPLETED")

        qs = Repair.all_objects.filter(pk=r1.pk)
        # Should not raise
        self.admin.bulk_delete_repairs(self._make_request(), qs)

        # Repair was deleted
        self.assertFalse(Repair.all_objects.filter(pk=r1.pk).exists())

    def test_multiple_units_decremented_independently(self):
        """
        Deleting repairs across multiple units decrements each UnitRepairCount
        independently.
        """
        unit_a = "UA-001"
        unit_b = "UB-001"
        r_a1 = _make_repair(self.tenant, self.customer, self.technician, unit_a, "COMPLETED")
        r_a2 = _make_repair(self.tenant, self.customer, self.technician, unit_a, "COMPLETED")
        r_b1 = _make_repair(self.tenant, self.customer, self.technician, unit_b, "COMPLETED")
        # Force known baselines
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number=unit_a
        ).update(repair_count=5)
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number=unit_b
        ).update(repair_count=3)
        urc_a = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit_a
        )
        urc_b = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit_b
        )

        qs = Repair.all_objects.filter(pk__in=[r_a1.pk, r_a2.pk, r_b1.pk])
        self.admin.bulk_delete_repairs(self._make_request(), qs)

        urc_a.refresh_from_db()
        urc_b.refresh_from_db()
        self.assertEqual(urc_a.repair_count, 3)  # 5 - 2
        self.assertEqual(urc_b.repair_count, 2)  # 3 - 1

    def test_invoiced_repairs_skipped_and_count_unchanged(self):
        """
        Repairs on active invoices are skipped by the action.
        Their UnitRepairCount should NOT be decremented.
        """
        from apps.billing.models import Invoice, InvoiceLineItem

        unit = "U-INV"
        repair = _make_repair(self.tenant, self.customer, self.technician, unit, "COMPLETED")
        # Force URC to known value (2) after Repair.save() may have incremented it
        UnitRepairCount.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        ).update(repair_count=2)
        urc = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit
        )

        # Create an active invoice referencing this repair
        invoice = Invoice.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            invoice_number="INV-161-TEST",
            status="SENT",
            subtotal=45.00,
            total=45.00,
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            repair=repair,
            description="Test",
            quantity=1,
            unit_price=45.00,
            amount=45.00,
        )

        qs = Repair.all_objects.filter(pk=repair.pk)
        self.admin.bulk_delete_repairs(self._make_request(), qs)

        # Repair should NOT be deleted (skipped)
        self.assertTrue(Repair.all_objects.filter(pk=repair.pk).exists())
        # UnitRepairCount should be unchanged
        urc.refresh_from_db()
        self.assertEqual(urc.repair_count, 2)
