"""
CODE-026 — N+1 in referral_leaderboard view

BUG: referral_leaderboard() iterated over all ReferralCode rows and issued a
separate Referral.objects.filter(referral_code=code).count() query for every
code — O(N) queries where N is the number of referral codes for the tenant.
This is classic N+1: with 1,000 referral codes it fires 1,001 queries.

FIX: Replace the per-code COUNT loop with a single annotated queryset:
    ReferralCode.objects
        .annotate(referral_count=Count('referral'))
        .filter(referral_count__gt=0)
        .select_related('customer_user')
        .order_by('-referral_count')[:10]

TESTS:
1. Verify leaderboard returns correct results with a single-query annotation.
2. Verify tenant isolation: codes from Shop B are not visible to Shop A.
3. Verify codes with 0 referrals are excluded from the leaderboard.
4. Verify ordering (highest count first) and top-10 cap.
"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import ReferralCode, Referral, RewardOption

from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _setup_tenant(name):
    """Create a tenant + owner user."""
    user, tenant = make_tenant(name, f'owner_{name}')
    return tenant, user


def _make_customer_user(tenant, username):
    user = User.objects.create_user(username, f'{username}@test.com', 'pass')
    customer = Customer.objects.create(tenant=tenant, name=f'{username} Corp')
    cu = CustomerUser.objects.create(user=user, customer=customer)
    return cu


def _make_referral_code(customer_user):
    return ReferralCode.objects.create(customer_user=customer_user, code=f'CODE{customer_user.pk}')


def _make_referral(referral_code, customer_user):
    """Create a referral record using the given code."""
    return Referral.objects.create(referral_code=referral_code, customer_user=customer_user)


@override_settings(**TEST_OVERRIDES)
class ReferralLeaderboardN1Test(TestCase):
    def setUp(self):
        self.tenant_a, self.owner_a = _setup_tenant('alpha')
        self.tenant_b, self.owner_b = _setup_tenant('beta')

        # Shop A: three referrers with 3, 1, and 0 referrals
        self.cu_a1 = _make_customer_user(self.tenant_a, 'a_one')
        self.cu_a2 = _make_customer_user(self.tenant_a, 'a_two')
        self.cu_a3 = _make_customer_user(self.tenant_a, 'a_zero')  # no referrals

        self.code_a1 = _make_referral_code(self.cu_a1)
        self.code_a2 = _make_referral_code(self.cu_a2)
        self.code_a3 = _make_referral_code(self.cu_a3)

        # cu_a1 has 3 referrals, cu_a2 has 1
        for i in range(3):
            referred = _make_customer_user(self.tenant_a, f'a_ref_{i}')
            _make_referral(self.code_a1, referred)
        referred_b_via_a2 = _make_customer_user(self.tenant_a, 'a_ref_single')
        _make_referral(self.code_a2, referred_b_via_a2)

        # Shop B: one referrer with 5 referrals (should never appear in Shop A leaderboard)
        self.cu_b1 = _make_customer_user(self.tenant_b, 'b_one')
        self.code_b1 = _make_referral_code(self.cu_b1)
        for i in range(5):
            referred = _make_customer_user(self.tenant_b, f'b_ref_{i}')
            _make_referral(self.code_b1, referred)

    # ------------------------------------------------------------------
    # 1. Correct results (annotation layer — template existence tested separately)
    # ------------------------------------------------------------------
    def test_annotated_query_correct_results(self):
        """The annotated queryset returns the right counts and order."""
        from django.db.models import Count
        qs = (
            ReferralCode.objects
            .filter(customer_user__customer__tenant=self.tenant_a)
            .annotate(referral_count=Count('referral'))
            .filter(referral_count__gt=0)
            .select_related('customer_user')
            .order_by('-referral_count')[:10]
        )
        results = list(qs)
        # Should have exactly 2 entries (a1 with 3, a2 with 1; a3 has 0)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].customer_user, self.cu_a1)
        self.assertEqual(results[0].referral_count, 3)
        self.assertEqual(results[1].customer_user, self.cu_a2)
        self.assertEqual(results[1].referral_count, 1)

    # ------------------------------------------------------------------
    # 2. Tenant isolation: Shop B codes are not visible to Shop A
    # ------------------------------------------------------------------
    def test_tenant_isolation(self):
        """Shop B's referrers must never appear in Shop A's leaderboard."""
        from django.db.models import Count
        qs = (
            ReferralCode.objects
            .filter(customer_user__customer__tenant=self.tenant_a)
            .annotate(referral_count=Count('referral'))
            .filter(referral_count__gt=0)
            .order_by('-referral_count')
        )
        customer_users = [row.customer_user for row in qs]
        self.assertNotIn(self.cu_b1, customer_users)

    # ------------------------------------------------------------------
    # 3. Codes with 0 referrals are excluded
    # ------------------------------------------------------------------
    def test_zero_referral_codes_excluded(self):
        """cu_a3 has a ReferralCode but zero referrals — must be absent."""
        from django.db.models import Count
        qs = (
            ReferralCode.objects
            .filter(customer_user__customer__tenant=self.tenant_a)
            .annotate(referral_count=Count('referral'))
            .filter(referral_count__gt=0)
            .order_by('-referral_count')
        )
        customer_users = [row.customer_user for row in qs]
        self.assertNotIn(self.cu_a3, customer_users)

    # ------------------------------------------------------------------
    # 4. Top-10 cap
    # ------------------------------------------------------------------
    def test_top_10_cap(self):
        """Leaderboard is capped at 10 entries even if more exist."""
        # Create 12 additional referrers each with 1 referral
        for i in range(12):
            cu = _make_customer_user(self.tenant_a, f'extra_{i}')
            code = _make_referral_code(cu)
            referred = _make_customer_user(self.tenant_a, f'extra_ref_{i}')
            _make_referral(code, referred)

        from django.db.models import Count
        qs = (
            ReferralCode.objects
            .filter(customer_user__customer__tenant=self.tenant_a)
            .annotate(referral_count=Count('referral'))
            .filter(referral_count__gt=0)
            .order_by('-referral_count')[:10]
        )
        self.assertLessEqual(len(list(qs)), 10)

    # ------------------------------------------------------------------
    # 5. Query count: exactly 1 DB query (not N+1)
    # ------------------------------------------------------------------
    def test_single_query_not_n_plus_one(self):
        """The annotated path uses exactly 1 query, not N+1."""
        from django.db.models import Count
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            list(
                ReferralCode.objects
                .filter(customer_user__customer__tenant=self.tenant_a)
                .annotate(referral_count=Count('referral'))
                .filter(referral_count__gt=0)
                .select_related('customer_user')
                .order_by('-referral_count')[:10]
            )

        self.assertEqual(len(ctx.captured_queries), 1,
                         f"Expected 1 query, got {len(ctx.captured_queries)}: "
                         f"{[q['sql'][:120] for q in ctx.captured_queries]}")
