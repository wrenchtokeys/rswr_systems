"""
Customer-anchored loyalty: new-behavior tests.

The loyalty ledger anchors on core.Customer (the company), not portal
accounts. These tests cover the behaviors introduced by the re-anchor:

 - award_points with a tenant-less customer is a safe no-op
 - the email balance line gating matrix (get_email_balance_line)
 - the {points_balance} placeholder in shop-customized invoice templates
 - the nav-badge context processor hides when the program is off
 - the in-shop (POS) redemption flow and its manager gate
 - the 0017 balance-merge migration (SUM per company, redemptions repointed)
"""

from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import (
    LoyaltyConfig,
    PointTransaction,
    Reward,
    RewardOption,
    RewardRedemption,
    RewardType,
)
from apps.rewards_referrals.services import LoyaltyService, RewardService


def _make_tenant(name, slug):
    owner = User.objects.create_user(f"owner_{slug}", f"owner_{slug}@test.com", "Pass123!")
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner,
        plan="trial", trial_started_at=timezone.now(),
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role="owner", is_active=True)
    return owner, tenant


def _make_tech(tenant, suffix, is_manager=False):
    u = User.objects.create_user(f"tech_{tenant.slug}_{suffix}", f"tech{suffix}@{tenant.slug}.com", "Pass123!")
    tech = Technician.objects.create(
        user=u, tenant=tenant, is_active=True, can_repair=True, is_manager=is_manager,
    )
    TenantMembership.objects.create(user=u, tenant=tenant, role="technician", is_active=True)
    return tech


def _make_discount_option(tenant, name="$25 Off Repair", points=100):
    rt = RewardType.objects.create(
        name=name, category='REPAIR_DISCOUNT',
        discount_type='FIXED_AMOUNT', discount_value=Decimal('25'),
    )
    return RewardOption.objects.create(
        tenant=tenant, name=name, description=name,
        points_required=points, reward_type=rt, is_active=True,
    )


class NullTenantAwardTest(TestCase):
    """A customer with no tenant must never crash the award path."""

    def test_award_points_returns_none_for_tenantless_customer(self):
        customer = Customer.objects.create(name="Orphan Co", tenant=None)
        pt = LoyaltyService.award_points(
            customer=customer, amount=50,
            transaction_type='repair_complete', description='test',
        )
        self.assertIsNone(pt)
        self.assertEqual(PointTransaction.objects.count(), 0)
        self.assertEqual(Reward.objects.count(), 0)


class EmailBalanceLineTest(TestCase):
    """get_email_balance_line is the single gate for both email surfaces."""

    def setUp(self):
        _, self.tenant = _make_tenant("Email Shop", "emailshop")
        self.customer = Customer.objects.create(tenant=self.tenant, name="Balance Co")
        self.config = LoyaltyConfig.get_for_tenant(self.tenant)

    def _give_points(self, amount=450):
        LoyaltyService.award_points(
            customer=self.customer, amount=amount,
            transaction_type='manual_adjustment', description='seed',
        )

    def test_line_present_when_active_toggle_on_and_positive_balance(self):
        self._give_points()
        line = LoyaltyService.get_email_balance_line(self.customer)
        self.assertIsNotNone(line)
        self.assertIn("450", line)
        self.assertIn("points", line)

    def test_none_when_program_inactive(self):
        self._give_points()
        self.config.is_active = False
        self.config.save()
        self.assertIsNone(LoyaltyService.get_email_balance_line(self.customer))

    def test_none_when_email_toggle_off(self):
        self._give_points()
        self.config.show_balance_in_emails = False
        self.config.save()
        self.assertIsNone(LoyaltyService.get_email_balance_line(self.customer))

    def test_none_when_zero_balance(self):
        self.assertIsNone(LoyaltyService.get_email_balance_line(self.customer))

    def test_none_when_customer_has_no_tenant(self):
        orphan = Customer.objects.create(name="Orphan Co 2", tenant=None)
        self.assertIsNone(LoyaltyService.get_email_balance_line(orphan))

    def test_points_balance_placeholder_in_custom_invoice_template(self):
        """Custom invoice templates render {points_balance}, empty when gated off."""
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        self._give_points()
        service = InvoiceEmailService(tenant=self.tenant)
        invoice_data = SimpleNamespace(
            customer_name="Balance Co", invoice_number="INV-1001",
            total=Decimal('100.00'), invoice_date=timezone.now(),
        )
        line = LoyaltyService.get_email_balance_line(self.customer)
        rendered = service._render_invoice_template(
            "Hi {customer_name}. {points_balance}", invoice_data,
            points_line=line,
        )
        self.assertIn("450", rendered)

        rendered_off = service._render_invoice_template(
            "Hi {customer_name}. {points_balance}", invoice_data,
            points_line=None,
        )
        self.assertNotIn("450", rendered_off)
        self.assertIn("Hi Balance Co.", rendered_off)


class ContextProcessorGateTest(TestCase):
    """The nav points badge disappears when the shop's program is off."""

    def setUp(self):
        _, self.tenant = _make_tenant("Badge Shop", "badgeshop")
        self.customer = Customer.objects.create(tenant=self.tenant, name="Badge Co")
        self.user = User.objects.create_user("badgeuser", "badge@test.com", "Pass123!")
        self.cu = CustomerUser.objects.create(user=self.user, customer=self.customer, is_primary_contact=True)
        self.factory = RequestFactory()

    def _run_processor(self):
        from common.context_processors import customer_loyalty
        request = self.factory.get('/')
        request.user = self.user
        request.tenant = self.tenant
        return customer_loyalty(request)

    def test_returns_company_balance_when_active(self):
        LoyaltyService.award_points(
            customer=self.customer, amount=75,
            transaction_type='manual_adjustment', description='seed',
        )
        self.assertEqual(self._run_processor(), {'loyalty_points': 75})

    def test_returns_empty_when_program_off(self):
        LoyaltyService.award_points(
            customer=self.customer, amount=75,
            transaction_type='manual_adjustment', description='seed',
        )
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()
        self.assertEqual(self._run_processor(), {})


class PosRedeemTest(TestCase):
    """In-shop redemption: manager-gated point spending from the customer page."""

    def setUp(self):
        _, self.tenant = _make_tenant("POS Shop", "posshop")
        self.customer = Customer.objects.create(tenant=self.tenant, name="Walkin Wanda", customer_type="WALK_IN")
        self.option = _make_discount_option(self.tenant)
        self.manager = _make_tech(self.tenant, "mgr", is_manager=True)
        self.plain_tech = _make_tech(self.tenant, "plain", is_manager=False)
        LoyaltyService.award_points(
            customer=self.customer, amount=500,
            transaction_type='manual_adjustment', description='seed',
        )

    def _login(self, tech):
        self.client.force_login(tech.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _redeem_url(self):
        return reverse('redeem_for_customer', args=[self.customer.id])

    def test_plain_tech_cannot_redeem(self):
        self._login(self.plain_tech)
        self.client.post(self._redeem_url(), {'option_id': self.option.id})
        self.assertEqual(RewardRedemption.objects.count(), 0)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)

    def test_manager_can_redeem(self):
        self._login(self.manager)
        response = self.client.post(self._redeem_url(), {'option_id': self.option.id})
        self.assertEqual(response.status_code, 302)
        redemption = RewardRedemption.objects.get()
        self.assertEqual(redemption.reward.customer, self.customer)
        self.assertEqual(redemption.status, 'PENDING')
        self.assertIn('Redeemed in-shop by', redemption.notes)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 400)
        # Ledger row records the staff actor, no portal user
        pt = PointTransaction.objects.get(transaction_type='redemption')
        self.assertIsNone(pt.customer_user)
        self.assertEqual(pt.created_by, self.manager.user)

    def test_redeem_blocked_when_program_off(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()
        self._login(self.manager)
        self.client.post(self._redeem_url(), {'option_id': self.option.id})
        self.assertEqual(RewardRedemption.objects.count(), 0)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)

    def test_redeem_and_apply_rolls_back_on_apply_failure(self):
        """If applying to the repair fails, the point deduction rolls back too."""
        repair = Repair.objects.create(
            tenant=self.tenant, technician=self.manager, customer=self.customer,
            unit_number="U-1", damage_type="Chip", queue_status="APPROVED",
        )
        # Pre-apply an existing redemption so apply_reward() refuses a second one
        # via the merchandise/one-reward rule: easiest failure is a MERCHANDISE option.
        merch_type = RewardType.objects.create(
            name="Donuts", category='MERCHANDISE', discount_type='NONE',
        )
        merch_option = RewardOption.objects.create(
            tenant=self.tenant, name="Donuts", description="Box of donuts",
            points_required=100, reward_type=merch_type, is_active=True,
        )
        self._login(self.manager)
        self.client.post(
            reverse('apply_reward_to_repair', args=[repair.id]),
            {'option_id': merch_option.id},
        )
        # Merchandise can't be applied to a repair → whole operation rolled back
        self.assertEqual(RewardRedemption.objects.count(), 0)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)

    def test_redeem_and_apply_success(self):
        repair = Repair.objects.create(
            tenant=self.tenant, technician=self.manager, customer=self.customer,
            unit_number="U-2", damage_type="Chip", queue_status="APPROVED",
        )
        self._login(self.manager)
        response = self.client.post(
            reverse('apply_reward_to_repair', args=[repair.id]),
            {'option_id': self.option.id},
        )
        self.assertEqual(response.status_code, 302)
        redemption = RewardRedemption.objects.get()
        self.assertEqual(redemption.applied_to_repair, repair)
        self.assertEqual(LoyaltyService.get_balance(self.customer), 400)
        disc = repair.get_discounted_cost()
        self.assertTrue(disc['discount_applied'])


class BalanceMergeMigrationTest(TransactionTestCase):
    """
    0017_customer_anchor_backfill: per-CustomerUser balances merge into one
    per-Customer row (SUM), and redemptions on duplicate rows are repointed
    to the survivor BEFORE the duplicates are deleted (RewardRedemption.reward
    is CASCADE — deleting first would destroy fulfillment history).
    """

    def test_merge_sums_balances_and_repoints_redemptions(self):
        executor = MigrationExecutor(connection)
        # Rewind rewards_referrals to the pre-merge schema (customer nullable,
        # customer_user still present on Reward).
        executor.migrate([('rewards_referrals', '0016_customer_anchor_schema')])
        executor.loader.build_graph()

        old_apps = executor.loader.project_state(
            [('rewards_referrals', '0016_customer_anchor_schema')]
        ).apps

        OldUser = old_apps.get_model('auth', 'User')
        OldTenant = old_apps.get_model('tenants', 'Tenant')
        OldCustomer = old_apps.get_model('core', 'Customer')
        OldCustomerUser = old_apps.get_model('customer_portal', 'CustomerUser')
        OldReward = old_apps.get_model('rewards_referrals', 'Reward')
        OldPT = old_apps.get_model('rewards_referrals', 'PointTransaction')
        OldRewardType = old_apps.get_model('rewards_referrals', 'RewardType')
        OldRewardOption = old_apps.get_model('rewards_referrals', 'RewardOption')
        OldRedemption = old_apps.get_model('rewards_referrals', 'RewardRedemption')

        owner = OldUser.objects.create(username='mergeowner', email='mo@test.com')
        tenant = OldTenant.objects.create(
            name='Merge Shop', slug='mergeshop', subdomain='mergeshop',
            owner_id=owner.pk, plan='trial', trial_started_at=timezone.now(),
        )
        customer = OldCustomer.objects.create(tenant_id=tenant.pk, name='Merge Fleet')

        u1 = OldUser.objects.create(username='mergeu1', email='m1@test.com')
        u2 = OldUser.objects.create(username='mergeu2', email='m2@test.com')
        cu1 = OldCustomerUser.objects.create(user_id=u1.pk, customer_id=customer.pk, is_primary_contact=True)
        cu2 = OldCustomerUser.objects.create(user_id=u2.pk, customer_id=customer.pk)

        r1 = OldReward.objects.create(customer_user_id=cu1.pk, tenant_id=tenant.pk, points=100)
        r2 = OldReward.objects.create(customer_user_id=cu2.pk, tenant_id=tenant.pk, points=250)

        OldPT.objects.create(
            tenant_id=tenant.pk, customer_user_id=cu1.pk, amount=100,
            balance_after=100, transaction_type='manual_adjustment', description='seed1',
        )
        OldPT.objects.create(
            tenant_id=tenant.pk, customer_user_id=cu2.pk, amount=250,
            balance_after=250, transaction_type='manual_adjustment', description='seed2',
        )

        rt = OldRewardType.objects.create(name='Disc', category='REPAIR_DISCOUNT', discount_type='FIXED_AMOUNT', discount_value=10)
        opt = OldRewardOption.objects.create(
            tenant_id=tenant.pk, name='Disc', description='d', points_required=50, reward_type_id=rt.pk,
        )
        # Redemption hangs off the DUPLICATE row (r2) — must survive the merge.
        redemption = OldRedemption.objects.create(reward_id=r2.pk, reward_option_id=opt.pk, status='PENDING')

        # Run the merge + constraints migrations forward.
        executor = MigrationExecutor(connection)
        executor.migrate([('rewards_referrals', '0019_referral_pending_payout')])
        executor.loader.build_graph()

        merged = Reward.objects.get(customer_id=customer.pk)
        self.assertEqual(merged.points, 350)
        self.assertEqual(merged.pk, r1.pk, "oldest row survives")
        self.assertFalse(Reward.objects.filter(pk=r2.pk).exists())

        surviving_redemption = RewardRedemption.objects.get(pk=redemption.pk)
        self.assertEqual(surviving_redemption.reward_id, r1.pk, "redemption repointed to survivor")

        # Ledger rows all carry the customer FK now
        self.assertEqual(
            PointTransaction.objects.filter(customer_id=customer.pk).count(), 2,
        )
