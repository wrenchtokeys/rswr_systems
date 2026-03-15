"""
CODE-037 Regression: Admin generate_invoices action ignores CANCELLED invoices
and skip_invoicing flag.

Bug 1 (Cancelled invoice blocks re-billing):
  generate_invoices() used:
      .exclude(invoice_line_items__isnull=False)
  This excluded repairs linked to ANY invoice line item — including line items
  on CANCELLED invoices.  A shop that cancels an invoice can NEVER re-invoice
  those repairs via the admin action.

Bug 2 (skip_invoicing flag ignored):
  The action did not filter out repairs with skip_invoicing=True.
  Repairs explicitly flagged as "already accounted for" got included in
  admin-generated draft invoices, causing double-billing.

Fix:
  - Replaced bare `.exclude(invoice_line_items__isnull=False)` with a scoped
    subquery that only excludes repairs on DRAFT/SENT/PARTIAL/PAID invoices
    (same pattern as InvoiceTrackingService.get_uninvoiced_repairs).
  - Added `.filter(skip_invoicing=False)` to the queryset.

Tests:
  1. Repair on an active DRAFT invoice → excluded (correct, no double-billing)
  2. Repair on a CANCELLED invoice → NOT excluded (re-invoiceable)
  3. Repair with skip_invoicing=True → excluded (respect the flag)
  4. Repair with skip_invoicing=False and no invoice → included (normal flow)
  5. Cross-tenant scoping: invoiced_repair_ids only considers the customer's tenant
  6. Multiple repairs, some active-invoiced, some cancelled: only active-invoiced ones skipped
"""

import uuid
from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.billing.models import Invoice, InvoiceLineItem
from apps.technician_portal.models import Repair, Technician
from apps.technician_portal.admin import CustomerAdmin
from core.models import Customer


def _make_tenant(slug):
    uid = uuid.uuid4().hex[:4]
    owner = User.objects.create_user(
        username=f'own{slug}{uid}',
        email=f'own{slug}{uid}@test.com',
        password='pass',
    )
    return Tenant.objects.create(
        name=f'T-{slug}-{uid}',
        slug=f'{slug}{uid}',
        subdomain=f'{slug}{uid}',
        plan='trial',
        trial_started_at=timezone.now(),
        owner=owner,
        is_active=True,
    )


def _make_customer(tenant, name='Fleet Co'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=f'{uuid.uuid4().hex[:8]}@fleet.com',
    )


def _make_technician(tenant):
    user = User.objects.create_user(
        username=f'tech_{uuid.uuid4().hex[:6]}',
        password='pass',
    )
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_active=True,
    )


def _make_repair(customer, tenant, technician, cost=Decimal('45.00'), skip_invoicing=False, unit_number='101'):
    """
    Create a completed repair with an explicit cost.
    We use cost_override so Repair.save() doesn't recalculate the cost via
    the pricing service (which would ignore our test value).
    """
    repair = Repair.objects.create(
        customer=customer,
        tenant=tenant,
        technician=technician,
        unit_number=unit_number,
        queue_status='COMPLETED',
        service_date=timezone.now().date(),
        cost_override=cost,
        skip_invoicing=skip_invoicing,
    )
    # Reload to get the cost field as saved by Repair.save()
    repair.refresh_from_db()
    return repair


def _make_invoice(tenant, customer, status='DRAFT'):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-{uuid.uuid4().hex[:8]}',
        status=status,
        invoice_date=timezone.now().date(),
        subtotal=Decimal('45.00'),
        discount=Decimal('0.00'),
        tax_rate=Decimal('0.00'),
        tax_amount=Decimal('0.00'),
        total=Decimal('45.00'),
        amount_paid=Decimal('0.00'),
        payment_terms='NET30',
    )


def _attach_repair_to_invoice(invoice, repair):
    return InvoiceLineItem.objects.create(
        invoice=invoice,
        repair=repair,
        description='Repair',
        quantity=1,
        unit_price=repair.cost,
        discount=Decimal('0.00'),
        amount=repair.cost,
        repair_date=repair.service_date,
        unit_number=repair.unit_number or '',
    )


class AdminGenerateInvoicesCancelledTest(TestCase):
    """Tests for the generate_invoices admin action's repair scoping logic."""

    def setUp(self):
        self.tenant = _make_tenant('main')
        self.customer = _make_customer(self.tenant)
        self.technician = _make_technician(self.tenant)

        # Admin user for requests
        self.admin_user = User.objects.create_superuser(
            username='superadmin', email='admin@test.com', password='pass'
        )
        self.site = AdminSite()
        self.admin = CustomerAdmin(Customer, self.site)
        self.factory = RequestFactory()

    def _run_action(self, customers):
        """Invoke generate_invoices on a queryset of customers."""
        from django.contrib.messages.storage.fallback import FallbackStorage
        request = self.factory.post('/')
        request.user = self.admin_user
        # Admin's message_user() requires messages middleware; set up in-memory storage.
        setattr(request, 'session', 'session')
        messages_storage = FallbackStorage(request)
        setattr(request, '_messages', messages_storage)
        qs = Customer.objects.filter(id__in=[c.id for c in customers])
        self.admin.generate_invoices(request, qs)

    def test_repair_on_draft_invoice_is_excluded(self):
        """A repair already on a DRAFT invoice must NOT be re-invoiced."""
        repair = _make_repair(self.customer, self.tenant, self.technician)
        invoice = _make_invoice(self.tenant, self.customer, status='DRAFT')
        _attach_repair_to_invoice(invoice, repair)

        initial_count = Invoice.objects.filter(tenant=self.tenant).count()
        self._run_action([self.customer])
        final_count = Invoice.objects.filter(tenant=self.tenant).count()

        self.assertEqual(initial_count, final_count, "No new invoice should be created — repair is already on a DRAFT invoice")

    def test_repair_on_cancelled_invoice_is_included(self):
        """A repair on a CANCELLED invoice MUST be re-invoiceable."""
        repair = _make_repair(self.customer, self.tenant, self.technician)
        cancelled_invoice = _make_invoice(self.tenant, self.customer, status='CANCELLED')
        _attach_repair_to_invoice(cancelled_invoice, repair)

        initial_count = Invoice.objects.filter(tenant=self.tenant).count()
        self._run_action([self.customer])
        final_count = Invoice.objects.filter(tenant=self.tenant).count()

        self.assertEqual(final_count, initial_count + 1, "A new draft invoice should be created for the repair on the cancelled invoice")

        new_invoice = Invoice.objects.filter(tenant=self.tenant).exclude(id=cancelled_invoice.id).latest('id')
        self.assertEqual(new_invoice.status, 'DRAFT')
        self.assertEqual(new_invoice.line_items.filter(repair=repair).count(), 1)

    def test_skip_invoicing_repair_is_excluded(self):
        """Repairs with skip_invoicing=True must not appear in admin-generated invoices."""
        _make_repair(self.customer, self.tenant, self.technician, skip_invoicing=True)

        initial_count = Invoice.objects.filter(tenant=self.tenant).count()
        self._run_action([self.customer])
        final_count = Invoice.objects.filter(tenant=self.tenant).count()

        self.assertEqual(initial_count, final_count, "skip_invoicing=True repairs must be excluded from admin-generated invoices")

    def test_normal_uninvoiced_repair_is_included(self):
        """A completed repair with no invoice and skip_invoicing=False must be invoiced."""
        repair = _make_repair(self.customer, self.tenant, self.technician, skip_invoicing=False)

        initial_count = Invoice.objects.filter(tenant=self.tenant).count()
        self._run_action([self.customer])
        final_count = Invoice.objects.filter(tenant=self.tenant).count()

        self.assertEqual(final_count, initial_count + 1, "A draft invoice should be created for the uninvoiced repair")

        new_invoice = Invoice.objects.filter(tenant=self.tenant).latest('id')
        self.assertEqual(new_invoice.status, 'DRAFT')
        self.assertEqual(new_invoice.line_items.filter(repair=repair).count(), 1)

    def test_cross_tenant_invoice_does_not_block_own_tenant(self):
        """An invoice from another tenant must not suppress this tenant's repair."""
        other_tenant = _make_tenant('other')
        other_customer = _make_customer(other_tenant, 'Other Fleet')
        other_tech = _make_technician(other_tenant)

        # Same repair PK is impossible to share — but we create a repair in our tenant
        # that is NOT on any invoice of its own, while another tenant has a repair on an invoice.
        # The key test is that our invoiced_repair_ids subquery is scoped to customer.tenant.
        repair = _make_repair(self.customer, self.tenant, self.technician)

        other_repair = _make_repair(other_customer, other_tenant, other_tech)
        other_invoice = _make_invoice(other_tenant, other_customer, status='DRAFT')
        _attach_repair_to_invoice(other_invoice, other_repair)

        initial_count = Invoice.objects.filter(tenant=self.tenant).count()
        self._run_action([self.customer])
        final_count = Invoice.objects.filter(tenant=self.tenant).count()

        self.assertEqual(final_count, initial_count + 1, "Our tenant's repair should be invoiced regardless of other tenants")

    def test_mixed_repairs_only_unbilled_get_invoiced(self):
        """When a customer has both active-invoiced and cancelled-invoiced repairs,
        only the one on the cancelled invoice should appear in the new draft."""
        active_repair = _make_repair(self.customer, self.tenant, self.technician, cost=Decimal('50.00'), unit_number='A01')
        cancelled_repair = _make_repair(self.customer, self.tenant, self.technician, cost=Decimal('75.00'), unit_number='B02')

        active_invoice = _make_invoice(self.tenant, self.customer, status='SENT')
        _attach_repair_to_invoice(active_invoice, active_repair)

        cancelled_invoice = _make_invoice(self.tenant, self.customer, status='CANCELLED')
        _attach_repair_to_invoice(cancelled_invoice, cancelled_repair)

        self._run_action([self.customer])

        # One new draft invoice should have been created
        new_invoices = Invoice.objects.filter(
            tenant=self.tenant,
            status='DRAFT',
        ).exclude(id=active_invoice.id).exclude(id=cancelled_invoice.id)
        self.assertEqual(new_invoices.count(), 1)

        new_invoice = new_invoices.first()
        # Only the cancelled_repair should be in it
        self.assertEqual(new_invoice.line_items.filter(repair=cancelled_repair).count(), 1)
        self.assertEqual(new_invoice.line_items.filter(repair=active_repair).count(), 0)
        # Total should reflect only the cancelled_repair's actual cost (set by pricing service)
        cancelled_repair.refresh_from_db()
        self.assertEqual(new_invoice.total, cancelled_repair.cost)
