"""
Regression tests for CODE-174: ReplacementAdmin missing delete_queryset() override.

Bug: ReplacementAdmin had no delete_queryset() override. Django's default admin
'Delete selected' action calls delete_queryset() → QuerySet.delete(), which raises
ProtectedError for any Replacement with an InvoiceLineItem (InvoiceLineItem.replacement
is on_delete=PROTECT).

Additionally, even for replacements without invoice line items, the default path
would silently succeed without any safety checks — consistent with the class of
bugs fixed in CODE-167 (RepairAdmin) and CODE-170 (InvoiceAdmin).

Fix: Added delete_queryset() override to ReplacementAdmin that:
  1. Skips replacements linked to active invoices (DRAFT/SENT/PARTIAL/PAID)
  2. Deletes safe replacements instance-by-instance
  3. Reports deleted/skipped counts to the admin user

(CODE-174)
"""

from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.technician_portal.admin import ReplacementAdmin
from apps.technician_portal.models import Customer, Technician, Replacement
from apps.billing.models import Invoice, InvoiceLineItem
from apps.tenants.models import Tenant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser(username):
    return User.objects.create_superuser(
        username=username,
        email=f"{username}@example.com",
        password="testpass",
    )


def _make_tenant(name, owner=None):
    if owner is None:
        owner = User.objects.create_user(
            username=f"owner_{name.lower().replace(' ', '_')}",
            email=f"owner_{name.lower().replace(' ', '_')}@example.com",
            password="testpass",
        )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=owner,
    )


def _make_customer(tenant, name="Test Customer"):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='fleet',
    )


def _make_technician(tenant, username):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass",
    )
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        phone_number="555-0000",
    )


def _make_replacement(tenant, customer, technician, status='COMPLETED'):
    return Replacement.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT001',
        glass_position='WINDSHIELD',
        parts_cost=Decimal('150.00'),
        labor_cost=Decimal('50.00'),
        cost=Decimal('200.00'),
        queue_status=status,
    )


def _make_invoice(tenant, customer, status='SENT'):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-{customer.id}-{status}-{id(customer)}',
        status=status,
        total=Decimal('200.00'),
        amount_paid=Decimal('0.00'),
    )


def _make_replacement_line_item(invoice, replacement):
    return InvoiceLineItem.objects.create(
        invoice=invoice,
        description="Windshield replacement",
        quantity=1,
        unit_price=Decimal('200.00'),
        amount=Decimal('200.00'),
        replacement=replacement,
    )


def _make_admin_request(superuser):
    from django.test import RequestFactory as DjangoRF
    from django.contrib.messages.storage.fallback import FallbackStorage
    rf = DjangoRF()
    request = rf.post('/')
    request.user = superuser
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class ReplacementAdminDeleteQuerysetTest(TestCase):
    """Tests for ReplacementAdmin.delete_queryset() override (CODE-174)."""

    def setUp(self):
        self.superuser = _make_superuser('admin_code174')
        self.tenant = _make_tenant('Shop CODE-174', self.superuser)
        self.customer = _make_customer(self.tenant)
        self.technician = _make_technician(self.tenant, 'tech_code174')
        self.site = AdminSite()
        self.admin = ReplacementAdmin(Replacement, self.site)

    def _make_request(self):
        return _make_admin_request(self.superuser)

    def test_delete_queryset_attribute_exists(self):
        """ReplacementAdmin must define delete_queryset, not use Django's default."""
        self.assertTrue(
            hasattr(ReplacementAdmin, 'delete_queryset'),
            "ReplacementAdmin is missing delete_queryset() override (CODE-174)."
        )
        # Ensure it's actually overridden (not inherited from ModelAdmin)
        from django.contrib import admin as django_admin
        self.assertNotEqual(
            ReplacementAdmin.delete_queryset,
            django_admin.ModelAdmin.delete_queryset,
            "ReplacementAdmin.delete_queryset should be overridden, not inherited."
        )

    def test_safe_replacement_is_deleted(self):
        """Replacements with no invoice line items are deleted normally."""
        r = _make_replacement(self.tenant, self.customer, self.technician)
        qs = Replacement.objects.filter(pk=r.pk)
        self.admin.delete_queryset(self._make_request(), qs)
        self.assertFalse(Replacement.objects.filter(pk=r.pk).exists())

    def test_invoiced_replacement_is_protected(self):
        """Replacements linked to active invoices are NOT deleted."""
        r = _make_replacement(self.tenant, self.customer, self.technician)
        inv = _make_invoice(self.tenant, self.customer, status='SENT')
        _make_replacement_line_item(inv, r)

        qs = Replacement.objects.filter(pk=r.pk)
        self.admin.delete_queryset(self._make_request(), qs)

        # Replacement must still exist
        self.assertTrue(Replacement.objects.filter(pk=r.pk).exists())

    def test_cancelled_invoice_replacement_is_still_protected(self):
        """
        Replacements on CANCELLED invoices are ALSO skipped.

        InvoiceLineItem.replacement uses on_delete=PROTECT — Django will raise
        ProtectedError for ANY replacement with an existing InvoiceLineItem, even
        if the associated invoice is CANCELLED. Attempting instance.delete() would
        crash. Therefore our override must also protect these rows (the CANCELLED
        line item should be cleaned up by the admin separately first).
        """
        r = _make_replacement(self.tenant, self.customer, self.technician)
        inv = _make_invoice(self.tenant, self.customer, status='CANCELLED')
        _make_replacement_line_item(inv, r)

        qs = Replacement.objects.filter(pk=r.pk)
        # delete_queryset must not crash AND must leave the replacement in place
        # (because the PROTECT FK would crash if we tried to delete it)
        try:
            self.admin.delete_queryset(self._make_request(), qs)
        except Exception as e:
            self.fail(f"delete_queryset raised {type(e).__name__}: {e}")
        # The replacement is still there (PROTECT blocked deletion)
        self.assertTrue(Replacement.objects.filter(pk=r.pk).exists())

    def test_mixed_batch_safe_deleted_invoiced_skipped(self):
        """Only safe replacements deleted; invoiced ones survive."""
        safe = _make_replacement(self.tenant, self.customer, self.technician)
        invoiced = _make_replacement(self.tenant, self.customer, self.technician)
        inv = _make_invoice(self.tenant, self.customer, status='PAID')
        _make_replacement_line_item(inv, invoiced)

        qs = Replacement.objects.filter(pk__in=[safe.pk, invoiced.pk])
        self.admin.delete_queryset(self._make_request(), qs)

        self.assertFalse(Replacement.objects.filter(pk=safe.pk).exists(),
                         "Safe replacement should have been deleted.")
        self.assertTrue(Replacement.objects.filter(pk=invoiced.pk).exists(),
                        "Invoiced replacement should have been protected.")

    def test_draft_invoice_replacement_is_protected(self):
        """Replacements on DRAFT invoices (pre-sent) are also protected."""
        r = _make_replacement(self.tenant, self.customer, self.technician)
        inv = _make_invoice(self.tenant, self.customer, status='DRAFT')
        _make_replacement_line_item(inv, r)

        qs = Replacement.objects.filter(pk=r.pk)
        self.admin.delete_queryset(self._make_request(), qs)
        self.assertTrue(Replacement.objects.filter(pk=r.pk).exists())

    def test_partial_invoice_replacement_is_protected(self):
        """Replacements on PARTIAL (partially paid) invoices are protected."""
        r = _make_replacement(self.tenant, self.customer, self.technician)
        inv = _make_invoice(self.tenant, self.customer, status='PARTIAL')
        _make_replacement_line_item(inv, r)

        qs = Replacement.objects.filter(pk=r.pk)
        self.admin.delete_queryset(self._make_request(), qs)
        self.assertTrue(Replacement.objects.filter(pk=r.pk).exists())

    def test_no_protectederror_on_default_delete_selected(self):
        """
        Calling delete_queryset (as Django would for 'Delete selected') must
        NOT raise ProtectedError even when invoiced replacements are present.
        """
        from django.db.models.deletion import ProtectedError
        r = _make_replacement(self.tenant, self.customer, self.technician)
        inv = _make_invoice(self.tenant, self.customer, status='SENT')
        _make_replacement_line_item(inv, r)

        qs = Replacement.objects.filter(pk=r.pk)
        try:
            self.admin.delete_queryset(self._make_request(), qs)
        except ProtectedError:
            self.fail(
                "delete_queryset() raised ProtectedError — the override is not "
                "filtering out invoiced replacements before calling .delete()."
            )

    def test_empty_queryset_handled_gracefully(self):
        """An empty queryset should not crash and report 0 deleted."""
        qs = Replacement.objects.none()
        # Should not raise
        self.admin.delete_queryset(self._make_request(), qs)
