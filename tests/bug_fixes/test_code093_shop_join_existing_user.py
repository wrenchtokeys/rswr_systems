"""
CODE-093: shop_join_view blocks existing users with unhelpful error.

Bug: When an authenticated user visits /join/<slug>/ they were shown the
registration form.  If they submitted with their existing email they got
"An account with this email already exists. Please log in instead." — but
logging in wouldn't automatically grant them access to the new shop.

Fix: The view now detects authenticated users at the top:
  - Already has a CustomerUser at this tenant → redirect to customer_dashboard.
  - No CustomerUser yet → auto-create Customer + CustomerUser + TenantMembership
    and redirect to customer_dashboard.

This ensures /login/?next=/join/<slug>/ works end-to-end for returning users.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.customer_portal.models import CustomerUser


class ShopJoinExistingUserTestCase(TestCase):
    """CODE-093 regression tests for shop_join_view."""

    def setUp(self):
        self.client = Client()

        # Tenant A owner (required FK)
        self.shop_owner = User.objects.create_user(
            username="shop_owner_a",
            email="owner@shop-a.com",
            password="ownerpass123",
        )

        # Tenant A (the shop being joined)
        self.tenant_a = Tenant.objects.create(
            name="Shop A",
            slug="shop-a",
            is_active=True,
            plan="trial",
            owner=self.shop_owner,
        )

        # An existing user with an account but no customer record at tenant_a
        self.user = User.objects.create_user(
            username="returning_user",
            email="user@example.com",
            password="testpass123",
            first_name="Jane",
            last_name="Doe",
        )

    def test_authenticated_user_without_customer_record_gets_auto_enrolled(self):
        """
        When an authenticated user visits /join/<slug>/ and has no CustomerUser
        at that tenant, a Customer + CustomerUser + TenantMembership should be
        created automatically and they should be redirected to customer_dashboard.
        """
        self.client.login(username="returning_user", password="testpass123")

        response = self.client.get(reverse("shop_join", kwargs={"slug": "shop-a"}))

        # Should redirect to customer_dashboard
        self.assertRedirects(response, reverse("customer_dashboard"), fetch_redirect_response=False)

        # CustomerUser should now exist
        self.assertTrue(
            CustomerUser.objects.filter(
                user=self.user, customer__tenant=self.tenant_a
            ).exists(),
            "CustomerUser should have been created automatically",
        )

        # Customer should be scoped to tenant_a
        customer = Customer.objects.get(customeruser__user=self.user, tenant=self.tenant_a)
        self.assertEqual(customer.tenant, self.tenant_a)

        # TenantMembership should exist
        self.assertTrue(
            TenantMembership.objects.filter(
                tenant=self.tenant_a, user=self.user
            ).exists(),
            "TenantMembership should have been created automatically",
        )

    def test_authenticated_user_with_existing_customer_record_is_redirected(self):
        """
        When an authenticated user already has a CustomerUser at the tenant,
        they should be redirected to customer_dashboard without creating duplicates.
        """
        # Pre-create the customer record
        existing_customer = Customer.objects.create(
            tenant=self.tenant_a,
            name="Jane Doe",
            customer_type="RETAIL",
            email="user@example.com",
        )
        CustomerUser.objects.create(
            user=self.user,
            customer=existing_customer,
            is_primary_contact=True,
        )

        self.client.login(username="returning_user", password="testpass123")
        response = self.client.get(reverse("shop_join", kwargs={"slug": "shop-a"}))

        self.assertRedirects(response, reverse("customer_dashboard"), fetch_redirect_response=False)

        # No duplicate customer records should be created
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant_a, customeruser__user=self.user).count(),
            1,
            "Should not create a duplicate Customer record",
        )

    def test_unauthenticated_user_sees_registration_form(self):
        """
        Unauthenticated users should still see the registration form.
        """
        response = self.client.get(reverse("shop_join", kwargs={"slug": "shop-a"}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shop A")

    def test_unauthenticated_post_with_existing_email_shows_helpful_error(self):
        """
        When an unauthenticated user POSTs with an email that already exists,
        the error message should guide them to log in.
        """
        response = self.client.post(
            reverse("shop_join", kwargs={"slug": "shop-a"}),
            {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "user@example.com",
                "password": "TestPass123!",
                "confirm_password": "TestPass123!",
                "company_name": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        # Should show the error about existing account
        self.assertContains(response, "already exists")
        # Should mention logging in
        self.assertContains(response, "log in")

    def test_auto_enroll_does_not_create_duplicate_on_second_visit(self):
        """
        Two visits by the same authenticated user should not create two
        CustomerUser records.
        """
        self.client.login(username="returning_user", password="testpass123")

        self.client.get(reverse("shop_join", kwargs={"slug": "shop-a"}))
        self.client.get(reverse("shop_join", kwargs={"slug": "shop-a"}))

        self.assertEqual(
            CustomerUser.objects.filter(
                user=self.user, customer__tenant=self.tenant_a
            ).count(),
            1,
            "Should only create one CustomerUser even on repeated visits",
        )
