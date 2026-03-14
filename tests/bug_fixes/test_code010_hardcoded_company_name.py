"""
CODE-010: Hardcoded "Rockstar Windshield Repair" in payment confirmation emails

Both `ReminderService.send_payment_confirmation()` and
`ReminderService._build_reminder_email()` fell back to the hard-coded string
"Rockstar Windshield Repair" instead of reading the per-tenant BillingConfig.

This means every tenant using payment-confirmation or payment-reminder emails
would receive emails signed off as "Rockstar Windshield Repair" — a critical
multi-tenant branding bug that would confuse customers of any other shop.

Additionally, `InvoiceService._load_branding_config()` also fell back to the
same hard-coded string when BillingConfig couldn't be loaded.

Fixes:
  1. `send_payment_confirmation()` — now looks up BillingConfig and falls
     through to tenant.name; never uses the hard-coded string.
  2. `_build_reminder_email()` — initial `company_name` default changed from
     the hard-coded string to ""; same BillingConfig lookup now falls through
     to tenant.name on miss.
  3. `InvoiceService._load_branding_config()` — both the `.company_name or`
     fallback and the except-block fallback now use `self.tenant.name` (or ""
     when no tenant) instead of the hard-coded string.

Regression tests verify:
  - Source code contains no bare "Rockstar Windshield Repair" strings in
    service business logic.
  - `send_payment_confirmation()` uses the tenant's actual company name.
  - `_build_reminder_email()` uses the tenant's actual company name.
  - `_build_reminder_email()` uses tenant.name when BillingConfig is missing.
  - `InvoiceService._load_branding_config()` uses tenant.name when
    BillingConfig raises an exception.
"""

import inspect
from decimal import Decimal
from unittest.mock import patch, MagicMock, PropertyMock

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice
from apps.billing.services.reminder_service import ReminderService
from apps.billing.services.invoice_service import InvoiceService
from apps.tenants.models import Tenant
from core.models import Customer


# ---------------------------------------------------------------------------
# Source-code guard — no bare hard-coded company name in service logic
# ---------------------------------------------------------------------------

class TestNoHardcodedCompanyName(TestCase):
    """Ensure service files don't contain the old hard-coded string."""

    def test_reminder_service_no_hardcoded_name(self):
        import apps.billing.services.reminder_service as mod
        source = inspect.getsource(mod)
        # Allow the string only in comments / docstrings — not in string literals
        # that appear in f-string bodies or regular string assignment in logic.
        # Simple check: count occurrences; if any appear it's a regression.
        self.assertNotIn(
            '"Rockstar Windshield Repair"',
            source,
            "reminder_service.py must not hard-code 'Rockstar Windshield Repair' "
            "as a string literal — use BillingConfig or tenant.name instead.",
        )

    def test_invoice_service_no_hardcoded_name(self):
        import apps.billing.services.invoice_service as mod
        source = inspect.getsource(mod)
        self.assertNotIn(
            '"Rockstar Windshield Repair"',
            source,
            "invoice_service.py must not hard-code 'Rockstar Windshield Repair' "
            "as a string literal — use BillingConfig or tenant.name instead.",
        )


# ---------------------------------------------------------------------------
# Helper — build a minimal tenant + customer + invoice fixture in memory
# ---------------------------------------------------------------------------

def _make_fixtures(tenant_name="Acme Glass Co."):
    """Return (tenant, customer, invoice) using unsaved/mocked objects."""
    tenant = MagicMock(spec=Tenant)
    tenant.name = tenant_name
    tenant.id = 99

    customer = MagicMock()
    customer.name = "Fleet Corp"
    customer.email = "fleet@example.com"
    customer.tenant = tenant

    invoice = MagicMock(spec=Invoice)
    invoice.invoice_number = "INV-20260314-001"
    invoice.invoice_date = timezone.now().date()
    invoice.due_date = timezone.now().date()
    invoice.status = "PAID"
    invoice.get_status_display.return_value = "Paid"
    invoice.total = Decimal("500.00")
    invoice.subtotal = Decimal("500.00")
    invoice.amount_paid = Decimal("500.00")
    invoice.amount_due = Decimal("0.00")
    invoice.customer = customer
    invoice.tenant = tenant
    invoice.stripe_hosted_url = None
    invoice.internal_notes = ""

    payment = MagicMock()
    payment.amount = Decimal("500.00")
    payment.get_payment_method_display.return_value = "Check"
    payment.payment_date = timezone.now().date()

    return tenant, customer, invoice, payment


# ---------------------------------------------------------------------------
# ReminderService.send_payment_confirmation — uses BillingConfig
# ---------------------------------------------------------------------------

class TestPaymentConfirmationCompanyName(TestCase):

    def test_uses_billing_config_company_name(self):
        """sign-off must use BillingConfig.company_name when available."""
        tenant, customer, invoice, payment = _make_fixtures("Glass Masters LLC")

        mock_config = MagicMock()
        mock_config.company_name = "Glass Masters LLC"
        mock_config.company_phone = ""
        mock_config.company_website = ""

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            with patch.object(svc, '_send_email', return_value=True) as mock_send:
                result = svc.send_payment_confirmation(invoice, payment)

        self.assertTrue(result['success'])
        # Grab the body that was passed to _send_email
        _, kwargs = mock_send.call_args
        body = kwargs.get('body', mock_send.call_args[0][1] if mock_send.call_args[0] else "")
        # Reconstruct from positional args if needed
        all_args = str(mock_send.call_args)
        self.assertIn("Glass Masters LLC", all_args,
                      "Payment confirmation body must include the tenant's company name.")
        self.assertNotIn("Rockstar Windshield Repair", all_args,
                         "Payment confirmation body must NOT include the old hard-coded name.")

    def test_falls_back_to_tenant_name_when_config_missing(self):
        """sign-off must fall back to tenant.name when BillingConfig unavailable."""
        tenant, customer, invoice, payment = _make_fixtures("Sunrise Auto Glass")

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', side_effect=Exception("No config")):
            with patch.object(svc, '_send_email', return_value=True) as mock_send:
                result = svc.send_payment_confirmation(invoice, payment)

        self.assertTrue(result['success'])
        all_args = str(mock_send.call_args)
        self.assertIn("Sunrise Auto Glass", all_args,
                      "Payment confirmation body must fall back to tenant.name.")
        self.assertNotIn("Rockstar Windshield Repair", all_args)

    def test_uses_invoice_tenant_when_service_tenant_is_none(self):
        """When ReminderService has no tenant, it uses invoice.tenant for the lookup."""
        tenant, customer, invoice, payment = _make_fixtures("Valley View Glass")

        mock_config = MagicMock()
        mock_config.company_name = "Valley View Glass"

        # Build service without a tenant set on the service itself
        svc = ReminderService(tenant=None)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config) as mock_get:
            with patch.object(svc, '_send_email', return_value=True) as mock_send:
                result = svc.send_payment_confirmation(invoice, payment)

        # BillingConfig.get_for_tenant must have been called with invoice.tenant
        mock_get.assert_called_once_with(tenant)
        self.assertIn("Valley View Glass", str(mock_send.call_args))


# ---------------------------------------------------------------------------
# ReminderService._build_reminder_email — uses BillingConfig
# ---------------------------------------------------------------------------

class TestBuildReminderEmailCompanyName(TestCase):

    def test_uses_billing_config_company_name(self):
        """Reminder email body must include tenant's company name."""
        tenant, customer, invoice, payment = _make_fixtures("Blue Ridge Glass")

        mock_config = MagicMock()
        mock_config.company_name = "Blue Ridge Glass"
        mock_config.company_phone = "555-1234"
        mock_config.company_website = "https://blueridgeglass.example.com"

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            subject, body = svc._build_reminder_email(invoice, 'overdue_7d')

        self.assertIn("Blue Ridge Glass", body)
        self.assertNotIn("Rockstar Windshield Repair", body)

    def test_falls_back_to_tenant_name_when_config_has_no_company_name(self):
        """When BillingConfig.company_name is blank, must use tenant.name."""
        tenant, customer, invoice, payment = _make_fixtures("Coastal Glass Pros")

        mock_config = MagicMock()
        mock_config.company_name = ""   # blank — should trigger fallback
        mock_config.company_phone = ""
        mock_config.company_website = ""

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            subject, body = svc._build_reminder_email(invoice, 'due_soon_3d')

        self.assertIn("Coastal Glass Pros", body,
                      "Should fall back to tenant.name when company_name is blank.")
        self.assertNotIn("Rockstar Windshield Repair", body)

    def test_falls_back_to_tenant_name_when_config_unavailable(self):
        """When BillingConfig lookup raises, must use tenant.name."""
        tenant, customer, invoice, payment = _make_fixtures("Mountain Glass Works")

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', side_effect=Exception("db error")):
            subject, body = svc._build_reminder_email(invoice, 'overdue_1d')

        self.assertIn("Mountain Glass Works", body)
        self.assertNotIn("Rockstar Windshield Repair", body)


# ---------------------------------------------------------------------------
# InvoiceService._load_branding_config — uses tenant.name as fallback
# ---------------------------------------------------------------------------

class TestInvoiceServiceCompanyName(TestCase):

    def test_uses_tenant_name_when_billing_config_raises(self):
        """InvoiceService must use tenant.name when BillingConfig fails to load."""
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Summit Glass Repair"
        tenant.id = 42

        svc = InvoiceService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', side_effect=Exception("no config")):
            svc._load_branding_config()

        self.assertEqual(svc.COMPANY_NAME, "Summit Glass Repair",
                         "COMPANY_NAME must fall back to tenant.name, not Rockstar.")

    def test_uses_tenant_name_when_company_name_blank_in_config(self):
        """InvoiceService must use tenant.name when config.company_name is blank."""
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Desert Sun Glass"
        tenant.id = 43

        mock_config = MagicMock()
        mock_config.company_name = ""
        mock_config.full_address = "123 Main St"
        mock_config.company_phone = ""
        mock_config.company_email = ""
        mock_config.company_website = ""
        mock_config.default_payment_terms = "NET30"
        mock_config.due_days_for_terms = 30
        mock_config.invoice_footer_note = ""
        mock_config.invoice_number_prefix = "INV"

        svc = InvoiceService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            with patch('core.models.email_branding.EmailBrandingConfig.get_instance',
                       side_effect=Exception("not configured")):
                svc._load_branding_config()

        self.assertEqual(svc.COMPANY_NAME, "Desert Sun Glass",
                         "COMPANY_NAME must fall back to tenant.name when config.company_name is blank.")

    def test_uses_billing_config_company_name_when_set(self):
        """InvoiceService must use BillingConfig.company_name when it is set."""
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Fallback Name"
        tenant.id = 44

        mock_config = MagicMock()
        mock_config.company_name = "Lakeside Auto Glass"
        mock_config.full_address = "456 Lake Rd"
        mock_config.company_phone = "555-9999"
        mock_config.company_email = "info@lakeside.example.com"
        mock_config.company_website = "https://lakeside.example.com"
        mock_config.default_payment_terms = "COD"
        mock_config.due_days_for_terms = 0
        mock_config.invoice_footer_note = "Thanks!"
        mock_config.invoice_number_prefix = "LAK"

        svc = InvoiceService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            with patch('core.models.email_branding.EmailBrandingConfig.get_instance',
                       side_effect=Exception("not configured")):
                svc._load_branding_config()

        self.assertEqual(svc.COMPANY_NAME, "Lakeside Auto Glass")
