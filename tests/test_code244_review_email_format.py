"""
Regression tests for CODE-244: Review email subject/body format crash.

Bug: _send_review_email() called config.email_subject.format(shop_name=...)
on tenant-editable CharField. If a shop owner customised the subject with
unknown placeholders (e.g. {customer_name}) or stray curly braces, the send
crashed with KeyError/ValueError, leaving the ReviewRequest stuck in 'pending'
and retried on every cron run.

Fix: _safe_format() wraps str.format() in try/except — on failure it returns
the raw template instead of crashing. Also added template var substitution to
email_body_template (was previously not substituted at all).
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.technician_portal.review_service import _safe_format


class SafeFormatTests(TestCase):
    """Test _safe_format() resilience to bad templates."""

    def test_normal_substitution(self):
        result = _safe_format("Hello {shop_name}!", shop_name="Bob's Glass")
        self.assertEqual(result, "Hello Bob's Glass!")

    def test_multiple_vars(self):
        result = _safe_format(
            "Dear {customer_name}, thanks for choosing {shop_name}!",
            shop_name="Bob's Glass",
            customer_name="John",
        )
        self.assertEqual(result, "Dear John, thanks for choosing Bob's Glass!")

    def test_unknown_placeholder_returns_raw(self):
        """Unknown {foo} placeholder should NOT crash — return raw template."""
        raw = "Rate your {service_type} experience!"
        result = _safe_format(raw, shop_name="Test")
        self.assertEqual(result, raw)

    def test_stray_closing_brace_returns_raw(self):
        """Stray } in template should NOT crash — return raw template."""
        raw = "We are #1}"
        result = _safe_format(raw, shop_name="Test")
        self.assertEqual(result, raw)

    def test_stray_opening_brace_returns_raw(self):
        """Stray { in template should NOT crash — return raw template."""
        raw = "Rate us! {broken"
        result = _safe_format(raw, shop_name="Test")
        self.assertEqual(result, raw)

    def test_empty_braces_returns_raw(self):
        """Empty {} (positional) should NOT crash — return raw template."""
        raw = "Hello {}!"
        result = _safe_format(raw, shop_name="Test")
        self.assertEqual(result, raw)

    def test_no_placeholders_passthrough(self):
        """Template with no placeholders returns as-is."""
        raw = "How was your experience?"
        result = _safe_format(raw, shop_name="Test")
        self.assertEqual(result, raw)

    def test_shop_name_with_braces(self):
        """Shop name containing curly braces shouldn't crash format."""
        result = _safe_format("Thanks for choosing {shop_name}!", shop_name="Bob's {Best} Glass")
        self.assertEqual(result, "Thanks for choosing Bob's {Best} Glass!")
