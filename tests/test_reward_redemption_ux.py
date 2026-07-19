"""
CODE-210: Reward Redemption UX Overhaul Tests

Tests the split redemption flows (monetary vs physical), auto-restore on
repair denial, and physical reward scheduling.
"""
from datetime import date, time
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.customer_portal.models import CustomerUser, RepairApproval
from apps.rewards_referrals.models import (
    Reward, RewardOption, RewardRedemption, RewardType,
)
from apps.technician_portal.models import Repair, Technician, TechnicianNotification
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class RewardRedemptionUXTestMixin:
    """Shared setup for CODE-210 tests."""

    def make_tenant_and_users(self, suffix=''):
        """Create a tenant with owner/tech/customer."""
        owner = User.objects.create_user(
            f'owner{suffix}', f'owner{suffix}@test.com', 'TestPass123!',
            first_name='Owner', last_name='Test',
        )
        self.tenant = Tenant.objects.create(
            name=f'UX Shop{suffix}', slug=f'ux-shop{suffix}',
            subdomain=f'uxshop{suffix}', owner=owner,
            plan='trial', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(user=owner, tenant=self.tenant, role='owner', is_active=True)

        tech_user = User.objects.create_user(
            f'tech{suffix}', f'tech{suffix}@test.com', 'TestPass123!',
        )
        self.tech = Technician.objects.create(user=tech_user, tenant=self.tenant, is_active=True)
        TenantMembership.objects.create(user=tech_user, tenant=self.tenant, role='technician', is_active=True)
        Group.objects.get_or_create(name='Technicians')
        tech_user.groups.add(Group.objects.get(name='Technicians'))

        self.customer = Customer.objects.create(
            tenant=self.tenant, name=f'Fleet{suffix}', customer_type='FLEET',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cust_user = User.objects.create_user(
            f'cust{suffix}', f'cust{suffix}@test.com', 'TestPass123!',
        )
        self.cu = CustomerUser.objects.create(user=self.cust_user, customer=self.customer)

    def make_monetary_reward_type(self):
        self.rt_discount = RewardType.objects.create(
            name='Repair Discount', category='REPAIR_DISCOUNT',
            discount_type='PERCENTAGE', discount_value=Decimal('25.00'),
            is_active=True,
        )
        self.opt_discount = RewardOption.objects.create(
            name='25% Off Repair', description='25 pct discount',
            points_required=500, reward_type=self.rt_discount,
            is_active=True, tenant=self.tenant,
        )

    def make_physical_reward_type(self):
        self.rt_merch = RewardType.objects.create(
            name='Merch', category='MERCHANDISE',
            discount_type='NONE', discount_value=Decimal('0'),
            is_active=True,
        )
        self.opt_pizza = RewardOption.objects.create(
            name='Pizza Party', description='Office pizza',
            points_required=1000, reward_type=self.rt_merch,
            is_active=True, tenant=self.tenant,
        )

    def make_reward_with_points(self, customer_user, points=1000):
        return Reward.objects.create(
            tenant=self.tenant, customer_user=customer_user, points=points,
        )

    def make_approved_redemption(self, customer_user, option, repair=None):
        reward = Reward.objects.filter(customer_user=customer_user).first()
        if not reward:
            reward = self.make_reward_with_points(customer_user)
        return RewardRedemption.objects.create(
            reward=reward, reward_option=option,
            status='APPROVED', applied_to_repair=repair,
        )

    def make_repair(self, status='PENDING'):
        return Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='UNIT-100', description='Test repair',
            damage_type='Chip', queue_status=status,
        )

    def login_customer(self, client):
        client.force_login(self.cust_user)
        session = client.session
        session['tenant_id'] = self.tenant.id
        session.save()


class ApplyMonetaryRewardToRepairTest(RewardRedemptionUXTestMixin, TestCase):
    """Flow A: apply monetary reward at repair request time."""

    def setUp(self):
        self.make_tenant_and_users(suffix='_apply')
        self.make_monetary_reward_type()
        self.reward = self.make_reward_with_points(self.cu)
        self.redemption = self.make_approved_redemption(self.cu, self.opt_discount)
        self.client = Client()
        self.login_customer(self.client)

    def test_available_rewards_shown_on_get(self):
        """GET request_repair should include available monetary rewards in context."""
        resp = self.client.get(reverse('customer_request_repair'))
        self.assertEqual(resp.status_code, 200)
        available = list(resp.context['available_rewards'])
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].id, self.redemption.id)

    def test_apply_reward_to_single_repair(self):
        """POST with apply_reward links the redemption to the created repair."""
        resp = self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-42',
            'damage_type': 'Chip',
            'description': 'Test break',
            'apply_reward': str(self.redemption.id),
        })
        self.assertEqual(resp.status_code, 302)  # redirect on success

        self.redemption.refresh_from_db()
        self.assertIsNotNone(self.redemption.applied_to_repair)
        self.assertEqual(self.redemption.applied_to_repair.unit_number, 'UNIT-42')

    def test_fulfilled_reward_not_in_available(self):
        """FULFILLED redemptions should not appear in available rewards."""
        self.redemption.status = 'FULFILLED'
        self.redemption.save()

        resp = self.client.get(reverse('customer_request_repair'))
        available = list(resp.context['available_rewards'])
        self.assertEqual(len(available), 0)

    def test_already_applied_reward_not_available(self):
        """Redemptions already applied to a repair should not appear."""
        repair = self.make_repair()
        self.redemption.applied_to_repair = repair
        self.redemption.save()

        resp = self.client.get(reverse('customer_request_repair'))
        available = list(resp.context['available_rewards'])
        self.assertEqual(len(available), 0)

    def test_physical_reward_not_shown(self):
        """Physical rewards should not be in available monetary rewards."""
        self.make_physical_reward_type()
        self.make_approved_redemption(self.cu, self.opt_pizza)

        resp = self.client.get(reverse('customer_request_repair'))
        available = list(resp.context['available_rewards'])
        # Only the monetary one
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].reward_option.name, '25% Off Repair')


class AutoRestoreOnDenialTest(RewardRedemptionUXTestMixin, TestCase):
    """When a repair is denied, any applied reward should be auto-restored."""

    def setUp(self):
        self.make_tenant_and_users(suffix='_deny')
        self.make_monetary_reward_type()
        self.reward = self.make_reward_with_points(self.cu)
        self.repair = self.make_repair(status='PENDING')
        self.redemption = self.make_approved_redemption(
            self.cu, self.opt_discount, repair=self.repair,
        )
        self.client = Client()
        self.login_customer(self.client)

    def test_single_deny_restores_reward(self):
        """Denying a single repair restores the applied reward to APPROVED."""
        resp = self.client.post(
            reverse('customer_repair_deny', args=[self.repair.id]),
            {'reason': 'Changed my mind'},
        )
        self.assertEqual(resp.status_code, 302)

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'APPROVED')
        self.assertIsNone(self.redemption.applied_to_repair)

    def test_deny_without_reward_works(self):
        """Denying a repair with no applied reward should still work normally."""
        self.redemption.applied_to_repair = None
        self.redemption.save()

        resp = self.client.post(
            reverse('customer_repair_deny', args=[self.repair.id]),
            {'reason': 'No reward attached'},
        )
        self.assertEqual(resp.status_code, 302)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')

    def test_batch_deny_restores_rewards(self):
        """Denying a batch restores rewards applied to any repair in the batch."""
        import uuid
        batch_id = uuid.uuid4()
        repair2 = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.customer,
            unit_number='UNIT-100', description='Break 2', damage_type='Crack',
            queue_status='PENDING', repair_batch_id=batch_id,
        )
        self.repair.repair_batch_id = batch_id
        self.repair.save()

        # Apply reward to first repair in batch
        self.redemption.applied_to_repair = self.repair
        self.redemption.save()

        resp = self.client.post(
            reverse('customer_batch_deny', args=[str(batch_id)]),
            {'reason': 'Cancel batch'},
        )
        self.assertEqual(resp.status_code, 302)

        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'APPROVED')
        self.assertIsNone(self.redemption.applied_to_repair)


class DenyThenReRequestTest(RewardRedemptionUXTestMixin, TestCase):
    """Edge case: apply reward, deny repair, then reward should be available again."""

    def setUp(self):
        self.make_tenant_and_users(suffix='_reuse')
        self.make_monetary_reward_type()
        self.reward = self.make_reward_with_points(self.cu)
        self.redemption = self.make_approved_redemption(self.cu, self.opt_discount)
        self.client = Client()
        self.login_customer(self.client)

    def test_deny_then_rerequest_with_same_reward(self):
        """After denial, the reward can be applied to a new repair request."""
        # Step 1: Create repair with applied reward
        resp = self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-1',
            'damage_type': 'Chip',
            'description': 'First try',
            'apply_reward': str(self.redemption.id),
        })
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        first_repair = self.redemption.applied_to_repair
        self.assertIsNotNone(first_repair)

        # Step 2: Deny that repair
        resp = self.client.post(
            reverse('customer_repair_deny', args=[first_repair.id]),
            {'reason': 'Oops'},
        )
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        self.assertEqual(self.redemption.status, 'APPROVED')
        self.assertIsNone(self.redemption.applied_to_repair)

        # Step 3: Reward should be available again
        resp = self.client.get(reverse('customer_request_repair'))
        available = list(resp.context['available_rewards'])
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0].id, self.redemption.id)

        # Step 4: Apply to new repair
        resp = self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-2',
            'damage_type': 'Crack',
            'description': 'Second try',
            'apply_reward': str(self.redemption.id),
        })
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        self.assertIsNotNone(self.redemption.applied_to_repair)
        self.assertNotEqual(self.redemption.applied_to_repair.id, first_repair.id)


class PhysicalRewardSchedulingTest(RewardRedemptionUXTestMixin, TestCase):
    """Flow B: physical reward scheduling with date/time/notes."""

    def setUp(self):
        self.make_tenant_and_users(suffix='_phys')
        self.make_physical_reward_type()
        self.reward = self.make_reward_with_points(self.cu, points=5000)
        self.client = Client()
        self.login_customer(self.client)

    def test_redeem_physical_with_schedule(self):
        """Physical reward redemption saves preferred date/time/notes."""
        resp = self.client.post(reverse('redeem_reward'), {
            'option_id': str(self.opt_pizza.id),
            'preferred_date': '2026-04-15',
            'preferred_time': '12:00',
            'customer_notes': 'Pepperoni, 10 people',
        })
        self.assertEqual(resp.status_code, 302)

        redemption = RewardRedemption.objects.filter(
            reward__customer_user=self.cu,
            reward_option=self.opt_pizza,
        ).first()
        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.preferred_date, date(2026, 4, 15))
        self.assertEqual(redemption.preferred_time, time(12, 0))
        self.assertEqual(redemption.customer_notes, 'Pepperoni, 10 people')

    def test_scheduled_status_exists(self):
        """SCHEDULED is a valid status on RewardRedemption."""
        redemption = RewardRedemption(
            reward=self.reward,
            reward_option=self.opt_pizza,
            status='SCHEDULED',
            preferred_date=date(2026, 4, 15),
        )
        redemption.full_clean()  # Should not raise
        redemption.save()
        self.assertEqual(redemption.status, 'SCHEDULED')
        self.assertEqual(redemption.get_status_display(), 'Scheduled')


class TenantIsolationTest(RewardRedemptionUXTestMixin, TestCase):
    """Rewards from another tenant must not appear."""

    def setUp(self):
        self.make_tenant_and_users(suffix='_iso1')
        self.make_monetary_reward_type()
        self.reward = self.make_reward_with_points(self.cu)
        self.redemption = self.make_approved_redemption(self.cu, self.opt_discount)

        # Create a second tenant with its own customer
        self.other_owner = User.objects.create_user(
            'other_owner', 'other@test.com', 'TestPass123!',
        )
        self.other_tenant = Tenant.objects.create(
            name='Other Shop', slug='other-shop', subdomain='othershop',
            owner=self.other_owner, plan='trial', trial_started_at=timezone.now(),
        )
        TenantMembership.objects.create(
            user=self.other_owner, tenant=self.other_tenant, role='owner', is_active=True,
        )
        # Other tenant's tech
        other_tech_user = User.objects.create_user('other_tech', 'ot@test.com', 'TestPass123!')
        Technician.objects.create(user=other_tech_user, tenant=self.other_tenant, is_active=True)
        TenantMembership.objects.create(
            user=other_tech_user, tenant=self.other_tenant, role='technician', is_active=True,
        )
        other_tech_user.groups.add(Group.objects.get(name='Technicians'))

        other_customer = Customer.objects.create(
            tenant=self.other_tenant, name='Other Fleet', customer_type='FLEET',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=other_customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.other_cust_user = User.objects.create_user(
            'other_cust', 'oc@test.com', 'TestPass123!',
        )
        self.other_cu = CustomerUser.objects.create(
            user=self.other_cust_user, customer=other_customer,
        )

        self.client = Client()

    def test_other_tenant_rewards_not_visible(self):
        """Customer from tenant B should not see tenant A's rewards."""
        # Login as other tenant's customer
        self.client.force_login(self.other_cust_user)
        session = self.client.session
        session['tenant_id'] = self.other_tenant.id
        session.save()

        resp = self.client.get(reverse('customer_request_repair'))
        self.assertEqual(resp.status_code, 200)
        available = list(resp.context['available_rewards'])
        self.assertEqual(len(available), 0)

    def test_cannot_apply_other_tenants_reward(self):
        """Attempting to apply another tenant's reward should silently fail."""
        self.client.force_login(self.other_cust_user)
        session = self.client.session
        session['tenant_id'] = self.other_tenant.id
        session.save()

        resp = self.client.post(reverse('customer_request_repair'), {
            'unit_number': 'UNIT-X',
            'damage_type': 'Chip',
            'description': 'Sneaky',
            'apply_reward': str(self.redemption.id),
        })
        # Should redirect (repair created) but reward NOT applied
        self.assertEqual(resp.status_code, 302)
        self.redemption.refresh_from_db()
        self.assertIsNone(self.redemption.applied_to_repair)
