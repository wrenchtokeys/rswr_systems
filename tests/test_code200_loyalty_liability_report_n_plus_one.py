"""
CODE-200: N+1 queries in LoyaltyService.get_point_liability_report()

The per-customer breakdown loop fired one aggregate query PER customer user
via PointTransaction.objects.filter(tenant=tenant, customer_user=cu).aggregate(...).
For a tenant with N customers with loyalty activity, that's N extra DB round-trips.

Fix: pre-compute all per-customer stats in a single .values('customer_user_id')
.annotate(...) query, then look up each customer_user_id in the result dict
during the loop — O(1) per customer, O(1) total DB queries.

Impact: The /owner/loyalty/liability/ JSON endpoint is only called by shop owners
and managers, but a tenant with 50 customers would trigger 50 extra DB queries
per page load of the loyalty liability report. At scale this is O(N) queries
on a hot endpoint.
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.test.utils import CaptureQueriesContext
from django.db import connection

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import (
    LoyaltyConfig, PointTransaction, Reward, RewardType,
)
from apps.rewards_referrals.services import LoyaltyService
from apps.tenants.models import Tenant
from core.models import Customer


def _make_tenant(slug):
    owner = User.objects.create_user(
        username=f'owner-{slug}', email=f'owner-{slug}@test.com', password='x'
    )
    return Tenant.objects.create(name=f'Shop {slug}', slug=slug, owner=owner)


def _make_customer_user(tenant, idx):
    email = f'cu{idx}@example.com'
    user = User.objects.create_user(username=f'cu{idx}', email=email, password='x')
    customer = Customer.objects.create(name=f'Customer {idx}', tenant=tenant)
    return CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=(idx == 1))


def _seed_transactions(tenant, cu, awarded=100, redeemed=-30, expired=-10):
    """Create PointTransaction rows directly (bypass LoyaltyService locking)."""
    Reward.objects.update_or_create(
        customer_user=cu,
        defaults={'tenant': tenant, 'points': max(0, awarded + redeemed + expired)},
    )
    PointTransaction.objects.create(
        tenant=tenant, customer_user=cu, amount=awarded,
        balance_after=awarded, transaction_type='repair_complete',
        description='test',
    )
    if redeemed:
        PointTransaction.objects.create(
            tenant=tenant, customer_user=cu, amount=redeemed,
            balance_after=awarded + redeemed, transaction_type='redemption',
            description='test',
        )
    if expired:
        PointTransaction.objects.create(
            tenant=tenant, customer_user=cu, amount=expired,
            balance_after=awarded + redeemed + expired, transaction_type='expiration',
            description='test',
        )


class LoyaltyLiabilityReportQueryCountTest(TestCase):
    """Verify get_point_liability_report() uses O(1) queries regardless of customer count."""

    def setUp(self):
        self.tenant = _make_tenant('query-test')
        LoyaltyConfig.objects.create(tenant=self.tenant, is_active=True)
        self.cus = [_make_customer_user(self.tenant, i) for i in range(1, 6)]
        for cu in self.cus:
            _seed_transactions(self.tenant, cu, awarded=100, redeemed=-20, expired=-5)

    def test_query_count_bounded_regardless_of_customer_count(self):
        """Total DB queries should not scale with number of customers."""
        with CaptureQueriesContext(connection) as ctx:
            LoyaltyService.get_point_liability_report(self.tenant)

        # Should be a small constant number of queries:
        # 1. Aggregate PointTransaction totals (global stats)
        # 2. Sum Reward.points for total_outstanding
        # 3. Single per-customer annotated PointTransaction query (NEW)
        # 4. Reward queryset with select_related
        # Tolerance: ≤8 total queries for 5 customers.
        # Before fix: would be 5+4 = 9+ queries (1 per customer + overhead).
        num_queries = len(ctx.captured_queries)
        self.assertLessEqual(
            num_queries,
            8,
            msg=(
                f"Expected ≤8 DB queries for 5 customers, got {num_queries}. "
                f"N+1 regression: the per-customer stats loop should use a "
                f"single annotated queryset, not one query per customer."
            ),
        )

    def test_no_per_customer_aggregate_queries(self):
        """Verify no individual per-customer PointTransaction aggregate queries."""
        with CaptureQueriesContext(connection) as ctx:
            LoyaltyService.get_point_liability_report(self.tenant)

        # Before the fix, individual queries looked like:
        # SELECT SUM(...) FROM rewards_referrals_pointtransaction
        # WHERE tenant_id=X AND customer_user_id=Y
        # There would be one per customer_user.
        individual_cu_queries = [
            q['sql'] for q in ctx.captured_queries
            if 'customer_user_id' in q['sql']
            and q['sql'].count('customer_user_id') == 1  # only the per-customer filter
            and 'GROUP BY' not in q['sql']
        ]
        # With the fix, per-cu stats uses GROUP BY, so no individual-CU-only queries
        self.assertEqual(
            len(individual_cu_queries),
            0,
            msg=(
                f"Found {len(individual_cu_queries)} individual per-customer queries "
                f"(N+1 pattern). These should be replaced by a single GROUP BY query."
            ),
        )


class LoyaltyLiabilityReportCorrectnessTest(TestCase):
    """Verify the report returns correct data after the N+1 fix."""

    def setUp(self):
        self.tenant = _make_tenant('correct-test')
        LoyaltyConfig.objects.create(tenant=self.tenant, is_active=True)

    def test_single_customer_stats(self):
        cu = _make_customer_user(self.tenant, 1)
        _seed_transactions(self.tenant, cu, awarded=200, redeemed=-50, expired=-20)

        report = LoyaltyService.get_point_liability_report(self.tenant)

        self.assertEqual(len(report['customers']), 1)
        cust = report['customers'][0]
        self.assertEqual(cust['customer_user_id'], cu.pk)
        self.assertEqual(cust['current_balance'], 130)  # 200 - 50 - 20
        self.assertEqual(cust['lifetime_earned'], 200)
        self.assertEqual(cust['lifetime_redeemed'], 50)
        self.assertEqual(cust['lifetime_expired'], 20)

    def test_multiple_customers_correct_totals(self):
        cu1 = _make_customer_user(self.tenant, 1)
        cu2 = _make_customer_user(self.tenant, 2)
        _seed_transactions(self.tenant, cu1, awarded=100, redeemed=-30, expired=0)
        _seed_transactions(self.tenant, cu2, awarded=200, redeemed=0, expired=-50)

        report = LoyaltyService.get_point_liability_report(self.tenant)

        self.assertEqual(len(report['customers']), 2)
        by_id = {c['customer_user_id']: c for c in report['customers']}

        c1 = by_id[cu1.pk]
        self.assertEqual(c1['lifetime_earned'], 100)
        self.assertEqual(c1['lifetime_redeemed'], 30)
        self.assertEqual(c1['lifetime_expired'], 0)

        c2 = by_id[cu2.pk]
        self.assertEqual(c2['lifetime_earned'], 200)
        self.assertEqual(c2['lifetime_redeemed'], 0)
        self.assertEqual(c2['lifetime_expired'], 50)

    def test_customer_with_no_transactions_has_zero_stats(self):
        """A customer_user with a Reward row but no PointTransactions gets zeros."""
        cu = _make_customer_user(self.tenant, 1)
        # Create Reward row but no PointTransactions
        Reward.objects.create(customer_user=cu, tenant=self.tenant, points=0)

        report = LoyaltyService.get_point_liability_report(self.tenant)

        # Should appear in customers list with zero stats
        cust = next((c for c in report['customers'] if c['customer_user_id'] == cu.pk), None)
        self.assertIsNotNone(cust)
        self.assertEqual(cust['lifetime_earned'], 0)
        self.assertEqual(cust['lifetime_redeemed'], 0)
        self.assertEqual(cust['lifetime_expired'], 0)

    def test_tenant_isolation_no_cross_tenant_bleed(self):
        """Stats for tenant A should not include transactions from tenant B."""
        other_tenant = _make_tenant('other-shop')
        LoyaltyConfig.objects.create(tenant=other_tenant, is_active=True)

        cu_a = _make_customer_user(self.tenant, 1)
        cu_b = _make_customer_user(other_tenant, 99)
        _seed_transactions(self.tenant, cu_a, awarded=100, redeemed=0, expired=0)
        _seed_transactions(other_tenant, cu_b, awarded=9999, redeemed=0, expired=0)

        report = LoyaltyService.get_point_liability_report(self.tenant)

        # Only cu_a's customer should appear
        self.assertEqual(len(report['customers']), 1)
        self.assertEqual(report['customers'][0]['customer_user_id'], cu_a.pk)
        self.assertEqual(report['customers'][0]['lifetime_earned'], 100)

    def test_total_outstanding_points_sum(self):
        """total_outstanding_points sums Reward.points > 0 across all customers."""
        cu1 = _make_customer_user(self.tenant, 1)
        cu2 = _make_customer_user(self.tenant, 2)
        Reward.objects.create(customer_user=cu1, tenant=self.tenant, points=150)
        Reward.objects.create(customer_user=cu2, tenant=self.tenant, points=80)

        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_outstanding_points'], 230)

    def test_report_sorted_by_balance_descending(self):
        """Customers are ordered by current_balance descending (highest earners first)."""
        for i, pts in enumerate([50, 200, 10, 150], start=1):
            cu = _make_customer_user(self.tenant, i)
            Reward.objects.create(customer_user=cu, tenant=self.tenant, points=pts)

        report = LoyaltyService.get_point_liability_report(self.tenant)
        balances = [c['current_balance'] for c in report['customers']]
        self.assertEqual(balances, sorted(balances, reverse=True))
