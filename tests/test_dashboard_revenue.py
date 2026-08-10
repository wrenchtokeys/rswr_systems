"""Owner dashboard revenue hero (UI_MAGIC_SESSIONS S5).

Covers the parts that are easy to get quietly wrong: the fair mid-month
comparison, the divide-by-zero guard, period validation, tenant scoping, and
the "only COMPLETED counts" rule.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.saas.views import _get_revenue_summary, _revenue_window
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


def _make_shop(business_name, email):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name=business_name, email=email, password='testpass123!',
        first_name='Test', last_name='Owner',
    )
    return result['tenant']


class RevenueWindowTests(TestCase):
    """_revenue_window: the month comparison must be elapsed-days, not full-month."""

    def test_month_compares_same_elapsed_days_not_whole_month(self):
        now = timezone.now().replace(year=2026, month=3, day=10, hour=9,
                                     minute=0, second=0, microsecond=0)
        start, end, prev_start, prev_end, label = _revenue_window('month', now)

        self.assertEqual(start.day, 1)
        self.assertEqual(start.month, 3)
        self.assertEqual(end, now)
        self.assertEqual(prev_start.month, 2)
        self.assertEqual(prev_start.day, 1)
        # Feb 1 + 9d09h — the same slice of the month, not all of February.
        self.assertEqual(prev_end.month, 2)
        self.assertEqual(prev_end.day, 10)
        self.assertIn('same days', label)

    def test_month_previous_window_never_spills_into_current_month(self):
        """A 31-day month elapsed against a 28-day February must clamp."""
        now = timezone.now().replace(year=2026, month=3, day=31, hour=23,
                                     minute=0, second=0, microsecond=0)
        _, _, prev_start, prev_end, _ = _revenue_window('month', now)
        self.assertEqual(prev_start.month, 2)
        # Clamped to the start of March rather than running past it, so the
        # baseline can never double-count the current month's own revenue.
        self.assertLessEqual(prev_end, now.replace(day=1, hour=0, minute=0))

    def test_last_month_is_a_full_month_against_the_one_before(self):
        now = timezone.now().replace(year=2026, month=3, day=10)
        start, end, prev_start, prev_end, label = _revenue_window('last_month', now)
        self.assertEqual((start.month, start.day), (2, 1))
        self.assertEqual((end.month, end.day), (3, 1))
        self.assertEqual((prev_start.month, prev_start.day), (1, 1))
        self.assertEqual(prev_end, start)
        self.assertIn('month before', label)

    def test_90d_window_spans_90_days_and_compares_to_prior_90(self):
        now = timezone.now()
        start, end, prev_start, prev_end, label = _revenue_window('90d', now)
        self.assertEqual((end - start).days, 89)
        self.assertEqual(prev_end, start)
        self.assertEqual((prev_end - prev_start).days, 90)
        self.assertIn('90 days', label)


class RevenueSummaryTests(TestCase):
    def setUp(self):
        self.tenant = _make_shop('Revenue Shop', 'revenue@test.com')
        self.tech = Technician.objects.filter(tenant=self.tenant).first()
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', email='fleet@test.com',
            phone='5015551234', customer_type='FLEET',
        )
        self.now = timezone.now()
        self.month_start = self.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _repair(self, when, cost, status='COMPLETED', tenant=None):
        repair = Repair.objects.create(
            tenant=tenant or self.tenant, customer=self.customer, technician=self.tech,
            description='Chip', queue_status=status, service_date=when,
        )
        # Repair.save() recalculates cost from the pricing rules, so set it after.
        Repair.objects.filter(pk=repair.pk).update(cost=Decimal(cost), service_date=when)
        return repair

    def test_totals_only_count_completed_jobs(self):
        self._repair(self.month_start + timedelta(days=1), '100.00')
        self._repair(self.month_start + timedelta(days=1), '999.00', status='IN_PROGRESS')

        summary = _get_revenue_summary(self.tenant, 'month')
        self.assertEqual(summary['revenue_total'], Decimal('100.00'))

    def test_no_previous_revenue_yields_no_percentage(self):
        """A zero baseline must show no delta, not a fabricated +100%."""
        self._repair(self.month_start + timedelta(days=1), '250.00')

        summary = _get_revenue_summary(self.tenant, 'month')
        self.assertEqual(summary['revenue_total'], Decimal('250.00'))
        self.assertIsNone(summary['revenue_delta_pct'])
        self.assertEqual(summary['revenue_delta_dir'], '')

    def test_delta_direction_and_magnitude(self):
        prev_month_day = (self.month_start - timedelta(days=1)).replace(
            day=1, hour=6, minute=0, second=0, microsecond=0
        )
        self._repair(prev_month_day, '100.00')
        self._repair(self.month_start, '150.00')

        summary = _get_revenue_summary(self.tenant, 'month')
        self.assertEqual(summary['revenue_delta_dir'], 'up')
        self.assertEqual(summary['revenue_delta_pct'], 50)

    def test_other_tenants_revenue_is_excluded(self):
        other = _make_shop('Other Shop', 'other@test.com')
        other_customer = Customer.objects.create(
            tenant=other, name='Other Fleet', email='of@test.com',
            phone='5015550000', customer_type='FLEET',
        )
        repair = Repair.objects.create(
            tenant=other, customer=other_customer,
            technician=Technician.objects.filter(tenant=other).first(),
            description='Chip', queue_status='COMPLETED',
            service_date=self.month_start + timedelta(days=1),
        )
        Repair.objects.filter(pk=repair.pk).update(cost=Decimal('500.00'))

        summary = _get_revenue_summary(self.tenant, 'month')
        self.assertEqual(summary['revenue_total'], Decimal('0.00'))

    def test_unknown_period_falls_back_to_month(self):
        summary = _get_revenue_summary(self.tenant, 'wat')
        self.assertEqual(summary['revenue_period'], 'month')
        self.assertEqual(summary['revenue_period_label'], 'This month')

    def test_sparkline_absent_when_no_revenue(self):
        summary = _get_revenue_summary(self.tenant, 'month')
        self.assertFalse(summary['revenue_spark_has_data'])
        self.assertEqual(summary['revenue_spark_points'], '')

    def test_sparkline_present_and_closed_when_revenue_exists(self):
        self._repair(self.month_start + timedelta(days=1), '100.00')

        summary = _get_revenue_summary(self.tenant, 'month')
        self.assertTrue(summary['revenue_spark_has_data'])
        self.assertTrue(summary['revenue_spark_points'])
        # The area polygon must start and end on the baseline or it renders as
        # a filled blob rather than an area under the line.
        self.assertTrue(summary['revenue_spark_area'].startswith('0,30 '))
        self.assertTrue(summary['revenue_spark_area'].endswith(' 100,30'))

    def test_never_raises_on_bad_tenant(self):
        """The dashboard must still render if the revenue query blows up."""
        summary = _get_revenue_summary(None, 'month')
        self.assertEqual(summary['revenue_total'], Decimal('0.00'))
        self.assertFalse(summary['revenue_spark_has_data'])


class RevenueDashboardRenderTests(TestCase):
    def setUp(self):
        self.tenant = _make_shop('Render Shop', 'render@test.com')
        from django.contrib.auth.models import User
        self.user = User.objects.filter(email='render@test.com').first()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_dashboard_renders_with_revenue_context(self):
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        for key in ('revenue_total', 'revenue_period', 'revenue_periods',
                    'revenue_spark_has_data'):
            self.assertIn(key, response.context)

    def test_period_querystring_is_honoured(self):
        response = self.client.get('/owner/?period=90d')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['revenue_period'], '90d')
        self.assertEqual(response.context['revenue_period_label'], 'Last 90 days')

    def test_legacy_billing_keys_are_still_present(self):
        """billing_context keys stay untouched — other code/tests rely on them."""
        response = self.client.get('/owner/')
        for key in ('total_revenue', 'repair_revenue', 'replacement_revenue'):
            self.assertIn(key, response.context)
