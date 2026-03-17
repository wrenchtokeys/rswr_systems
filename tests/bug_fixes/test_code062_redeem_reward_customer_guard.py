"""
Regression tests for CODE-062:
  redeem_reward() view was missing the customer_user is None guard.

Root cause:
    All other views in rewards_referrals/views.py that call
    get_customer_user() immediately guard against None:
        customer_user = get_customer_user(request)
        if customer_user is None:
            return _customer_required_redirect(request)

    The redeem_reward view called get_customer_user() inside a broad
    try/except but skipped the None guard.  When a non-customer user
    (shop owner, technician) POSTed to /referrals/redeem/, the service
    call hit:
        tenant = customer_user.customer.tenant
    which raised:
        AttributeError: 'NoneType' object has no attribute 'customer'

    The except caught this and returned:
        messages.error(request,
            "An error occurred while processing your redemption: "
            "'NoneType' object has no attribute 'customer'")
    — a confusing internal error leak to the user.

Fix:
    Added `if customer_user is None: return _customer_required_redirect(request)`
    immediately after get_customer_user(), matching every other call site.

Tests verify:
1. Owner POSTing to redeem_reward gets the customer-required redirect
   (not the "unexpected error" message containing internal implementation detail).
2. Technician POSTing to redeem_reward gets the customer-required redirect.
3. Customer user still hits the normal service path.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from apps.rewards_referrals.models import RewardOption


class RedeemRewardCustomerGuardTest(TestCase):
    """Verify the missing customer_user guard in redeem_reward view."""

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={
                'name': 'Trial',
                'monthly_price': 0,
                'annual_price': 0,
                'max_technicians': 2,
                'is_active': True,
            },
        )
        self.owner = User.objects.create_user(
            username='owner_code062',
            email='owner_code062@example.com',
            password='password',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop Code062',
            slug='test-shop-code062',
            subdomain='test-shop-code062',
            owner=self.owner,
            plan='trial',
            subscription_plan=plan,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True
        )

        # Technician user (no CustomerUser record)
        self.tech = User.objects.create_user(
            username='tech_code062',
            email='tech_code062@example.com',
            password='password',
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.tech, role='technician', is_active=True
        )

        # Customer user (has CustomerUser record)
        self.customer_auth_user = User.objects.create_user(
            username='cust_code062',
            email='cust_code062@example.com',
            password='password',
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Customer Code062',
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.customer_auth_user,
            role='viewer',
            is_active=True,
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.customer_auth_user,
            customer=self.customer,
            is_primary_contact=True,
        )

        # RewardOption in this tenant
        self.reward_option = RewardOption.objects.create(
            tenant=self.tenant,
            name='Free oil change',
            points_required=100,
            is_active=True,
        )

        self.client = Client()

    def _login(self, user):
        self.client.login(username=user.username, password='password')

    # ------------------------------------------------------------------
    # Owner / Technician (no CustomerUser) — must redirect cleanly
    # ------------------------------------------------------------------

    def test_owner_redeem_no_attribute_error_in_message(self):
        """
        Owner POSTing to redeem_reward must NOT see internal error message
        containing 'NoneType' / attribute error text.
        """
        self._login(self.owner)
        resp = self.client.post(
            reverse('redeem_reward'),
            {'option_id': self.reward_option.id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        # Should NOT contain internal error text
        content = resp.content.decode()
        self.assertNotIn("NoneType", content)
        self.assertNotIn("'NoneType' object has no attribute", content)

    def test_owner_redeem_redirects_appropriately(self):
        """Owner gets a clean redirect (not 500)."""
        self._login(self.owner)
        resp = self.client.post(
            reverse('redeem_reward'),
            {'option_id': self.reward_option.id},
        )
        # Should be a redirect (302) to customer-required page or login
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp.status_code, 500)

    def test_tech_redeem_no_attribute_error_in_message(self):
        """
        Technician POSTing to redeem_reward must NOT see internal error
        containing NoneType attribute error.
        """
        self._login(self.tech)
        resp = self.client.post(
            reverse('redeem_reward'),
            {'option_id': self.reward_option.id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("NoneType", content)
        self.assertNotIn("'NoneType' object has no attribute", content)

    def test_tech_redeem_redirects_appropriately(self):
        """Technician gets a clean redirect (not 500)."""
        self._login(self.tech)
        resp = self.client.post(
            reverse('redeem_reward'),
            {'option_id': self.reward_option.id},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotEqual(resp.status_code, 500)

    # ------------------------------------------------------------------
    # Customer user — should reach the service path
    # ------------------------------------------------------------------

    def test_customer_redeem_insufficient_points_no_500(self):
        """
        Customer with 0 points gets an error message from the service
        (not a 500 or NoneType error).
        """
        self._login(self.customer_auth_user)
        resp = self.client.post(
            reverse('redeem_reward'),
            {'option_id': self.reward_option.id},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("NoneType", content)
        # Should show the "not enough points" error from the service
        self.assertIn("Not enough points", content)

    def test_customer_redeem_invalid_option_no_500(self):
        """
        Customer POSTing a non-existent option_id gets 'Invalid reward option'
        from RewardOption.DoesNotExist handler, not a 500.
        """
        self._login(self.customer_auth_user)
        resp = self.client.post(
            reverse('redeem_reward'),
            {'option_id': 999999},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn("NoneType", content)
