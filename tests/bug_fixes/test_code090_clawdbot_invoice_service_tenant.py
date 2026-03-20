"""
Regression tests for CODE-090:
clawdbot invoice_preview and generate_invoice called InvoiceService() without tenant.

Root cause:
  apps/clawdbot/views.py — `invoice_preview()` and `generate_invoice()` both:
  1. Correctly scoped the customer lookup: Customer.objects.get(id=..., tenant=tenant)
  2. BUT then called InvoiceService() without passing tenant.

  Inside InvoiceService:
  - _load_branding_config() called BillingConfig.get_for_tenant(None) which fell
    through to its default-values except branch, so invoices had no company name,
    address, or configured payment terms.
  - get_completed_repairs() with self.tenant=None filtered only by customer_id
    and queue_status='COMPLETED', with no tenant filter. This is safe (customer_id
    was already validated) but is not defense-in-depth.

Fix (CODE-090):
  Both views now call InvoiceService(tenant=tenant) so:
  - BillingConfig loads the correct shop's info (company name, address, prefix).
  - get_completed_repairs() includes tenant filter.

Test scenarios:
  A. invoice_preview passes tenant to InvoiceService (BillingConfig is scoped).
  B. generate_invoice passes tenant to InvoiceService (BillingConfig is scoped).
  C. Unauthenticated requests are rejected (401/redirect).
  D. Requests without tenant context are rejected (403).
  E. Cross-tenant customer_id is rejected (404) even with valid auth.
"""

from unittest.mock import patch, MagicMock, PropertyMock
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.clawdbot.views import invoice_preview, generate_invoice


def _make_request(factory, user, tenant, method='get', path='/clawdbot/invoices/preview/1/'):
    """Build a request with user, tenant, and messages backend set."""
    req = factory.get(path) if method == 'get' else factory.post(path)
    req.user = user
    req.tenant = tenant
    # Messages middleware is not active in RequestFactory; attach session then
    # fallback storage (FallbackStorage needs session backend initialized first).
    req.session = {}
    setattr(req, '_messages', FallbackStorage(req))
    return req


class ClawdbotInvoiceServiceTenantTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        # Shop A
        self.owner_a = User.objects.create_user('owner_a', password='pw')
        self.tenant_a = Tenant.objects.create(
            name='Shop Alpha',
            slug='shop-alpha',
            owner=self.owner_a,
            is_active=True,
        )
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.owner_a, role='owner')

        # Shop B (different shop)
        self.owner_b = User.objects.create_user('owner_b', password='pw')
        self.tenant_b = Tenant.objects.create(
            name='Shop Beta',
            slug='shop-beta',
            owner=self.owner_b,
            is_active=True,
        )
        TenantMembership.objects.create(tenant=self.tenant_b, user=self.owner_b, role='owner')

        # Customer A belongs to Shop A
        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a,
            name='Alpha Fleet',
            email='fleet@alpha.com',
        )

        # Customer B belongs to Shop B
        self.customer_b = Customer.objects.create(
            tenant=self.tenant_b,
            name='Beta Fleet',
            email='fleet@beta.com',
        )

    # -------------------------------------------------------------------------
    # A. invoice_preview passes tenant to InvoiceService
    # -------------------------------------------------------------------------
    @patch('apps.billing.services.invoice_service.InvoiceService')
    def test_invoice_preview_passes_tenant_to_invoice_service(self, MockInvoiceService):
        """InvoiceService must be constructed with tenant=tenant, not tenant=None."""
        mock_instance = MagicMock()
        MockInvoiceService.return_value = mock_instance
        mock_instance.build_invoice_data.side_effect = Exception('no line items')  # bail early

        req = _make_request(self.factory, self.owner_a, self.tenant_a)
        invoice_preview(req, customer_id=self.customer_a.id)

        # Verify InvoiceService was called with the correct tenant
        MockInvoiceService.assert_called_once_with(tenant=self.tenant_a)

    # -------------------------------------------------------------------------
    # B. generate_invoice passes tenant to InvoiceService
    # -------------------------------------------------------------------------
    @patch('apps.billing.services.invoice_service.InvoiceService')
    def test_generate_invoice_passes_tenant_to_invoice_service(self, MockInvoiceService):
        """generate_invoice must also pass tenant=tenant to InvoiceService."""
        mock_instance = MagicMock()
        MockInvoiceService.return_value = mock_instance
        mock_instance.generate_invoice.side_effect = Exception('no repairs')  # bail early

        req = _make_request(self.factory, self.owner_a, self.tenant_a)
        generate_invoice(req, customer_id=self.customer_a.id)

        MockInvoiceService.assert_called_once_with(tenant=self.tenant_a)

    # -------------------------------------------------------------------------
    # C. Unauthenticated requests are rejected
    # -------------------------------------------------------------------------
    def test_invoice_preview_rejects_unauthenticated(self):
        """@login_required should redirect unauthenticated users."""
        from django.contrib.auth.models import AnonymousUser
        req = self.factory.get('/clawdbot/invoices/preview/1/')
        req.user = AnonymousUser()
        req.tenant = None

        resp = invoice_preview(req, customer_id=self.customer_a.id)
        # @login_required returns a redirect (302) to login
        self.assertIn(resp.status_code, [302, 403])

    # -------------------------------------------------------------------------
    # D. Requests without tenant context return 403
    # -------------------------------------------------------------------------
    @patch('apps.billing.services.invoice_service.InvoiceService')
    def test_invoice_preview_rejects_no_tenant(self, MockInvoiceService):
        """Without request.tenant, _get_tenant_or_403 must return 403."""
        req = self.factory.get('/clawdbot/invoices/preview/1/')
        req.user = self.owner_a
        req.tenant = None
        req.session = {}
        setattr(req, '_messages', FallbackStorage(req))

        resp = invoice_preview(req, customer_id=self.customer_a.id)
        self.assertEqual(resp.status_code, 403)
        # InvoiceService must NOT have been instantiated (we returned early)
        MockInvoiceService.assert_not_called()

    # -------------------------------------------------------------------------
    # E. Cross-tenant customer_id returns 404
    # -------------------------------------------------------------------------
    @patch('apps.billing.services.invoice_service.InvoiceService')
    def test_invoice_preview_rejects_cross_tenant_customer(self, MockInvoiceService):
        """Customer belonging to Shop B cannot be previewed by Shop A's owner."""
        req = _make_request(self.factory, self.owner_a, self.tenant_a)
        # customer_b belongs to tenant_b, not tenant_a
        resp = invoice_preview(req, customer_id=self.customer_b.id)
        self.assertEqual(resp.status_code, 404)
        # InvoiceService must NOT have been instantiated (we returned early)
        MockInvoiceService.assert_not_called()

    @patch('apps.billing.services.invoice_service.InvoiceService')
    def test_generate_invoice_rejects_cross_tenant_customer(self, MockInvoiceService):
        """generate_invoice with a cross-tenant customer_id must return 404."""
        req = _make_request(self.factory, self.owner_a, self.tenant_a)
        resp = generate_invoice(req, customer_id=self.customer_b.id)
        self.assertEqual(resp.status_code, 404)
        MockInvoiceService.assert_not_called()
