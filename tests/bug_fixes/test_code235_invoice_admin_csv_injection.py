"""
CODE-235 — CSV formula injection in InvoiceAdmin.export_csv

The InvoiceAdmin's 'Export selected invoices as CSV' action wrote
user-controlled strings (customer name, invoice number, payment terms)
directly to CSV cells without sanitisation.  A customer name like
'=HYPERLINK("http://evil.com","Click")' would execute as a spreadsheet
formula when opened in Excel, LibreOffice, or Google Sheets.

CODE-214 fixed this in RepairAdmin, CustomerAdmin, and the AR aging
export — but the InvoiceAdmin export_csv action was missed.

Fix: apply _csv_safe() to all user-controlled string columns in
InvoiceAdmin.export_csv (billing/admin.py).
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from decimal import Decimal
from datetime import date

from apps.billing.admin import InvoiceAdmin, _csv_safe
from apps.billing.models import Invoice

User = get_user_model()


class CsvSafeTests(TestCase):
    """Unit tests for the _csv_safe helper."""

    def test_formula_prefix_equals(self):
        self.assertEqual(_csv_safe('=SUM(A1:A10)'), "'=SUM(A1:A10)")

    def test_formula_prefix_plus(self):
        self.assertEqual(_csv_safe('+cmd|OPEN'), "'+cmd|OPEN")

    def test_formula_prefix_minus(self):
        self.assertEqual(_csv_safe('-1+1'), "'-1+1")

    def test_formula_prefix_at(self):
        self.assertEqual(_csv_safe('@SUM(A1:A10)'), "'@SUM(A1:A10)")

    def test_formula_prefix_tab(self):
        self.assertEqual(_csv_safe('\tmalicious'), "'\tmalicious")

    def test_formula_prefix_cr(self):
        self.assertEqual(_csv_safe('\rmalicious'), "'\rmalicious")

    def test_safe_string_unchanged(self):
        self.assertEqual(_csv_safe('Acme Trucking'), 'Acme Trucking')

    def test_empty_string_unchanged(self):
        self.assertEqual(_csv_safe(''), '')

    def test_non_string_passthrough(self):
        self.assertEqual(_csv_safe(42), 42)
        self.assertEqual(_csv_safe(None), None)
        self.assertEqual(_csv_safe(Decimal('100.00')), Decimal('100.00'))

    def test_hyperlink_injection(self):
        payload = '=HYPERLINK("http://evil.com","Click")'
        result = _csv_safe(payload)
        self.assertTrue(result.startswith("'"))
        self.assertIn('HYPERLINK', result)


class InvoiceAdminExportCsvTests(TestCase):
    """
    Integration tests for InvoiceAdmin.export_csv with malicious data.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant
        from core.models import Customer

        cls.superuser = User.objects.create_superuser(
            username='admin_csv_test',
            email='admin_csv@example.com',
            password='testpass123',
        )
        cls.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop',
            plan='professional',
            owner=cls.superuser,
        )
        cls.customer = Customer.objects.create(
            tenant=cls.tenant,
            name='=HYPERLINK("http://evil.com","Click")',
            email='evil@example.com',
        )
        cls.invoice = Invoice.objects.create(
            customer=cls.customer,
            tenant=cls.tenant,
            invoice_number='+CMD|OPEN',
            invoice_date=date(2026, 3, 29),
            due_date=date(2026, 4, 28),
            payment_terms='-NET30',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            status='SENT',
        )
    def test_export_csv_sanitises_customer_name(self):
        """Customer names with formula prefixes must be escaped in CSV output."""
        import csv
        import io

        site = AdminSite()
        admin_instance = InvoiceAdmin(Invoice, site)
        factory = RequestFactory()
        request = factory.get('/admin/billing/invoice/')
        request.user = self.superuser

        qs = Invoice.objects.filter(pk=self.invoice.pk)
        response = admin_instance.export_csv(request, qs)

        content = response.content.decode('utf-8')
        # Parse the CSV to check the actual cell value
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        # Row 0 is headers, row 1 is data
        data_row = rows[1]
        customer_cell = data_row[1]  # Customer is column index 1
        # The cell must start with ' to neutralise formula execution
        self.assertTrue(
            customer_cell.startswith("'"),
            f"Customer cell should start with quote prefix, got: {customer_cell!r}"
        )

    def test_export_csv_sanitises_invoice_number(self):
        """Invoice numbers with formula prefixes must be escaped."""
        site = AdminSite()
        admin_instance = InvoiceAdmin(Invoice, site)
        factory = RequestFactory()
        request = factory.get('/admin/billing/invoice/')
        request.user = self.superuser

        qs = Invoice.objects.filter(pk=self.invoice.pk)
        response = admin_instance.export_csv(request, qs)

        content = response.content.decode('utf-8')
        # +CMD|OPEN should be escaped
        self.assertNotIn('+CMD|OPEN', content.replace("'+CMD|OPEN", ''))
        self.assertIn("'+CMD|OPEN", content)

    def test_export_csv_sanitises_payment_terms(self):
        """Payment terms with formula prefixes must be escaped."""
        site = AdminSite()
        admin_instance = InvoiceAdmin(Invoice, site)
        factory = RequestFactory()
        request = factory.get('/admin/billing/invoice/')
        request.user = self.superuser

        qs = Invoice.objects.filter(pk=self.invoice.pk)
        response = admin_instance.export_csv(request, qs)

        content = response.content.decode('utf-8')
        self.assertIn("'-NET30", content)

    def test_export_csv_safe_values_unchanged(self):
        """Normal string values pass through without modification."""
        from core.models import Customer

        safe_customer = Customer.objects.create(
            tenant=self.tenant,
            name='Acme Trucking',
            email='acme@example.com',
        )
        safe_invoice = Invoice.objects.create(
            customer=safe_customer,
            tenant=self.tenant,
            invoice_number='INV-0042',
            invoice_date=date(2026, 3, 29),
            due_date=date(2026, 4, 28),
            payment_terms='NET30',
            subtotal=Decimal('200.00'),
            total=Decimal('200.00'),
            status='SENT',
        )

        site = AdminSite()
        admin_instance = InvoiceAdmin(Invoice, site)
        factory = RequestFactory()
        request = factory.get('/admin/billing/invoice/')
        request.user = self.superuser

        qs = Invoice.objects.filter(pk=safe_invoice.pk)
        response = admin_instance.export_csv(request, qs)

        content = response.content.decode('utf-8')
        self.assertIn('Acme Trucking', content)
        self.assertIn('INV-0042', content)
        self.assertIn('NET30', content)
