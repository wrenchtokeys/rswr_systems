"""
Loyalty parity for replacements (PR4 of the Jobs overhaul).

Covers: points awarded on replacement completion (idempotent), milestone
counting across both job types, reward redemption applied to a replacement
reaching the invoice math, and the customer-portal apply endpoint.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import (
    LoyaltyConfig, PointTransaction, Reward, RewardOption, RewardRedemption,
    RewardType,
)
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Repair, Replacement
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_shop(business_name, email, services='replacement'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'),
            'trial_days': 30, 'display_order': 0, 'is_active': True,
        },
    )
    result = create_tenant_with_owner(
        business_name=business_name,
        email=email,
        password='testpass123!',
        first_name='Test',
        last_name='Owner',
        services_offered=services,
    )
    return result['user'], result['tenant']


@override_settings(**TEST_SETTINGS)
class ReplacementLoyaltyPointsTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_shop('Loyal Glass', 'loyal@test.com')
        self.customer = Customer.objects.create(name='Loyal Fleet', tenant=self.tenant)
        self.portal_user = User.objects.create_user('loyalcust', password='pass123!')
        self.customer_user = CustomerUser.objects.create(
            user=self.portal_user, customer=self.customer, is_primary_contact=True,
        )
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.config = LoyaltyConfig.get_for_tenant(self.tenant)

    def _make_replacement(self, unit='U-1', status='APPROVED'):
        return Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=unit, glass_position='WINDSHIELD',
            queue_status=status, cost_override=Decimal('400.00'),
        )

    def test_completion_awards_points(self):
        repl = self._make_replacement()
        repl.queue_status = 'COMPLETED'
        repl.save()

        pt = PointTransaction.objects.get(
            customer=self.customer,
            transaction_type='replacement_complete',
        )
        self.assertEqual(pt.amount, self.config.points_per_repair)
        self.assertEqual(pt.related_replacement, repl)
        self.assertIsNone(pt.related_repair)

    def test_completion_is_idempotent_on_resave(self):
        repl = self._make_replacement()
        repl.queue_status = 'COMPLETED'
        repl.save()
        repl.save()  # COMPLETED → COMPLETED re-save must not re-award

        self.assertEqual(
            PointTransaction.objects.filter(
                transaction_type='replacement_complete').count(),
            1,
        )

    def test_milestone_counts_both_job_types(self):
        # 4 completed repairs + the 5th job as a replacement → 5-job milestone
        for i in range(4):
            Repair.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number=f'R-{i}', queue_status='COMPLETED',
            )
        repl = self._make_replacement(unit='U-5')
        repl.queue_status = 'COMPLETED'
        repl.save()

        milestone = PointTransaction.objects.filter(
            customer=self.customer,
            transaction_type='milestone_bonus',
        ).order_by('-id').first()
        self.assertIsNotNone(milestone)
        self.assertEqual(milestone.amount, self.config.milestone_5_bonus)
        self.assertEqual(milestone.related_replacement, repl)


@override_settings(**TEST_SETTINGS)
class ReplacementRewardRedemptionTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_shop('Redeem Glass', 'redeem@test.com')
        self.customer = Customer.objects.create(name='Redeem Fleet', tenant=self.tenant)
        self.portal_user = User.objects.create_user('redeemcust', password='pass123!')
        self.customer_user = CustomerUser.objects.create(
            user=self.portal_user, customer=self.customer, is_primary_contact=True,
        )
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)

        self.reward_type = RewardType.objects.create(
            name='Replacement $50 Off', category='REPLACEMENT_DISCOUNT',
            discount_type='FIXED_AMOUNT', discount_value=Decimal('50.00'),
        )
        self.reward_option = RewardOption.objects.create(
            tenant=self.tenant, name='$50 Off a Replacement',
            points_required=100, reward_type=self.reward_type,
        )
        self.reward = Reward.objects.create(
            tenant=self.tenant, customer=self.customer, points=500,
        )
        self.redemption = RewardRedemption.objects.create(
            reward=self.reward, reward_option=self.reward_option,
            status='APPROVED',
        )
        self.replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='RD-1', glass_position='WINDSHIELD',
            queue_status='APPROVED', cost_override=Decimal('400.00'),
        )

    def test_discount_reaches_invoice(self):
        self.redemption.applied_to_replacement = self.replacement
        self.redemption.status = 'PENDING'
        self.redemption.save()

        discounted = self.replacement.get_discounted_cost()
        self.assertTrue(discounted['discount_applied'])
        self.assertEqual(discounted['final_cost'], Decimal('350.00'))

        self.replacement.queue_status = 'COMPLETED'
        self.replacement.save()

        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        invoice = InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            customer=self.customer, services=[self.replacement],
        )
        line = invoice.line_items.get()
        self.assertEqual(line.unit_price, Decimal('400.00'))
        self.assertEqual(line.discount, Decimal('50.00'))
        self.assertEqual(line.amount, Decimal('350.00'))

    def test_customer_can_apply_reward_via_portal(self):
        client = Client()
        client.force_login(self.portal_user)
        session = client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        resp = client.post(
            reverse('customer_apply_reward_replacement', args=[self.replacement.id]),
            {'redemption_id': self.redemption.id},
        )
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.applied_to_replacement, self.replacement)

    def test_repair_category_reward_rejected_for_replacement(self):
        repair_type = RewardType.objects.create(
            name='Repair Discount', category='REPAIR_DISCOUNT',
            discount_type='FIXED_AMOUNT', discount_value=Decimal('10.00'),
        )
        self.reward_option.reward_type = repair_type
        self.reward_option.save()

        client = Client()
        client.force_login(self.portal_user)
        session = client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        resp = client.post(
            reverse('customer_apply_reward_replacement', args=[self.replacement.id]),
            {'redemption_id': self.redemption.id},
        )
        self.assertEqual(resp.status_code, 404)
        self.redemption.refresh_from_db()
        self.assertIsNone(self.redemption.applied_to_replacement)

    def test_applied_reward_not_reusable_on_repairs(self):
        self.redemption.applied_to_replacement = self.replacement
        self.redemption.save()
        from apps.customer_portal.views import _get_available_monetary_rewards
        self.assertEqual(
            list(_get_available_monetary_rewards(self.customer_user)), [],
        )
