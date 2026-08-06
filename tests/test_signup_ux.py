"""
Phase 1 launch-readiness tests: signup funnel UX + plans-surface integrity.

Covers (docs/proposals/launch-readiness-roadmap.md):
- PRG: signup POST redirects to /signup/check-email/; refresh-safe; direct
  visits without a pending signup bounce back to /signup/
- Optional phone saved to Tenant.business_phone
- ?plan= preselect (valid slugs only); single "undecided" plan option;
  stale 'not_sure' POSTs degrade to undecided instead of erroring
- Confirmation-email failure surfaced (warning + resend link), account still
  created inactive
- Service exceptions never leak raw text to the response
- Sitemap advertises /signup/ + /pricing/, not the dead /register/
- billing_view resolves ONE current plan (tenant.plan wins over stale FK);
  platform owner sees no Cancel button
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.tenants.models import SubscriptionPlan, Tenant
from apps.tenants.services.signup_service import create_tenant_with_owner

LOCMEM_CACHE = {
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    # These classes POST /signup/ more than 5×/run; the per-IP limit (5/h)
    # would 403 later tests. The limit has its own coverage elsewhere.
    'RATELIMIT_ENABLE': False,
}


def seed_plans():
    trial, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    starter, _ = SubscriptionPlan.objects.get_or_create(
        slug='starter',
        defaults={
            'name': 'Starter', 'monthly_price': Decimal('49.00'),
            'annual_price': Decimal('470.00'), 'is_active': True, 'display_order': 1,
            'features': {'invoicing': True, 'customer_portal': True, 'rewards': True,
                         'support': 'Email support'},
        },
    )
    pro, _ = SubscriptionPlan.objects.get_or_create(
        slug='pro',
        defaults={
            'name': 'Pro', 'monthly_price': Decimal('99.00'),
            'annual_price': Decimal('950.00'), 'is_active': True, 'display_order': 2,
            'features': {'invoicing': True, 'customer_portal': True, 'rewards': True,
                         'custom_branding': True, 'support': 'Priority email support'},
        },
    )
    return trial, starter, pro


SIGNUP_POST = {
    'business_name': 'Prg Glass Co',
    'first_name': 'Prg',
    'last_name': 'Owner',
    'email': 'prg@test.com',
    'password': 'GoodPass123!x',
    'password_confirm': 'GoodPass123!x',
    'services_offered': 'both',
}


@override_settings(**LOCMEM_CACHE)
class SignupPrgFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_plans()

    def test_post_success_redirects_to_check_email(self):
        resp = self.client.post('/signup/', SIGNUP_POST)
        self.assertRedirects(resp, '/signup/check-email/')

    def test_check_email_page_is_refresh_safe(self):
        self.client.post('/signup/', SIGNUP_POST)
        first = self.client.get('/signup/check-email/')
        second = self.client.get('/signup/check-email/')  # simulated refresh
        for resp in (first, second):
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'prg@test.com')
        # Resend link present (existing resend route, wired by uidb64)
        self.assertContains(second, '/resend/')

    def test_check_email_direct_visit_redirects_to_signup(self):
        resp = self.client.get('/signup/check-email/')
        self.assertRedirects(resp, '/signup/')

    def test_account_created_inactive(self):
        self.client.post('/signup/', SIGNUP_POST)
        user = User.objects.get(email='prg@test.com')
        self.assertFalse(user.is_active)

    def test_email_failure_surfaced_but_account_created(self):
        with patch('core.email_utils.send_branded_email', side_effect=RuntimeError('SES down')):
            resp = self.client.post('/signup/', SIGNUP_POST, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'trouble sending')
        self.assertContains(resp, 'Resend')
        self.assertTrue(User.objects.filter(email='prg@test.com').exists())

    def test_service_exception_does_not_leak_raw_text(self):
        with patch(
            'apps.saas.views.create_tenant_with_owner',
            side_effect=RuntimeError('secret db detail xyzzy'),
        ):
            resp = self.client.post('/signup/', SIGNUP_POST)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'xyzzy')

    def test_signup_service_wraps_exception_without_leaking(self):
        from apps.tenants.services.signup_service import SignupError
        with patch(
            'apps.tenants.services.signup_service.Tenant.objects.create',
            side_effect=RuntimeError('secret db detail xyzzy'),
        ):
            with self.assertRaises(SignupError) as ctx:
                create_tenant_with_owner(
                    business_name='Leak Shop', email='leak@test.com',
                    password='GoodPass123!x', first_name='L', last_name='O',
                )
        self.assertNotIn('xyzzy', str(ctx.exception))


@override_settings(**LOCMEM_CACHE)
class SignupPhoneAndPlanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_plans()

    def test_phone_saved_to_tenant(self):
        data = dict(SIGNUP_POST, email='phone@test.com', phone='(501) 555-1234')
        self.client.post('/signup/', data)
        tenant = Tenant.objects.get(owner__email='phone@test.com')
        self.assertEqual(tenant.business_phone, '(501) 555-1234')

    def test_phone_optional(self):
        data = dict(SIGNUP_POST, email='nophone@test.com')
        resp = self.client.post('/signup/', data)
        self.assertRedirects(resp, '/signup/check-email/')
        tenant = Tenant.objects.get(owner__email='nophone@test.com')
        self.assertEqual(tenant.business_phone, '')

    def test_plan_param_preselects(self):
        resp = self.client.get('/signup/?plan=pro')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['form'].initial.get('plan'), 'pro')

    def test_invalid_plan_param_ignored(self):
        resp = self.client.get('/signup/?plan=zzz')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('plan', resp.context['form'].initial)

    def test_trial_plan_param_ignored(self):
        resp = self.client.get('/signup/?plan=trial')
        self.assertNotIn('plan', resp.context['form'].initial)

    def test_single_undecided_option(self):
        from apps.saas.forms import SignupForm
        labels = [label for _, label in SignupForm().fields['plan'].widget.choices]
        undecided = [l for l in labels if 'decide' in l.lower() or 'not sure' in l.lower()]
        self.assertEqual(len(undecided), 1, f"expected one undecided option, got {undecided}")

    def test_stale_not_sure_post_degrades_to_undecided(self):
        data = dict(SIGNUP_POST, email='stale@test.com', plan='not_sure')
        resp = self.client.post('/signup/', data)
        self.assertRedirects(resp, '/signup/check-email/')
        tenant = Tenant.objects.get(owner__email='stale@test.com')
        self.assertEqual(tenant.intended_plan, '')

    def test_valid_plan_saved_as_intended(self):
        data = dict(SIGNUP_POST, email='intent@test.com', plan='pro')
        self.client.post('/signup/', data)
        tenant = Tenant.objects.get(owner__email='intent@test.com')
        self.assertEqual(tenant.intended_plan, 'pro')


class SitemapTests(TestCase):
    def test_sitemap_has_real_routes(self):
        resp = self.client.get('/sitemap.xml')
        content = resp.content.decode()
        self.assertIn('https://rssystems.io/signup/', content)
        self.assertIn('https://rssystems.io/pricing/', content)
        self.assertNotIn('/register/', content)


class PublicPlanSurfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_plans()

    def test_pricing_page_excludes_trial_card(self):
        resp = self.client.get('/pricing/')
        self.assertEqual(resp.status_code, 200)
        slugs = [p.slug for p in resp.context['plans']]
        self.assertNotIn('trial', slugs)
        self.assertContains(resp, 'Every plan starts with a 30-day free trial')

    def test_pricing_cards_link_plan_preselect(self):
        resp = self.client.get('/pricing/')
        self.assertContains(resp, '/signup/?plan=pro')
        self.assertContains(resp, '/signup/?plan=starter')

    def test_landing_cards_link_plan_preselect(self):
        resp = self.client.get('/')
        self.assertContains(resp, '/signup/?plan=pro')


class BillingCurrentPlanTests(TestCase):
    """billing_view resolves one authoritative current plan."""

    @classmethod
    def setUpTestData(cls):
        cls.trial, cls.starter, cls.pro = seed_plans()

    def _make_owner(self, email='billing@test.com'):
        result = create_tenant_with_owner(
            business_name='Billing Shop', email=email,
            password='GoodPass123!x', first_name='Bill', last_name='Owner',
        )
        self.user, self.tenant = result['user'], result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_char_field_wins_over_stale_fk(self):
        # Mirror prod drift: plan='pro' but FK still points at starter
        self._make_owner()
        self.tenant.plan = 'pro'
        self.tenant.subscription_plan = self.starter
        self.tenant.subscription_status = 'active'
        self.tenant.save()
        resp = self.client.get('/owner/billing/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['current_plan'].slug, 'pro')
        self.assertEqual(resp.context['current_plan_slug'], 'pro')

    def test_platform_owner_hides_cancel(self):
        self._make_owner(email='platform@test.com')
        self.tenant.is_platform_owner = True
        self.tenant.plan = 'pro'
        self.tenant.subscription_status = 'active'
        self.tenant.save()
        resp = self.client.get('/owner/billing/')
        self.assertNotContains(resp, 'Cancel Subscription')
        self.assertContains(resp, 'Permanent plan')

    def test_normal_active_owner_sees_cancel(self):
        self._make_owner(email='normal@test.com')
        self.tenant.plan = 'starter'
        self.tenant.subscription_plan = self.starter
        self.tenant.subscription_status = 'active'
        self.tenant.save()
        resp = self.client.get('/owner/billing/')
        self.assertContains(resp, 'Cancel Subscription')
