"""
CODE-197: InvoiceLineItemInline repair_date/unit_number not shown in admin.

repair_date and unit_number were listed in InvoiceLineItemInline.readonly_fields
but NOT in InvoiceLineItemInline.fields.  When 'fields' is explicitly set on a
TabularInline, Django only renders fields that appear in that list — anything
in readonly_fields that isn't also in fields is silently ignored.  Admins
viewing an invoice could not see the repair date or unit number for each line
item without clicking through to the individual repair record.

Fix: Add 'unit_number' and 'repair_date' to the fields list so they render in
the tabular inline alongside the other line item columns.
"""

from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.test import TestCase, RequestFactory

from apps.billing.admin import InvoiceLineItemInline
from apps.billing.models import Invoice, InvoiceLineItem, Payment
from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Repair, Technician
from django.contrib.auth.models import User


class InvoiceLineItemInlineFieldsTest(TestCase):
    """
    Verify that InvoiceLineItemInline.fields includes 'repair_date' and
    'unit_number' so they are rendered in the admin tabular inline.
    """

    def test_repair_date_in_fields(self):
        """repair_date must appear in InvoiceLineItemInline.fields."""
        inline = InvoiceLineItemInline(Invoice, AdminSite())
        self.assertIn(
            'repair_date',
            inline.fields,
            "repair_date must be in InvoiceLineItemInline.fields — "
            "without it Django silently omits the column even though it is "
            "listed in readonly_fields. (CODE-197)"
        )

    def test_unit_number_in_fields(self):
        """unit_number must appear in InvoiceLineItemInline.fields."""
        inline = InvoiceLineItemInline(Invoice, AdminSite())
        self.assertIn(
            'unit_number',
            inline.fields,
            "unit_number must be in InvoiceLineItemInline.fields — "
            "without it Django silently omits the column even though it is "
            "listed in readonly_fields. (CODE-197)"
        )

    def test_repair_date_and_unit_number_in_readonly_fields(self):
        """repair_date and unit_number must remain readonly (they are denormalized copies)."""
        inline = InvoiceLineItemInline(Invoice, AdminSite())
        self.assertIn('repair_date', inline.readonly_fields)
        self.assertIn('unit_number', inline.readonly_fields)

    def test_all_fields_are_valid_on_model_or_callable(self):
        """
        Every entry in InvoiceLineItemInline.fields must be either a real
        InvoiceLineItem field/property or a callable defined on the inline class.
        This catches future typos like 'repair_dates' or 'unit_no'.
        """
        from django.db import models as djmodels

        inline = InvoiceLineItemInline(Invoice, AdminSite())
        model_field_names = {f.name for f in InvoiceLineItem._meta.get_fields()}

        for field_name in inline.fields:
            is_model_field = field_name in model_field_names
            is_inline_method = hasattr(inline, field_name) and callable(getattr(inline, field_name))
            self.assertTrue(
                is_model_field or is_inline_method,
                f"'{field_name}' in InvoiceLineItemInline.fields is neither a "
                f"model field nor a method on the inline class. Possible typo?"
            )
