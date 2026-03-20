"""
CODE-106 Regression Test: accept_customer_invitation() unclear "Contact support" message

Bug: accept_customer_invitation() used an unscoped CustomerUser lookup, then checked
equality between the found customer and the invitation's customer. When a user with a
CustomerUser at Shop A clicked on a Shop B invitation, the else-branch showed:

    "You're already linked to Shop A. Contact support if you need access to Shop B."

This was the only message — no context about what's happening, no explanation that
the schema doesn't support multi-shop customers, and no actionable next step. "Contact
support" is a dead-end that makes the invitation process feel broken.

Root cause: The check was correct in concept (CustomerUser.user is a OneToOneField —
one CustomerUser per User globally, so a second one literally cannot be created), but
the error messaging was unhelpful and didn't explain the limitation.

Additionally, the check didn't distinguish between:
  1. User already linked to the SAME customer (already done — just redirect).
  2. User linked to a DIFFERENT customer at the SAME shop (has access under another account).
  3. User linked to a customer at a DIFFERENT shop (schema limitation — clear message needed).

Fix (CODE-106):
  - Case 1 (same customer): Show "You're already set up for X" and redirect.
  - Case 2 (different customer, same shop): Show "You have access under Y, contact admin".
  - Case 3 (different shop): Show a clear explanation that portal accounts are per-shop,
    and tell them to ask the shop to create a new account (instead of "Contact support").
  - No CustomerUser in DB: Proceed as before (create CustomerUser + TenantMembership).

Impact: Multi-shop users who receive a customer portal invitation now get a clear,
actionable message instead of a confusing dead-end.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.customer_portal.models import CustomerUser, CustomerInvitation


def _make_tenant(name, slug, owner):
    """Helper to create a tenant."""
    return Tenant.objects.create(
        name=name,
        slug=slug,
        is_active=True,
        plan="trial",
        owner=owner,
    )


class AcceptInvitationMultiShopTestCase(TestCase):
    """
    CODE-106 regression tests for accept_customer_invitation() edge cases.
    """

    def setUp(self):
        self.client = Client()

        # Two shop owners
        self.owner_a = User.objects.create_user(
            username="owner_a", email="owner_a@example.com", password="pass123"
        )
        self.owner_b = User.objects.create_user(
            username="owner_b", email="owner_b@example.com", password="pass123"
        )

        # Two shops
        self.shop_a = _make_tenant("Shop A", "shop-a", self.owner_a)
        self.shop_b = _make_tenant("Shop B", "shop-b", self.owner_b)

        TenantMembership.objects.create(
            tenant=self.shop_a, user=self.owner_a, role="owner", is_active=True
        )
        TenantMembership.objects.create(
            tenant=self.shop_b, user=self.owner_b, role="owner", is_active=True
        )

        # Customers at each shop
        self.customer_a = Customer.objects.create(
            tenant=self.shop_a, name="Fleet A", customer_type="FLEET"
        )
        self.customer_b = Customer.objects.create(
            tenant=self.shop_b, name="Fleet B", customer_type="FLEET"
        )
        # A second customer at Shop B (for same-tenant different-customer test)
        self.customer_b2 = Customer.objects.create(
            tenant=self.shop_b, name="Fleet B2", customer_type="FLEET"
        )

        # User who is already linked to Shop A customer_a
        self.shop_a_user = User.objects.create_user(
            username="shop_a_user", email="shop_a@example.com", password="pass123"
        )
        CustomerUser.objects.create(
            user=self.shop_a_user, customer=self.customer_a, is_primary_contact=True
        )
        TenantMembership.objects.create(
            tenant=self.shop_a, user=self.shop_a_user, role="viewer", is_active=True
        )

        # User who is already linked to Shop B customer_b (same shop, different customer)
        self.shop_b_user = User.objects.create_user(
            username="shop_b_user", email="shop_b@example.com", password="pass123"
        )
        CustomerUser.objects.create(
            user=self.shop_b_user, customer=self.customer_b, is_primary_contact=True
        )
        TenantMembership.objects.create(
            tenant=self.shop_b, user=self.shop_b_user, role="viewer", is_active=True
        )

        # Invitation from Shop B for the Shop-A user (cross-shop scenario)
        self.invitation_b_for_a_user = CustomerInvitation.objects.create(
            customer=self.customer_b,
            email=self.shop_a_user.email,
            invited_by=self.owner_b,
            is_primary_contact=False,
        )

        # Invitation from Shop B (customer_b2) for the existing shop-B user
        # (same shop, different customer scenario)
        self.invitation_b2_for_b_user = CustomerInvitation.objects.create(
            customer=self.customer_b2,
            email=self.shop_b_user.email,
            invited_by=self.owner_b,
            is_primary_contact=False,
        )

    # -------------------------------------------------------------------------
    # CORE BUG: cross-shop user gets actionable message, not "Contact support"
    # -------------------------------------------------------------------------

    def test_cross_shop_user_does_not_see_contact_support(self):
        """
        CODE-106: A user linked to Shop A who receives a Shop B invitation
        should NOT see the vague "Contact support" message.
        Before the fix, this was the only message shown.
        """
        self.client.force_login(self.shop_a_user)
        url = reverse("accept_customer_invitation", args=[self.invitation_b_for_a_user.token])
        response = self.client.get(url, follow=True)

        self.assertNotContains(response, "Contact support")

    def test_cross_shop_user_sees_clear_limitation_message(self):
        """
        CODE-106: Cross-shop user should see a clear explanation of the limitation
        and what to do next.
        """
        self.client.force_login(self.shop_a_user)
        url = reverse("accept_customer_invitation", args=[self.invitation_b_for_a_user.token])
        response = self.client.get(url, follow=True)

        # Message should mention "one shop" or the shop name
        content = response.content.decode()
        # Should contain actionable guidance (not just "contact support")
        has_actionable = ("one shop" in content or "new account" in content or
                         "Shop A" in content or "Fleet A" in content)
        self.assertTrue(has_actionable, "Response should contain actionable information about the limitation")

    def test_cross_shop_user_redirects_to_dashboard(self):
        """
        CODE-106: Cross-shop user should be redirected to dashboard gracefully.
        """
        self.client.force_login(self.shop_a_user)
        url = reverse("accept_customer_invitation", args=[self.invitation_b_for_a_user.token])
        response = self.client.get(url)

        self.assertRedirects(response, reverse("customer_dashboard"))

    def test_cross_shop_user_customer_user_not_created(self):
        """
        CODE-106: A cross-shop user's existing CustomerUser should not be
        duplicated — the DB constraint prevents it anyway, but we should
        not even attempt it.
        """
        self.client.force_login(self.shop_a_user)
        url = reverse("accept_customer_invitation", args=[self.invitation_b_for_a_user.token])
        self.client.get(url)

        # Only ONE CustomerUser should exist for this user (the original one)
        cu_count = CustomerUser.objects.filter(user=self.shop_a_user).count()
        self.assertEqual(cu_count, 1, "No extra CustomerUser should be created")

        # Original link to Shop A must be preserved
        cu = CustomerUser.objects.get(user=self.shop_a_user)
        self.assertEqual(cu.customer, self.customer_a)

    # -------------------------------------------------------------------------
    # SAME-SHOP, DIFFERENT CUSTOMER: should redirect with a helpful message
    # -------------------------------------------------------------------------

    def test_same_shop_different_customer_redirects(self):
        """
        CODE-106: A user who already has access at the same shop but under
        a different customer account should be redirected to dashboard.
        """
        self.client.force_login(self.shop_b_user)
        url = reverse("accept_customer_invitation", args=[self.invitation_b2_for_b_user.token])
        response = self.client.get(url)

        self.assertRedirects(response, reverse("customer_dashboard"))

    def test_same_shop_different_customer_does_not_create_extra_cu(self):
        """
        CODE-106: A user already linked at the same shop under a different
        customer should not get a second CustomerUser record created.
        """
        self.client.force_login(self.shop_b_user)
        url = reverse("accept_customer_invitation", args=[self.invitation_b2_for_b_user.token])
        self.client.get(url)

        cu_count = CustomerUser.objects.filter(user=self.shop_b_user).count()
        self.assertEqual(cu_count, 1)

    # -------------------------------------------------------------------------
    # UNCHANGED BEHAVIOUR: user already linked to SAME customer
    # -------------------------------------------------------------------------

    def test_user_already_at_same_customer_gets_info_message(self):
        """
        Accepting an invitation for the same customer where the user is
        already linked should show an "already set up" info message.
        """
        # Create invitation for shop_b_user back to their own customer_b
        same_inv = CustomerInvitation.objects.create(
            customer=self.customer_b,
            email=self.shop_b_user.email,
            invited_by=self.owner_b,
        )
        self.client.force_login(self.shop_b_user)
        url = reverse("accept_customer_invitation", args=[same_inv.token])
        response = self.client.get(url, follow=True)

        # Should not get an error; should see "already set up" type message
        self.assertRedirects(response, reverse("customer_dashboard"))
        content = response.content.decode()
        self.assertIn("already", content.lower())

    def test_user_already_at_same_customer_no_duplicate_cu(self):
        """
        No extra CustomerUser should be created when the user is already set up.
        """
        same_inv = CustomerInvitation.objects.create(
            customer=self.customer_b,
            email=self.shop_b_user.email,
            invited_by=self.owner_b,
        )
        self.client.force_login(self.shop_b_user)
        url = reverse("accept_customer_invitation", args=[same_inv.token])
        self.client.get(url)

        cu_count = CustomerUser.objects.filter(user=self.shop_b_user).count()
        self.assertEqual(cu_count, 1)

    # -------------------------------------------------------------------------
    # UNCHANGED: happy path — new user with no existing CustomerUser
    # -------------------------------------------------------------------------

    def test_new_user_sees_registration_form(self):
        """
        A non-authenticated user accessing an invitation link still sees the
        registration form (existing behaviour preserved).
        """
        new_inv = CustomerInvitation.objects.create(
            customer=self.customer_b,
            email="newperson@example.com",
            invited_by=self.owner_b,
        )
        url = reverse("accept_customer_invitation", args=[new_inv.token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "customer_portal/invitation_accept.html")

    def test_authenticated_user_no_cu_gets_linked(self):
        """
        An authenticated user with no existing CustomerUser should be linked
        to the invitation's customer (no regression on the normal happy path).
        """
        fresh_user = User.objects.create_user(
            username="fresh_user", email="fresh@example.com", password="pass123"
        )
        TenantMembership.objects.create(
            tenant=self.shop_b, user=fresh_user, role="viewer", is_active=True
        )
        fresh_inv = CustomerInvitation.objects.create(
            customer=self.customer_b,
            email=fresh_user.email,
            invited_by=self.owner_b,
            is_primary_contact=True,
        )
        self.client.force_login(fresh_user)
        url = reverse("accept_customer_invitation", args=[fresh_inv.token])
        response = self.client.get(url)

        self.assertRedirects(response, reverse("customer_dashboard"))
        cu = CustomerUser.objects.filter(user=fresh_user).first()
        self.assertIsNotNone(cu)
        self.assertEqual(cu.customer, self.customer_b)
        self.assertTrue(cu.is_primary_contact)

    def test_invalid_token_returns_invalid_page(self):
        """
        An invalid or expired token shows the invalid invitation page.
        """
        url = reverse("accept_customer_invitation", args=["invalidtoken12345678"])
        response = self.client.get(url)
        self.assertTemplateUsed(response, "customer_portal/invitation_invalid.html")
