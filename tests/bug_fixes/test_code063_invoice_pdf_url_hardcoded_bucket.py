"""
Regression tests for CODE-063:
  Invoice PDF URL hardcoded the S3 bucket name 'rs-systems-media-20251029'
  in two view functions instead of reading from Django settings.

Root cause:
    customer_invoice_detail() and owner_invoice_detail() both contained:
        pdf_url = f"https://rs-systems-media-20251029.s3.amazonaws.com/{invoice.s3_key}"

    Problems:
    1. Bucket name is hardcoded — survives a bucket rename only by manual find-replace.
    2. In local/dev with USE_S3=False, these still build an S3 URL instead of
       returning None (because AWS_S3_CUSTOM_DOMAIN / AWS_STORAGE_BUCKET_NAME
       are not set in dev settings).
    3. Violates DRY — the bucket name appears in settings; it should be the
       single source of truth.

Fix:
    Added Invoice.get_pdf_url() model method that reads from settings:
        1. AWS_S3_CUSTOM_DOMAIN (preferred — already constructed by production.py)
        2. AWS_STORAGE_BUCKET_NAME + AWS_S3_REGION_NAME (fallback)
        3. None if neither is set (local/dev without S3)

    Both views now call invoice.get_pdf_url() instead of constructing their own URL.

Tests verify:
1. get_pdf_url() returns None when s3_key is blank.
2. get_pdf_url() uses AWS_S3_CUSTOM_DOMAIN when set.
3. get_pdf_url() constructs URL from AWS_STORAGE_BUCKET_NAME + region as fallback.
4. get_pdf_url() returns None in dev environments (no S3 settings at all).
5. Bucket rename is reflected automatically (not hardcoded in views).
6. AWS_S3_CUSTOM_DOMAIN takes priority over AWS_STORAGE_BUCKET_NAME.
7. Neither view file hardcodes the bucket name — source-level guard.
8. Invoice model has get_pdf_url() method.
"""

from decimal import Decimal
from datetime import date
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings

from apps.billing.models import Invoice


class InvoiceGetPdfUrlUnitTest(TestCase):
    """
    Unit tests for Invoice.get_pdf_url() — use unsaved model instances
    so we don't need DB fixtures (method only reads self.s3_key and settings).
    """

    def _make_unsaved_invoice(self, s3_key='invoices/customer/1/INV-001.pdf'):
        """Create an Invoice instance without saving to DB."""
        invoice = Invoice.__new__(Invoice)
        invoice.s3_key = s3_key
        return invoice

    def test_no_s3_key_returns_none(self):
        """get_pdf_url() must return None when s3_key is blank."""
        invoice = self._make_unsaved_invoice(s3_key='')
        with override_settings(
            AWS_S3_CUSTOM_DOMAIN='mybucket.s3.amazonaws.com',
            AWS_STORAGE_BUCKET_NAME='mybucket',
        ):
            self.assertIsNone(invoice.get_pdf_url())

    def test_uses_aws_s3_custom_domain(self):
        """get_pdf_url() should use AWS_S3_CUSTOM_DOMAIN when set."""
        invoice = self._make_unsaved_invoice(s3_key='invoices/1/INV-001.pdf')
        with override_settings(
            AWS_S3_CUSTOM_DOMAIN='rs-systems-media-20251029.s3.amazonaws.com',
        ):
            url = invoice.get_pdf_url()
        self.assertEqual(
            url,
            'https://rs-systems-media-20251029.s3.amazonaws.com/invoices/1/INV-001.pdf'
        )

    def test_falls_back_to_bucket_name_and_region(self):
        """get_pdf_url() should construct URL from bucket name + region when no custom domain."""
        invoice = self._make_unsaved_invoice(s3_key='invoices/1/INV-001.pdf')
        with override_settings(
            AWS_STORAGE_BUCKET_NAME='my-other-bucket',
            AWS_S3_REGION_NAME='us-west-2',
        ):
            # Ensure custom domain is absent
            from django.conf import settings as django_settings
            original = getattr(django_settings, 'AWS_S3_CUSTOM_DOMAIN', 'NOTSET')
            if hasattr(django_settings, 'AWS_S3_CUSTOM_DOMAIN'):
                delattr(django_settings, 'AWS_S3_CUSTOM_DOMAIN')
            try:
                url = invoice.get_pdf_url()
            finally:
                if original != 'NOTSET':
                    django_settings.AWS_S3_CUSTOM_DOMAIN = original

        self.assertEqual(
            url,
            'https://my-other-bucket.s3.us-west-2.amazonaws.com/invoices/1/INV-001.pdf'
        )

    def test_returns_none_in_dev_no_s3_settings(self):
        """get_pdf_url() returns None in dev env where no S3 settings are configured."""
        invoice = self._make_unsaved_invoice(s3_key='invoices/1/INV-001.pdf')

        from django.conf import settings as django_settings

        # Temporarily remove both AWS settings
        saved = {}
        for attr in ('AWS_S3_CUSTOM_DOMAIN', 'AWS_STORAGE_BUCKET_NAME'):
            if hasattr(django_settings, attr):
                saved[attr] = getattr(django_settings, attr)
                delattr(django_settings, attr)

        try:
            url = invoice.get_pdf_url()
        finally:
            for attr, val in saved.items():
                setattr(django_settings, attr, val)

        # Should return None, not raise AttributeError
        self.assertIsNone(url)

    def test_bucket_rename_reflected_automatically(self):
        """Changing the domain is reflected without code changes."""
        invoice = self._make_unsaved_invoice(s3_key='invoices/1/INV-001.pdf')

        with override_settings(AWS_S3_CUSTOM_DOMAIN='new-bucket.s3.amazonaws.com'):
            url = invoice.get_pdf_url()

        # URL should reflect the new domain, not a hardcoded old bucket name
        self.assertNotIn('rs-systems-media-20251029', url)
        self.assertIn('new-bucket.s3.amazonaws.com', url)

    def test_custom_domain_takes_priority_over_bucket_name(self):
        """AWS_S3_CUSTOM_DOMAIN takes priority over AWS_STORAGE_BUCKET_NAME."""
        invoice = self._make_unsaved_invoice(s3_key='invoices/1/INV-001.pdf')

        with override_settings(
            AWS_S3_CUSTOM_DOMAIN='cdn.myshop.com',
            AWS_STORAGE_BUCKET_NAME='rs-systems-media-20251029',
            AWS_S3_REGION_NAME='us-east-1',
        ):
            url = invoice.get_pdf_url()

        # Should use custom domain, not bucket name
        self.assertIn('cdn.myshop.com', url)
        self.assertNotIn('rs-systems-media-20251029', url)

    def test_url_contains_s3_key(self):
        """The s3_key should appear in the returned URL."""
        invoice = self._make_unsaved_invoice(s3_key='invoices/my-shop/2026/INV-042.pdf')
        with override_settings(AWS_S3_CUSTOM_DOMAIN='testbucket.s3.amazonaws.com'):
            url = invoice.get_pdf_url()
        self.assertIn('invoices/my-shop/2026/INV-042.pdf', url)

    def test_views_do_not_hardcode_bucket_name(self):
        """
        Neither view file should contain the hardcoded bucket name.
        Source-level guard — if someone re-introduces the hardcode, this fails.
        """
        import inspect
        import apps.customer_portal.views as cpv
        import apps.saas.views as sv

        cp_source = inspect.getsource(cpv)
        saas_source = inspect.getsource(sv)

        self.assertNotIn(
            'rs-systems-media-20251029',
            cp_source,
            "customer_portal/views.py contains hardcoded S3 bucket name — use invoice.get_pdf_url() instead"
        )
        self.assertNotIn(
            'rs-systems-media-20251029',
            saas_source,
            "saas/views.py contains hardcoded S3 bucket name — use invoice.get_pdf_url() instead"
        )

    def test_invoice_model_has_get_pdf_url_method(self):
        """Invoice model must have get_pdf_url() method."""
        self.assertTrue(
            callable(getattr(Invoice, 'get_pdf_url', None)),
            "Invoice model must have a get_pdf_url() method"
        )
