"""
Regression tests for CODE-055:
  get_customer_user() in rewards_referrals/views.py raised
  CustomerUser.DoesNotExist (→ unhandled 500) for any authenticated
  non-customer user (shop owner, technician) who hit any /referrals/ URL.

Root cause:
    get_customer_user() did CustomerUser.objects.get(user=request.user)
    which raises DoesNotExist for users without a CustomerUser record.

Fix:
    Changed to .filter().first() (returns None), added
    _customer_required_redirect() helper, and added `if customer_user is None`
    guards to all 12 call sites.

Tests verify that:
1. Owner / technician get a redirect or 403, NOT a 500.
2. Customers still get the normal response.
"""

import json

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.customer_portal.models import CustomerUser
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(name="TestShop"):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial",
        defaults={"name": "Trial", "monthly_price": 0, "annual_price": 0, "max_customers": 50, "max_technicians": 5, "is_active": True},
    )
    owner = User.objects.create_user(
        username=f"owner_{name.lower()}",
        email=f"owner@{name.lower()}.com",
        password="pass1234",
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower(),
        subdomain=name.lower(),
        owner=owner,
        plan="trial",
        subscription_plan=plan,
        subscription_status="trialing",
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role="owner")
    return tenant, owner


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class RewardsNonCustomer500TestCase(TestCase):
    """
    All /referrals/ views must return redirect or 403 for non-customer users,
    not an unhandled 500.
    """

    def setUp(self):
        self.client = Client()
        self.tenant, self.owner = _make_tenant("Shopify")

        # Technician user (has TenantMembership but no CustomerUser)
        self.tech_user = User.objects.create_user(
            username="techie",
            email="tech@shopify.com",
            password="pass1234",
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.tech_user, role="technician")

        # Customer user (has CustomerUser)
        self.cust_user = User.objects.create_user(
            username="customer1",
            email="cust@fleet.com",
            password="pass1234",
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Fleet Co",
            email="fleet@example.com",
        )
        CustomerUser.objects.create(user=self.cust_user, customer=self.customer)

    def _login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["tenant_id"] = self.tenant.id
        session.save()

    # -- HTML views ----------------------------------------------------------

    def test_generate_referral_code_owner_no_500(self):
        """Owner hitting /referrals/generate-referral-code/ must NOT get 500."""
        self._login(self.owner)
        resp = self.client.get(reverse("generate_referral_code"))
        self.assertNotEqual(resp.status_code, 500, "Expected redirect/403, got 500")
        self.assertIn(resp.status_code, [302, 403])

    def test_generate_referral_code_tech_no_500(self):
        """Technician hitting /referrals/generate-referral-code/ must NOT get 500."""
        self._login(self.tech_user)
        resp = self.client.get(reverse("generate_referral_code"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_referral_history_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("referral_history"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_referral_stats_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("referral_stats"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_reward_balance_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("reward_balance"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_reward_history_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("reward_history"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_referral_rewards_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("referral_rewards"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_referral_rewards_history_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("referral_rewards_history"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_referral_rewards_balance_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("referral_rewards_balance"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_referral_code_endpoint_owner_no_500(self):
        self._login(self.owner)
        resp = self.client.get(reverse("referral_code"))
        self.assertNotEqual(resp.status_code, 500)
        self.assertIn(resp.status_code, [302, 403])

    def test_redeem_reward_owner_no_500(self):
        """POST to redeem_reward from owner must not 500."""
        self._login(self.owner)
        resp = self.client.post(reverse("redeem_reward"), {"option_id": 999})
        self.assertNotEqual(resp.status_code, 500)
        # Should redirect to referral_rewards or 403/302
        self.assertIn(resp.status_code, [302, 403])

    # -- Customers still work ------------------------------------------------

    def test_referral_rewards_customer_ok(self):
        """Customer user should still get a valid response (200 or redirect to setup)."""
        self._login(self.cust_user)
        resp = self.client.get(reverse("referral_rewards"))
        # Should NOT be a redirect-away to profile_creation and definitely not 500
        self.assertNotEqual(resp.status_code, 500)
        # 200 (dashboard) or 302 (to create profile if not fully set up)
        self.assertIn(resp.status_code, [200, 302])

    def test_reward_balance_customer_returns_json(self):
        """Customer reward_balance should return JSON with points."""
        self._login(self.cust_user)
        resp = self.client.get(reverse("reward_balance"))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data["success"])
        self.assertIn("points", data)

    # -- Unauthenticated users redirect to login -----------------------------

    def test_referral_rewards_unauthenticated_redirects_to_login(self):
        """Unauthenticated request must redirect to login, not 500."""
        resp = self.client.get(reverse("referral_rewards"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp["Location"])
