"""
Subscription Expiry UX Tests

Tests for:
1. SubscriptionEnforcementMiddleware grace period logic
2. Role-aware /subscription-blocked/ page
3. check_subscription_alerts management command
4. Tenant model grace period properties

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client, RequestFactory, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.subscription_middleware import SubscriptionEnforcementMiddleware, WRITE_METHODS


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    return plan


def _make_tenant(name='Test Shop', days_ago=0, subscription_status='trialing', plan='trial',
                 stripe_subscription_id='', grace_period_end=None):
    """
    Create a tenant with an owner and optional membership.
    days_ago: how many days ago the trial started (to control trial expiry).
    """
    plan_obj = _make_plan()
    suffix = name.replace(' ', '-').lower()
    owner = User.objects.create_user(
        f'owner-{suffix}', f'owner-{suffix}@test.com', 'pass',
        first_name='Shop', last_name='Owner'
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=suffix,
        subdomain=suffix,
        owner=owner,
        subscription_plan=plan_obj,
        plan=plan,
        subscription_status=subscription_status,
        trial_started_at=timezone.now() - timezone.timedelta(days=days_ago),
        stripe_subscription_id=stripe_subscription_id,
        grace_period_end=grace_period_end,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _add_member(tenant, role='technician', email_suffix='tech'):
    user = User.objects.create_user(
        f'{email_suffix}-{tenant.slug}', f'{email_suffix}@test.com', 'pass'
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role=role)
    return user


# ===========================================================================
# Tenant Model Grace Period Properties
# ===========================================================================

@override_settings(**TEST_OVERRIDES)
class TenantGracePeriodModelTests(TestCase):
    """Test Tenant model grace period properties."""

    def test_trial_not_expired_no_grace(self):
        """Active trial has no grace period."""
        tenant, _ = _make_tenant(days_ago=5)  # Trial started 5 days ago, 30-day trial
        self.assertFalse(tenant.is_trial_expired)
        self.assertFalse(tenant.is_in_grace_period)
        self.assertIsNone(tenant.effective_grace_period_end)

    def test_trial_expired_no_grace_without_explicit_grace_period(self):
        """Expired trial without explicit grace_period_end has no grace period.
        
        Free trials do NOT get automatic grace period after expiry.
        Grace period only applies to paid subscriptions (set via webhook).
        """
        # Trial started 35 days ago → expired 5 days ago, no grace_period_end
        tenant, _ = _make_tenant(days_ago=35)
        self.assertTrue(tenant.is_trial_expired)
        self.assertFalse(tenant.is_in_grace_period)
        self.assertIsNone(tenant.effective_grace_period_end)
        self.assertEqual(tenant.grace_days_remaining, 0)

    def test_paid_subscription_deleted_grace_period(self):
        """When subscription is deleted, grace_period_end is set explicitly."""
        grace_end = timezone.now() + timezone.timedelta(days=20)
        tenant, _ = _make_tenant(
            subscription_status='expired',
            plan='trial',
            stripe_subscription_id='sub_123',
            grace_period_end=grace_end,
        )
        self.assertTrue(tenant.is_in_grace_period)
        self.assertGreater(tenant.grace_days_remaining, 0)
        self.assertLessEqual(tenant.grace_days_remaining, 20)

    def test_paid_subscription_grace_period_ended(self):
        """Paid subscription grace period ended — fully locked."""
        grace_end = timezone.now() - timezone.timedelta(days=5)
        tenant, _ = _make_tenant(
            subscription_status='expired',
            plan='trial',
            stripe_subscription_id='sub_123',
            grace_period_end=grace_end,
        )
        self.assertFalse(tenant.is_in_grace_period)
        self.assertEqual(tenant.grace_days_remaining, 0)

    def test_had_paid_subscription_flag(self):
        """had_paid_subscription returns True only if stripe_subscription_id is set."""
        tenant_no_paid, _ = _make_tenant(name='No Paid Sub')
        tenant_paid, _ = _make_tenant(
            name='Had Paid Sub',
            stripe_subscription_id='sub_abc123'
        )
        self.assertFalse(tenant_no_paid.had_paid_subscription)
        self.assertTrue(tenant_paid.had_paid_subscription)

    def test_trial_days_remaining_active(self):
        """Trial with 25 days remaining shows correct count."""
        tenant, _ = _make_tenant(days_ago=5)
        remaining = tenant.trial_days_remaining
        self.assertGreaterEqual(remaining, 24)
        self.assertLessEqual(remaining, 25)

    def test_trial_days_remaining_expired(self):
        """Expired trial has 0 days remaining."""
        tenant, _ = _make_tenant(days_ago=35)
        self.assertEqual(tenant.trial_days_remaining, 0)


# ===========================================================================
# Middleware Grace Period Logic
# ===========================================================================

@override_settings(**TEST_OVERRIDES)
class SubscriptionMiddlewareGracePeriodTests(TestCase):
    """Test SubscriptionEnforcementMiddleware grace period behavior."""

    def setUp(self):
        self.factory = RequestFactory()

    def _make_request(self, method='GET', path='/tech/dashboard/', user=None, tenant=None):
        if method == 'GET':
            request = self.factory.get(path)
        elif method == 'POST':
            request = self.factory.post(path)
        elif method == 'DELETE':
            request = self.factory.delete(path)
        else:
            request = self.factory.generic(method, path)
        request.user = user
        request.tenant = tenant
        return request

    def _run_middleware(self, request):
        """Run the middleware and return its response (or call get_response)."""
        responses = []

        def get_response(req):
            responses.append('passed_through')
            from django.http import HttpResponse
            return HttpResponse('OK')

        middleware = SubscriptionEnforcementMiddleware(get_response)
        response = middleware(request)
        return response, responses

    def test_active_subscription_passes_through(self):
        """Active subscription — all requests pass through."""
        tenant, owner = _make_tenant(days_ago=5, subscription_status='active', plan='starter')
        request = self._make_request(user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, ['passed_through'])
        self.assertEqual(response.status_code, 200)

    def test_trial_active_passes_through(self):
        """Active trial — passes through."""
        tenant, owner = _make_tenant(days_ago=5)
        request = self._make_request(user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, ['passed_through'])

    def test_trial_expired_redirect_to_blocked(self):
        """Expired trial (no explicit grace_period_end) — redirect to /subscription-blocked/."""
        # Trials do NOT get automatic grace period; grace is only for paid subscriptions
        # that were explicitly deleted via Stripe webhook (which sets grace_period_end).
        tenant, owner = _make_tenant(days_ago=35)  # 35 days: expired 5 days ago, no grace
        request = self._make_request(method='GET', user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, [])
        self.assertEqual(response.status_code, 302)
        self.assertIn('/subscription-blocked/', response['Location'])

    def test_paid_subscription_grace_period_get_allowed_with_explicit_grace(self):
        """Paid sub expired, explicit grace_period_end — GETs allowed."""
        grace_end = timezone.now() + timezone.timedelta(days=15)
        tenant, owner = _make_tenant(
            subscription_status='expired', plan='trial',
            stripe_subscription_id='sub_123', grace_period_end=grace_end
        )
        request = self._make_request(method='GET', user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, ['passed_through'])
        self.assertTrue(getattr(request, 'subscription_grace_period', False))

    def test_paid_subscription_grace_period_get_allowed(self):
        """Paid sub expired, in grace period — GETs allowed."""
        grace_end = timezone.now() + timezone.timedelta(days=15)
        tenant, owner = _make_tenant(
            subscription_status='expired', plan='trial',
            stripe_subscription_id='sub_123', grace_period_end=grace_end
        )
        request = self._make_request(method='GET', user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, ['passed_through'])
        self.assertTrue(getattr(request, 'subscription_grace_period', False))

    def test_paid_subscription_grace_ended_blocked(self):
        """Paid sub expired, grace period ended — full block."""
        grace_end = timezone.now() - timezone.timedelta(days=5)
        tenant, owner = _make_tenant(
            subscription_status='expired', plan='trial',
            stripe_subscription_id='sub_123', grace_period_end=grace_end
        )
        request = self._make_request(user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, [])
        self.assertEqual(response.status_code, 302)
        self.assertIn('/subscription-blocked/', response['Location'])

    def test_api_request_in_grace_period_write_blocked_json(self):
        """API write request during grace period returns JSON 402."""
        grace_end = timezone.now() + timezone.timedelta(days=15)
        tenant, owner = _make_tenant(
            subscription_status='expired', plan='trial',
            stripe_subscription_id='sub_456', grace_period_end=grace_end
        )
        request = self._make_request(method='POST', path='/api/some-endpoint/', user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, [])
        self.assertEqual(response.status_code, 402)
        import json
        data = json.loads(response.content)
        self.assertIn('grace_days_remaining', data)

    def test_api_request_after_grace_ended_blocked_json(self):
        """API request after grace period returns JSON 402."""
        grace_end = timezone.now() - timezone.timedelta(days=5)
        tenant, owner = _make_tenant(
            subscription_status='expired', plan='trial',
            stripe_subscription_id='sub_789', grace_period_end=grace_end
        )
        request = self._make_request(method='GET', path='/api/some-endpoint/', user=owner, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, [])
        self.assertEqual(response.status_code, 402)

    def test_exempt_paths_always_allowed(self):
        """Exempt paths pass through even for expired subscriptions."""
        tenant, owner = _make_tenant(days_ago=65)  # Grace ended
        for path in ['/owner/billing/', '/login/', '/pricing/', '/subscription-blocked/']:
            request = self._make_request(path=path, user=owner, tenant=tenant)
            response, passed = self._run_middleware(request)
            self.assertEqual(passed, ['passed_through'], f"Expected {path} to be exempt")

    def test_superuser_bypasses_all_checks(self):
        """Superusers are never blocked."""
        tenant, _ = _make_tenant(days_ago=65)
        superuser = User.objects.create_superuser('super', 'super@test.com', 'pass')
        request = self._make_request(user=superuser, tenant=tenant)
        response, passed = self._run_middleware(request)
        self.assertEqual(passed, ['passed_through'])


# ===========================================================================
# Role-Aware Subscription Blocked Page
# ===========================================================================

@override_settings(**TEST_OVERRIDES)
class SubscriptionBlockedViewTests(TestCase):
    """Test the /subscription-blocked/ view for different roles."""

    def setUp(self):
        self.client = Client()
        self.plan = _make_plan()

    def _login_as(self, user, tenant):
        """Log in the user and set tenant on session (simulate middleware)."""
        self.client.force_login(user)
        # Patch the tenant onto the request via middleware
        session = self.client.session
        session['tenant_id'] = tenant.pk
        session.save()

    def test_owner_sees_upgrade_button(self):
        """Owner visiting /subscription-blocked/ sees upgrade prompt."""
        tenant, owner = _make_tenant(name='Owner Shop')

        factory = RequestFactory()
        request = factory.get('/subscription-blocked/')
        request.user = owner
        request.tenant = tenant

        from apps.saas.views import subscription_blocked_view
        response = subscription_blocked_view(request)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Upgrade Now', content)
        self.assertIn('/owner/billing/', content)

    def test_technician_sees_contact_owner(self):
        """Technician visiting /subscription-blocked/ sees contact owner info."""
        tenant, owner = _make_tenant(name='Tech Shop')
        tech = _add_member(tenant, role='technician', email_suffix='tech')

        factory = RequestFactory()
        request = factory.get('/subscription-blocked/')
        request.user = tech
        request.tenant = tenant

        from apps.saas.views import subscription_blocked_view
        response = subscription_blocked_view(request)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Technician should see owner contact info
        self.assertIn('shop owner', content.lower())
        self.assertNotIn('/owner/billing/', content)

    def test_customer_sees_shop_info(self):
        """Customer visiting /subscription-blocked/ sees shop contact info."""
        from apps.customer_portal.models import CustomerUser
        from core.models import Customer

        tenant, owner = _make_tenant(name='Customer Shop')
        # Minimal customer setup
        customer_user = User.objects.create_user('cust-user', 'cust@test.com', 'pass')

        factory = RequestFactory()
        request = factory.get('/subscription-blocked/')
        request.user = customer_user
        request.tenant = tenant

        from apps.saas.views import subscription_blocked_view
        response = subscription_blocked_view(request)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Customer should see shop name and contact info
        self.assertIn('Customer Shop', content)
        self.assertNotIn('/owner/billing/', content)
        self.assertNotIn('Upgrade Now', content)

    def test_manager_sees_upgrade_button(self):
        """Manager sees same upgrade prompt as owner."""
        tenant, owner = _make_tenant(name='Manager Shop')
        manager = _add_member(tenant, role='manager', email_suffix='mgr')

        factory = RequestFactory()
        request = factory.get('/subscription-blocked/')
        request.user = manager
        request.tenant = tenant

        from apps.saas.views import subscription_blocked_view
        response = subscription_blocked_view(request)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Upgrade Now', content)
        self.assertIn('/owner/billing/', content)


# ===========================================================================
# check_subscription_alerts Management Command
# ===========================================================================

@override_settings(**TEST_OVERRIDES)
class CheckSubscriptionAlertsCommandTests(TestCase):
    """Test the check_subscription_alerts management command."""

    def _run_command(self, dry_run=False):
        from django.core.management import call_command
        out = StringIO()
        call_command('check_subscription_alerts', dry_run=dry_run, stdout=out)
        return out.getvalue()

    def test_no_alerts_for_active_subscriptions(self):
        """No alerts sent for tenants with active subscriptions."""
        from django.core import mail
        _make_tenant(name='Active Shop', days_ago=5, subscription_status='active', plan='starter')
        self._run_command()
        self.assertEqual(len(mail.outbox), 0)

    def test_trial_7_day_alert_sent(self):
        """Alert sent when trial expires in 7 days."""
        from django.core import mail
        # Trial started 24 days ago — expires in 6 days (within 7-day window)
        tenant, owner = _make_tenant(name='Seven Day Shop', days_ago=24)
        self._run_command()
        self.assertGreater(len(mail.outbox), 0)
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any('trial ends in 7 days' in s.lower() for s in subjects))

    def test_trial_1_day_alert_sent(self):
        """Alert sent when trial expires in 1 day."""
        from django.core import mail
        # Trial started 29 days ago — expires in 1 day
        tenant, owner = _make_tenant(name='One Day Shop', days_ago=29)
        self._run_command()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any('tomorrow' in s.lower() or '7 days' in s.lower() for s in subjects))

    def test_trial_expired_alert_sent(self):
        """Alert sent when trial just expired (within last 60 days)."""
        from django.core import mail
        # Trial started 35 days ago — expired 5 days ago
        tenant, owner = _make_tenant(name='Expired Shop', days_ago=35)
        # Ensure is_trial_expired is True
        self.assertTrue(tenant.is_trial_expired)
        self._run_command()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(
            any('expired' in s.lower() or 'ended' in s.lower() for s in subjects),
            f"Expected expired alert. Got subjects: {subjects}"
        )

    def test_duplicate_alerts_not_sent(self):
        """Alerts are not sent twice for the same event."""
        from django.core import mail
        from apps.tenants.management.commands.check_subscription_alerts import ALERT_TRIAL_EXPIRED

        tenant, owner = _make_tenant(name='No Dupe Shop', days_ago=35)
        # Mark the trial_expired alert as already sent
        tenant.subscription_alerts_sent = {ALERT_TRIAL_EXPIRED: timezone.now().isoformat()}
        tenant.save(update_fields=['subscription_alerts_sent'])

        self._run_command()
        # No new emails for this alert type
        trial_expired_subjects = [
            m for m in mail.outbox
            if 'No Dupe Shop' in m.subject and 'expired' in m.subject.lower()
        ]
        self.assertEqual(len(trial_expired_subjects), 0)

    def test_alert_sent_to_managers_too(self):
        """Alerts go to managers as well as the owner."""
        from django.core import mail
        tenant, owner = _make_tenant(name='Manager Alert Shop', days_ago=35)
        manager = _add_member(tenant, role='manager', email_suffix='mgr-alert')

        self._run_command()
        all_recipients = [email for m in mail.outbox for email in m.to]
        # Both owner and manager should receive the alert
        self.assertIn(owner.email, all_recipients)
        self.assertIn(manager.email, all_recipients)

    def test_grace_15_day_alert(self):
        """Alert sent when 15 days of grace period remain."""
        from django.core import mail
        # Grace period ends in 14 days → within 15-day window
        grace_end = timezone.now() + timezone.timedelta(days=14)
        tenant, owner = _make_tenant(
            name='Grace 15 Shop',
            days_ago=40,
            subscription_status='expired',
            grace_period_end=grace_end,
        )
        self._run_command()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(
            any('15 days' in s.lower() or 'read-only' in s.lower() for s in subjects),
            f"Expected 15-day grace alert. Got: {subjects}"
        )

    def test_grace_5_day_alert(self):
        """Alert sent when 5 days of grace period remain."""
        from django.core import mail
        # Grace period ends in 4 days → within 5-day window
        grace_end = timezone.now() + timezone.timedelta(days=4)
        tenant, owner = _make_tenant(
            name='Grace 5 Shop',
            days_ago=40,
            subscription_status='expired',
            grace_period_end=grace_end,
        )
        self._run_command()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(
            any('5 days' in s.lower() or '4 days' in s.lower() or 'read-only access ends' in s.lower() for s in subjects),
            f"Expected 5-day grace alert. Got: {subjects}"
        )

    def test_grace_ended_alert(self):
        """Alert sent when grace period has ended."""
        from django.core import mail
        grace_end = timezone.now() - timezone.timedelta(days=5)
        tenant, owner = _make_tenant(
            name='Grace Ended Shop',
            days_ago=40,
            subscription_status='expired',
            grace_period_end=grace_end,
        )
        self._run_command()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(
            any('ended' in s.lower() or 'read-only access has ended' in s.lower() for s in subjects),
            f"Expected grace ended alert. Got: {subjects}"
        )

    def test_dry_run_sends_no_emails(self):
        """Dry run mode logs but does not send emails."""
        from django.core import mail
        _make_tenant(name='Dry Run Shop', days_ago=35)
        output = self._run_command(dry_run=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('DRY RUN', output)
