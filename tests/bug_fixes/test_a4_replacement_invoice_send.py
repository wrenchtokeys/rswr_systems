"""
Regression tests for A4 (Remediation Plan 2026-07-09):
Replacement-only / manual invoices could never be sent, or sent the wrong PDF.

Root cause:
    The PDF builder sourced line items exclusively from completed REPAIRS.
    owner_send_invoice passed repair_ids=None whenever the invoice had no
    repair-backed line items — exactly the case for replacement-only invoices
    created by _create_batch_invoice. With repair_ids=None,
    send_invoice_email fell back to a 30-day completed-repair lookback:

    - Customer has NO recent repairs -> "No completed repairs found for
      invoicing" -> the invoice is stuck in DRAFT forever. The shop cannot
      bill for a windshield replacement.
    - Customer HAS recent repairs -> the emailed PDF contains those
      unrelated repairs and their amounts, bearing no relation to the
      invoice being sent — and the invoice is then marked SENT.

Fix:
    InvoiceService.build_invoice_data_from_record() /
    generate_invoice_from_record() render a PDF from the Invoice's OWN line
    items and stored totals. send_invoice_email(invoice=...) uses that path
    whenever an Invoice record is provided — which, in owner_send_invoice,
    is always. The repair-lookback path remains only for generating NEW
    invoices.

Tests:
    A. Replacement-only invoice + unrelated recent repair: sends, PDF shows
       the invoice's own line item and total, NOT the unrelated repair.
    B. Replacement-only invoice + NO repairs at all: still sends (was stuck
       in DRAFT forever).
    C. Repair-backed invoice still works through the record path.
"""

import io
from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem, TaxRate
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


def _pdf_text(pdf_bytes):
    """
    Extract all text from a PDF for content assertions.

    Returns the text with ALL whitespace stripped, because the PDF layout
    wraps long values (e.g. unit numbers) across lines mid-word. Callers
    must assert against whitespace-free needles.
    """
    import re
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw = "\n".join((page.extract_text() or '') for page in reader.pages)
    return re.sub(r'\s+', '', raw)


class ReplacementInvoiceSendTests(TestCase):
    """A4: sending an existing invoice must render the invoice itself."""

    def setUp(self):
        self.client = Client()

        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='A4 Test Shop',
            email='owner_a4@test.com',
            password='testpass123!',
            first_name='AfourOwner',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='A4 Fleet',
            customer_type='FLEET',
            email='billing@a4fleet.test',
        )
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

    def _make_unrelated_repair(self):
        """A completed repair from 5 days ago that must NOT leak into the PDF."""
        repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNRELATED-UNIT-999',
            queue_status='COMPLETED',
        )
        repair.service_date = timezone.now() - timedelta(days=5)
        repair.save(update_fields=['service_date'])
        return repair

    def _make_replacement_invoice(self):
        """Replacement-only invoice: line items with repair=None."""
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-A4-REPL-001',
            status='DRAFT',
            subtotal=Decimal('350.00'),
            total=Decimal('350.00'),
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            repair=None,
            description='Windshield Replacement - 2020 Ford F-150',
            quantity=1,
            unit_price=Decimal('350.00'),
            amount=Decimal('350.00'),
            unit_number='REPL-UNIT-1',
        )
        return invoice

    def _send(self, invoice):
        return self.client.post(reverse('owner_send_invoice', args=[invoice.id]))

    def _sent_pdf_text(self):
        self.assertEqual(len(mail.outbox), 1, "exactly one invoice email must be sent")
        pdf_attachments = [a for a in mail.outbox[0].attachments if a[2] == 'application/pdf']
        self.assertEqual(len(pdf_attachments), 1, "invoice email must carry exactly one PDF")
        return _pdf_text(pdf_attachments[0][1])

    def test_a_replacement_invoice_sends_own_line_items(self):
        self._make_unrelated_repair()
        invoice = self._make_replacement_invoice()

        self._send(invoice)

        invoice.refresh_from_db()
        self.assertEqual(
            invoice.status, 'SENT',
            "Replacement-only invoice must be sendable",
        )

        text = self._sent_pdf_text()
        self.assertIn('INV-A4-REPL-001', text, "PDF must carry the stored invoice number")
        self.assertIn('WindshieldReplacement', text, "PDF must contain the invoice's own line item")
        self.assertIn('350.00', text, "PDF total must equal the invoice total")
        self.assertNotIn(
            'UNRELATED-UNIT-999', text,
            "PDF must NOT contain the customer's unrelated recent repair",
        )

    def test_b_replacement_invoice_sends_with_no_repair_history(self):
        # No repairs at all for this customer — the old fallback found
        # nothing and left the invoice stuck in DRAFT forever.
        invoice = self._make_replacement_invoice()

        self._send(invoice)

        invoice.refresh_from_db()
        self.assertEqual(
            invoice.status, 'SENT',
            "An invoice with no repair-backed line items must still send "
            "even when the customer has no repair history",
        )
        text = self._sent_pdf_text()
        self.assertIn('INV-A4-REPL-001', text)
        self.assertIn('WindshieldReplacement', text)

    def test_c_repair_backed_invoice_still_sends_correctly(self):
        repair = self._make_unrelated_repair()  # here it IS the invoiced repair
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-A4-REP-002',
            status='DRAFT',
            subtotal=repair.cost,
            total=repair.total_with_tax,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            repair=repair,
            description='Windshield chip repair',
            quantity=1,
            unit_price=repair.cost,
            amount=repair.cost,
            unit_number=repair.unit_number,
        )

        self._send(invoice)

        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')
        text = self._sent_pdf_text()
        self.assertIn('INV-A4-REP-002', text)
        self.assertIn('UNRELATED-UNIT-999', text, "the invoiced repair's unit must appear")
