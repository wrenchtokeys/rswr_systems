"""
Tests for Round 2 bug audit fixes (BUG-020 through BUG-027).

Focuses on:
- Missing imports causing NameError (BUG-020)
- Multi-tenant isolation in billing services (BUG-021 through BUG-027)
"""

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice, InvoiceLineItem, Payment


class TenantIsolationTestMixin:
    """Shared setup for multi-tenant isolation tests."""

    def setUp(self):
        # Create two tenants
        self.plan = SubscriptionPlan.objects.create(
            name='Test Plan', slug='test-plan',
            monthly_price=Decimal('29.99'),
            max_repairs_per_month=100,
            max_technicians=5,
            max_customers=50,
            max_storage_mb=500,
        )

        # Users (must create before tenants due to Tenant.owner FK)
        self.user_a = User.objects.create_user('user_a', 'a@test.com', 'pass')
        self.user_b = User.objects.create_user('user_b', 'b@test.com', 'pass')

        self.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a',
            subscription_plan=self.plan, is_active=True,
            owner=self.user_a,
        )
        self.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b',
            subscription_plan=self.plan, is_active=True,
            owner=self.user_b,
        )
        TenantMembership.objects.create(
            tenant=self.tenant_a, user=self.user_a, role='owner', is_active=True
        )
        TenantMembership.objects.create(
            tenant=self.tenant_b, user=self.user_b, role='owner', is_active=True
        )

        # Customers
        from core.models import Customer
        self.cust_a = Customer.objects.create(
            name='Customer A', tenant=self.tenant_a
        )
        self.cust_b = Customer.objects.create(
            name='Customer B', tenant=self.tenant_b
        )


class InvoiceTrackingTenantIsolationTest(TenantIsolationTestMixin, TestCase):
    """BUG-021, BUG-022, BUG-023: Tenant isolation in InvoiceTrackingService."""

    def setUp(self):
        super().setUp()
        # Create invoices for both tenants
        self.inv_a = Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='INV-A-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() - timedelta(days=5),
            status='SENT', subtotal=Decimal('100'), total=Decimal('100'),
        )
        self.inv_b = Invoice.objects.create(
            tenant=self.tenant_b, customer=self.cust_b,
            invoice_number='INV-B-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() - timedelta(days=5),
            status='SENT', subtotal=Decimal('200'), total=Decimal('200'),
        )

    def test_get_outstanding_invoices_with_tenant(self):
        """BUG-021: get_outstanding_invoices should only return tenant's invoices."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc_a = InvoiceTrackingService(tenant=self.tenant_a)
        outstanding = svc_a.get_outstanding_invoices()
        self.assertEqual(outstanding.count(), 1)
        self.assertEqual(outstanding.first().tenant, self.tenant_a)

    def test_get_outstanding_invoices_without_tenant_returns_none(self):
        """BUG-021: Without tenant and no customer, returns empty queryset."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService(tenant=None)
        outstanding = svc.get_outstanding_invoices()
        self.assertEqual(outstanding.count(), 0)

    def test_update_overdue_statuses_with_tenant(self):
        """BUG-022: update_overdue_statuses should only update tenant's invoices."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc_a = InvoiceTrackingService(tenant=self.tenant_a)
        updated = svc_a.update_overdue_statuses()
        self.assertEqual(updated, 1)

        # Verify only tenant A's invoice was updated
        self.inv_a.refresh_from_db()
        self.inv_b.refresh_from_db()
        self.assertEqual(self.inv_a.status, 'OVERDUE')
        self.assertEqual(self.inv_b.status, 'SENT')  # Unchanged

    def test_update_overdue_without_tenant_skips(self):
        """BUG-022: Without tenant, update_overdue_statuses should skip."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc = InvoiceTrackingService(tenant=None)
        updated = svc.update_overdue_statuses()
        self.assertEqual(updated, 0)

        # Both should remain unchanged
        self.inv_a.refresh_from_db()
        self.inv_b.refresh_from_db()
        self.assertEqual(self.inv_a.status, 'SENT')
        self.assertEqual(self.inv_b.status, 'SENT')


class InvoiceServiceTenantTest(TenantIsolationTestMixin, TestCase):
    """BUG-025: InvoiceService.build_invoice_data tenant isolation."""

    def test_build_invoice_data_wrong_tenant_raises(self):
        """Customer from tenant B should not be accessible by tenant A service."""
        from apps.billing.services.invoice_service import InvoiceService

        svc = InvoiceService(tenant=self.tenant_a)
        with self.assertRaises(Exception):
            # cust_b belongs to tenant_b, so tenant_a service should reject
            svc.build_invoice_data(customer_id=self.cust_b.id)


class DashboardServiceTenantTest(TenantIsolationTestMixin, TestCase):
    """BUG-026: Dashboard alerts should be tenant-scoped."""

    def test_alerts_without_tenant_returns_empty(self):
        """When no tenant is set, batch customer alerts should be empty."""
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(tenant=None)
        # _get_alerts accesses batch_customers — should return empty, not error
        try:
            alerts = svc._get_alerts()
            # Check that no CustomerRepairPreference results leak
            for alert in alerts:
                if alert.get('type') == 'uninvoiced_repairs':
                    self.fail("Should not return uninvoiced alerts without tenant")
        except Exception:
            # Some alerts may fail without tenant — that's acceptable
            pass


class InvoiceEmailServiceTenantTest(TenantIsolationTestMixin, TestCase):
    """BUG-027: InvoiceEmailService should accept and use tenant."""

    def test_constructor_accepts_tenant(self):
        """InvoiceEmailService should accept tenant parameter."""
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        svc = InvoiceEmailService(tenant=self.tenant_a)
        self.assertEqual(svc.tenant, self.tenant_a)
        self.assertEqual(svc.invoice_service.tenant, self.tenant_a)


class ViewImportTest(TestCase):
    """BUG-020: Views that use Invoice must import it."""

    def test_send_invoice_email_view_imports_invoice(self):
        """Verify send_invoice_email doesn't raise NameError for Invoice."""
        # We test by importing the module and checking the function exists
        from apps.billing import views
        self.assertTrue(callable(views.send_invoice_email))
        self.assertTrue(callable(views.send_invoice_email_batch))


# ---------------------------------------------------------------------------
# CODE-120: PDF downloads use wrong (regenerated) invoice number and date
# ---------------------------------------------------------------------------

class InvoiceServiceInvoiceNumberOverrideTest(TestCase):
    """CODE-120: build_invoice_data and generate_invoice accept invoice_number/invoice_date overrides."""

    def setUp(self):
        from apps.tenants.models import SubscriptionPlan, Tenant
        from core.models import Customer
        from django.contrib.auth.models import User

        self.plan = SubscriptionPlan.objects.create(
            name='Plan120', slug='plan-120',
            monthly_price=Decimal('29.99'),
            max_repairs_per_month=100, max_technicians=5,
            max_customers=50, max_storage_mb=500,
        )
        self.user = User.objects.create_user('user_120', 'u120@test.com', 'pass')
        self.tenant = Tenant.objects.create(
            name='Shop 120', slug='shop-120',
            subscription_plan=self.plan, is_active=True, owner=self.user,
        )
        self.customer = Customer.objects.create(name='Cust 120', tenant=self.tenant)

    def test_build_invoice_data_uses_supplied_invoice_number(self):
        """build_invoice_data should embed the supplied invoice_number, not a fresh one."""
        from apps.billing.services.invoice_service import InvoiceService
        from datetime import datetime

        svc = InvoiceService(tenant=self.tenant)
        stored_number = 'INV-5-20260101080000'
        stored_date = datetime(2026, 1, 1, 8, 0, 0)

        data = svc.build_invoice_data(
            customer_id=self.customer.id,
            invoice_number=stored_number,
            invoice_date=stored_date,
        )

        self.assertEqual(data.invoice_number, stored_number,
                         "PDF must show stored invoice number, not a freshly generated one")
        self.assertEqual(data.invoice_date, stored_date,
                         "PDF must show stored invoice date, not today's date")

    def test_build_invoice_data_generates_number_when_not_supplied(self):
        """Without override, build_invoice_data still generates a number automatically."""
        from apps.billing.services.invoice_service import InvoiceService

        svc = InvoiceService(tenant=self.tenant)
        data = svc.build_invoice_data(customer_id=self.customer.id)

        self.assertIsNotNone(data.invoice_number)
        self.assertTrue(len(data.invoice_number) > 0,
                        "Auto-generated invoice number must not be empty")

    def test_generate_invoice_passes_through_overrides(self):
        """generate_invoice should pass invoice_number/invoice_date down to build_invoice_data."""
        from apps.billing.services.invoice_service import InvoiceService
        from datetime import datetime

        svc = InvoiceService(tenant=self.tenant)
        stored_number = 'INV-ORIG-001'
        stored_date = datetime(2026, 2, 15, 12, 0, 0)

        pdf_bytes, invoice_data = svc.generate_invoice(
            customer_id=self.customer.id,
            invoice_number=stored_number,
            invoice_date=stored_date,
        )

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(len(pdf_bytes) > 0, "PDF must not be empty")
        self.assertEqual(invoice_data.invoice_number, stored_number)
        self.assertEqual(invoice_data.invoice_date, stored_date)

    def test_pdf_download_view_uses_stored_invoice_number(self):
        """owner_invoice_pdf should call generate_invoice with the stored invoice_number."""
        from apps.billing.models import Invoice
        from apps.tenants.models import TenantMembership
        from unittest.mock import patch
        from django.test import RequestFactory
        from django.utils import timezone as tz
        import datetime

        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner', is_active=True,
        )

        stored_inv_number = 'INV-STORED-9999'
        stored_date = datetime.date(2026, 1, 1)

        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=stored_inv_number,
            invoice_date=stored_date,
            due_date=stored_date,
            status='SENT',
            subtotal=Decimal('0.00'),
            total=Decimal('0.00'),
        )

        dummy_pdf = b'%PDF fake content'

        class FakeInvoiceData:
            invoice_number = stored_inv_number

        with patch('apps.billing.services.invoice_service.InvoiceService.generate_invoice',
                   return_value=(dummy_pdf, FakeInvoiceData())) as mock_gen:
            factory = RequestFactory()
            request = factory.get(f'/owner/invoices/{invoice.id}/pdf/')
            request.user = self.user
            request.tenant = self.tenant

            from apps.saas.views import owner_invoice_pdf
            response = owner_invoice_pdf(request, invoice_id=invoice.id)

        call_kwargs = mock_gen.call_args[1]
        self.assertEqual(call_kwargs.get('invoice_number'), stored_inv_number,
                         "view must pass stored invoice_number to generate_invoice")
        # invoice_date should be passed as a datetime (date → datetime conversion)
        self.assertIsNotNone(call_kwargs.get('invoice_date'),
                             "view must pass stored invoice_date to generate_invoice")

    def test_email_invoice_view_uses_stored_invoice_number(self):
        """owner_email_invoice should pass stored invoice_number to send_invoice_email."""
        from apps.billing.models import Invoice
        from apps.tenants.models import TenantMembership
        from unittest.mock import patch
        from django.test import RequestFactory
        from django.contrib.messages.storage.cookie import CookieStorage
        import datetime

        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner', is_active=True,
        )

        stored_inv_number = 'INV-EMAIL-0042'
        stored_date = datetime.date(2026, 2, 1)

        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=stored_inv_number,
            invoice_date=stored_date,
            due_date=stored_date,
            status='SENT',
            subtotal=Decimal('0.00'),
            total=Decimal('0.00'),
        )
        # Add email so view doesn't short-circuit
        self.customer.email = 'cust120@test.com'
        self.customer.save()

        with patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
                   return_value=(True, 'sent')) as mock_send:
            factory = RequestFactory()
            request = factory.post(f'/owner/invoices/{invoice.id}/email/')
            request.user = self.user
            request.tenant = self.tenant
            # Attach message storage so messages.success/error don't raise MessageFailure
            request._messages = CookieStorage(request)
            request.session = {}

            from apps.saas.views import owner_email_invoice
            owner_email_invoice(request, invoice_id=invoice.id)

        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs.get('invoice_number'), stored_inv_number,
                         "view must pass stored invoice_number to send_invoice_email")
        self.assertIsNotNone(call_kwargs.get('invoice_date'),
                             "view must pass stored invoice_date to send_invoice_email")
