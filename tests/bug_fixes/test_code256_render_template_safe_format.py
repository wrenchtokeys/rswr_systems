"""
CODE-256: ReminderService._render_template() crashes on malformed user templates

ReminderService._render_template() used bare str.format() on user-editable
reminder email templates.  If a shop owner included a stray "{" or an unknown
placeholder like "{foo}", the method would raise KeyError/ValueError.

While the immediate caller at line 83 wrapped the call in `except Exception: pass`,
this had two problems:
1. The custom template failure was completely silent — no log, no warning.
   Shop owners had no idea their custom template was being ignored.
2. Any future caller of _render_template() would crash without protection.

Fix: Wrap the .format() call in a try/except that catches KeyError, IndexError,
and ValueError (same pattern as invoice_email_service.py and billing/tasks.py),
logs a warning, and returns '' so callers fall back to the default template.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.billing.services.reminder_service import ReminderService


def _make_mock_invoice(tenant=None, days_overdue=5):
    """Create a mock invoice suitable for _render_template()."""
    invoice = MagicMock()
    invoice.customer.name = 'EOS Trucking'
    invoice.invoice_number = 'INV-20260401-001'
    invoice.total = Decimal('250.00')
    invoice.amount_due = Decimal('250.00')
    invoice.due_date = date.today() - timedelta(days=days_overdue)
    invoice.tenant = tenant
    return invoice


def _make_mock_tenant(pk=1, name='Test Shop'):
    tenant = MagicMock()
    tenant.pk = pk
    tenant.name = name
    return tenant


class RenderTemplateTests(TestCase):
    """Tests for ReminderService._render_template() safe formatting."""

    def test_valid_template_renders_correctly(self):
        """A well-formed template should render with all placeholders filled."""
        tenant = _make_mock_tenant()
        svc = ReminderService(tenant=tenant)
        invoice = _make_mock_invoice(tenant=tenant)

        template = (
            "Dear {customer_name}, invoice {invoice_number} for {total} "
            "is {days_overdue} days overdue. Balance: {amount_due}. "
            "Due: {due_date}. — {company_name}"
        )
        # Patch BillingConfig.get_for_tenant to return a config with company_name
        with patch('apps.billing.models.BillingConfig.get_for_tenant') as mock_config:
            mock_config.return_value = MagicMock(company_name='Test Shop')
            result = svc._render_template(template, invoice)

        self.assertIn('EOS Trucking', result)
        self.assertIn('INV-20260401-001', result)
        self.assertIn('$250.00', result)
        self.assertIn('Test Shop', result)
        self.assertNotEqual(result, '')

    def test_unknown_placeholder_returns_empty_string(self):
        """A template with an unknown {placeholder} should not crash."""
        tenant = _make_mock_tenant()
        svc = ReminderService(tenant=tenant)
        invoice = _make_mock_invoice(tenant=tenant)

        # {unknown_field} is not a valid placeholder
        template = "Dear {customer_name}, your {unknown_field} is ready."
        with patch('apps.billing.models.BillingConfig.get_for_tenant') as mock_config:
            mock_config.return_value = MagicMock(company_name='Test Shop')
            result = svc._render_template(template, invoice)

        # Should return empty string (fallback) instead of crashing
        self.assertEqual(result, '')

    def test_stray_brace_returns_empty_string(self):
        """A template with a stray '{' should not crash with ValueError."""
        tenant = _make_mock_tenant()
        svc = ReminderService(tenant=tenant)
        invoice = _make_mock_invoice(tenant=tenant)

        # Stray brace causes ValueError in str.format()
        template = "Dear {customer_name}, please pay { immediately."
        with patch('apps.billing.models.BillingConfig.get_for_tenant') as mock_config:
            mock_config.return_value = MagicMock(company_name='Test Shop')
            result = svc._render_template(template, invoice)

        self.assertEqual(result, '')

    def test_malformed_template_logs_warning(self):
        """A malformed template should log a warning for debugging."""
        tenant = _make_mock_tenant()
        svc = ReminderService(tenant=tenant)
        invoice = _make_mock_invoice(tenant=tenant)

        template = "Bad template: {nonexistent_field}"
        with patch('apps.billing.models.BillingConfig.get_for_tenant') as mock_config:
            mock_config.return_value = MagicMock(company_name='Test Shop')
            with self.assertLogs('apps.billing.services.reminder_service', level='WARNING') as cm:
                result = svc._render_template(template, invoice)

        self.assertEqual(result, '')
        self.assertTrue(any('Malformed reminder_email_template' in msg for msg in cm.output))

    def test_empty_template_returns_empty_string(self):
        """An empty template string should return empty without error."""
        tenant = _make_mock_tenant()
        svc = ReminderService(tenant=tenant)
        invoice = _make_mock_invoice(tenant=tenant)

        with patch('apps.billing.models.BillingConfig.get_for_tenant') as mock_config:
            mock_config.return_value = MagicMock(company_name='Test Shop')
            result = svc._render_template('', invoice)

        self.assertEqual(result, '')

    def test_index_error_from_positional_placeholder(self):
        """A template with positional {0} should not crash with IndexError."""
        tenant = _make_mock_tenant()
        svc = ReminderService(tenant=tenant)
        invoice = _make_mock_invoice(tenant=tenant)

        # {0} causes IndexError when .format() is called with keyword args only
        template = "Dear {customer_name}, your invoice {0} is due."
        with patch('apps.billing.models.BillingConfig.get_for_tenant') as mock_config:
            mock_config.return_value = MagicMock(company_name='Test Shop')
            result = svc._render_template(template, invoice)

        self.assertEqual(result, '')

    def test_no_tenant_still_renders(self):
        """_render_template should work even when tenant is None."""
        svc = ReminderService(tenant=None)
        invoice = _make_mock_invoice(tenant=None)

        template = "Dear {customer_name}, invoice {invoice_number} is due."
        result = svc._render_template(template, invoice)

        self.assertIn('EOS Trucking', result)
        self.assertIn('INV-20260401-001', result)
