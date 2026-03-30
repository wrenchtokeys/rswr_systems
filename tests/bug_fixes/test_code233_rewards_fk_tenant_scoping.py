"""
CODE-233: FK dropdown scoping for rewards/referrals admin classes.

Bug: CustomerUserTenantFilterMixin (used by RewardAdmin, ReferralCodeAdmin)
and ReferralAdmin had no formfield_for_foreignkey override. Non-superuser
staff could see FK dropdown entries from ALL tenants when editing rewards,
referral codes, or referrals — a cross-tenant data leak.

Fix: Added formfield_for_foreignkey to CustomerUserTenantFilterMixin and
ReferralAdmin that scopes FK dropdowns to the user's tenant(s).
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.admin import (
    ReferralAdmin,
    ReferralCodeAdmin,
    RewardAdmin,
)
from apps.rewards_referrals.models import (
    Referral,
    ReferralCode,
    Reward,
)
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Customer


class RewardsFKTenantScopingTests(TestCase):
    """Verify FK dropdowns in rewards/referrals admin are tenant-scoped."""

    @classmethod
    def setUpTestData(cls):
        # Staff user for tenant A (non-superuser)
        cls.staff_user = User.objects.create_user(
            'staff_a', 'staff@shopa.com', 'pass',
            is_staff=True,
        )

        # Owner for tenant B
        cls.owner_b = User.objects.create_user(
            'owner_b', 'owner@shopb.com', 'pass',
        )

        # Two tenants
        cls.tenant_a = Tenant.objects.create(
            name='Shop A', slug='shop-a', subscription_status='active',
            owner=cls.staff_user,
        )
        cls.tenant_b = Tenant.objects.create(
            name='Shop B', slug='shop-b', subscription_status='active',
            owner=cls.owner_b,
        )

        TenantMembership.objects.create(
            user=cls.staff_user, tenant=cls.tenant_a, role='owner', is_active=True,
        )

        # Superuser
        cls.superuser = User.objects.create_superuser(
            'super', 'super@test.com', 'pass'
        )

        # Customers in each tenant
        cls.customer_a = Customer.objects.create(
            name='Customer A', tenant=cls.tenant_a,
        )
        cls.customer_b = Customer.objects.create(
            name='Customer B', tenant=cls.tenant_b,
        )

        # CustomerUsers in each tenant
        cls.cu_user_a = User.objects.create_user('cu_a', 'cu_a@test.com', 'pass')
        cls.cu_user_b = User.objects.create_user('cu_b', 'cu_b@test.com', 'pass')
        cls.cu_a = CustomerUser.objects.create(
            user=cls.cu_user_a, customer=cls.customer_a,
        )
        cls.cu_b = CustomerUser.objects.create(
            user=cls.cu_user_b, customer=cls.customer_b,
        )

        # Rewards
        cls.reward_a = Reward.objects.create(customer_user=cls.cu_a, points=100)
        cls.reward_b = Reward.objects.create(customer_user=cls.cu_b, points=200)

        # Referral codes
        cls.code_a = ReferralCode.objects.create(
            customer_user=cls.cu_a, code='CODE-A',
        )
        cls.code_b = ReferralCode.objects.create(
            customer_user=cls.cu_b, code='CODE-B',
        )

        cls.factory = RequestFactory()
        cls.site = AdminSite()

    def _make_request(self, user):
        request = self.factory.get('/admin/')
        request.user = user
        return request

    # ---- RewardAdmin: customer_user FK scoping ----

    def test_reward_admin_customer_user_fk_scoped_for_staff(self):
        """Staff should only see their tenant's CustomerUsers in the dropdown."""
        admin_obj = RewardAdmin(Reward, self.site)
        request = self._make_request(self.staff_user)
        db_field = Reward._meta.get_field('customer_user')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        qs = formfield.queryset
        self.assertIn(self.cu_a, qs)
        self.assertNotIn(self.cu_b, qs)

    def test_reward_admin_customer_user_fk_unscoped_for_superuser(self):
        """Superuser should see ALL CustomerUsers."""
        admin_obj = RewardAdmin(Reward, self.site)
        request = self._make_request(self.superuser)
        db_field = Reward._meta.get_field('customer_user')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        qs = formfield.queryset
        self.assertIn(self.cu_a, qs)
        self.assertIn(self.cu_b, qs)

    # ---- ReferralCodeAdmin: customer_user FK scoping ----

    def test_referral_code_admin_customer_user_fk_scoped(self):
        """Staff should only see their tenant's CustomerUsers."""
        admin_obj = ReferralCodeAdmin(ReferralCode, self.site)
        request = self._make_request(self.staff_user)
        db_field = ReferralCode._meta.get_field('customer_user')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        qs = formfield.queryset
        self.assertIn(self.cu_a, qs)
        self.assertNotIn(self.cu_b, qs)

    # ---- ReferralAdmin: referral_code FK scoping ----

    def test_referral_admin_referral_code_fk_scoped(self):
        """Staff should only see their tenant's ReferralCodes in the dropdown."""
        admin_obj = ReferralAdmin(Referral, self.site)
        request = self._make_request(self.staff_user)
        db_field = Referral._meta.get_field('referral_code')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        qs = formfield.queryset
        self.assertIn(self.code_a, qs)
        self.assertNotIn(self.code_b, qs)

    def test_referral_admin_customer_user_fk_scoped(self):
        """Staff should only see their tenant's CustomerUsers in the dropdown."""
        admin_obj = ReferralAdmin(Referral, self.site)
        request = self._make_request(self.staff_user)
        db_field = Referral._meta.get_field('customer_user')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        qs = formfield.queryset
        self.assertIn(self.cu_a, qs)
        self.assertNotIn(self.cu_b, qs)

    def test_referral_admin_fk_unscoped_for_superuser(self):
        """Superuser should see ALL records in FK dropdowns."""
        admin_obj = ReferralAdmin(Referral, self.site)
        request = self._make_request(self.superuser)
        # referral_code
        db_field = Referral._meta.get_field('referral_code')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        self.assertIn(self.code_a, formfield.queryset)
        self.assertIn(self.code_b, formfield.queryset)
        # customer_user
        db_field = Referral._meta.get_field('customer_user')
        formfield = admin_obj.formfield_for_foreignkey(db_field, request)
        self.assertIn(self.cu_a, formfield.queryset)
        self.assertIn(self.cu_b, formfield.queryset)
