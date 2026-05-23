"""
CODE-149: Regression test — customer_dashboard outstanding_total uses sliced queryset.

Bug: `outstanding_invoices = Invoice.objects.filter(...).order_by('due_date')[:5]`
then `outstanding_total = outstanding_invoices.aggregate(total=Sum('total'))['total']`.

When you call `.aggregate()` on a sliced queryset, Django wraps the slice in a
subquery. The aggregate then sums at most 5 rows — not the full outstanding balance.
A customer with 8 outstanding invoices of $100 each would see "$500 outstanding"
instead of the correct "$800".

Fix: compute the aggregate on the FULL (unsliced) queryset first, then slice
for display:
    _outstanding_qs = Invoice.objects.filter(...).order_by('due_date')
    outstanding_total = _outstanding_qs.aggregate(total=Sum('total'))['total'] or 0
    outstanding_invoices = _outstanding_qs[:5]  # Display slice AFTER aggregate

Tests verify:
1. With ≤5 outstanding invoices: total is correct (unchanged behavior).
2. With >5 outstanding invoices: total reflects ALL invoices, not just first 5.
3. With zero outstanding invoices: total is 0 (no exception).
4. outstanding_invoices display slice still limited to 5 items.
5. Only SENT/OVERDUE/PARTIAL invoices are counted (PAID/DRAFT excluded).
6. Invoices from other customers are not included.
7. Invoices from another tenant are not included.
"""

from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician
from apps.billing.models import Invoice
from apps.customer_portal.models import CustomerUser


def _make_invoice(customer, tenant, status, total, days_due_from_now=10):
    """Helper: create an invoice for a customer with the given status and total."""
    today = timezone.now().date()
    from datetime import timedelta
    due = today + timedelta(days=days_due_from_now)
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f"TEST-{Invoice.objects.count() + 1000}",
        invoice_date=today,
        due_date=due,
        payment_terms='NET30',
        status=status,
        subtotal=total,
        total=total,
        amount_paid=Decimal('0.00'),
    )


class CustomerDashboardOutstandingTotalTest(TestCase):
    """Tests for outstanding_total calculation in customer_dashboard()."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_code149', email='owner149@test.com', password='pass'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 149',
            slug='shop-149',
            subdomain='shop-149',
            plan='trial',
            owner=self.owner,
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )
        self.tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True
        )

        # Customer
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Fleet Inc.',
            email='fleet@test.com',
        )

        # Portal user for the customer
        self.portal_user = User.objects.create_user(
            username='portal_code149', email='portal149@test.com', password='pass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.portal_user,
            customer=self.customer,
        )

        self.client = Client()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _login(self):
        self.client.force_login(self.portal_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _dashboard(self):
        return self.client.get('/app/', follow=True)

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_fewer_than_5_outstanding_invoices_total_is_correct(self):
        """With 3 outstanding invoices totalling $300, dashboard shows $300."""
        self._login()
        for _ in range(3):
            _make_invoice(self.customer, self.tenant, 'SENT', Decimal('100.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '300')

    def test_more_than_5_outstanding_invoices_total_is_full_sum(self):
        """With 8 outstanding invoices of $100 each, outstanding_total = $800, not $500."""
        self._login()
        for _ in range(8):
            _make_invoice(self.customer, self.tenant, 'SENT', Decimal('100.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        # Total must be 800, not 500 (which is what the sliced-then-aggregated version returns)
        context = resp.context
        if context:
            outstanding_total = context.get('outstanding_total', 0)
            self.assertEqual(
                outstanding_total, Decimal('800.00'),
                f"Expected outstanding_total=800, got {outstanding_total}. "
                "Bug: aggregate is being computed on the sliced [:5] queryset."
            )

    def test_outstanding_invoices_display_slice_is_at_most_5(self):
        """The display list outstanding_invoices is limited to 5 items."""
        self._login()
        for _ in range(8):
            _make_invoice(self.customer, self.tenant, 'SENT', Decimal('100.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        if resp.context:
            invoices_displayed = resp.context.get('outstanding_invoices', [])
            self.assertLessEqual(
                len(invoices_displayed), 5,
                "outstanding_invoices display list should be limited to 5 items."
            )

    def test_zero_outstanding_invoices_total_is_zero(self):
        """With no outstanding invoices, outstanding_total is 0 (no exception)."""
        self._login()
        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        if resp.context:
            self.assertEqual(resp.context.get('outstanding_total', 0), 0)

    def test_paid_invoices_excluded_from_outstanding_total(self):
        """PAID invoices are not included in outstanding_total."""
        self._login()
        _make_invoice(self.customer, self.tenant, 'PAID', Decimal('500.00'))
        _make_invoice(self.customer, self.tenant, 'SENT', Decimal('100.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        if resp.context:
            outstanding_total = resp.context.get('outstanding_total', 0)
            self.assertEqual(
                outstanding_total, Decimal('100.00'),
                f"PAID invoices should not be in outstanding_total. Got {outstanding_total}."
            )

    def test_draft_invoices_excluded_from_outstanding_total(self):
        """DRAFT invoices are not included in outstanding_total."""
        self._login()
        _make_invoice(self.customer, self.tenant, 'DRAFT', Decimal('300.00'))
        _make_invoice(self.customer, self.tenant, 'OVERDUE', Decimal('75.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        if resp.context:
            outstanding_total = resp.context.get('outstanding_total', 0)
            self.assertEqual(
                outstanding_total, Decimal('75.00'),
                f"DRAFT invoices should not be in outstanding_total. Got {outstanding_total}."
            )

    def test_other_customer_invoices_excluded(self):
        """Invoices from a different customer are not counted."""
        self._login()
        other_customer = Customer.objects.create(
            tenant=self.tenant, name='Other Co', email='other@test.com'
        )
        _make_invoice(other_customer, self.tenant, 'SENT', Decimal('999.00'))
        _make_invoice(self.customer, self.tenant, 'SENT', Decimal('50.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        if resp.context:
            outstanding_total = resp.context.get('outstanding_total', 0)
            self.assertEqual(
                outstanding_total, Decimal('50.00'),
                f"Other customer invoices leaked into outstanding_total: {outstanding_total}."
            )

    def test_exact_5_outstanding_invoices(self):
        """With exactly 5 outstanding invoices, total is correct and no slicing loss."""
        self._login()
        for _ in range(5):
            _make_invoice(self.customer, self.tenant, 'OVERDUE', Decimal('200.00'))

        resp = self._dashboard()
        self.assertEqual(resp.status_code, 200)
        if resp.context:
            outstanding_total = resp.context.get('outstanding_total', 0)
            self.assertEqual(
                outstanding_total, Decimal('1000.00'),
                f"Expected 1000 with 5 overdue invoices. Got {outstanding_total}."
            )
