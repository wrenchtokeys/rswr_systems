"""
Tests for the `check_connect_status` management command.

The command is the server-side answer to "can my customers actually pay an
invoice online right now?", so its verdict must track Tenant.can_accept_payments
exactly — a command that says READY while the Pay button is hidden is worse
than no command at all.
"""

from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(slug, **connect_fields):
    user = User.objects.create_user(
        username=f'owner_{slug}', password='pass1234', email=f'{slug}@test.com',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}', slug=slug, subdomain=slug, owner=user, plan='trial',
    )
    TenantMembership.objects.create(
        user=user, tenant=tenant, role='owner', is_active=True,
    )
    if connect_fields:
        Tenant.objects.filter(pk=tenant.pk).update(**connect_fields)
        tenant.refresh_from_db()
    return tenant


# Blank key keeps the command off the network — it skips the live sync and
# reports stored values, which is what these assertions are about.
@override_settings(STRIPE_SECRET_KEY='')
class CheckConnectStatusCommandTest(TestCase):

    def _run(self, **kwargs):
        out = StringIO()
        call_command('check_connect_status', stdout=out, **kwargs)
        return out.getvalue()

    def test_reports_not_ready_without_account(self):
        _make_tenant('no-acct')
        output = self._run(tenant='no-acct')
        self.assertIn('NOT READY', output)
        self.assertIn('no Stripe Connect account', output)
        self.assertIn('0/1 shop(s) ready', output)

    def test_reports_ready_when_active(self):
        _make_tenant(
            'ready-shop',
            stripe_connect_account_id='acct_ready',
            stripe_onboarding_status='active',
            stripe_connect_charges_enabled=True,
            stripe_connect_payouts_enabled=True,
            stripe_connect_onboarding_complete=True,
        )
        output = self._run(tenant='ready-shop')
        self.assertIn('READY', output)
        self.assertNotIn('NOT READY', output)
        self.assertIn('1/1 shop(s) ready', output)

    def test_ready_but_payouts_held_is_called_out(self):
        """Charges on, payouts off: money comes in but Stripe holds it."""
        _make_tenant(
            'payouts-held',
            stripe_connect_account_id='acct_held',
            stripe_onboarding_status='active',
            stripe_connect_charges_enabled=True,
            stripe_connect_payouts_enabled=False,
            stripe_connect_onboarding_complete=True,
        )
        output = self._run(tenant='payouts-held')
        self.assertIn('READY', output)
        self.assertIn('payouts are NOT enabled', output)

    def test_restricted_account_is_not_ready(self):
        """charges_enabled can stay true while Stripe restricts the account."""
        _make_tenant(
            'restricted-shop',
            stripe_connect_account_id='acct_restricted',
            stripe_onboarding_status='restricted',
            stripe_connect_charges_enabled=True,
            stripe_connect_onboarding_complete=True,
        )
        output = self._run(tenant='restricted-shop')
        self.assertIn('NOT READY', output)
        self.assertIn('Stripe restricted the account', output)

    def test_incomplete_onboarding_is_not_ready(self):
        _make_tenant(
            'half-done',
            stripe_connect_account_id='acct_half',
            stripe_onboarding_status='pending',
            stripe_connect_onboarding_complete=False,
        )
        output = self._run(tenant='half-done')
        self.assertIn('NOT READY', output)
        self.assertIn('Onboarding was never finished', output)

    def test_missing_stripe_key_is_reported(self):
        _make_tenant('any-shop')
        output = self._run(tenant='any-shop')
        self.assertIn('STRIPE_SECRET_KEY is not set', output)

    def test_null_platform_fee_reported_as_default(self):
        """NULL means 'use PlatformConfig default', not 'no fee'."""
        tenant = _make_tenant(
            'fee-shop',
            stripe_connect_account_id='acct_fee',
            stripe_onboarding_status='active',
            stripe_connect_charges_enabled=True,
        )
        self.assertIsNone(tenant.platform_fee_percent)
        self.assertIn('uses PlatformConfig default', self._run(tenant='fee-shop'))

    def test_lookup_by_numeric_id(self):
        tenant = _make_tenant('by-id')
        self.assertIn('Shop by-id', self._run(tenant=str(tenant.id)))

    def test_unknown_tenant_raises(self):
        with self.assertRaises(CommandError):
            self._run(tenant='does-not-exist')

    def test_checks_all_active_tenants_by_default(self):
        _make_tenant('shop-a')
        _make_tenant(
            'shop-b',
            stripe_connect_account_id='acct_b',
            stripe_onboarding_status='active',
            stripe_connect_charges_enabled=True,
        )
        output = self._run()
        self.assertIn('Shop shop-a', output)
        self.assertIn('Shop shop-b', output)
        self.assertIn('1/2 shop(s) ready', output)
