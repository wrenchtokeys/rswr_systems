"""
Loyalty management: redemption cancel/refund + owner reward-option CRUD.

Covers:
  - RewardService.cancel_redemption(): refund through the ledger
    (transaction_type='redemption_refund'), PENDING-only guard, inactive
    program guard, tenant scoping, un-apply from open jobs, blocked on
    completed/invoiced jobs
  - Liability report / lifetime-earned treatment of refunds
  - /owner/loyalty/options/... create / edit / toggle / delete views
  - /owner/loyalty/redemptions/<id>/cancel/ owner view
  - /tech/reward-fulfillment/<id>/cancel/ manager gate
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.rewards_referrals.models import (
    LoyaltyConfig,
    PointTransaction,
    RewardOption,
    RewardRedemption,
    RewardType,
)
from apps.rewards_referrals.services import LoyaltyService, RewardService
from core.models import Customer
from tests.test_simplicity_pass import TEST_OVERRIDES, OwnerClientMixin, make_owner_tenant


def _make_discount_option(tenant, name='50% Off', points=1000, percent=50):
    reward_type, _ = RewardType.objects.get_or_create(
        category='REPAIR_DISCOUNT',
        discount_type='PERCENTAGE',
        discount_value=Decimal(percent),
        defaults={'name': f'{percent}% Off Service'},
    )
    return RewardOption.objects.create(
        tenant=tenant, name=name, description=name,
        points_required=points, reward_type=reward_type, is_active=True,
    )


class LoyaltyManagementBase(OwnerClientMixin, TestCase):
    """Owner tenant + funded customer + a PENDING redemption."""

    EMAIL = 'loyaltybase@test.com'
    SHOP = 'Loyalty Base Shop'

    def setUp(self):
        self.login_owner(make_owner_tenant(self.SHOP, self.EMAIL))
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='EOS Trucking', customer_type='FLEET',
        )
        self.option = _make_discount_option(self.tenant)
        LoyaltyService.award_points(
            self.customer, 1500, 'repair_complete', 'seed', tenant=self.tenant,
        )
        ok, self.redemption = RewardService.redeem_reward(
            self.customer, self.option.id, created_by=self.user,
        )
        assert ok, self.redemption

    def _make_repair(self, status='APPROVED'):
        from apps.technician_portal.models import Repair, Technician
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=tech,
            unit_number='U-1', queue_status=status,
            service_date=timezone.now(),
        )


@override_settings(**TEST_OVERRIDES)
class CancelRedemptionServiceTests(LoyaltyManagementBase):

    EMAIL = 'cancelsvc@test.com'
    SHOP = 'Cancel Svc Shop'

    def test_cancel_refunds_points_and_rejects(self):
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)

        ok, msg = RewardService.cancel_redemption(
            self.redemption.id, self.tenant, cancelled_by=self.user, reason='wrong option',
        )
        self.assertTrue(ok, msg)

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'REJECTED')
        self.assertEqual(self.redemption.processed_by, self.user)
        self.assertIsNotNone(self.redemption.processed_at)
        self.assertIn('wrong option', self.redemption.notes)

        self.assertEqual(LoyaltyService.get_balance(self.customer), 1500)
        refund = PointTransaction.objects.get(
            customer=self.customer, transaction_type='redemption_refund',
        )
        self.assertEqual(refund.amount, 1000)
        self.assertEqual(refund.related_redemption_id, self.redemption.id)
        self.assertEqual(refund.created_by, self.user)

    def test_cancel_non_pending_fails(self):
        self.redemption.status = 'FULFILLED'
        self.redemption.save(update_fields=['status'])

        ok, msg = RewardService.cancel_redemption(self.redemption.id, self.tenant)
        self.assertFalse(ok)
        self.assertIn('pending', msg.lower())
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)

    def test_cancel_requires_active_program(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.is_active = False
        config.save()

        ok, msg = RewardService.cancel_redemption(self.redemption.id, self.tenant)
        self.assertFalse(ok)
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'PENDING')
        self.assertFalse(
            PointTransaction.objects.filter(transaction_type='redemption_refund').exists()
        )

    def test_cancel_scoped_to_tenant(self):
        other = make_owner_tenant('Other Cancel Shop', 'othercancel@test.com')
        ok, msg = RewardService.cancel_redemption(self.redemption.id, other['tenant'])
        self.assertFalse(ok)
        self.assertIn('not found', msg.lower())
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'PENDING')

    def test_cancel_unapplies_from_open_repair(self):
        repair = self._make_repair('APPROVED')
        applied, msg = repair.apply_reward(self.redemption)
        self.assertTrue(applied, msg)

        ok, msg = RewardService.cancel_redemption(self.redemption.id, self.tenant)
        self.assertTrue(ok, msg)
        self.redemption.refresh_from_db()
        self.assertIsNone(self.redemption.applied_to_repair)
        self.assertEqual(self.redemption.status, 'REJECTED')
        self.assertEqual(LoyaltyService.get_balance(self.customer), 1500)

    def test_cancel_blocked_on_completed_repair(self):
        repair = self._make_repair('APPROVED')
        repair.apply_reward(self.redemption)
        repair.queue_status = 'COMPLETED'
        repair.save()

        self.redemption.refresh_from_db()
        if self.redemption.status != 'PENDING':
            # Completion auto-fulfilled the applied reward — cancel must
            # refuse for that reason instead.
            ok, msg = RewardService.cancel_redemption(self.redemption.id, self.tenant)
            self.assertFalse(ok)
            return

        ok, msg = RewardService.cancel_redemption(self.redemption.id, self.tenant)
        self.assertFalse(ok)
        self.assertIn('completed', msg.lower())

    def test_cancel_blocked_on_invoiced_job(self):
        from apps.billing.models import Invoice, InvoiceLineItem
        repair = self._make_repair('APPROVED')
        repair.apply_reward(self.redemption)
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-CXL-1', invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status='DRAFT', subtotal=Decimal('50.00'),
            discount=Decimal('0.00'), total=Decimal('50.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=inv, repair=repair, description='Repair', quantity=1,
            unit_price=Decimal('50.00'), amount=Decimal('50.00'),
        )

        ok, msg = RewardService.cancel_redemption(self.redemption.id, self.tenant)
        self.assertFalse(ok)
        self.assertIn('invoiced', msg.lower())
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'PENDING')

    def test_liability_report_nets_refund(self):
        RewardService.cancel_redemption(self.redemption.id, self.tenant, cancelled_by=self.user)

        report = LoyaltyService.get_point_liability_report(self.tenant)
        self.assertEqual(report['total_redeemed_lifetime'], 0)
        self.assertEqual(report['total_outstanding_points'], 1500)

        row = next(
            c for c in report['customers'] if c['customer_id'] == self.customer.id
        )
        # Refund is not new issuance — lifetime earned stays at the seed award.
        self.assertEqual(row['lifetime_earned'], 1500)
        self.assertEqual(row['lifetime_redeemed'], 0)
        self.assertEqual(
            LoyaltyService.get_lifetime_earned(self.customer), 1500,
        )


@override_settings(**TEST_OVERRIDES)
class OwnerRewardOptionCrudTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Option Crud Shop', 'optioncrud@test.com'))

    def test_create_percent_option(self):
        resp = self.client.post(reverse('owner_reward_option_create'), {
            'name': '25% Off Next Repair',
            'description': 'Quarter off',
            'points_required': '1200',
            'kind': 'percent',
            'discount_value': '25',
        })
        self.assertRedirects(resp, reverse('owner_loyalty_dashboard'))
        opt = RewardOption.objects.get(tenant=self.tenant, name='25% Off Next Repair')
        self.assertEqual(opt.points_required, 1200)
        self.assertEqual(opt.reward_type.category, 'REPAIR_DISCOUNT')
        self.assertEqual(opt.reward_type.discount_type, 'PERCENTAGE')
        self.assertEqual(opt.reward_type.discount_value, Decimal('25'))
        self.assertTrue(opt.is_active)

    def test_create_merch_option_ignores_value(self):
        self.client.post(reverse('owner_reward_option_create'), {
            'name': 'Donuts', 'description': '', 'points_required': '500',
            'kind': 'merch', 'discount_value': '9999',
        })
        opt = RewardOption.objects.get(tenant=self.tenant, name='Donuts')
        self.assertEqual(opt.reward_type.category, 'MERCHANDISE')
        self.assertEqual(opt.reward_type.discount_value, Decimal('0'))

    def test_create_rejects_bad_input(self):
        self.client.post(reverse('owner_reward_option_create'), {
            'name': '', 'points_required': '-5', 'kind': 'percent',
            'discount_value': '150',
        })
        self.assertEqual(RewardOption.objects.filter(tenant=self.tenant).count(), 0)

    def test_edit_option(self):
        opt = _make_discount_option(self.tenant, name='Old Name', points=1000)
        self.client.post(reverse('owner_reward_option_edit', args=[opt.id]), {
            'name': 'New Name', 'description': 'Ten bucks off',
            'points_required': '800', 'kind': 'fixed', 'discount_value': '10',
        })
        opt.refresh_from_db()
        self.assertEqual(opt.name, 'New Name')
        self.assertEqual(opt.points_required, 800)
        self.assertEqual(opt.reward_type.discount_type, 'FIXED_AMOUNT')
        self.assertEqual(opt.reward_type.discount_value, Decimal('10'))

    def test_edit_other_tenants_option_404(self):
        other = make_owner_tenant('Other Crud Shop', 'othercrud@test.com')
        foreign = _make_discount_option(other['tenant'], name='Foreign')
        resp = self.client.post(
            reverse('owner_reward_option_edit', args=[foreign.id]),
            {'name': 'Hacked', 'points_required': '1', 'kind': 'free', 'discount_value': '0'},
        )
        self.assertEqual(resp.status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, 'Foreign')

    def test_toggle_option(self):
        opt = _make_discount_option(self.tenant)
        self.client.post(reverse('owner_reward_option_toggle', args=[opt.id]))
        opt.refresh_from_db()
        self.assertFalse(opt.is_active)
        self.client.post(reverse('owner_reward_option_toggle', args=[opt.id]))
        opt.refresh_from_db()
        self.assertTrue(opt.is_active)

    def test_delete_unused_option(self):
        opt = _make_discount_option(self.tenant)
        self.client.post(reverse('owner_reward_option_delete', args=[opt.id]))
        self.assertFalse(RewardOption.objects.filter(pk=opt.id).exists())

    def test_delete_redeemed_option_deactivates_instead(self):
        customer = Customer.objects.create(
            tenant=self.tenant, name='Redeemer Co', customer_type='FLEET',
        )
        opt = _make_discount_option(self.tenant)
        LoyaltyService.award_points(
            customer, 2000, 'repair_complete', 'seed', tenant=self.tenant,
        )
        ok, redemption = RewardService.redeem_reward(customer, opt.id)
        self.assertTrue(ok)

        self.client.post(reverse('owner_reward_option_delete', args=[opt.id]))
        opt.refresh_from_db()
        self.assertFalse(opt.is_active)
        self.assertTrue(RewardRedemption.objects.filter(pk=redemption.id).exists())

    def test_dashboard_lists_options_and_pending_redemptions(self):
        opt = _make_discount_option(self.tenant, name='Visible Reward')
        customer = Customer.objects.create(
            tenant=self.tenant, name='Dash Co', customer_type='FLEET',
        )
        LoyaltyService.award_points(
            customer, 2000, 'repair_complete', 'seed', tenant=self.tenant,
        )
        RewardService.redeem_reward(customer, opt.id)

        resp = self.client.get(reverse('owner_loyalty_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Visible Reward')
        self.assertContains(resp, 'Dash Co')
        self.assertContains(resp, 'Cancel &amp; Refund')


@override_settings(**TEST_OVERRIDES)
class OwnerCancelRedemptionViewTests(LoyaltyManagementBase):

    EMAIL = 'ownercancel@test.com'
    SHOP = 'Owner Cancel Shop'

    def test_owner_cancels_and_refunds(self):
        resp = self.client.post(
            reverse('owner_loyalty_cancel_redemption', args=[self.redemption.id]),
        )
        self.assertRedirects(resp, reverse('owner_loyalty_dashboard'))
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'REJECTED')
        self.assertEqual(LoyaltyService.get_balance(self.customer), 1500)


@override_settings(**TEST_OVERRIDES)
class TechPortalCancelRedemptionTests(LoyaltyManagementBase):

    EMAIL = 'techcancel@test.com'
    SHOP = 'Tech Cancel Shop'

    def test_manager_cancels_via_tech_portal(self):
        resp = self.client.post(
            reverse('cancel_redemption', args=[self.redemption.id]),
        )
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'REJECTED')
        self.assertEqual(LoyaltyService.get_balance(self.customer), 1500)

    def test_plain_technician_blocked(self):
        from django.contrib.auth.models import User
        from apps.technician_portal.models import Technician

        tech_user = User.objects.create_user(
            'plaintech', 'plaintech@test.com', 'testpass123!',
            first_name='Plain', last_name='Tech',
        )
        Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_manager=False,
            phone_number='5015550000',
        )
        client = Client()
        client.force_login(tech_user)
        session = client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        resp = client.post(reverse('cancel_redemption', args=[self.redemption.id]))
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'PENDING')
        self.assertEqual(LoyaltyService.get_balance(self.customer), 500)

    def test_fulfillment_page_shows_cancel_for_manager(self):
        resp = self.client.get(
            reverse('reward_fulfillment_detail', args=[self.redemption.id]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cancel &amp; Refund Points')

    def test_customer_page_shows_cancel_for_manager(self):
        resp = self.client.get(
            reverse('customer_detail', args=[self.customer.id]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Cancel redemption')


@override_settings(**{
    **TEST_OVERRIDES,
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
})
class RedemptionEmailTests(LoyaltyManagementBase):

    EMAIL = 'redemail@test.com'
    SHOP = 'Redemption Email Shop'

    def setUp(self):
        super().setUp()
        self.customer.email = 'fleet@eos.com'
        self.customer.save(update_fields=['email'])

    def test_cancel_emails_customer_with_refund(self):
        from django.core import mail
        with self.captureOnCommitCallbacks(execute=True):
            ok, msg = RewardService.cancel_redemption(
                self.redemption.id, self.tenant, cancelled_by=self.user,
            )
        self.assertTrue(ok, msg)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['fleet@eos.com'])
        self.assertIn('cancelled', sent.subject.lower())
        self.assertIn('1000', sent.subject)
        self.assertIn('1,500 points', sent.body)

    def test_standalone_fulfill_emails_customer(self):
        from django.core import mail
        from apps.rewards_referrals.services import RewardFulfillmentService
        with self.captureOnCommitCallbacks(execute=True):
            RewardFulfillmentService.mark_as_fulfilled(self.redemption, None)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ready', mail.outbox[0].subject.lower())

    def test_applied_fulfill_sends_no_email(self):
        from django.core import mail
        from apps.rewards_referrals.services import RewardFulfillmentService
        repair = self._make_repair('APPROVED')
        repair.apply_reward(self.redemption)
        self.redemption.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            RewardFulfillmentService.mark_as_fulfilled(self.redemption, None)
        self.assertEqual(len(mail.outbox), 0)

    def test_auto_apply_off_completion_does_not_consume_reward(self):
        """Default: completing a job leaves the waiting reward untouched."""
        repair = self._make_repair('APPROVED')
        repair.queue_status = 'COMPLETED'
        repair.save()

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'PENDING')
        self.assertIsNone(self.redemption.applied_to_repair)

    def test_auto_apply_on_restores_old_behavior(self):
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        config.auto_apply_rewards = True
        config.save()

        repair = self._make_repair('APPROVED')
        repair.queue_status = 'COMPLETED'
        repair.save()

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'FULFILLED')
        self.assertEqual(self.redemption.applied_to_repair_id, repair.id)

    def test_explicitly_applied_reward_fulfills_on_completion(self):
        """A deliberate apply is finalized at completion even with auto off."""
        repair = self._make_repair('APPROVED')
        applied, msg = repair.apply_reward(self.redemption)
        self.assertTrue(applied, msg)

        repair.queue_status = 'COMPLETED'
        repair.save()

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'FULFILLED')

    def test_edit_form_shows_waiting_reward_prompt(self):
        repair = self._make_repair('APPROVED')
        resp = self.client.get(reverse('update_repair', args=[repair.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'has a reward waiting')
        self.assertContains(resp, self.redemption.reward_option.name)

    def test_edit_form_post_applies_chosen_reward(self):
        from apps.technician_portal.models import Technician
        repair = self._make_repair('APPROVED')
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        resp = self.client.post(
            reverse('update_repair', args=[repair.id]),
            data={
                'customer': self.customer.id,
                'technician': tech.id,
                'unit_number': repair.unit_number,
                'queue_status': 'COMPLETED',
                'repair_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
                'technician_notes': 'apply reward via form',
                'apply_redemption_id': str(self.redemption.id),
            },
        )
        self.assertIn(resp.status_code, (200, 302))

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.applied_to_repair_id, repair.id)
        self.assertEqual(self.redemption.status, 'FULFILLED')

    def test_config_endpoint_saves_auto_apply(self):
        resp = self.client.post(reverse('owner_loyalty_save_config'), {
            'is_active': 'true',
            'auto_apply_rewards': 'true',
        })
        self.assertEqual(resp.status_code, 200)
        config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.auto_apply_rewards)

    def test_cancel_without_customer_email_is_silent(self):
        from django.core import mail
        self.customer.email = ''
        self.customer.save(update_fields=['email'])
        with self.captureOnCommitCallbacks(execute=True):
            ok, _ = RewardService.cancel_redemption(self.redemption.id, self.tenant)
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 0)
