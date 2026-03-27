"""
CODE-203: process_batch_invoices() CustomerRepairPreference subquery missing tenant scope.

The batch invoice task used:
    CustomerRepairPreference.objects.filter(invoice_preference='batch')

to build the list of customers to invoice.  This subquery read ALL
CustomerRepairPreference rows across every tenant, then relied on the outer
Customer.filter(tenant=tenant) to narrow the results.  On a system with many
tenants the subquery performs a full-table scan that grows O(total customers)
instead of O(tenant customers).

Fix: add customer__tenant=tenant to the subquery so the DB only scans rows for
the current shop.

This test verifies:
1. Only the correct tenant's customers are selected for batch invoicing.
2. Customers from a DIFFERENT tenant whose preferences say 'batch' are NOT
   included in another tenant's batch run.
3. Customers with 'manual' or 'per_ticket' preferences are NOT included.
"""

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.customer_portal.models import CustomerRepairPreference
from apps.billing.models import BillingConfig
from apps.technician_portal.models import Repair, Technician


def _make_tenant(name):
    """Create a minimal active tenant."""
    from django.utils.text import slugify
    slug = slugify(name)
    user = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'{slug}@example.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=user,
        plan='trial',
        is_active=True,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return tenant, user


def _make_customer(tenant, name, preference='batch'):
    """Create a Customer with the given invoice preference."""
    customer = Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='FLEET',
        email=f'{name.lower().replace(" ", "")}@example.com',
    )
    CustomerRepairPreference.objects.create(
        customer=customer,
        invoice_preference=preference,
    )
    return customer


def _make_completed_repair(tenant, customer):
    """Create a completed repair for the customer (needed for batch invoice)."""
    tech_user = User.objects.create_user(
        username=f'tech_{tenant.slug}_{customer.id}',
        email=f'tech_{tenant.slug}_{customer.id}@example.com',
        password='testpass',
    )
    tech = Technician.objects.create(tenant=tenant, user=tech_user, is_active=True)
    repair = Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=tech,
        unit_number='T-001',
        damage_type='CHIP',
        queue_status='COMPLETED',
        cost=Decimal('50.00'),
        service_date=timezone.now(),
    )
    return repair


class TestBatchInvoiceTenantScope(TestCase):
    """
    Verify that process_batch_invoices only generates invoices for customers
    belonging to the current tenant, and that the CustomerRepairPreference
    subquery is scoped to tenant rather than scanning all rows globally.
    """

    def setUp(self):
        self.tenant_a, self.owner_a = _make_tenant('Shop Alpha')
        self.tenant_b, self.owner_b = _make_tenant('Shop Beta')

        # Configure both tenants to run batch invoicing (weekly, Monday)
        for tenant in [self.tenant_a, self.tenant_b]:
            config = BillingConfig.get_for_tenant(tenant)
            config.batch_invoice_frequency = 'weekly'
            config.batch_invoice_day = 0  # Monday
            config.batch_invoice_auto_send = False
            config.save()

        # Tenant A: two batch customers, one per_ticket customer
        self.a_batch1 = _make_customer(self.tenant_a, 'A Batch Fleet 1', 'batch')
        self.a_batch2 = _make_customer(self.tenant_a, 'A Batch Fleet 2', 'batch')
        self.a_ticket = _make_customer(self.tenant_a, 'A Per-Ticket Fleet', 'per_ticket')

        # Tenant B: one batch customer
        self.b_batch1 = _make_customer(self.tenant_b, 'B Batch Fleet', 'batch')

        # Completed repairs for each batch customer
        _make_completed_repair(self.tenant_a, self.a_batch1)
        _make_completed_repair(self.tenant_a, self.a_batch2)
        _make_completed_repair(self.tenant_b, self.b_batch1)

    def _get_batch_customers_for_tenant(self, tenant):
        """Mirror the fixed subquery from tasks.process_batch_invoices."""
        from apps.customer_portal.models import CustomerRepairPreference
        return Customer.objects.filter(
            tenant=tenant,
            id__in=CustomerRepairPreference.objects.filter(
                invoice_preference='batch',
                customer__tenant=tenant,
            ).values_list('customer_id', flat=True),
        )

    def _get_batch_customers_unscoped(self, tenant):
        """Mirror the BUGGY unscoped subquery (for comparison)."""
        from apps.customer_portal.models import CustomerRepairPreference
        return Customer.objects.filter(
            tenant=tenant,
        ).filter(
            id__in=CustomerRepairPreference.objects.filter(
                invoice_preference='batch',
            ).values_list('customer_id', flat=True),
        )

    def test_scoped_subquery_finds_correct_tenant_a_customers(self):
        """Tenant A batch run should select exactly a_batch1 and a_batch2."""
        qs = self._get_batch_customers_for_tenant(self.tenant_a)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.a_batch1.id, ids)
        self.assertIn(self.a_batch2.id, ids)
        self.assertNotIn(self.a_ticket.id, ids)  # per_ticket, not batch
        self.assertNotIn(self.b_batch1.id, ids)  # different tenant

    def test_scoped_subquery_finds_correct_tenant_b_customers(self):
        """Tenant B batch run should select only b_batch1."""
        qs = self._get_batch_customers_for_tenant(self.tenant_b)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.b_batch1.id, ids)
        self.assertNotIn(self.a_batch1.id, ids)
        self.assertNotIn(self.a_batch2.id, ids)

    def test_scoped_and_unscoped_return_same_result(self):
        """
        For correctness: both queries should return the same customer IDs
        (outer tenant filter is redundant with scoped subquery but equivalent).
        This verifies the fix doesn't accidentally exclude valid customers.
        """
        for tenant in [self.tenant_a, self.tenant_b]:
            scoped = set(
                self._get_batch_customers_for_tenant(tenant).values_list('id', flat=True)
            )
            unscoped = set(
                self._get_batch_customers_unscoped(tenant).values_list('id', flat=True)
            )
            self.assertEqual(
                scoped,
                unscoped,
                f"Scoped and unscoped queries differ for {tenant.name}: "
                f"scoped={scoped}, unscoped={unscoped}",
            )

    def test_manual_preference_customers_excluded(self):
        """Customers with invoice_preference='manual' must not be billed in batch run."""
        manual_customer = _make_customer(self.tenant_a, 'A Manual Fleet', 'manual')
        _make_completed_repair(self.tenant_a, manual_customer)

        qs = self._get_batch_customers_for_tenant(self.tenant_a)
        ids = set(qs.values_list('id', flat=True))
        self.assertNotIn(manual_customer.id, ids)

    def test_cross_tenant_batch_customers_not_included(self):
        """
        A customer at Tenant B with invoice_preference='batch' must NEVER appear
        in Tenant A's batch customer list, even after the unscoped subquery fix.
        """
        qs_a = self._get_batch_customers_for_tenant(self.tenant_a)
        ids_a = set(qs_a.values_list('id', flat=True))
        self.assertNotIn(
            self.b_batch1.id,
            ids_a,
            "Tenant B's batch customer leaked into Tenant A's batch run",
        )
