"""
CODE-121 regression tests: admin CustomerAdmin.generate_invoices action must
apply TaxService and get_discounted_cost() — not hardcode tax_rate/amount=0.

Bug: The 'Generate draft invoices' admin action created invoices with hardcoded
    tax_rate=0, tax_amount=0
    and used r.cost (not r.get_discounted_cost()) for line item amounts.
Result: All admin-generated invoices had $0 tax even for shops with active tax
    rates, and reward discounts were silently ignored.

Fix: Delegate to InvoiceTrackingService.create_invoice_from_repairs() which
    already calls TaxService.apply_tax_to_invoice() and get_discounted_cost().
"""
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.billing.models import Invoice, InvoiceLineItem, BillingConfig, TaxRate
from apps.technician_portal.admin import CustomerAdmin
from apps.technician_portal.models import Repair, Customer, Technician
from apps.tenants.models import Tenant, TenantMembership


def _make_shop(name, slug):
    owner = User.objects.create_user(username=f'owner_{slug}', password='x')
    tenant = Tenant.objects.create(name=name, slug=slug, owner=owner, is_active=True)
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    BillingConfig.get_for_tenant(tenant)
    return tenant, owner


def _make_tech(tenant, suffix='a'):
    user = User.objects.create_user(username=f'tech_{suffix}', password='x')
    TenantMembership.objects.create(user=user, tenant=tenant, role='technician', is_active=True)
    return Technician.objects.create(user=user, tenant=tenant)


def _make_repair(customer, tech, cost='50.00', status='COMPLETED'):
    return Repair.objects.create(
        customer=customer,
        tenant=customer.tenant,
        technician=tech,
        unit_number='UNIT-1',
        queue_status=status,
        cost=Decimal(cost),
    )


class AdminGenerateInvoicesTaxTests(TestCase):
    """TaxService must be called when admin generates draft invoices."""

    def setUp(self):
        self.tenant, self.owner = _make_shop('Tax Shop', 'tax-shop-121')
        self.tech = _make_tech(self.tenant, 'tax121')
        self.customer = Customer.objects.create(
            name='Tax Customer',
            tenant=self.tenant,
            email='tax@test.com',
        )
        # Enable tax: 10% rate. Tax overhaul: the config flag decides IF tax
        # applies; the TaxRate row supplies the rate.
        config = BillingConfig.get_for_tenant(self.tenant)
        config.tax_enabled = True
        config.save()
        TaxRate.objects.create(
            tenant=self.tenant,
            city='TestCity',
            state='TX',
            state_rate=Decimal('6.000'),
            county_rate=Decimal('2.000'),
            city_rate=Decimal('2.000'),
            special_rate=Decimal('0.000'),
            is_active=True,
        )

        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = CustomerAdmin(Customer, self.site)

        # Superuser for admin action
        self.superuser = User.objects.create_superuser(
            username='super_121', password='x', email='super121@test.com'
        )

    def _run_action(self, customers):
        """Run the generate_invoices admin action."""
        request = self.factory.post('/')
        request.user = self.superuser
        # Attach _messages support
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        self.admin.generate_invoices(request, Customer.objects.filter(pk__in=[c.pk for c in customers]))

    def test_tax_applied_to_admin_generated_invoice(self):
        """Admin generate_invoices must apply TaxService (not hardcode $0 tax)."""
        _make_repair(self.customer, self.tech, cost='50.00')

        self._run_action([self.customer])

        invoice = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertGreater(invoice.tax_amount, Decimal('0.00'),
                           "Tax amount must be > $0 when TaxRate is active")
        # total must incorporate tax
        self.assertEqual(invoice.total, invoice.subtotal + invoice.tax_amount - invoice.discount)

    def test_tax_rate_field_set_on_invoice(self):
        """tax_rate field on the invoice must reflect the configured rate."""
        _make_repair(self.customer, self.tech, cost='100.00')

        self._run_action([self.customer])

        invoice = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertGreater(invoice.tax_rate, Decimal('0'))

    def test_no_tax_when_no_active_taxrate(self):
        """When no TaxRate exists for a tenant, invoice must have $0 tax."""
        tenant2, _ = _make_shop('No-Tax Shop', 'notax-121')
        tech2 = _make_tech(tenant2, 'notax121')
        customer2 = Customer.objects.create(
            name='No Tax Customer', tenant=tenant2, email='notax@test.com'
        )
        _make_repair(customer2, tech2, cost='50.00')

        self._run_action([customer2])

        invoice = Invoice.objects.filter(customer=customer2).latest('id')
        self.assertEqual(invoice.tax_amount, Decimal('0.00'))
        # Total should equal subtotal minus discount (no tax)
        self.assertEqual(invoice.total, invoice.subtotal - invoice.discount)

    def test_tax_exempt_customer_zero_tax(self):
        """Tax-exempt customers must have $0 tax even when TaxRate is active."""
        self.customer.tax_exempt = True
        self.customer.save()
        _make_repair(self.customer, self.tech, cost='100.00')

        self._run_action([self.customer])

        invoice = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertEqual(invoice.tax_amount, Decimal('0.00'))

    def test_line_items_created(self):
        """Line items should be created for each repair."""
        repair1 = _make_repair(self.customer, self.tech, cost='50.00')
        repair2 = _make_repair(self.customer, self.tech, cost='40.00')

        self._run_action([self.customer])

        invoice = Invoice.objects.filter(customer=self.customer).latest('id')
        line_items = InvoiceLineItem.objects.filter(invoice=invoice)
        self.assertEqual(line_items.count(), 2)
        repair_ids = set(line_items.values_list('repair_id', flat=True))
        self.assertIn(repair1.pk, repair_ids)
        self.assertIn(repair2.pk, repair_ids)

    def test_no_double_billing(self):
        """Already-invoiced repairs must not be re-billed."""
        repair = _make_repair(self.customer, self.tech, cost='50.00')
        # First run
        self._run_action([self.customer])
        first_count = Invoice.objects.filter(customer=self.customer).count()

        # Second run — repair is now invoiced; should create no new invoice
        self._run_action([self.customer])
        second_count = Invoice.objects.filter(customer=self.customer).count()
        self.assertEqual(first_count, second_count, "Second action should not create a duplicate invoice")

    def test_skip_invoicing_repair_excluded(self):
        """Repairs with skip_invoicing=True must be skipped."""
        r1 = _make_repair(self.customer, self.tech, cost='50.00')
        r2 = _make_repair(self.customer, self.tech, cost='40.00')
        r2.skip_invoicing = True
        r2.save()

        self._run_action([self.customer])

        invoice = Invoice.objects.filter(customer=self.customer).latest('id')
        line_items = InvoiceLineItem.objects.filter(invoice=invoice)
        repair_ids = set(line_items.values_list('repair_id', flat=True))
        self.assertIn(r1.pk, repair_ids)
        self.assertNotIn(r2.pk, repair_ids)

    def test_customer_with_no_unbilled_repairs_skipped(self):
        """Customers with no unbilled repairs must not get a new invoice."""
        initial_count = Invoice.objects.count()
        self._run_action([self.customer])
        self.assertEqual(Invoice.objects.count(), initial_count)

    def test_invoice_status_is_draft(self):
        """Admin-generated invoices must be DRAFT (not SENT)."""
        _make_repair(self.customer, self.tech, cost='50.00')

        self._run_action([self.customer])

        invoice = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertEqual(invoice.status, 'DRAFT')
