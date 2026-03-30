"""
CODE-190: DashboardService._filter() crashed with FieldError on Payment querysets.

Root cause:
    DashboardService._filter(qs) blindly applied filter(tenant=self.tenant) to
    any queryset passed in.  Invoice has a direct tenant FK, so _filter(Invoice.objects)
    works.  Payment does NOT have a direct tenant FK — the path is
    Payment → Invoice → Tenant.  Calling _filter(Payment.objects) therefore raised:

        FieldError: Cannot resolve keyword 'tenant' into field. Choices are:
            amount, created_at, id, invoice, invoice_id, notes, payment_date,
            payment_method, point_transactions, recorded_by, recorded_by_id,
            reference_number, stripe_charge_id, stripe_payment_id

    Three methods were affected:
        - get_revenue_metrics()   → payment revenue sums crashed
        - get_payment_metrics()   → recent-payment list and method breakdown crashed
        - get_trends()            → daily-revenue chart data crashed

    Because these all call get_full_dashboard(), the entire billing dashboard
    API endpoint (/billing/dashboard/) crashed with a 500 error whenever called.

Fix:
    Added _filter_payment() helper that uses filter(invoice__tenant=self.tenant)
    for Payment querysets.  All four Payment.objects usages now call
    _filter_payment() instead of _filter().

Tests:
    1. _filter_payment() scopes to the correct tenant (never leaks cross-tenant).
    2. get_revenue_metrics() returns without FieldError.
    3. get_payment_metrics() returns without FieldError.
    4. get_trends() returns without FieldError.
    5. get_full_dashboard() returns without FieldError (integration test).
    6. Cross-tenant isolation: payments from Shop B don't appear in Shop A's dashboard.
"""

from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User


class DashboardServicePaymentFilterTests(TestCase):
    """Regression tests for CODE-190."""

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant, TenantMembership
        from apps.technician_portal.models import Customer
        from apps.billing.models import BillingConfig, Invoice, Payment

        # --- Shop A ---
        cls.owner_a = User.objects.create_user('owner_a', 'a@example.com', 'pass')
        cls.tenant_a = Tenant.objects.create(name='Shop A', slug='shop-a', owner=cls.owner_a)
        BillingConfig.objects.create(tenant=cls.tenant_a)
        TenantMembership.objects.create(
            tenant=cls.tenant_a, user=cls.owner_a, role='owner', is_active=True
        )
        cls.customer_a = Customer.objects.create(name='Fleet A', tenant=cls.tenant_a)

        cls.invoice_a = Invoice.objects.create(
            tenant=cls.tenant_a,
            customer=cls.customer_a,
            invoice_number='INV-A-001',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            status='PAID',
            amount_paid=Decimal('100.00'),
        )
        cls.payment_a = Payment.objects.create(
            invoice=cls.invoice_a,
            amount=Decimal('100.00'),
            payment_method='CHECK',
        )

        # --- Shop B ---
        cls.owner_b = User.objects.create_user('owner_b', 'b2@example.com', 'pass')
        cls.tenant_b = Tenant.objects.create(name='Shop B', slug='shop-b', owner=cls.owner_b)
        BillingConfig.objects.create(tenant=cls.tenant_b)
        cls.customer_b = Customer.objects.create(name='Fleet B', tenant=cls.tenant_b)
        cls.invoice_b = Invoice.objects.create(
            tenant=cls.tenant_b,
            customer=cls.customer_b,
            invoice_number='INV-B-001',
            subtotal=Decimal('200.00'),
            total=Decimal('200.00'),
            status='PAID',
            amount_paid=Decimal('200.00'),
        )
        cls.payment_b = Payment.objects.create(
            invoice=cls.invoice_b,
            amount=Decimal('200.00'),
            payment_method='CASH',
        )

    # ------------------------------------------------------------------
    # Core fix: _filter_payment uses invoice__tenant, not tenant
    # ------------------------------------------------------------------

    def test_filter_payment_scopes_to_correct_tenant(self):
        """_filter_payment returns only payments whose invoices belong to the tenant."""
        from apps.billing.models import Payment
        from apps.billing.services.dashboard_service import DashboardService

        svc_a = DashboardService(self.tenant_a)
        qs = svc_a._filter_payment(Payment.objects)
        self.assertIn(self.payment_a, qs)
        self.assertNotIn(self.payment_b, qs)

    def test_filter_payment_excludes_other_tenant(self):
        """_filter_payment called for tenant B excludes tenant A's payments."""
        from apps.billing.models import Payment
        from apps.billing.services.dashboard_service import DashboardService

        svc_b = DashboardService(self.tenant_b)
        qs = svc_b._filter_payment(Payment.objects)
        self.assertIn(self.payment_b, qs)
        self.assertNotIn(self.payment_a, qs)

    def test_filter_payment_no_tenant_returns_none_qs(self):
        """_filter_payment with no tenant returns an empty queryset."""
        from apps.billing.models import Payment
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(tenant=None)
        qs = svc._filter_payment(Payment.objects)
        self.assertEqual(qs.count(), 0)

    # ------------------------------------------------------------------
    # get_revenue_metrics — previously raised FieldError on Payment filter
    # ------------------------------------------------------------------

    def test_get_revenue_metrics_no_field_error(self):
        """get_revenue_metrics() must not raise FieldError (CODE-190 regression)."""
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(self.tenant_a)
        result = svc.get_revenue_metrics()  # Should NOT raise FieldError
        self.assertIn('today', result)
        self.assertIn('this_month', result)

    def test_get_revenue_metrics_returns_correct_amounts(self):
        """Revenue metrics include this tenant's payments and exclude other tenants'."""
        from apps.billing.services.dashboard_service import DashboardService
        import datetime

        svc_a = DashboardService(self.tenant_a)
        result = svc_a.get_revenue_metrics()

        # Payment was made today, so it should show up in this_month (at minimum)
        self.assertGreaterEqual(result['this_month'], 100.0)
        # Shop B's $200 payment should NOT be counted
        self.assertLess(result['this_month'], 200.0)

    # ------------------------------------------------------------------
    # get_payment_metrics — previously raised FieldError on Payment filter
    # ------------------------------------------------------------------

    def test_get_payment_metrics_no_field_error(self):
        """get_payment_metrics() must not raise FieldError (CODE-190 regression)."""
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(self.tenant_a)
        result = svc.get_payment_metrics()  # Should NOT raise FieldError
        self.assertIn('last_30_days', result)
        self.assertIn('recent', result)

    def test_get_payment_metrics_cross_tenant_isolation(self):
        """get_payment_metrics() for Shop A does not include Shop B's payments."""
        from apps.billing.services.dashboard_service import DashboardService

        svc_a = DashboardService(self.tenant_a)
        result = svc_a.get_payment_metrics()

        recent_ids = [p['id'] for p in result['recent']]
        self.assertIn(self.payment_a.id, recent_ids)
        self.assertNotIn(self.payment_b.id, recent_ids)

    # ------------------------------------------------------------------
    # get_trends — previously raised FieldError on Payment filter
    # ------------------------------------------------------------------

    def test_get_trends_no_field_error(self):
        """get_trends() must not raise FieldError (CODE-190 regression)."""
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(self.tenant_a)
        result = svc.get_trends()  # Should NOT raise FieldError
        self.assertIn('daily_revenue_30d', result)
        self.assertIn('weekly_invoices_12w', result)

    # ------------------------------------------------------------------
    # get_full_dashboard — integration test (all three methods at once)
    # ------------------------------------------------------------------

    def test_get_full_dashboard_no_field_error(self):
        """
        get_full_dashboard() must not raise FieldError.

        This is the critical regression test: the /billing/dashboard/ API
        endpoint was returning 500 errors because all three broken methods
        (revenue, payments, trends) are called here.
        """
        from apps.billing.services.dashboard_service import DashboardService

        svc = DashboardService(self.tenant_a)
        result = svc.get_full_dashboard()  # Should NOT raise FieldError
        self.assertIn('revenue', result)
        self.assertIn('payments', result)
        self.assertIn('trends', result)
        self.assertIn('invoices', result)
        self.assertIn('customers', result)
        self.assertIn('alerts', result)
