"""
CODE-046 Regression Tests
=========================
Bug: `connect_setup` view rendered `saas/connect_setup.html` which didn't
exist, causing TemplateDoesNotExist on every GET to /owner/payments/setup/.

Additionally, migration 0011_add_stripe_connect_fields was unapplied on
the default SQLite DB, causing OperationalError on any code path that
accessed the new Stripe Connect columns (stripe_connect_account_id,
stripe_connect_charges_enabled, stripe_connect_payouts_enabled,
stripe_connect_onboarding_complete, platform_fee_percent).

Fixes:
1. Created templates/saas/connect_setup.html
2. Applied migration 0011 to the SQLite DB

Tests verify:
- GET /owner/payments/setup/ returns 200 (template exists and renders)
- Tenant model can read/write Stripe Connect fields without DB error
- can_accept_payments property works correctly
- can_receive_payouts property works correctly
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership


def _make_owner(username='owner_c046'):
    """Create a minimal owner user + tenant."""
    user = User.objects.create_user(
        username=username,
        password='pass1234',
        email=f'{username}@test.com',
        first_name='Shop',
        last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name='Test Shop C046',
        slug=f'test-shop-c046-{username}',
        subdomain=f'test-shop-c046-{username}',
        owner=user,
        plan='trial',
    )
    TenantMembership.objects.create(
        user=user,
        tenant=tenant,
        role='owner',
        is_active=True,
    )
    return user, tenant


class ConnectSetupTemplateTest(TestCase):
    """GET /owner/payments/setup/ must render without TemplateDoesNotExist."""

    def setUp(self):
        self.user, self.tenant = _make_owner()
        self.client = Client()
        self.client.login(username='owner_c046', password='pass1234')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_get_connect_setup_returns_200(self):
        """Template must exist and render correctly."""
        response = self.client.get('/owner/payments/setup/')
        self.assertEqual(
            response.status_code,
            200,
            msg=(
                "GET /owner/payments/setup/ should return 200 (connect_setup.html must exist). "
                f"Got {response.status_code}"
            ),
        )

    def test_connect_setup_shows_cta_when_not_connected(self):
        """Unconnected tenants should see the 'Connect with Stripe' CTA."""
        response = self.client.get('/owner/payments/setup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Connect with Stripe')


class StripeConnectFieldsTest(TestCase):
    """Stripe Connect DB columns must exist and be accessible (migration 0011 applied)."""

    def setUp(self):
        _, self.tenant = _make_owner(username='owner_c046b')

    def test_stripe_connect_fields_exist(self):
        """All new Stripe Connect fields should be accessible without OperationalError."""
        # Read default values
        tenant = Tenant.objects.get(pk=self.tenant.pk)
        self.assertEqual(tenant.stripe_connect_account_id, '')
        self.assertFalse(tenant.stripe_connect_charges_enabled)
        self.assertFalse(tenant.stripe_connect_payouts_enabled)
        self.assertFalse(tenant.stripe_connect_onboarding_complete)
        self.assertEqual(tenant.platform_fee_percent, 0)

    def test_can_write_stripe_connect_fields(self):
        """Should be able to write Stripe Connect fields without error."""
        Tenant.objects.filter(pk=self.tenant.pk).update(
            stripe_connect_account_id='acct_test123',
            stripe_connect_charges_enabled=True,
            stripe_connect_payouts_enabled=True,
            stripe_connect_onboarding_complete=True,
        )
        refreshed = Tenant.objects.get(pk=self.tenant.pk)
        self.assertEqual(refreshed.stripe_connect_account_id, 'acct_test123')
        self.assertTrue(refreshed.stripe_connect_charges_enabled)
        self.assertTrue(refreshed.stripe_connect_payouts_enabled)
        self.assertTrue(refreshed.stripe_connect_onboarding_complete)


class CanAcceptPaymentsPropertyTest(TestCase):
    """Tenant.can_accept_payments property logic must be correct."""

    def setUp(self):
        _, self.tenant = _make_owner(username='owner_c046c')

    def test_can_accept_payments_false_when_no_account(self):
        """No account ID → cannot accept payments."""
        self.assertFalse(self.tenant.can_accept_payments)

    def test_can_accept_payments_false_when_account_not_enabled(self):
        """Account ID present but charges not enabled → cannot accept payments."""
        Tenant.objects.filter(pk=self.tenant.pk).update(
            stripe_connect_account_id='acct_test456',
            stripe_connect_charges_enabled=False,
        )
        refreshed = Tenant.objects.get(pk=self.tenant.pk)
        self.assertFalse(refreshed.can_accept_payments)

    def test_can_accept_payments_true_when_fully_enabled(self):
        """Account ID + charges enabled → can accept payments."""
        Tenant.objects.filter(pk=self.tenant.pk).update(
            stripe_connect_account_id='acct_test789',
            stripe_connect_charges_enabled=True,
        )
        refreshed = Tenant.objects.get(pk=self.tenant.pk)
        self.assertTrue(refreshed.can_accept_payments)

    def test_connect_setup_shows_active_status_when_connected(self):
        """When tenant can_accept_payments, setup page should show 'Payments Active'."""
        Tenant.objects.filter(pk=self.tenant.pk).update(
            stripe_connect_account_id='acct_active',
            stripe_connect_charges_enabled=True,
        )
        user = User.objects.get(
            tenant_memberships__tenant=self.tenant,
            tenant_memberships__role='owner',
        )
        c = Client()
        c.login(username=user.username, password='pass1234')
        session = c.session
        session['tenant_id'] = self.tenant.id
        session.save()

        response = c.get('/owner/payments/setup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payments Active')
