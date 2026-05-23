"""
CODE-242: Duplicate @customer_required decorators on customer portal API endpoints.

repair_pricing_api and unit_repair_data_api both had @customer_required applied
twice, causing two separate DB lookups per request (CustomerUser.objects.filter)
when only one is needed.

This test verifies the decorator is applied exactly once by inspecting the
wrapped function's __wrapped__ chain depth.  It also confirms both endpoints
remain protected (unauthenticated → redirect).
"""

from django.test import TestCase

from apps.customer_portal import views


class DuplicateDecoratorRegressionTest(TestCase):
    """Ensure customer_required is applied exactly once on API endpoints."""

    def _wrapper_depth(self, fn):
        """Count how many times a function is wrapped (via __wrapped__)."""
        depth = 0
        current = fn
        while hasattr(current, '__wrapped__'):
            depth += 1
            current = current.__wrapped__
        return depth

    def test_repair_pricing_api_single_decorator(self):
        """repair_pricing_api should have exactly 1 wrapper (customer_required)."""
        depth = self._wrapper_depth(views.repair_pricing_api)
        self.assertEqual(
            depth, 1,
            f"repair_pricing_api has {depth} wrappers; expected 1 "
            f"(@customer_required should not be duplicated)"
        )

    def test_unit_repair_data_api_single_decorator(self):
        """unit_repair_data_api should have exactly 1 wrapper (customer_required)."""
        depth = self._wrapper_depth(views.unit_repair_data_api)
        self.assertEqual(
            depth, 1,
            f"unit_repair_data_api has {depth} wrappers; expected 1 "
            f"(@customer_required should not be duplicated)"
        )

    def test_repair_pricing_api_still_protected(self):
        """Unauthenticated requests to repair_pricing_api should redirect to login."""
        response = self.client.post('/app/api/repair-pricing/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_unit_repair_data_api_still_protected(self):
        """Unauthenticated requests to unit_repair_data_api should redirect to login."""
        response = self.client.get('/app/api/unit-repair-data/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_repair_cost_data_api_single_decorator(self):
        """repair_cost_data_api should also have exactly 1 wrapper (sanity check)."""
        depth = self._wrapper_depth(views.repair_cost_data_api)
        self.assertEqual(
            depth, 1,
            f"repair_cost_data_api has {depth} wrappers; expected 1"
        )
