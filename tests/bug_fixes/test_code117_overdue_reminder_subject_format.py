"""
CODE-117 Regression tests: process_overdue_invoices — reminder loop resilience
and overdue_reminder_subject template completeness.

Two bugs fixed:

1. The `.format()` call in `_send_overdue_reminder` only passed four kwargs
   (invoice_number, customer_name, amount_due, days_overdue) but the model's
   help_text advertises {total}, {due_date}, and {company_name} as valid
   placeholders. A custom subject containing {company_name} would raise
   KeyError.

2. The `process_overdue_invoices` per-invoice loop had no try/except. A single
   KeyError (or any exception) from `_send_overdue_reminder` would abort
   processing of all subsequent invoices for that tenant.

Fix: pass all advertised placeholders; wrap the per-invoice call in
try/except; fall back to the system default subject on malformed templates.
"""
import unittest
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock, call
import django
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rs_systems.settings.development')
django.setup()


class TestOverdueReminderSubjectFormat(unittest.TestCase):
    """Unit tests for _send_overdue_reminder subject template formatting."""

    def _make_invoice(self, invoice_number='INV-001', amount_due=Decimal('100.00'),
                      total=Decimal('108.00'), due_date=None):
        """Build a minimal mock invoice."""
        inv = MagicMock()
        inv.invoice_number = invoice_number
        inv.total = total
        inv.amount_paid = total - amount_due
        inv.amount_due = amount_due
        inv.due_date = due_date or date.today() - timedelta(days=7)
        inv.invoice_date = date.today() - timedelta(days=37)
        inv.tenant = MagicMock()
        inv.tenant.name = 'Test Glass Shop'
        inv.tenant_id = 1
        inv.internal_notes = ''
        inv.customer = MagicMock()
        inv.customer.email = 'fleet@example.com'
        inv.customer.name = 'Acme Fleet'
        return inv

    def _make_config(self, subject_template):
        config = MagicMock()
        config.overdue_reminder_subject = subject_template
        config.company_name = 'Test Glass Shop'
        config.company_phone = '555-0100'
        config.company_email = 'info@testglassshop.com'
        return config

    @patch('apps.billing.tasks.send_mail', return_value=1)
    def test_default_subject_template(self, mock_send):
        """Default template {invoice_number} renders correctly."""
        from apps.billing.tasks import _send_overdue_reminder

        inv = self._make_invoice()
        config = self._make_config('Reminder: Invoice #{invoice_number} is overdue')
        result = _send_overdue_reminder(inv, config, 7)

        self.assertTrue(result)
        mock_send.assert_called_once()
        subject = mock_send.call_args[1]['subject']
        self.assertIn('INV-001', subject)

    @patch('apps.billing.tasks.send_mail', return_value=1)
    def test_company_name_placeholder(self, mock_send):
        """{company_name} placeholder should render without KeyError."""
        from apps.billing.tasks import _send_overdue_reminder

        inv = self._make_invoice()
        config = self._make_config('Invoice #{invoice_number} from {company_name} is overdue')
        result = _send_overdue_reminder(inv, config, 7)

        self.assertTrue(result)
        subject = mock_send.call_args[1]['subject']
        self.assertIn('Test Glass Shop', subject)
        self.assertIn('INV-001', subject)

    @patch('apps.billing.tasks.send_mail', return_value=1)
    def test_total_placeholder(self, mock_send):
        """{total} placeholder should render without KeyError."""
        from apps.billing.tasks import _send_overdue_reminder

        inv = self._make_invoice(total=Decimal('108.00'))
        config = self._make_config('Invoice #{invoice_number} — total {total} overdue')
        result = _send_overdue_reminder(inv, config, 7)

        self.assertTrue(result)
        subject = mock_send.call_args[1]['subject']
        self.assertIn('108.00', subject)

    @patch('apps.billing.tasks.send_mail', return_value=1)
    def test_due_date_placeholder(self, mock_send):
        """{due_date} placeholder should render without KeyError."""
        from apps.billing.tasks import _send_overdue_reminder

        inv = self._make_invoice(due_date=date(2026, 3, 1))
        config = self._make_config('Invoice #{invoice_number} due {due_date}')
        result = _send_overdue_reminder(inv, config, 7)

        self.assertTrue(result)
        subject = mock_send.call_args[1]['subject']
        self.assertIn('03/01/2026', subject)

    @patch('apps.billing.tasks.send_mail', return_value=1)
    def test_malformed_template_falls_back_to_default(self, mock_send):
        """An unknown placeholder {unknown_key} should not raise; falls back to default subject."""
        from apps.billing.tasks import _send_overdue_reminder

        inv = self._make_invoice()
        config = self._make_config('Invoice #{invoice_number} {unknown_key} overdue')
        result = _send_overdue_reminder(inv, config, 7)

        # Reminder still sent (fallback subject used)
        self.assertTrue(result)
        subject = mock_send.call_args[1]['subject']
        # Default fallback subject contains the invoice number
        self.assertIn('INV-001', subject)


class TestProcessOverdueInvoicesLoopResilient(unittest.TestCase):
    """
    Verify that process_overdue_invoices() continues processing remaining
    invoices even when _send_overdue_reminder raises for one of them.
    """

    @patch('apps.billing.tasks._send_overdue_reminder')
    @patch('apps.billing.tasks.Tenant')
    @patch('apps.billing.tasks.BillingConfig')
    @patch('apps.billing.tasks.Invoice')
    def test_reminder_exception_does_not_abort_loop(
        self, mock_Invoice, mock_BillingConfig, mock_Tenant, mock_send_reminder
    ):
        """
        If _send_overdue_reminder raises for invoice #1, invoice #2 must still
        be processed (loop continues rather than aborting).
        """
        from apps.billing.tasks import process_overdue_invoices

        today = date.today()

        # --- Tenant setup ---
        mock_tenant = MagicMock()
        mock_tenant.id = 1
        mock_tenant.slug = 'test-shop'
        mock_tenant.is_active = True
        mock_Tenant.objects.filter.return_value = [mock_tenant]

        # --- BillingConfig setup ---
        mock_config = MagicMock()
        mock_config.overdue_reminder_enabled = True
        mock_config.overdue_reminder_days = '7'
        mock_BillingConfig.get_for_tenant.return_value = mock_config

        # --- Invoice setup: two overdue invoices, due 7 days ago ---
        inv1 = MagicMock()
        inv1.invoice_number = 'INV-001'
        inv1.id = 1
        inv1.due_date = today - timedelta(days=7)
        inv1.last_reminder_days_overdue = None  # C3 tier tracking: none sent yet

        inv2 = MagicMock()
        inv2.invoice_number = 'INV-002'
        inv2.id = 2
        inv2.due_date = today - timedelta(days=7)
        inv2.last_reminder_days_overdue = None

        # filter().update() for overdue status update — return 0 so we don't
        # conflate with the reminder count.
        mock_filter_qs = MagicMock()
        mock_filter_qs.update.return_value = 0
        mock_filter_qs.select_related.return_value = [inv1, inv2]
        mock_Invoice.objects.filter.return_value = mock_filter_qs

        # _send_overdue_reminder raises on inv1, succeeds on inv2
        def _side_effect(invoice, config, days_overdue):
            if invoice.id == 1:
                raise KeyError('company_name')
            return True

        mock_send_reminder.side_effect = _side_effect

        result = process_overdue_invoices()

        # inv2 must have been processed despite inv1 raising
        self.assertEqual(mock_send_reminder.call_count, 2)
        # One successful reminder (inv2)
        self.assertEqual(result['reminders_sent'], 1)


if __name__ == '__main__':
    unittest.main()
