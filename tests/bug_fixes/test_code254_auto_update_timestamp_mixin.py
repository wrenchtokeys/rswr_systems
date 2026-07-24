"""
Tests for CODE-254: AutoUpdateTimestampMixin on all models with auto_now updated_at.

Django's auto_now=True on DateTimeField is NOT automatically included when
save() is called with update_fields=[...]. The AutoUpdateTimestampMixin
fixes this by injecting 'updated_at' into update_fields when missing.

This was originally fixed for Tenant only (CODE-253). CODE-254 creates
a reusable mixin and applies it to all 18 affected models.
"""
import time
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant, SubscriptionPlan


class AutoUpdateTimestampMixinTestMixin:
    """
    Reusable test mixin — subclasses provide `create_instance()` and
    `get_updatable_field()` returning (field_name, old_value, new_value).
    """

    def create_instance(self):
        raise NotImplementedError

    def get_updatable_field(self):
        """Return (field_name, new_value) for a field that can be updated."""
        raise NotImplementedError

    def test_update_fields_bumps_updated_at(self):
        """save(update_fields=[field]) must also bump updated_at."""
        obj = self.create_instance()
        old_updated_at = obj.updated_at

        # Small sleep to ensure timestamp differs
        time.sleep(0.05)

        field_name, new_value = self.get_updatable_field()
        setattr(obj, field_name, new_value)
        obj.save(update_fields=[field_name])

        obj.refresh_from_db()
        self.assertGreater(obj.updated_at, old_updated_at,
                           f"{type(obj).__name__}.updated_at was not bumped by save(update_fields=['{field_name}'])")

    def test_update_fields_does_not_mutate_caller_list(self):
        """save() should not mutate the caller's update_fields list."""
        obj = self.create_instance()
        field_name, new_value = self.get_updatable_field()
        setattr(obj, field_name, new_value)

        fields = [field_name]
        original_fields = list(fields)
        obj.save(update_fields=fields)

        self.assertEqual(fields, original_fields,
                         "save() mutated the caller's update_fields list")

    def test_explicit_updated_at_in_update_fields(self):
        """save(update_fields=[field, 'updated_at']) should not duplicate."""
        obj = self.create_instance()
        field_name, new_value = self.get_updatable_field()
        setattr(obj, field_name, new_value)

        # Should not raise or duplicate
        obj.save(update_fields=[field_name, 'updated_at'])
        obj.refresh_from_db()
        # Just verify it saved without error
        self.assertIsNotNone(obj.updated_at)

    def test_full_save_still_works(self):
        """save() without update_fields still works normally."""
        obj = self.create_instance()
        old_updated_at = obj.updated_at
        time.sleep(0.05)

        field_name, new_value = self.get_updatable_field()
        setattr(obj, field_name, new_value)
        obj.save()

        obj.refresh_from_db()
        self.assertGreater(obj.updated_at, old_updated_at)


class SetUpMixin:
    """Common setup for tests needing tenant + user."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='code254_test', password='testpass123',
            email='code254@test.com',
        )
        cls.tenant = Tenant.objects.create(
            name='Code254 Test Shop', slug='code254-test',
            owner=cls.user, plan='trial',
        )


class BillingConfigTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.billing.models import BillingConfig
        obj, _ = BillingConfig.objects.get_or_create(
            tenant=self.tenant,
            defaults={'company_name': 'Test Co'},
        )
        return obj

    def get_updatable_field(self):
        return ('company_name', 'Updated Co')


class InvoiceTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.billing.models import Invoice
        from apps.technician_portal.models import Customer
        customer = Customer.objects.create(
            name='Invoice Test Customer', tenant=self.tenant, email='inv@test.com',
        )
        return Invoice.objects.create(
            tenant=self.tenant,
            customer=customer,
            invoice_number='INV-CODE254-001',
            status='DRAFT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
        )

    def get_updatable_field(self):
        return ('status', 'SENT')


class WarrantyPolicyTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.technician_portal.models import WarrantyPolicy
        return WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Code254 Warranty',
            applies_to='repairs', duration_type='days', duration_days=365,
        )

    def get_updatable_field(self):
        return ('duration_days', 180)


class ViscosityRecommendationTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.technician_portal.models import ViscosityRecommendation
        return ViscosityRecommendation.objects.create(
            tenant=self.tenant, name='Code254 Viscosity',
            recommended_viscosity='Medium', display_order=1,
        )

    def get_updatable_field(self):
        return ('recommended_viscosity', 'Thick')


class CustomerRepairPreferenceTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.customer_portal.models import CustomerRepairPreference
        from apps.technician_portal.models import Customer
        customer = Customer.objects.create(
            name='CRP Test Customer', tenant=self.tenant, email='crp@test.com',
        )
        return CustomerRepairPreference.objects.create(customer=customer)

    def get_updatable_field(self):
        return ('auto_email_invoices', True)


class RewardTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.rewards_referrals.models import Reward
        from apps.technician_portal.models import Customer
        from apps.customer_portal.models import CustomerUser
        customer = Customer.objects.create(
            name='Reward Test Customer', tenant=self.tenant, email='rwd@test.com',
        )
        cu = CustomerUser.objects.create(user=self.user, customer=customer)
        return Reward.objects.create(customer_user=cu, points=100)

    def get_updatable_field(self):
        return ('points', 200)


class RewardOptionTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.rewards_referrals.models import RewardOption, RewardType
        rt = RewardType.objects.create(
            name='Code254 Type', category='DISCOUNT',
            discount_type='PERCENTAGE', discount_value=Decimal('10.00'),
        )
        return RewardOption.objects.create(
            tenant=self.tenant, name='Code254 Option',
            points_required=50, reward_type=rt,
        )

    def get_updatable_field(self):
        return ('points_required', 100)


class LoyaltyConfigTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from apps.rewards_referrals.models import LoyaltyConfig
        obj, _ = LoyaltyConfig.objects.get_or_create(
            tenant=self.tenant,
            defaults={'program_name': 'Test Loyalty'},
        )
        return obj

    def get_updatable_field(self):
        return ('program_name', 'Updated Loyalty')


class VehicleTimestampTest(SetUpMixin, AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from core.models import Vehicle, Customer
        customer = Customer.objects.create(
            name='Vehicle Test Customer', tenant=self.tenant, email='veh@test.com',
        )
        return Vehicle.objects.create(
            tenant=self.tenant, customer=customer, unit_number='VEH-254',
        )

    def get_updatable_field(self):
        return ('unit_number', 'VEH-254-UPDATED')


class NotificationTemplateTimestampTest(AutoUpdateTimestampMixinTestMixin, TestCase):
    def create_instance(self):
        from core.models import NotificationTemplate
        return NotificationTemplate.objects.create(
            name='Code254 Template', category='system',
            title_template='Test Title', message_template='Test Body',
        )

    def get_updatable_field(self):
        return ('title_template', 'Updated Title')
