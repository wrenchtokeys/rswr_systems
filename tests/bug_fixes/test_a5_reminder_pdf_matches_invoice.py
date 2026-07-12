"""
Regression tests for A5 (Remediation Plan 2026-07-09):
Reminder emails attached a regenerated, mismatched PDF.

Root cause:
    ReminderService.send_reminder() rebuilt the PDF via
    InvoiceService.generate_invoice() WITHOUT the invoice_number /
    invoice_date / invoice_status overrides. The attached PDF carried a
    freshly minted invoice number (INV-<cust>-<timestamp>), today's date,
    and totals recomputed from current rates — none matching the invoice
    named in the reminder's email body.

    Worse: for an invoice with no repair-backed line items
    (replacement-only), repair_ids was None and the call site passed NO
    date filter, so get_completed_repairs ran UNBOUNDED and the PDF billed
    every completed repair in the customer's history. (Verified: with
    repair_ids=None and no start_date, get_completed_repairs applies no
    date restriction.)

Fix:
    Same root cause as A4 — send_reminder() now uses
    InvoiceService.generate_invoice_from_record(invoice), rendering the
    stored invoice number, date, line items, and totals.

Tests:
    A. Overdue reminder for INV-A5-001 (customer has 5 unrelated completed
       repairs): PDF carries the stored number and total; none of the
       unrelated repairs appear.
    B. Replacement-only invoice with rich repair history: reminder PDF
       contains the single replacement line item, not the history.
"""

import io
import re
from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem, TaxRate
from apps.billing.services.reminder_service import ReminderService
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


def _pdf_text(pdf_bytes):
    """All PDF text with whitespace stripped (layout wraps values mid-word)."""
    from PyPDF2 import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw = "\n".join((page.extract_text() or '') for page in reader.pages)
    return re.sub(r'\s+', '', raw)


class ReminderPdfMatchesInvoiceTests(TestCase):
    """A5: the reminder's attached PDF must be THE invoice, not a fresh one."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='A5 Test Shop',
            email='owner_a5@test.com',
            password='testpass123!',
            first_name='AfiveOwner',
            last_name='Owner',
        )
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=result['user'], tenant=self.tenant)

        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='A5 Fleet',
            customer_type='FLEET',
            email='ap@a5fleet.test',
        )
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

        # 5 old completed repairs that must never appear in a reminder PDF
        for i in range(5):
            r = Repair.objects.create(
                tenant=self.tenant,
                customer=self.customer,
                technician=self.technician,
                unit_number=f'HISTORY-UNIT-{i}',
                queue_status='COMPLETED',
            )
            r.service_date = timezone.now() - timedelta(days=100 + i)
            r.save(update_fields=['service_date'])

    def _make_overdue_invoice(self, number='INV-A5-001'):
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=number,
            status='OVERDUE',
            subtotal=Decimal('275.00'),
            total=Decimal('275.00'),
            invoice_date=(timezone.now() - timedelta(days=60)).date(),
            due_date=(timezone.now() - timedelta(days=30)).date(),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            repair=None,
            description='Windshield Replacement - Kenworth T680',
            quantity=1,
            unit_price=Decimal('275.00'),
            amount=Decimal('275.00'),
            unit_number='KW-T680-7',
        )
        return invoice

    def _reminder_pdf_text(self):
        self.assertEqual(len(mail.outbox), 1, "exactly one reminder email must be sent")
        pdf_attachments = [a for a in mail.outbox[0].attachments if a[2] == 'application/pdf']
        self.assertEqual(len(pdf_attachments), 1, "reminder must carry exactly one PDF")
        return _pdf_text(pdf_attachments[0][1])

    def test_a_reminder_pdf_carries_stored_invoice(self):
        invoice = self._make_overdue_invoice()

        result = ReminderService(tenant=self.tenant).send_reminder(invoice, 'overdue_30d')
        self.assertTrue(result['success'], f"reminder failed: {result}")

        text = self._reminder_pdf_text()
        self.assertIn('INV-A5-001', text, "PDF must carry the STORED invoice number")
        self.assertIn('275.00', text, "PDF must carry the STORED total")
        # The stored invoice date (60 days ago), not today
        stored_date = (timezone.now() - timedelta(days=60)).strftime('%B')
        self.assertIn(stored_date.replace(' ', ''), text, "PDF must carry the stored invoice date's month")
        for i in range(5):
            self.assertNotIn(
                f'HISTORY-UNIT-{i}', text,
                "PDF must not bill the customer's unrelated repair history",
            )
        # A freshly-minted number would look like INV-<id>-<14-digit timestamp>
        self.assertNotRegex(
            text, rf'INV-{self.customer.id}-\d{{14}}',
            "PDF must not carry a freshly generated invoice number",
        )

    def test_b_process_overdue_reminders_uses_stored_invoice(self):
        """The cron entry point must go through the same record path."""
        invoice = self._make_overdue_invoice(number='INV-A5-002')
        # Align due_date with a reminder tier (7 days overdue)
        invoice.due_date = (timezone.now() - timedelta(days=7)).date()
        invoice.save(update_fields=['due_date'])

        results = ReminderService(tenant=self.tenant).process_overdue_reminders()
        self.assertEqual(results['sent'], 1, f"expected 1 reminder: {results}")

        text = self._reminder_pdf_text()
        self.assertIn('INV-A5-002', text)
        for i in range(5):
            self.assertNotIn(f'HISTORY-UNIT-{i}', text)
