"""
CODE-113 Regression Test: shop_join_view() IntegrityError for multi-shop users

Bug: shop_join_view() checked if the authenticated user already had a CustomerUser
at the TARGET tenant. If not, it tried to create one automatically. However, it did
NOT check if the user already had a CustomerUser at ANY other tenant.

CustomerUser.user is a OneToOneField — only ONE CustomerUser record per Django User
globally. If the user already had a CustomerUser at Shop A and visited /join/shop-b/,
the code would find no existing_cu for shop-b (correct), then attempt to create a
second CustomerUser record (CRASH: IntegrityError on the unique constraint).

The transaction.atomic() would roll back, but there was no except block around the
create() call in the authenticated path — so this propagated as an unhandled 500.

Root cause: The CODE-093 fix (shop_join_view for authenticated users) correctly
handled the "already at this shop" case, but did not guard against the
"already at a different shop" case.

Fix (CODE-113):
  After the "existing at this tenant" check, add an "any existing CustomerUser"
  check. If the user already has a CustomerUser at ANY shop, show a clear message
  explaining the per-shop limitation and redirect to customer_dashboard (where
  their existing shop will handle the display).
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.customer_portal.models import CustomerUser


def _make_tenant(name, slug, owner):
    """Helper to create a tenant with an owner."""
    return Tenant.objects.create(
        name=name,
        slug=slug,
        is_active=True,
        plan="trial",
        owner=owner,
    )


class ShopJoinMultiShopUserTestCase(TestCase):
    """
    CODE-113 regression tests for shop_join_view() with authenticated multi-shop users.
    """

    def setUp(self):
        self.client = Client()

        # Create two shop owners
        self.owner_a = User.objects.create_user('owner_a', 'ownera@test.com', 'pass123')
        self.owner_b = User.objects.create_user('owner_b', 'ownerb@test.com', 'pass123')

        # Create two shops
        self.shop_a = _make_tenant('Shop A', 'shop-a', self.owner_a)
        self.shop_b = _make_tenant('Shop B', 'shop-b', self.owner_b)

        # Create a regular customer user at Shop A
        self.customer_at_a = User.objects.create_user('cust_a', 'custa@test.com', 'pass123')
        customer_obj = Customer.objects.create(
            tenant=self.shop_a, name='Cust A Customer', customer_type='RETAIL', email='custa@test.com'
        )
        self.cu_at_a = CustomerUser.objects.create(
            user=self.customer_at_a,
            customer=customer_obj,
            is_primary_contact=True,
        )
        TenantMembership.objects.create(tenant=self.shop_a, user=self.customer_at_a, role='viewer')

        # Create a user with NO CustomerUser (blank slate)
        self.fresh_user = User.objects.create_user('fresh', 'fresh@test.com', 'pass123')
        TenantMembership.objects.create(tenant=self.shop_a, user=self.fresh_user, role='viewer')

    def _join_url(self, shop):
        return reverse('shop_join', kwargs={'slug': shop.slug})

    def test_unauthenticated_user_sees_join_form(self):
        """Anonymous users get the join form — no crash."""
        resp = self.client.get(self._join_url(self.shop_b))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Shop B')

    def test_user_already_at_this_shop_redirects(self):
        """User with CustomerUser at Shop A visiting /join/shop-a/ is redirected cleanly."""
        self.client.force_login(self.customer_at_a)
        resp = self.client.get(self._join_url(self.shop_a))
        self.assertRedirects(resp, reverse('customer_dashboard'), fetch_redirect_response=False)

    def test_user_at_different_shop_does_not_crash(self):
        """
        CODE-113 regression: User with CustomerUser at Shop A visiting /join/shop-b/
        must NOT crash with IntegrityError (was unhandled 500 before fix).
        """
        self.client.force_login(self.customer_at_a)
        # This is the crash path: user has CU at shop_a, tries to join shop_b
        resp = self.client.get(self._join_url(self.shop_b))
        # Should be a redirect, not a 500
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)

    def test_user_at_different_shop_redirects_to_dashboard(self):
        """User with CustomerUser at Shop A visiting /join/shop-b/ gets redirected."""
        self.client.force_login(self.customer_at_a)
        resp = self.client.get(self._join_url(self.shop_b))
        self.assertRedirects(resp, reverse('customer_dashboard'), fetch_redirect_response=False)

    def test_user_at_different_shop_sees_informative_message(self):
        """User at Shop A visiting /join/shop-b/ gets a clear warning message."""
        self.client.force_login(self.customer_at_a)
        # Follow redirect to check messages
        resp = self.client.get(self._join_url(self.shop_b), follow=True)
        messages = list(resp.context.get('messages', []) if hasattr(resp, 'context') and resp.context else [])
        # Also check response content
        resp_text = resp.content.decode() if hasattr(resp, 'content') else ''
        # Message should mention per-shop limitation or "another shop"
        all_messages_text = ' '.join(str(m) for m in messages)
        has_informative_msg = (
            'Shop A' in all_messages_text or
            'another shop' in all_messages_text.lower() or
            'account is already linked' in all_messages_text.lower() or
            'portal accounts are' in all_messages_text.lower()
        )
        self.assertTrue(has_informative_msg, f"Expected informative message, got: {all_messages_text}")

    def test_user_at_different_shop_no_new_customer_user_created(self):
        """No new CustomerUser is created when user already has one at a different shop."""
        initial_count = CustomerUser.objects.filter(user=self.customer_at_a).count()
        self.client.force_login(self.customer_at_a)
        self.client.get(self._join_url(self.shop_b))
        final_count = CustomerUser.objects.filter(user=self.customer_at_a).count()
        self.assertEqual(initial_count, final_count, "No new CustomerUser should be created")
        # Verify it's still just the Shop A CustomerUser
        cu = CustomerUser.objects.get(user=self.customer_at_a)
        self.assertEqual(cu.customer.tenant, self.shop_a)

    def test_user_at_different_shop_no_new_customer_created(self):
        """No new Customer object is created for the cross-shop user."""
        initial_count = Customer.objects.filter(tenant=self.shop_b).count()
        self.client.force_login(self.customer_at_a)
        self.client.get(self._join_url(self.shop_b))
        final_count = Customer.objects.filter(tenant=self.shop_b).count()
        self.assertEqual(initial_count, final_count, "No new Customer should be created at Shop B")

    def test_fresh_user_gets_customer_user_created(self):
        """
        User with no CustomerUser visiting /join/shop-b/ gets a CustomerUser created.
        The happy path should still work after the fix.
        """
        initial_count = CustomerUser.objects.filter(user=self.fresh_user).count()
        self.assertEqual(initial_count, 0)

        self.client.force_login(self.fresh_user)
        resp = self.client.get(self._join_url(self.shop_b))
        self.assertRedirects(resp, reverse('customer_dashboard'), fetch_redirect_response=False)

        final_count = CustomerUser.objects.filter(user=self.fresh_user).count()
        self.assertEqual(final_count, 1)
        cu = CustomerUser.objects.get(user=self.fresh_user)
        self.assertEqual(cu.customer.tenant, self.shop_b)
