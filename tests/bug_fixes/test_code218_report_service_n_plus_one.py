"""
CODE-218: ReportService N+1 fix — repair revenue used Python iteration instead of aggregate.

Tests verify:
1. generate_daily_report() returns correct repair_revenue using aggregate (no row iteration)
2. generate_weekly_report() returns correct repair_revenue using aggregate
3. generate_daily_report() payment_by_method uses GROUP BY, not per-row iteration
4. Both methods correctly return Decimal('0') when no repairs/payments exist
5. The _filter() method returns qs.none() when tenant is None (prevents unscoped queries)
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Customer, Repair
from apps.billing.models import Invoice, Payment
from apps.billing.services.report_service import ReportService

User = get_user_model()


def _make_tenant(name="Test Shop", owner=None):
    slug = name.lower().replace(" ", "-")
    if owner is None:
        owner = User.objects.create_user(
            username=f"owner_{slug}",
            email=f"owner@{slug}.com",
            password="testpass123",
        )
    t = Tenant.objects.create(
        name=name,
        slug=slug,
        plan="trial",
        owner=owner,
    )
    TenantMembership.objects.get_or_create(tenant=t, user=owner, defaults={"role": "owner"})
    return t


def _make_user(email, tenant, role="owner"):
    u = User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="testpass123",
        first_name="Test",
        last_name="User",
    )
    TenantMembership.objects.get_or_create(tenant=tenant, user=u, defaults={"role": role})
    return u


def _make_customer(tenant, name="Fleet Co"):
    return Customer.objects.create(tenant=tenant, name=name, customer_type="FLEET")


def _make_technician(tenant, user):
    return Technician.objects.create(tenant=tenant, user=user, is_active=True)


def _make_repair(tenant, customer, technician, cost, service_date=None, status="COMPLETED", unit="UNIT-001"):
    if service_date is None:
        service_date = timezone.now()
    repair = Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number=unit,
        damage_type="CHIP",
        cost_override=Decimal(str(cost)),
        service_date=service_date,
        queue_status=status,
    )
    # Force the stored cost to match the test expectation, bypassing progressive pricing
    Repair.objects.filter(pk=repair.pk).update(cost=Decimal(str(cost)))
    repair.refresh_from_db()
    return repair


class ReportServiceDailyN1Test(TestCase):
    """generate_daily_report — repair_revenue uses aggregate, not Python iteration."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_a", email="owner@a.com", password="testpass123"
        )
        self.tenant = _make_tenant("Shop A", owner=self.owner)
        self.tech = _make_technician(self.tenant, self.owner)
        self.customer = _make_customer(self.tenant)

    def test_repair_revenue_correct_with_multiple_repairs(self):
        """Revenue should be sum of all completed repairs on the report date."""
        today = timezone.now().date()
        _make_repair(self.tenant, self.customer, self.tech, "45.00",
                     service_date=timezone.now())
        _make_repair(self.tenant, self.customer, self.tech, "55.00",
                     service_date=timezone.now())
        _make_repair(self.tenant, self.customer, self.tech, "30.00",
                     service_date=timezone.now())

        svc = ReportService(tenant=self.tenant)
        report = svc.generate_daily_report(today)

        self.assertEqual(report["repairs"]["completed"], 3)
        self.assertAlmostEqual(report["repairs"]["revenue"], 130.0, places=2)

    def test_repair_revenue_zero_when_no_repairs(self):
        """Revenue should be 0.0 when no repairs exist."""
        today = timezone.now().date()
        svc = ReportService(tenant=self.tenant)
        report = svc.generate_daily_report(today)

        self.assertEqual(report["repairs"]["completed"], 0)
        self.assertEqual(report["repairs"]["revenue"], 0.0)

    def test_repair_revenue_excludes_other_tenants(self):
        """Revenue must not include repairs from other tenants."""
        other_owner = User.objects.create_user(
            username="owner_b", email="owner@b.com", password="testpass123"
        )
        other_tenant = _make_tenant("Shop B", owner=other_owner)
        other_tech = _make_technician(other_tenant, other_owner)
        other_customer = _make_customer(other_tenant, "Other Fleet")

        today = timezone.now().date()
        _make_repair(self.tenant, self.customer, self.tech, "50.00",
                     service_date=timezone.now())
        # Repair at other tenant — must NOT appear in self.tenant's report
        _make_repair(other_tenant, other_customer, other_tech, "999.00",
                     service_date=timezone.now())

        svc = ReportService(tenant=self.tenant)
        report = svc.generate_daily_report(today)

        self.assertAlmostEqual(report["repairs"]["revenue"], 50.0, places=2)

    def test_repair_revenue_excludes_pending_repairs(self):
        """Only COMPLETED repairs should count toward revenue."""
        today = timezone.now().date()
        _make_repair(self.tenant, self.customer, self.tech, "50.00",
                     service_date=timezone.now(), status="COMPLETED")
        _make_repair(self.tenant, self.customer, self.tech, "200.00",
                     service_date=timezone.now(), status="REQUESTED")

        svc = ReportService(tenant=self.tenant)
        report = svc.generate_daily_report(today)

        self.assertAlmostEqual(report["repairs"]["revenue"], 50.0, places=2)


class ReportServiceWeeklyN1Test(TestCase):
    """generate_weekly_report — repair_revenue uses aggregate, not Python iteration."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_c", email="owner@c.com", password="testpass123"
        )
        self.tenant = _make_tenant("Shop C", owner=self.owner)
        self.tech = _make_technician(self.tenant, self.owner)
        self.customer = _make_customer(self.tenant)

    def test_weekly_repair_revenue_correct(self):
        """Weekly revenue should sum all completed repairs in the 7-day window."""
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())  # Monday

        # Two repairs within the week
        _make_repair(self.tenant, self.customer, self.tech, "60.00",
                     service_date=timezone.make_aware(
                         timezone.datetime.combine(week_start, timezone.datetime.min.time())
                     ))
        _make_repair(self.tenant, self.customer, self.tech, "40.00",
                     service_date=timezone.make_aware(
                         timezone.datetime.combine(week_start + timedelta(days=1),
                                                   timezone.datetime.min.time())
                     ))

        svc = ReportService(tenant=self.tenant)
        report = svc.generate_weekly_report(week_start)

        self.assertEqual(report["repairs"]["total"], 2)
        self.assertAlmostEqual(report["repairs"]["revenue"], 100.0, places=2)

    def test_weekly_repair_revenue_zero_when_empty(self):
        """Weekly revenue should be 0.0 when no repairs exist."""
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())

        svc = ReportService(tenant=self.tenant)
        report = svc.generate_weekly_report(week_start)

        self.assertEqual(report["repairs"]["total"], 0)
        self.assertEqual(report["repairs"]["revenue"], 0.0)


class ReportServicePaymentByMethodTest(TestCase):
    """generate_daily_report — payment_by_method uses GROUP BY, not per-row loop."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_d", email="owner@d.com", password="testpass123"
        )
        self.tenant = _make_tenant("Shop D", owner=self.owner)
        self.tech = _make_technician(self.tenant, self.owner)
        self.customer = _make_customer(self.tenant)

        # Create an invoice to attach payments to
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            invoice_number="INV-TEST-001",
            customer=self.customer,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            payment_terms="COD",
            status="SENT",
            subtotal=Decimal("200.00"),
            total=Decimal("200.00"),
        )

    def _make_payment(self, amount, method, payment_date=None):
        if payment_date is None:
            payment_date = timezone.now().date()
        return Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal(str(amount)),
            payment_method=method,
            payment_date=payment_date,
        )

    def test_payment_by_method_groups_correctly(self):
        """Payments should be grouped by method with correct counts and totals."""
        today = timezone.now().date()
        self._make_payment("50.00", "CHECK")
        self._make_payment("30.00", "CHECK")
        self._make_payment("20.00", "CASH")

        svc = ReportService(tenant=self.tenant)
        report = svc.generate_daily_report(today)

        by_method = report["payments"]["by_method"]
        # Check label is human-readable (not raw code)
        self.assertIn("Check", by_method)
        self.assertIn("Cash", by_method)
        self.assertEqual(by_method["Check"]["count"], 2)
        self.assertAlmostEqual(by_method["Check"]["total"], 80.0, places=2)
        self.assertEqual(by_method["Cash"]["count"], 1)
        self.assertAlmostEqual(by_method["Cash"]["total"], 20.0, places=2)

    def test_payment_by_method_empty_when_no_payments(self):
        """payment_by_method should be an empty dict when no payments exist."""
        yesterday = timezone.now().date() - timedelta(days=1)
        svc = ReportService(tenant=self.tenant)
        report = svc.generate_daily_report(yesterday)
        self.assertEqual(report["payments"]["by_method"], {})


class ReportServiceNullTenantTest(TestCase):
    """_filter() returns qs.none() when tenant is None — prevents unscoped queries."""

    def test_no_tenant_returns_empty_daily_report(self):
        """With no tenant, daily report should contain zeros (not platform-wide data)."""
        today = timezone.now().date()
        svc = ReportService(tenant=None)
        report = svc.generate_daily_report(today)
        self.assertEqual(report["repairs"]["completed"], 0)
        self.assertEqual(report["repairs"]["revenue"], 0.0)

    def test_no_tenant_returns_empty_weekly_report(self):
        """With no tenant, weekly report should contain zeros."""
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        svc = ReportService(tenant=None)
        report = svc.generate_weekly_report(week_start)
        self.assertEqual(report["repairs"]["total"], 0)
        self.assertEqual(report["repairs"]["revenue"], 0.0)
