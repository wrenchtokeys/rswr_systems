"""
Regression tests for CODE-094:
  1. AutoInvoiceService.generate_and_save() now passes tenant= to InvoiceTrackingService
     so the correct BillingConfig (payment_terms, prefix) is loaded for auto-invoices.
  2. Invoice is created as DRAFT; only marked SENT after email delivery is confirmed
     (AGENTS.md gotcha: "Don't mark invoices SENT before confirming email delivery").
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock, PropertyMock
from django.test import TestCase
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.billing.models import BillingConfig, Invoice
from apps.customer_portal.models import CustomerRepairPreference


def _make_owner(prefix='owner'):
    return User.objects.create_user(
        username=f'{prefix}_{User.objects.count()}',
        email=f'{prefix}{User.objects.count()}@example.com',
        password='pass',
    )


def _make_tenant(name='Test Shop'):
    owner = _make_owner()
    return Tenant.objects.create(
        name=name,
        slug=f'{name.lower().replace(" ", "-")}-{Tenant.objects.count()}',
        plan='trial',
        owner=owner,
    )


def _make_user(username):
    return User.objects.create_user(username=username, email=f'{username}@example.com', password='pass')


def _make_customer(tenant, name='Fleet Co'):
    return Customer.objects.create(tenant=tenant, name=name, email=f'{name.lower().replace(" ", "")}@example.com')


def _make_technician(tenant, user):
    return Technician.objects.create(tenant=tenant, user=user, is_active=True)


def _make_repair(tenant, customer, technician, status='COMPLETED'):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='T-001',
        damage_type='chip',
        queue_status=status,
        cost=Decimal('50.00'),
    )


class InvoiceTrackingServiceTenantTests(TestCase):
    """Bug: InvoiceTrackingService() called without tenant= → wrong payment terms."""

    def setUp(self):
        self.tenant = _make_tenant('Tracking Shop')
        # Configure non-default payment terms
        self.billing_config = BillingConfig.get_for_tenant(self.tenant)
        self.billing_config.default_payment_terms = 'NET30'
        self.billing_config.invoice_number_prefix = 'TRK'
        self.billing_config.save()

        self.user = _make_user('track_tech')
        self.technician = _make_technician(self.tenant, self.user)
        self.customer = _make_customer(self.tenant, 'Tracking Fleet')
        self.repair = _make_repair(self.tenant, self.customer, self.technician)

    def test_tracking_service_with_tenant_loads_billing_config(self):
        """InvoiceTrackingService(tenant=) loads the correct BillingConfig."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService(tenant=self.tenant)
        self.assertIsNotNone(svc.billing_config, "billing_config should be loaded when tenant is passed")
        self.assertEqual(svc.billing_config.default_payment_terms, 'NET30')

    def test_tracking_service_without_tenant_gets_no_billing_config(self):
        """Without tenant=, InvoiceTrackingService has no BillingConfig."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService()  # no tenant
        self.assertIsNone(svc.billing_config, "billing_config should be None without tenant")

    def test_invoice_uses_shop_payment_terms_when_tenant_passed(self):
        """create_invoice_from_repairs() with tenant= uses the shop's payment terms."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService(tenant=self.tenant)
        invoice = svc.create_invoice_from_repairs(
            customer=self.customer,
            repairs=[self.repair],
            auto_send=False,
        )
        self.assertEqual(
            invoice.payment_terms, 'NET30',
            "Invoice should use the shop's NET30 terms, not the default COD"
        )

    def test_invoice_gets_default_terms_without_tenant(self):
        """create_invoice_from_repairs() without tenant= defaults to COD terms."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService()  # no tenant
        invoice = svc.create_invoice_from_repairs(
            customer=self.customer,
            repairs=[self.repair],
            auto_send=False,
        )
        # Without BillingConfig, payment_terms falls back to 'COD'
        self.assertEqual(invoice.payment_terms, 'COD')

    def test_auto_send_false_creates_draft(self):
        """auto_send=False creates invoice as DRAFT."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService(tenant=self.tenant)
        invoice = svc.create_invoice_from_repairs(
            customer=self.customer,
            repairs=[self.repair],
            auto_send=False,
        )
        self.assertEqual(invoice.status, 'DRAFT')
        self.assertIsNone(invoice.sent_at)

    def test_auto_send_true_creates_sent(self):
        """auto_send=True creates invoice as SENT (legacy / manual override)."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService(tenant=self.tenant)
        invoice = svc.create_invoice_from_repairs(
            customer=self.customer,
            repairs=[self.repair],
            auto_send=True,
        )
        self.assertEqual(invoice.status, 'SENT')
        self.assertIsNotNone(invoice.sent_at)


class AutoInvoiceEmailSentStatusTests(TestCase):
    """
    Bug: auto_invoice_service used auto_send=True, marking invoice SENT before
    the email was attempted.  Now: DRAFT on creation, SENT only after email confirms.
    """

    def setUp(self):
        self.tenant = _make_tenant('Email Shop')
        BillingConfig.get_for_tenant(self.tenant)

        self.user = _make_user('email_tech2')
        self.technician = _make_technician(self.tenant, self.user)
        self.customer = _make_customer(self.tenant, 'Email Fleet')
        # Create the repair BEFORE the per_ticket preference so the
        # completion signal doesn't auto-invoice it during setUp — each test
        # calls generate_and_save explicitly.
        self.repair = _make_repair(self.tenant, self.customer, self.technician)
        # per_ticket + auto_email_invoices
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='AUTO_APPROVE',
            invoice_preference='per_ticket',
            auto_email_invoices=True,
        )

    def _make_mock_invoice_data(self, num='TRK-X'):
        """Create a mock InvoiceData-like object."""
        inv = MagicMock()
        inv.invoice_number = num
        inv.line_items = [MagicMock()]
        return inv

    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._send_invoice_email', return_value=False)
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._save_to_s3', return_value='invoices/1/t1.pdf')
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._create_payment_link', return_value=None)
    def test_invoice_stays_draft_when_email_fails(self, _mock_stripe, _mock_s3, _mock_email):
        """When email fails, invoice must remain DRAFT.

        Record-first flow: generate_and_save creates the tracked Invoice
        itself, so we assert on the real record it produced.
        """
        from apps.billing.services.auto_invoice_service import AutoInvoiceService

        svc = AutoInvoiceService()
        result = svc.generate_and_save(self.repair)

        self.assertTrue(result['success'], result.get('error'))
        created_invoice = Invoice.objects.get(id=result['invoice_id'])
        self.assertEqual(
            created_invoice.status, 'DRAFT',
            "Invoice must remain DRAFT when email delivery failed"
        )
        self.assertIsNone(created_invoice.sent_at)

    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._send_invoice_email', return_value=True)
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._save_to_s3', return_value='invoices/1/t2.pdf')
    @patch('apps.billing.services.auto_invoice_service.AutoInvoiceService._create_payment_link', return_value=None)
    def test_invoice_marked_sent_after_email_success(self, _mock_stripe, _mock_s3, _mock_email):
        """When email succeeds, invoice must be updated to SENT."""
        from apps.billing.services.auto_invoice_service import AutoInvoiceService

        svc = AutoInvoiceService()
        result = svc.generate_and_save(self.repair)

        self.assertTrue(result['success'], result.get('error'))
        created_invoice = Invoice.objects.get(id=result['invoice_id'])
        self.assertEqual(
            created_invoice.status, 'SENT',
            "Invoice must be marked SENT after confirmed email delivery"
        )
        self.assertIsNotNone(created_invoice.sent_at)
