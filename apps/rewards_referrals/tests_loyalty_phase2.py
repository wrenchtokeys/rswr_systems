"""
Comprehensive tests for Loyalty System Phase 2.

Covers:
  - reconcile_loyalty_balances management command
  - expire_loyalty_points management command
  - LoyaltyService.reconcile_balance() diagnostic method
  - LoyaltyService.manual_adjustment() endpoint service
  - LoyaltyService.get_point_liability_report() service
  - POST /owner/loyalty/customers/<id>/adjust/ view
  - GET /owner/loyalty/liability/ view
  - Tenant isolation on all new endpoints
  - Edge cases: zero-amount guard, empty-reason guard, negative-balance guard,
    inactive-program guard, cross-tenant guard
"""

import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import (
    LoyaltyConfig,
    PointTransaction,
    Reward,
    RewardOption,
    RewardType,
)
from apps.rewards_referrals.services import LoyaltyService
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    return plan


def _make_tenant(name, slug):
    plan = _make_plan()
    owner = User.objects.create_user(
        f'{slug}_owner', f'{slug}_owner@test.com', 'testpass123!',
        first_name='Owner', last_name=slug.title(),
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
        subscription_status='trialing',
    )
    TenantMembership.objects.create(
        user=owner, tenant=tenant, role='owner', is_active=True,
    )
    return tenant, owner


def _make_customer_user(tenant, email, is_primary=True):
    user = User.objects.create_user(
        email.replace('@', '_').replace('.', '_'), email, 'testpass123!',
        first_name='Test', last_name='User',
    )
    customer = Customer.objects.create(
        name=f'{email} Co', email=email, tenant=tenant,
    )
    cu = CustomerUser.objects.create(
        user=user, customer=customer, is_primary_contact=is_primary,
    )
    return cu


def _award(cu, amount, tenant=None, txn_type='repair_complete'):
    return LoyaltyService.award_points(
        cu, amount, txn_type, f'Test award {amount}', tenant=tenant,
    )


# ──────────────────────────────────────────────────────────────────────────────
# LoyaltyService.reconcile_balance()
# ──────────────────────────────────────────────────────────────────────────────

class ReconcileBalanceServiceTest(TestCase):
    """Unit tests for LoyaltyService.reconcile_balance()."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Reconcile Shop', 'reconcile-shop')
        self.cu = _make_customer_user(self.tenant, 'rec@test.com')

    def test_in_sync_when_ledger_matches_cache(self):
        _award(self.cu, 100)
        result = LoyaltyService.reconcile_balance(self.cu)
        self.assertTrue(result['in_sync'])
        self.assertEqual(result['drift'], 0)
        self.assertEqual(result['ledger_sum'], 100)
        self.assertEqual(result['cached_balance'], 100)

    def test_drift_detected_when_cache_is_wrong(self):
        _award(self.cu, 100)
        # Manually corrupt the cached balance without creating a transaction
        reward = Reward.objects.get(customer_user=self.cu)
        reward.points = 150  # should be 100
        reward.save()

        result = LoyaltyService.reconcile_balance(self.cu)
        self.assertFalse(result['in_sync'])
        self.assertEqual(result['ledger_sum'], 100)
        self.assertEqual(result['cached_balance'], 150)
        self.assertEqual(result['drift'], -50)

    def test_no_reward_row_returns_zero_balance(self):
        result = LoyaltyService.reconcile_balance(self.cu)
        # No transactions, no Reward row → both zero, in sync
        self.assertTrue(result['in_sync'])
        self.assertEqual(result['ledger_sum'], 0)
        self.assertEqual(result['cached_balance'], 0)

    def test_reconcile_does_not_mutate(self):
        _award(self.cu, 100)
        reward_before = Reward.objects.get(customer_user=self.cu).points
        LoyaltyService.reconcile_balance(self.cu)
        reward_after = Reward.objects.get(customer_user=self.cu).points
        self.assertEqual(reward_before, reward_after, 'reconcile_balance must not mutate Reward.points')

    def test_multiple_transactions_summed(self):
        _award(self.cu, 50)
        _award(self.cu, 25)
        _award(self.cu, 75)
        result = LoyaltyService.reconcile_balance(self.cu)
        self.assertTrue(result['in_sync'])
        self.assertEqual(result['ledger_sum'], 150)


# ──────────────────────────────────────────────────────────────────────────────
# LoyaltyService.manual_adjustment()
# ──────────────────────────────────────────────────────────────────────────────

class ManualAdjustmentServiceTest(TestCase):
    """Unit tests for LoyaltyService.manual_adjustment()."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Adjust Shop', 'adjust-shop')
        self.cu = _make_customer_user(self.tenant, 'adj@test.com')
        _award(self.cu, 200)  # starting balance of 200

    def test_positive_adjustment_increases_balance(self):
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.cu,
            amount=50,
            reason='Goodwill bonus',
            created_by=self.owner,
            tenant=self.tenant,
        )
        self.assertEqual(pt.transaction_type, 'manual_adjustment')
        self.assertEqual(pt.amount, 50)
        self.assertEqual(pt.balance_after, 250)
        self.assertIn('Goodwill bonus', pt.description)
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 250)

    def test_negative_adjustment_decreases_balance(self):
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.cu,
            amount=-50,
            reason='Error correction',
            created_by=self.owner,
            tenant=self.tenant,
        )
        self.assertEqual(pt.amount, -50)
        self.assertEqual(pt.balance_after, 150)
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 150)

    def test_zero_amount_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            LoyaltyService.manual_adjustment(
                customer_user=self.cu,
                amount=0,
                reason='Test',
                created_by=self.owner,
            )
        self.assertIn('zero', str(ctx.exception).lower())

    def test_blank_reason_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            LoyaltyService.manual_adjustment(
                customer_user=self.cu,
                amount=50,
                reason='   ',
                created_by=self.owner,
            )
        self.assertIn('reason', str(ctx.exception).lower())

    def test_empty_reason_raises_value_error(self):
        with self.assertRaises(ValueError):
            LoyaltyService.manual_adjustment(
                customer_user=self.cu,
                amount=50,
                reason='',
                created_by=self.owner,
            )

    def test_deduction_below_zero_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            LoyaltyService.manual_adjustment(
                customer_user=self.cu,
                amount=-201,  # balance is 200
                reason='Over-deduct test',
                created_by=self.owner,
            )
        self.assertIn('below zero', str(ctx.exception).lower())

    def test_exact_deduction_to_zero_is_allowed(self):
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.cu,
            amount=-200,
            reason='Clearing balance',
            created_by=self.owner,
        )
        self.assertEqual(pt.balance_after, 0)
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 0)

    def test_inactive_program_raises_value_error(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()
        with self.assertRaises(ValueError) as ctx:
            LoyaltyService.manual_adjustment(
                customer_user=self.cu,
                amount=50,
                reason='Should fail',
                created_by=self.owner,
            )
        self.assertIn('inactive', str(ctx.exception).lower())

    def test_creates_point_transaction_with_correct_type(self):
        LoyaltyService.manual_adjustment(
            customer_user=self.cu,
            amount=100,
            reason='Test bonus',
            created_by=self.owner,
        )
        pt = PointTransaction.objects.filter(
            customer_user=self.cu,
            transaction_type='manual_adjustment',
        ).first()
        self.assertIsNotNone(pt)
        self.assertEqual(pt.created_by, self.owner)

    def test_tenant_resolved_from_customer_if_not_passed(self):
        """manual_adjustment resolves tenant from customer_user.customer.tenant."""
        pt = LoyaltyService.manual_adjustment(
            customer_user=self.cu,
            amount=10,
            reason='Tenant auto-resolve test',
            created_by=self.owner,
            # tenant=None intentionally omitted
        )
        self.assertEqual(pt.tenant, self.tenant)


# ──────────────────────────────────────────────────────────────────────────────
# LoyaltyService.get_point_liability_report()
# ──────────────────────────────────────────────────────────────────────────────

class PointLiabilityReportServiceTest(TestCase):
    """Unit tests for LoyaltyService.get_point_liability_report()."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Liability Shop', 'liability-shop')
        self.cu1 = _make_customer_user(self.tenant, 'cu1@liability.com')
        self.cu2 = _make_customer_user(self.tenant, 'cu2@liability.com')

    def test_empty_tenant_returns_zero_report(self):
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_outstanding_points'], 0)
        self.assertEqual(report['total_issued_lifetime'], 0)
        self.assertEqual(report['active_customer_count'], 0)

    def test_outstanding_points_sums_across_customers(self):
        _award(self.cu1, 100)
        _award(self.cu2, 50)
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_outstanding_points'], 150)
        self.assertEqual(report['total_issued_lifetime'], 150)

    def test_redeemed_points_subtracted_from_liability(self):
        _award(self.cu1, 200)
        # Simulate redemption (negative transaction)
        _award(self.cu1, -50, txn_type='redemption')
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_outstanding_points'], 150)
        self.assertEqual(report['total_redeemed_lifetime'], 50)

    def test_expired_points_tracked_separately(self):
        _award(self.cu1, 200)
        _award(self.cu1, -30, txn_type='expiration')
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_expired_lifetime'], 30)
        self.assertEqual(report['total_outstanding_points'], 170)

    def test_manual_adjustments_tracked(self):
        _award(self.cu1, 100)
        LoyaltyService.manual_adjustment(self.cu1, 25, 'Bonus', self.owner)
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_outstanding_points'], 125)
        # manual_adjusted should be non-zero
        self.assertGreater(abs(report['total_manually_adjusted']), 0)

    def test_active_customer_count_correct(self):
        _award(self.cu1, 100)
        # cu2 has no points — should not count
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['active_customer_count'], 1)

    def test_customer_list_contains_correct_data(self):
        _award(self.cu1, 100)
        report = LoyaltyService.get_point_liability_report(self.tenant)
        emails = [c['email'] for c in report['customers']]
        self.assertIn(self.cu1.user.email, emails)

    def test_tenant_isolation_in_report(self):
        """Liability report must not include another tenant's points."""
        other_tenant, _ = _make_tenant('Other Shop', 'other-shop')
        other_cu = _make_customer_user(other_tenant, 'other@shop.com')
        _award(other_cu, 9999, tenant=other_tenant)

        _award(self.cu1, 100)
        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_outstanding_points'], 100)
        self.assertNotIn(9999, [c['current_balance'] for c in report['customers']])


# ──────────────────────────────────────────────────────────────────────────────
# reconcile_loyalty_balances management command
# ──────────────────────────────────────────────────────────────────────────────

class ReconcileCommandTest(TestCase):
    """Tests for reconcile_loyalty_balances management command."""

    def setUp(self):
        from django.core.management import call_command
        self._call = call_command
        self.tenant, self.owner = _make_tenant('RecCmd Shop', 'reccmd-shop')
        self.cu = _make_customer_user(self.tenant, 'reccmd@test.com')

    def _call_command(self, *args, **kwargs):
        from django.core.management import call_command
        out = StringIO()
        try:
            call_command('reconcile_loyalty_balances', *args, stdout=out, stderr=out, **kwargs)
        except SystemExit:
            pass
        return out.getvalue()

    def test_all_ok_reports_consistent(self):
        _award(self.cu, 100)
        output = self._call_command()
        self.assertIn('OK', output)

    def test_reports_drift_without_fixing(self):
        _award(self.cu, 100)
        # Corrupt balance
        Reward.objects.filter(customer_user=self.cu).update(points=999)
        output = self._call_command()
        self.assertIn('DRIFT', output)

    def test_fix_mode_corrects_balance(self):
        _award(self.cu, 100)
        Reward.objects.filter(customer_user=self.cu).update(points=999)
        self._call_command('--fix')
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 100, 'Fix mode must restore balance to ledger sum')

    def test_tenant_id_filter_limits_scope(self):
        other_tenant, _ = _make_tenant('OtherRecCmd', 'other-reccmd')
        other_cu = _make_customer_user(other_tenant, 'other_reccmd@test.com')
        _award(other_cu, 50, tenant=other_tenant)
        Reward.objects.filter(customer_user=other_cu).update(points=9999)

        # Reconcile only self.tenant — other_tenant's drift should NOT be fixed
        self._call_command('--fix', tenant_id=self.tenant.pk)
        other_reward = Reward.objects.get(customer_user=other_cu)
        self.assertEqual(other_reward.points, 9999, 'Other tenant must not be touched')

    def test_json_output_is_parseable(self):
        _award(self.cu, 100)
        output = self._call_command('--json')
        data = json.loads(output)
        self.assertIn('total_customers_checked', data)
        self.assertIn('total_drifted', data)
        self.assertIn('total_ok', data)

    def test_missing_reward_row_logged(self):
        """customer_user with transactions but no Reward row is flagged."""
        # Create a PointTransaction without a Reward row
        PointTransaction.objects.create(
            tenant=self.tenant,
            customer_user=self.cu,
            amount=100,
            balance_after=100,
            transaction_type='repair_complete',
            description='Orphaned transaction',
        )
        # Ensure no Reward row exists
        Reward.objects.filter(customer_user=self.cu).delete()
        output = self._call_command('--json')
        data = json.loads(output)
        self.assertGreater(data['total_missing_reward_row'], 0)

    def test_command_does_not_use_select_for_update_outside_atomic(self):
        """
        Regression test for CODE-199: reconcile_loyalty_balances used
        select_for_update(nowait=True) outside of an atomic block, which raises
        TransactionManagementError on PostgreSQL.

        The read pass should use a plain .get(). Only the fix_mode path (inside
        its own atomic block) needs the lock. Verify the command completes
        without raising TransactionManagementError even with multiple customers.
        """
        _award(self.cu, 100)
        # Add a second customer to trigger multiple iterations of the loop
        cu2 = _make_customer_user(self.tenant, 'reccmd2_no_sfu@test.com')
        _award(cu2, 200)

        # Must NOT raise TransactionManagementError
        try:
            output = self._call_command('--json')
            data = json.loads(output)
        except Exception as exc:
            self.fail(
                f'reconcile_loyalty_balances raised {type(exc).__name__}: {exc}\n'
                f'This likely means select_for_update() was called outside an atomic block.'
            )

        self.assertEqual(data['total_customers_checked'], 2)
        self.assertEqual(data['total_drifted'], 0)
        self.assertEqual(data['total_ok'], 2)


# ──────────────────────────────────────────────────────────────────────────────
# expire_loyalty_points management command
# ──────────────────────────────────────────────────────────────────────────────

class ExpireLoyaltyCommandTest(TestCase):
    """Tests for expire_loyalty_points management command."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Expire Shop', 'expire-shop')
        self.cu = _make_customer_user(self.tenant, 'expire@test.com')

    def _call_command(self, *args, **kwargs):
        from django.core.management import call_command
        out = StringIO()
        call_command('expire_loyalty_points', *args, stdout=out, stderr=out, **kwargs)
        return out.getvalue()

    def _create_expired_transaction(self, amount=100):
        """Create a PointTransaction with an expires_at in the past."""
        # Award via LoyaltyService first (sets up Reward row)
        pt = _award(self.cu, amount)
        # Manually set expires_at in the past
        past = timezone.now() - timedelta(days=1)
        PointTransaction.objects.filter(pk=pt.pk).update(expires_at=past, expired=False)
        return pt

    def test_expiration_creates_negative_transaction(self):
        self._create_expired_transaction(100)
        self._call_command()
        expiration_txns = PointTransaction.objects.filter(
            customer_user=self.cu,
            transaction_type='expiration',
        )
        self.assertEqual(expiration_txns.count(), 1)
        self.assertEqual(expiration_txns.first().amount, -100)

    def test_expiration_updates_reward_balance(self):
        self._create_expired_transaction(100)
        self._call_command()
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 0)

    def test_marks_expired_flag_true(self):
        pt = self._create_expired_transaction(100)
        self._call_command()
        pt.refresh_from_db()
        self.assertTrue(pt.expired)

    def test_future_expiry_not_expired(self):
        """Points with future expires_at must NOT be expired."""
        pt = _award(self.cu, 100)
        future = timezone.now() + timedelta(days=30)
        PointTransaction.objects.filter(pk=pt.pk).update(expires_at=future, expired=False)
        self._call_command()
        pt.refresh_from_db()
        self.assertFalse(pt.expired)
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 100)

    def test_dry_run_does_not_modify(self):
        self._create_expired_transaction(100)
        self._call_command('--dry-run')
        # Reward balance should be unchanged
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 100)
        # No expiration transaction created
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type='expiration').count(),
            0,
        )

    def test_dry_run_counts_would_expire(self):
        self._create_expired_transaction(100)
        output = self._call_command('--dry-run')
        self.assertIn('Dry run', output)

    def test_already_expired_not_double_expired(self):
        """Transactions with expired=True must not be processed again."""
        pt = self._create_expired_transaction(100)
        PointTransaction.objects.filter(pk=pt.pk).update(expired=True)
        self._call_command()
        # No new expiration transactions should be created
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type='expiration').count(),
            0,
        )

    def test_tenant_id_filter(self):
        other_tenant, _ = _make_tenant('Other Expire', 'other-expire')
        other_cu = _make_customer_user(other_tenant, 'other_expire@test.com')
        other_pt = _award(other_cu, 200, tenant=other_tenant)
        past = timezone.now() - timedelta(days=1)
        PointTransaction.objects.filter(pk=other_pt.pk).update(expires_at=past, expired=False)

        # Run expire only for self.tenant — other tenant's points must not expire
        self._call_command(tenant_id=self.tenant.pk)
        other_pt.refresh_from_db()
        self.assertFalse(other_pt.expired)

    def test_json_output_parseable(self):
        self._create_expired_transaction(100)
        output = self._call_command('--json')
        data = json.loads(output)
        self.assertIn('total_transactions_expired', data)
        self.assertIn('total_points_removed', data)

    def test_only_positive_transactions_expire(self):
        """Negative transactions (redemptions, adjustments) must not expire."""
        # Create a redemption-type transaction in the past
        reward = Reward.objects.create(
            tenant=self.tenant, customer_user=self.cu, points=0,
        )
        past = timezone.now() - timedelta(days=1)
        PointTransaction.objects.create(
            tenant=self.tenant,
            customer_user=self.cu,
            amount=-50,
            balance_after=0,
            transaction_type='redemption',
            description='Redemption',
            expires_at=past,
            expired=False,
        )
        self._call_command()
        # No expiration should be created
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type='expiration').count(),
            0,
        )

    def test_balance_clamped_to_zero_if_cache_wrong(self):
        """If cached balance is less than expiry amount (due to drift), clamp to 0."""
        # Create a transaction that expires
        pt = self._create_expired_transaction(100)
        # Corrupt cache to be lower than the expiry amount
        Reward.objects.filter(customer_user=self.cu).update(points=50)
        self._call_command()
        reward = Reward.objects.get(customer_user=self.cu)
        self.assertEqual(reward.points, 0, 'Balance must clamp to 0, not go negative')


# ──────────────────────────────────────────────────────────────────────────────
# Manual Point Adjustment View: POST /owner/loyalty/customers/<id>/adjust/
# ──────────────────────────────────────────────────────────────────────────────

class ManualAdjustmentViewTest(TestCase):
    """Tests for owner_loyalty_adjust_points view."""

    def setUp(self):
        self.client = Client()
        self.tenant, self.owner = _make_tenant('View Adjust Shop', 'view-adjust-shop')
        self.cu = _make_customer_user(self.tenant, 'viewadj@test.com')
        _award(self.cu, 200)
        self.url = reverse('owner_loyalty_adjust_points', kwargs={'customer_user_id': self.cu.pk})

    def test_award_points_returns_200_with_new_balance(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': '50', 'reason': 'Test bonus'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['new_balance'], 250)

    def test_deduct_points_returns_200(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': '-50', 'reason': 'Error correction'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['new_balance'], 150)

    def test_zero_amount_returns_400(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': '0', 'reason': 'Test'})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_blank_reason_returns_400(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': '50', 'reason': '   '})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_over_deduction_returns_400(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': '-999', 'reason': 'Too much'})
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_unauthenticated_returns_redirect(self):
        resp = self.client.post(self.url, {'amount': '50', 'reason': 'Test'})
        self.assertIn(resp.status_code, [302, 403])

    def test_cross_tenant_returns_404(self):
        """Owner of tenant A must not adjust points for tenant B's customer."""
        other_tenant, _ = _make_tenant('Other View Adjust', 'other-view-adjust')
        other_cu = _make_customer_user(other_tenant, 'other_viewadj@test.com')
        _award(other_cu, 100, tenant=other_tenant)

        self.client.force_login(self.owner)
        cross_url = reverse('owner_loyalty_adjust_points', kwargs={'customer_user_id': other_cu.pk})
        resp = self.client.post(cross_url, {'amount': '50', 'reason': 'Attack'})
        self.assertEqual(resp.status_code, 404)

    def test_non_integer_amount_returns_400(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': 'notanumber', 'reason': 'Test'})
        self.assertEqual(resp.status_code, 400)

    def test_get_method_not_allowed(self):
        """The endpoint only accepts POST."""
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_creates_point_transaction_in_db(self):
        self.client.force_login(self.owner)
        before = PointTransaction.objects.filter(customer_user=self.cu).count()
        self.client.post(self.url, {'amount': '50', 'reason': 'DB check'})
        after = PointTransaction.objects.filter(customer_user=self.cu).count()
        self.assertEqual(after, before + 1)

    def test_response_contains_transaction_id(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'amount': '50', 'reason': 'ID check'})
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('transaction_id', data)
        self.assertIsNotNone(data['transaction_id'])


# ──────────────────────────────────────────────────────────────────────────────
# Point Liability Report View: GET /owner/loyalty/liability/
# ──────────────────────────────────────────────────────────────────────────────

class PointLiabilityReportViewTest(TestCase):
    """Tests for owner_loyalty_liability_report view."""

    def setUp(self):
        self.client = Client()
        self.tenant, self.owner = _make_tenant('View Liability Shop', 'view-liability-shop')
        self.cu = _make_customer_user(self.tenant, 'viewlib@test.com')
        self.url = reverse('owner_loyalty_liability_report')

    def test_returns_200_for_owner(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_returns_json_with_correct_structure(self):
        _award(self.cu, 100)
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertIn('total_outstanding_points', data)
        self.assertIn('total_issued_lifetime', data)
        self.assertIn('total_redeemed_lifetime', data)
        self.assertIn('total_expired_lifetime', data)
        self.assertIn('active_customer_count', data)
        self.assertIn('customers', data)
        self.assertIn('tenant_name', data)

    def test_tenant_name_matches_owner(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertEqual(data['tenant_name'], self.tenant.name)

    def test_outstanding_points_correct(self):
        _award(self.cu, 300)
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertEqual(data['total_outstanding_points'], 300)

    def test_unauthenticated_returns_403(self):
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, [302, 403])

    def test_cross_tenant_isolation(self):
        """Liability report must only show data for the authenticated owner's tenant."""
        other_tenant, other_owner = _make_tenant('Other Liability', 'other-liability')
        other_cu = _make_customer_user(other_tenant, 'other_lib@test.com')
        _award(other_cu, 9999, tenant=other_tenant)

        _award(self.cu, 100)

        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertEqual(data['total_outstanding_points'], 100)

    def test_empty_shop_returns_zeros(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertEqual(data['total_outstanding_points'], 0)
        self.assertEqual(data['active_customer_count'], 0)

    def test_customer_list_includes_balance(self):
        _award(self.cu, 150)
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        data = resp.json()
        self.assertEqual(len(data['customers']), 1)
        self.assertEqual(data['customers'][0]['current_balance'], 150)
        self.assertEqual(data['customers'][0]['email'], self.cu.user.email)
