"""
CODE-007: Leftover BillingConfig.get_instance() calls after CODE-002 migration

After CODE-002 (BillingConfig made per-tenant), BillingConfig.get_instance()
was deprecated and now raises RuntimeError.  Three call sites were missed:

  1. billing/tasks.py::process_overdue_invoices   — silently swallowed config,
     meaning no overdue reminders were ever sent.
  2. billing/tasks.py::process_batch_invoices     — silently skipped every
     tenant, meaning no batch invoices were ever created.
  3. technician_portal/admin.py::generate_invoices admin action — no try/except,
     so the action crashed with RuntimeError on first use.

All three are fixed here:
  - tasks use BillingConfig.get_for_tenant(tenant)
  - admin action fetches config per-customer via get_for_tenant(customer.tenant)

Regression tests verify:
  - tasks no longer call get_instance()
  - admin action no longer calls get_instance()
  - tasks actually produce results (not silently empty) when config exists
  - admin action works end-to-end without crashing
"""

import inspect
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.billing.tasks import process_overdue_invoices, process_batch_invoices
from apps.tenants.models import Tenant
from core.models import Customer


# ---------------------------------------------------------------------------
# Source-code guard — no get_instance() may remain in these modules
# ---------------------------------------------------------------------------

class TestNoGetInstanceInTasks(TestCase):
    """Ensure tasks.py uses get_for_tenant() everywhere."""

    def test_process_overdue_invoices_no_get_instance(self):
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(process_overdue_invoices)
        self.assertNotIn(
            'get_instance()', source,
            "process_overdue_invoices still calls BillingConfig.get_instance() "
            "which raises RuntimeError. Use get_for_tenant(tenant) instead."
        )

    def test_process_batch_invoices_no_get_instance(self):
        source = inspect.getsource(process_batch_invoices)
        self.assertNotIn(
            'get_instance()', source,
            "process_batch_invoices still calls BillingConfig.get_instance() "
            "which raises RuntimeError. Use get_for_tenant(tenant) instead."
        )

    def test_process_overdue_invoices_uses_get_for_tenant(self):
        source = inspect.getsource(process_overdue_invoices)
        self.assertIn('get_for_tenant(', source)

    def test_process_batch_invoices_uses_get_for_tenant(self):
        source = inspect.getsource(process_batch_invoices)
        self.assertIn('get_for_tenant(', source)


class TestNoGetInstanceInAdminGenerateInvoices(TestCase):
    """Ensure CustomerAdmin.generate_invoices doesn't call get_instance()."""

    def test_generate_invoices_no_get_instance(self):
        from apps.technician_portal.admin import CustomerAdmin
        source = inspect.getsource(CustomerAdmin.generate_invoices)
        self.assertNotIn(
            'get_instance()', source,
            "CustomerAdmin.generate_invoices still calls BillingConfig.get_instance() "
            "which raises RuntimeError. Use get_for_tenant(customer.tenant) instead."
        )

    def test_generate_invoices_uses_get_for_tenant(self):
        from apps.technician_portal.admin import CustomerAdmin
        source = inspect.getsource(CustomerAdmin.generate_invoices)
        self.assertIn('get_for_tenant(', source)


# ---------------------------------------------------------------------------
# Functional: process_overdue_invoices reads config per-tenant
# ---------------------------------------------------------------------------

class TestProcessOverdueInvoicesFunctional(TestCase):
    """
    process_overdue_invoices should read BillingConfig per tenant and not crash.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='owner007', password='pass', email='owner007@example.com'
        )
        self.tenant = Tenant.objects.create(
            name='Test Tenant CODE-007', slug='tt-code007',
            owner=self.user, is_active=True,
        )
        self.config = BillingConfig.get_for_tenant(self.tenant)
        self.customer = Customer.objects.create(
            name='Fleet Co',
            tenant=self.tenant,
        )

    def test_process_overdue_does_not_raise(self):
        """Task must not raise even when tenants exist with BillingConfig."""
        try:
            result = process_overdue_invoices()
        except RuntimeError as e:
            self.fail(
                f"process_overdue_invoices raised RuntimeError: {e}"
            )
        self.assertIn('updated', result)

    def test_process_overdue_marks_sent_invoices_overdue(self):
        """Invoices past their due date should be flipped to OVERDUE."""
        overdue_inv = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='TEST-007-001',
            status='SENT',
            invoice_date=date.today() - timedelta(days=60),
            due_date=date.today() - timedelta(days=5),
            subtotal=Decimal('100.00'),
            discount=Decimal('0.00'),
            tax_rate=Decimal('0.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            payment_terms='NET30',
        )

        result = process_overdue_invoices()

        overdue_inv.refresh_from_db()
        self.assertEqual(overdue_inv.status, 'OVERDUE')
        self.assertGreaterEqual(result['updated'], 1)


# ---------------------------------------------------------------------------
# Functional: admin generate_invoices action
# ---------------------------------------------------------------------------

class TestAdminGenerateInvoicesFunctional(TestCase):
    """
    CustomerAdmin.generate_invoices should work without crashing even though
    BillingConfig.get_instance() now raises RuntimeError.
    """

    def setUp(self):
        from apps.technician_portal.models import Repair, Technician
        from apps.billing.models import BillingConfig

        self.superuser = User.objects.create_superuser(
            username='admin007', password='pass', email='admin007@example.com'
        )
        self.tenant = Tenant.objects.create(
            name='Admin Test Tenant 007',
            slug='admin-tt-007',
            owner=self.superuser,
            is_active=True,
        )
        BillingConfig.get_for_tenant(self.tenant)  # ensure config exists

        self.customer = Customer.objects.create(
            name='Fleet Admin 007',
            tenant=self.tenant,
        )
        self.tech_user = User.objects.create_user(
            username='tech007', password='pass', email='tech007@example.com'
        )
        self.technician = Technician.objects.create(
            user=self.tech_user,
            tenant=self.tenant,
        )
        # Create a completed repair to invoice.
        # Use cost_override so the pricing service doesn't recalculate cost on save.
        self.repair = Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            technician=self.technician,
            queue_status='COMPLETED',
            damage_type='chip',
            unit_number='UNIT-007',
            cost_override=Decimal('75.00'),
        )
        # Reload so cost reflects whatever save() computed (should equal cost_override)
        self.repair.refresh_from_db()

    def test_generate_invoices_does_not_crash(self):
        """Action must not raise RuntimeError."""
        from apps.technician_portal.admin import CustomerAdmin
        from django.contrib.admin.sites import AdminSite

        ma = CustomerAdmin(Customer, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.superuser

        # Attach a simple message storage stub
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))

        try:
            ma.generate_invoices(request, Customer.objects.filter(pk=self.customer.pk))
        except RuntimeError as e:
            self.fail(f"generate_invoices raised RuntimeError: {e}")

    def test_generate_invoices_creates_draft_invoice(self):
        """Action should create a DRAFT invoice for the customer's unbilled repairs."""
        from apps.technician_portal.admin import CustomerAdmin
        from django.contrib.admin.sites import AdminSite
        from django.contrib.messages.storage.fallback import FallbackStorage

        ma = CustomerAdmin(Customer, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.superuser
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))

        before = Invoice.objects.filter(customer=self.customer).count()
        ma.generate_invoices(request, Customer.objects.filter(pk=self.customer.pk))
        after = Invoice.objects.filter(customer=self.customer).count()

        self.assertEqual(after, before + 1, "Expected exactly one new draft invoice")

        inv = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertEqual(inv.status, 'DRAFT')
        self.assertEqual(inv.tenant, self.tenant)
        # Total should match repair's actual cost (pricing service may adjust it on save)
        self.repair.refresh_from_db()
        self.assertEqual(inv.total, self.repair.cost)

    def test_generate_invoices_uses_tenant_prefix(self):
        """Invoice number prefix should come from the tenant's BillingConfig."""
        from apps.technician_portal.admin import CustomerAdmin
        from django.contrib.admin.sites import AdminSite
        from django.contrib.messages.storage.fallback import FallbackStorage

        config = BillingConfig.get_for_tenant(self.tenant)
        config.invoice_number_prefix = 'ADM007'
        config.save()

        ma = CustomerAdmin(Customer, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.superuser
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))

        ma.generate_invoices(request, Customer.objects.filter(pk=self.customer.pk))

        inv = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertTrue(
            inv.invoice_number.startswith('ADM007-'),
            f"Expected prefix 'ADM007-', got '{inv.invoice_number}'"
        )
