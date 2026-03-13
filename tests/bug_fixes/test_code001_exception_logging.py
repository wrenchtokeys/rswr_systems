"""
Regression tests for CODE-001: Bare except clauses swallow errors silently.

Verifies that exceptions are logged (not silently swallowed) in:
  - apps/saas/views.py: billing dashboard stats helper
  - apps/tenants/middleware.py: _get_customer_tenant()
  - core/models/email_branding.py: get_logo_url()

Also verifies that apps/saas/views.py email verification no longer catches
broad Exception (only CustomerUser.DoesNotExist).
"""

import logging
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User


class BillingContextLoggingTest(TestCase):
    """saas/views.py _get_billing_context should log on Exception."""

    def test_logs_exception_on_error(self):
        """When DB query blows up, exception is logged before returning empty context."""
        from apps.saas.views import _get_billing_context

        tenant = MagicMock()
        tenant.pk = 99

        with patch('apps.saas.views.Invoice.objects') as mock_invoice_qs:
            mock_invoice_qs.filter.side_effect = RuntimeError("DB is on fire")
            with self.assertLogs('apps.saas.views', level='ERROR') as log_ctx:
                result = _get_billing_context(tenant)

        # Should return the safe empty fallback
        self.assertEqual(result['outstanding_count'], 0)
        self.assertEqual(result['overdue_count'], 0)

        # Should have logged the exception
        self.assertTrue(
            any("billing" in msg.lower() or "stats" in msg.lower() for msg in log_ctx.output),
            f"Expected error log about billing stats, got: {log_ctx.output}"
        )

    def test_returns_empty_dict_structure_on_error(self):
        """Fallback dict has all expected keys."""
        from apps.saas.views import _get_billing_context

        tenant = MagicMock()
        with patch('apps.saas.views.Invoice.objects') as mock_qs:
            mock_qs.filter.side_effect = Exception("any error")
            with self.assertLogs('apps.saas.views', level='ERROR'):
                result = _get_billing_context(tenant)

        expected_keys = {
            'outstanding_invoices', 'outstanding_count', 'outstanding_amount',
            'overdue_count', 'recent_payments', 'collected_this_month',
            'total_revenue', 'repair_revenue', 'replacement_revenue',
        }
        self.assertEqual(set(result.keys()), expected_keys)


class TenantMiddlewareLoggingTest(TestCase):
    """apps/tenants/middleware.py _get_customer_tenant should log on unexpected Exception."""

    def test_logs_exception_on_unexpected_error(self):
        """When CustomerUser query raises an unexpected error, it is logged."""
        from apps.tenants.middleware import TenantMiddleware

        middleware = TenantMiddleware(get_response=lambda r: r)
        user = MagicMock()
        user.pk = 42

        with patch('apps.tenants.middleware.TenantMiddleware._get_customer_tenant') as mock_method:
            # Re-implement the real logic so we can test it properly
            mock_method.side_effect = None  # reset

        # Test the actual method with a mocked CustomerUser that raises unexpectedly
        with patch('apps.customer_portal.models.CustomerUser.objects') as mock_qs:
            mock_qs.select_related.return_value.filter.side_effect = RuntimeError("unexpected DB error")
            with self.assertLogs('apps.tenants.middleware', level='ERROR') as log_ctx:
                result = middleware._get_customer_tenant(user)

        self.assertIsNone(result)
        self.assertTrue(
            any("CustomerUser" in msg or "tenant" in msg.lower() for msg in log_ctx.output),
            f"Expected error log, got: {log_ctx.output}"
        )

    def test_returns_none_on_unexpected_error(self):
        """_get_customer_tenant returns None (not raises) on unexpected errors."""
        from apps.tenants.middleware import TenantMiddleware

        middleware = TenantMiddleware(get_response=lambda r: r)
        user = MagicMock()
        user.pk = 1

        with patch('apps.customer_portal.models.CustomerUser.objects') as mock_qs:
            mock_qs.select_related.return_value.filter.side_effect = RuntimeError("db gone")
            with self.assertLogs('apps.tenants.middleware', level='ERROR'):
                result = middleware._get_customer_tenant(user)

        self.assertIsNone(result)


class EmailBrandingLoggingTest(TestCase):
    """core/models/email_branding.py get_logo_url should log when Site.objects fails."""

    def test_logs_warning_when_site_lookup_fails(self):
        """When the Site.get_current() call raises, a warning is logged and relative URL returned."""
        from core.models.email_branding import EmailBrandingConfig
        import core.models.email_branding as email_branding_module

        config = EmailBrandingConfig.__new__(EmailBrandingConfig)
        mock_logo = MagicMock()
        mock_logo.url = '/media/logo.png'
        config.logo = mock_logo

        # Fake the Site class so it raises when get_current() is called.
        # We patch it where it's imported (local import inside get_logo_url),
        # by replacing the module in sys.modules before the method runs.
        mock_site_module = MagicMock()
        mock_site_module.Site.objects.get_current.side_effect = Exception("sites broken")

        with patch.object(type(config), 'logo', new_callable=lambda: property(lambda self: mock_logo)):
            with patch('django.conf.settings') as mock_settings:
                mock_settings.AWS_S3_CUSTOM_DOMAIN = None
                mock_settings.USE_HTTPS = False

                mock_logger = MagicMock()
                with patch.object(email_branding_module, 'logger', mock_logger):
                    with patch.dict('sys.modules', {'django.contrib.sites.models': mock_site_module}):
                        result = config.get_logo_url()

        self.assertEqual(result, '/media/logo.png')
        # The logger.warning should have been called with exc_info=True
        mock_logger.warning.assert_called_once()
        call_kwargs = mock_logger.warning.call_args
        self.assertTrue(
            call_kwargs.kwargs.get('exc_info') is True,
            f"Expected warning with exc_info=True, got: {call_kwargs}"
        )


class EmailVerificationExceptScopeTest(TestCase):
    """apps/saas/views.py email verification should only catch CustomerUser.DoesNotExist."""

    def test_except_clause_is_specific(self):
        """
        The email verification try/except only catches CustomerUser.DoesNotExist,
        not broad Exception. Verify by inspecting the source.
        """
        import inspect
        from apps.saas import views

        source = inspect.getsource(views)
        # The old pattern was: except (CustomerUser.DoesNotExist, Exception):
        self.assertNotIn(
            'except (CustomerUser.DoesNotExist, Exception)',
            source,
            "Overly broad except clause still present in saas/views.py"
        )
