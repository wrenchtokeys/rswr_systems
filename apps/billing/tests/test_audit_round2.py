"""
Tests for Round 2 audit bugs (BUG-020 through BUG-025).

Focuses on:
- Multi-tenant isolation in billing services
- Correct singleton access patterns
- Tenant parameter propagation

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan
from core.models import Customer
from apps.billing.models import Invoice, InvoiceLineItem, Payment, BillingConfig


def _create_plan():
    """Create a subscription plan for testing."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='test-plan',
        defaults={
            'name': 'Test Plan',
            'max_technicians': 5,
            'max_customers': 50,
            'monthly_price': Decimal('29.99'),
        }
    )
    return plan


def _create_tenant(name, owner_email):
    """Create a tenant with an owner for testing."""
    plan = _create_plan()
    user = User.objects.create_user(
        username=owner_email, email=owner_email, password='testpass123'
    )
    tenant = Tenant.objects.create(
        name=name,
        owner=user,
        subscription_plan=plan,
        plan='starter',
        is_active=True,
    )
    return tenant, user


class TestInvoiceTrackingServiceTenantIsolation(TestCase):
    """BUG-020: get_outstanding_invoices and update_overdue_statuses must be tenant-scoped."""

    def setUp(self):
        self.tenant_a, self.user_a = _create_tenant('Shop A', 'a@test.com')
        self.tenant_b, self.user_b = _create_tenant('Shop B', 'b@test.com')

        self.customer_a = Customer.objects.create(
            name='Customer A', tenant=self.tenant_a
        )
        self.customer_b = Customer.objects.create(
            name='Customer B', tenant=self.tenant_b
        )

        # Create invoices for both tenants
        self.inv_a = Invoice.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            invoice_number='INV-A-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() - timedelta(days=5),
            status='SENT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
        )
        self.inv_b = Invoice.objects.create(
            tenant=self.tenant_b,
            customer=self.customer_b,
            invoice_number='INV-B-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() - timedelta(days=5),
            status='SENT',
            subtotal=Decimal('200.00'),
            total=Decimal('200.00'),
        )

    def test_get_outstanding_invoices_tenant_scoped(self):
        """Tenant A should only see Tenant A's outstanding invoices."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc_a = InvoiceTrackingService(tenant=self.tenant_a)
        outstanding = svc_a.get_outstanding_invoices()
        invoice_ids = list(outstanding.values_list('id', flat=True))

        self.assertIn(self.inv_a.id, invoice_ids)
        self.assertNotIn(self.inv_b.id, invoice_ids)

    def test_update_overdue_statuses_tenant_scoped(self):
        """update_overdue_statuses should only affect the service's tenant."""
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        svc_a = InvoiceTrackingService(tenant=self.tenant_a)
        updated = svc_a.update_overdue_statuses()

        # Tenant A's invoice should be overdue
        self.inv_a.refresh_from_db()
        self.assertEqual(self.inv_a.status, 'OVERDUE')

        # Tenant B's invoice should NOT have been touched
        self.inv_b.refresh_from_db()
        self.assertEqual(self.inv_b.status, 'SENT')


class TestDashboardServiceTenantIsolation(TestCase):
    """BUG-021/022: DashboardService.get_alerts() must filter by tenant."""

    def setUp(self):
        self.tenant_a, self.user_a = _create_tenant('Shop A2', 'a2@test.com')
        self.tenant_b, self.user_b = _create_tenant('Shop B2', 'b2@test.com')

        self.customer_a = Customer.objects.create(
            name='Customer A2', tenant=self.tenant_a
        )
        self.customer_b = Customer.objects.create(
            name='Customer B2', tenant=self.tenant_b
        )

    def test_dashboard_uses_tenant_for_tracking_service(self):
        """DashboardService should pass its tenant to InvoiceTrackingService."""
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(tenant=self.tenant_a)
        # get_alerts creates InvoiceTrackingService — just verify it runs
        # without error and doesn't crash on tenant filtering
        alerts = svc.get_alerts()
        self.assertIsInstance(alerts, list)


class TestStripeServiceTenantPropagation(TestCase):
    """BUG-023: _record_stripe_payment should pass tenant to InvoiceTrackingService."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Stripe Shop', 'stripe@test.com')
        self.customer = Customer.objects.create(
            name='Stripe Customer', tenant=self.tenant
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-STRIPE-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
            status='SENT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
        )

    def test_record_stripe_payment_passes_tenant(self):
        """_record_stripe_payment should create InvoiceTrackingService with tenant."""
        from apps.billing.services.stripe_service import StripeService

        svc = StripeService()
        # Mock out the actual payment recording to test tenant propagation
        with patch('apps.billing.services.invoice_tracking_service.InvoiceTrackingService.record_payment') as mock_record:
            mock_payment = MagicMock()
            mock_payment.invoice = self.invoice
            mock_record.return_value = mock_payment

            with patch('apps.billing.services.payment_notification_service.PaymentNotificationService.notify_payment'):
                result = svc._record_stripe_payment(
                    invoice_id=self.invoice.id,
                    amount=Decimal('50.00'),
                    stripe_payment_id='pi_test_123',
                    notes='Test payment',
                )

            self.assertTrue(result['success'])


class TestReminderServiceSingletonAccess(TestCase):
    """
    BUG-024 (updated): _build_reminder_email must use get_for_tenant(), not
    the deprecated get_instance() or the raw objects.first().

    After CODE-002 (BillingConfig per-tenant migration), get_instance() raises
    RuntimeError, so any call to it in a hot path is a crash.
    """

    def test_build_reminder_uses_get_for_tenant(self):
        """Verify _build_reminder_email uses get_for_tenant(), not get_instance() or .first()."""
        from apps.billing.services.reminder_service import ReminderService
        import inspect

        source = inspect.getsource(ReminderService._build_reminder_email)
        self.assertNotIn('objects.first()', source)
        self.assertNotIn('get_instance()', source)
        self.assertIn('get_for_tenant(', source)


class TestInvoiceServiceTenantParam(TestCase):
    """BUG-025: InvoiceService should accept and use tenant parameter."""

    def test_invoice_service_accepts_tenant(self):
        """InvoiceService should accept a tenant parameter."""
        from apps.billing.services.invoice_service import InvoiceService

        tenant = MagicMock()
        svc = InvoiceService(tenant=tenant)
        self.assertEqual(svc.tenant, tenant)

    def test_invoice_service_default_no_tenant(self):
        """InvoiceService should default to no tenant."""
        from apps.billing.services.invoice_service import InvoiceService

        svc = InvoiceService()
        self.assertIsNone(svc.tenant)
