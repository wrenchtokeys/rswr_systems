"""
CODE-201: Missing validation for batch_invoice_frequency in owner settings

The 'batch_invoice_settings' handler in owner_settings_view() accepted any
string for batch_invoice_frequency and any integer for batch_invoice_day
without checking against BillingConfig.BATCH_FREQUENCY_CHOICES or valid
day ranges.

An invalid frequency (e.g. "quarterly") would be silently saved, causing
process_batch_invoices()._should_run_batch_today() to always return False
and silently disabling batch invoicing with no error or warning to the owner.

An out-of-range batch_invoice_day (e.g. 99 for weekly, or 0 for monthly)
would similarly produce a schedule that never fires.

Fix: Validate frequency against BATCH_FREQUENCY_CHOICES and day against the
correct range for the chosen frequency before saving.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.billing.models import BillingConfig
from apps.tenants.models import Tenant, TenantMembership


def _setup_owner_tenant():
    """Create a minimal owner + tenant + billing config for testing."""
    owner = User.objects.create_user(
        username='batchtest_owner',
        email='batchtest@example.com',
        password='TestPass123!',
    )
    tenant = Tenant.objects.create(
        name='Batch Test Shop',
        slug='batch-test-shop',
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


class BatchInvoiceFrequencyValidationTests(TestCase):
    """Tests for CODE-201: invalid batch_invoice_frequency / batch_invoice_day rejected."""

    def setUp(self):
        self.owner, self.tenant = _setup_owner_tenant()
        self.client = Client()
        self.client.login(username='batchtest_owner', password='TestPass123!')
        # Bind the session to the test tenant
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_batch_settings(self, frequency, day, auto_send='0'):
        return self.client.post(
            '/owner/settings/',
            {
                'form_type': 'batch_invoice_settings',
                'batch_invoice_frequency': frequency,
                'batch_invoice_day': str(day),
                'batch_invoice_auto_send': auto_send,
            },
            follow=True,
        )

    # ── Valid inputs ─────────────────────────────────────────────────────────

    def test_valid_disabled_accepted(self):
        """Frequency='disabled' with any day is accepted."""
        resp = self._post_batch_settings('disabled', 1)
        self.assertEqual(resp.status_code, 200)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_valid_weekly_day0_accepted(self):
        """Weekly on Monday (day=0) is accepted."""
        resp = self._post_batch_settings('weekly', 0)
        self.assertEqual(resp.status_code, 200)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'weekly')
        self.assertEqual(config.batch_invoice_day, 0)

    def test_valid_weekly_day6_accepted(self):
        """Weekly on Sunday (day=6) is accepted."""
        resp = self._post_batch_settings('weekly', 6)
        self.assertEqual(resp.status_code, 200)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_day, 6)

    def test_valid_biweekly_accepted(self):
        """Bi-weekly frequency is accepted."""
        resp = self._post_batch_settings('biweekly', 2)
        self.assertEqual(resp.status_code, 200)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'biweekly')

    def test_valid_monthly_day1_accepted(self):
        """Monthly on day 1 is accepted."""
        resp = self._post_batch_settings('monthly', 1)
        self.assertEqual(resp.status_code, 200)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_frequency, 'monthly')
        self.assertEqual(config.batch_invoice_day, 1)

    def test_valid_monthly_day28_accepted(self):
        """Monthly on day 28 is the maximum allowed and must be accepted."""
        resp = self._post_batch_settings('monthly', 28)
        self.assertEqual(resp.status_code, 200)
        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.batch_invoice_day, 28)

    # ── Invalid frequency ────────────────────────────────────────────────────

    def test_invalid_frequency_rejected(self):
        """An unrecognised frequency string is rejected without saving."""
        # First set a known-good value to verify it doesn't change
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('quarterly', 1)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        # Must NOT have been overwritten
        self.assertEqual(
            config.batch_invoice_frequency,
            'disabled',
            "Invalid frequency 'quarterly' should have been rejected",
        )

    def test_empty_frequency_rejected(self):
        """An empty string for frequency is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('', 1)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_xss_attempt_in_frequency_rejected(self):
        """A script-injection attempt in frequency is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('<script>alert(1)</script>', 1)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertNotIn('<script>', config.batch_invoice_frequency)
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    # ── Invalid day for weekly/biweekly ──────────────────────────────────────

    def test_weekly_day_minus1_rejected(self):
        """Weekly batch_invoice_day=-1 (below 0) is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.batch_invoice_day = 1
        config.save(update_fields=['batch_invoice_frequency', 'batch_invoice_day'])

        resp = self._post_batch_settings('weekly', -1)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertEqual(
            config.batch_invoice_frequency,
            'disabled',
            "weekly with day=-1 should have been rejected",
        )

    def test_weekly_day7_rejected(self):
        """Weekly batch_invoice_day=7 (above 6) is rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('weekly', 7)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_biweekly_day99_rejected(self):
        """Biweekly batch_invoice_day=99 is out of range and rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('biweekly', 99)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    # ── Invalid day for monthly ───────────────────────────────────────────────

    def test_monthly_day0_rejected(self):
        """Monthly batch_invoice_day=0 is below 1 and rejected."""
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('monthly', 0)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')

    def test_monthly_day29_rejected(self):
        """Monthly batch_invoice_day=29 is above 28 and rejected.

        29/30/31 are avoided because not all months have these dates.
        """
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'disabled'
        config.save(update_fields=['batch_invoice_frequency'])

        resp = self._post_batch_settings('monthly', 29)
        self.assertEqual(resp.status_code, 200)
        config.refresh_from_db()
        self.assertEqual(config.batch_invoice_frequency, 'disabled')
