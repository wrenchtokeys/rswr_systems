"""
CODE-202: Missing validation for batch_invoice_frequency and default_payment_terms
          in owner_setup_save_billing (setup wizard endpoint).

The setup wizard endpoint POST /owner/setup/save/billing/ accepted any string for
batch_invoice_frequency, any integer for batch_invoice_day, and any string for
default_payment_terms without validating against the defined model choices.

An invalid frequency (e.g. "quarterly") would be silently saved and cause
process_batch_invoices()._should_run_batch_today() to always return False,
silently disabling batch invoicing with no error to the owner.

An invalid default_payment_terms (e.g. "NET90") would be silently saved and
cause invoice creation to store an unrecognised terms value, producing
incorrect due dates on all subsequent invoices.

Fix: Apply the same frequency + day validation that owner_settings_view received
in CODE-201, plus terms validation, to this setup wizard endpoint.
"""

import json

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.billing.models import BillingConfig
from apps.tenants.models import Tenant, TenantMembership


def _setup_owner_tenant(username='setupbilling_owner'):
    """Create a minimal owner + tenant + billing config for testing."""
    owner = User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password='TestPass123!',
    )
    tenant = Tenant.objects.create(
        name=f'{username} Shop',
        slug=f'{username}-shop',
        owner=owner,
    )
    TenantMembership.objects.create(
        user=owner,
        tenant=tenant,
        role='owner',
        is_active=True,
    )
    BillingConfig.get_for_tenant(tenant)  # ensure row exists
    return owner, tenant


class SetupBillingValidationTests(TestCase):
    """Tests for CODE-202: validation in owner_setup_save_billing."""

    def setUp(self):
        self.owner, self.tenant = _setup_owner_tenant()
        self.client = Client()
        self.client.login(username='setupbilling_owner', password='TestPass123!')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_setup_billing(self, *, frequency='disabled', day='1', terms='COD',
                             auto_email='0', overdue_enabled='0',
                             overdue_days='7,14,30'):
        return self.client.post(
            '/owner/setup/save/billing/',
            {
                'batch_invoice_frequency': frequency,
                'batch_invoice_day': str(day),
                'default_payment_terms': terms,
                'auto_email_invoices': auto_email,
                'overdue_reminder_enabled': overdue_enabled,
                'overdue_reminder_days': overdue_days,
            },
        )

    def _json(self, resp):
        return json.loads(resp.content)

    # ── Valid inputs ─────────────────────────────────────────────────────────

    def test_valid_disabled_frequency_accepted(self):
        """frequency='disabled' with valid terms is saved."""
        resp = self._post_setup_billing(frequency='disabled', day=1, terms='COD')
        self.assertEqual(resp.status_code, 200)
        data = self._json(resp)
        self.assertTrue(data.get('success'), data)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'disabled')
        self.assertEqual(config.default_payment_terms, 'COD')

    def test_valid_weekly_frequency_accepted(self):
        """Weekly frequency with day=0 is accepted."""
        resp = self._post_setup_billing(frequency='weekly', day=0, terms='NET30')
        self.assertEqual(resp.status_code, 200)
        data = self._json(resp)
        self.assertTrue(data.get('success'), data)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'weekly')
        self.assertEqual(config.batch_invoice_day, 0)
        self.assertEqual(config.default_payment_terms, 'NET30')

    def test_valid_monthly_frequency_accepted(self):
        """Monthly frequency with day=15 is accepted."""
        resp = self._post_setup_billing(frequency='monthly', day=15, terms='NET15')
        self.assertEqual(resp.status_code, 200)
        data = self._json(resp)
        self.assertTrue(data.get('success'), data)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'monthly')
        self.assertEqual(config.batch_invoice_day, 15)

    def test_valid_biweekly_frequency_accepted(self):
        """Biweekly frequency with day=3 is accepted."""
        resp = self._post_setup_billing(frequency='biweekly', day=3, terms='NET60')
        data = self._json(resp)
        self.assertTrue(data.get('success'), data)

    # ── Invalid frequency ────────────────────────────────────────────────────

    def test_invalid_frequency_rejected(self):
        """An unrecognised frequency string is rejected; DB not updated."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='quarterly', day=1)
        data = self._json(resp)
        self.assertFalse(data.get('success'), "Invalid frequency 'quarterly' should be rejected")
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_empty_frequency_rejected(self):
        """Empty string for frequency is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='', day=1)
        data = self._json(resp)
        self.assertFalse(data.get('success'), "Empty frequency should be rejected")
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_xss_frequency_rejected(self):
        """Script-injection attempt in frequency is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='<script>alert(1)</script>', day=1)
        data = self._json(resp)
        self.assertFalse(data.get('success'))
        config.refresh_from_db()
        self.assertNotIn('<script>', config.batch_invoice_frequency)

    # ── Invalid day for weekly/biweekly ──────────────────────────────────────

    def test_weekly_day_7_rejected(self):
        """Weekly batch_invoice_day=7 is out of range [0-6] and rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='weekly', day=7)
        data = self._json(resp)
        self.assertFalse(data.get('success'), "weekly day=7 should be rejected")
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_weekly_day_negative_rejected(self):
        """Weekly batch_invoice_day=-1 is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='weekly', day=-1)
        data = self._json(resp)
        self.assertFalse(data.get('success'))
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_biweekly_day_99_rejected(self):
        """Biweekly batch_invoice_day=99 is out of range and rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='biweekly', day=99)
        data = self._json(resp)
        self.assertFalse(data.get('success'))

    # ── Invalid day for monthly ───────────────────────────────────────────────

    def test_monthly_day_0_rejected(self):
        """Monthly batch_invoice_day=0 is below 1 and rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='monthly', day=0)
        data = self._json(resp)
        self.assertFalse(data.get('success'), "monthly day=0 should be rejected")

    def test_monthly_day_29_rejected(self):
        """Monthly batch_invoice_day=29 is above 28 (unsafe for all months)."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_setup_billing(frequency='monthly', day=29)
        data = self._json(resp)
        self.assertFalse(data.get('success'))

    # ── Invalid payment terms ────────────────────────────────────────────────

    def test_invalid_payment_terms_rejected(self):
        """Unrecognised payment terms are rejected; DB not updated."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.default_payment_terms = 'COD'
        config.save(update_fields=['default_payment_terms'])

        resp = self._post_setup_billing(terms='NET90')
        data = self._json(resp)
        self.assertFalse(data.get('success'), "Invalid terms 'NET90' should be rejected")
        config.refresh_from_db()
        self.assertEqual(config.default_payment_terms, 'COD')

    def test_empty_payment_terms_rejected(self):
        """Empty payment terms string is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.default_payment_terms = 'COD'
        config.save(update_fields=['default_payment_terms'])

        resp = self._post_setup_billing(terms='')
        data = self._json(resp)
        self.assertFalse(data.get('success'), "Empty payment terms should be rejected")
        config.refresh_from_db()
        self.assertEqual(config.default_payment_terms, 'COD')

    def test_all_valid_terms_accepted(self):
        """All defined PAYMENT_TERMS_CHOICES values are accepted."""
        for code, _ in BillingConfig.PAYMENT_TERMS_CHOICES:
            with self.subTest(terms=code):
                resp = self._post_setup_billing(terms=code)
                data = self._json(resp)
                self.assertTrue(data.get('success'), f"Terms '{code}' should be accepted, got: {data}")
                config = BillingConfig.get_for_tenant(self.tenant)
                self.assertEqual(config.default_payment_terms, code)
