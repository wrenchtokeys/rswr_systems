"""
CODE-239: Missing @customer_required on customer portal API endpoints

repair_pricing_api and unit_repair_data_api lacked the @customer_required
decorator, meaning unauthenticated requests could reach them. While both
called _get_customer_user_for_tenant (which would fail for AnonymousUser),
the missing decorator meant:
  1. No clean redirect to login — just a raw 404/500 JSON error
  2. No gatekeeper verifying the user has a valid CustomerUser record
  3. Inconsistent with repair_cost_data_api which had the decorator

Fix: Added @customer_required to both endpoints.
"""

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.contrib.auth.models import User


class TestRepairPricingApiAuth(TestCase):
    """Verify repair_pricing_api requires authentication."""

    def test_anonymous_user_redirected(self):
        """Unauthenticated GET to repair_pricing_api should redirect to login."""
        url = reverse('repair_pricing_api')
        response = self.client.post(url, content_type='application/json', data='{}')
        # @customer_required redirects unauthenticated users to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_anonymous_get_redirected(self):
        url = reverse('repair_pricing_api')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class TestUnitRepairDataApiAuth(TestCase):
    """Verify unit_repair_data_api requires authentication."""

    def test_anonymous_user_redirected(self):
        """Unauthenticated GET to unit_repair_data_api should redirect to login."""
        url = reverse('unit_repair_data_api')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class TestRepairCostDataApiAuth(TestCase):
    """Sanity check: repair_cost_data_api already had @customer_required."""

    def test_anonymous_user_redirected(self):
        url = reverse('repair_cost_data_api')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
