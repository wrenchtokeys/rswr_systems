"""
The help center promises only what the product does (HELP_CENTER_SESSIONS H1/H4).

The launch-readiness charter — "never promise what doesn't exist" — held for
six weeks and then broke in three places without anyone editing a guide: the
overdue-reminder cron was disabled by policy while three guides and a settings
card kept describing it, and the trial guide said "30-day grace" while
settings said 14. Only a test notices when the policy changes under the copy,
so this one ties the guides to the code they describe.
"""

import os
import re
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUPPORT_TEMPLATES = os.path.join(REPO, 'templates', 'support')

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

# The exact claims that were untrue on 2026-09-17. Matched case-insensitively
# across every guide so a copy-paste into a new guide fails the same way.
BANNED_PHRASES = (
    r'overdue reminder',
    r'reminders do the chasing',
    r'reminders can go out',
    r'30-day grace',
    r'30-day soft landing',
    r'coming soon',
)


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


class GuideSourceTests(SimpleTestCase):
    """Source-level: the phrases are gone from every guide and the settings page."""

    def test_no_guide_promises_reminders_or_a_fixed_grace_period(self):
        offenders = []
        for name in sorted(os.listdir(SUPPORT_TEMPLATES)):
            if not name.endswith('.html'):
                continue
            html = _read(os.path.join(SUPPORT_TEMPLATES, name))
            for phrase in BANNED_PHRASES:
                if re.search(phrase, html, re.IGNORECASE):
                    offenders.append(f'{name}: /{phrase}/')
        self.assertEqual(offenders, [], 'Guides claim something the product does not do:\n' + '\n'.join(offenders))

    def test_settings_page_no_longer_offers_overdue_reminders(self):
        # process_overdue_invoices is DISABLED BY POLICY (CLAUDE.md). A card
        # that lets an owner "enable" it promises an email that never sends.
        html = _read(os.path.join(REPO, 'templates', 'saas', 'owner_settings.html'))
        self.assertNotIn('Overdue Reminders', html)
        self.assertNotIn('overdue_reminder', html)

    def test_help_registry_does_not_advertise_reminders(self):
        from apps.support.views import HELP_TOPICS
        for slug, topic in HELP_TOPICS.items():
            haystack = f"{topic['title']} {topic['blurb']} {topic.get('keywords', '')}".lower()
            self.assertNotIn('reminder', haystack, f'{slug} advertises reminders')


def _make_owner(name, username):
    trial, _ = SubscriptionPlan.objects.update_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'), 'trial_days': 30,
            'max_customers': 10, 'max_repairs_per_month': 50, 'display_order': 0,
        },
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Test', last_name='Owner')
    tenant = Tenant.objects.create(
        name=name, slug=username, subdomain=username, owner=user,
        subscription_plan=trial, plan='trial', subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant, trial


@override_settings(**TEST_SETTINGS)
class RenderedTruthTests(TestCase):
    """Rendered: the numbers on the page are the numbers in settings and plan rows."""

    def setUp(self):
        self.user, self.tenant, self.trial = _make_owner('Truth Shop', 'truth_owner')
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_trial_guide_reads_grace_days_from_settings(self):
        with override_settings(TRIAL_GRACE_DAYS=9):
            r = self.client.get('/help/trial-ending/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Then a 9-day soft landing')
        self.assertContains(r, 'a 9-day grace period')
        self.assertNotContains(r, '30-day grace')
        # And the default, for the deploy that has no env override.
        r = self.client.get('/help/trial-ending/')
        self.assertContains(r, f'a {settings.TRIAL_GRACE_DAYS}-day grace period')

    def test_trial_guide_reads_limits_and_length_from_the_plan_row(self):
        r = self.client.get('/help/trial-ending/')
        self.assertContains(r, 'Your 30 days, no strings')
        self.assertContains(r, 'room for 10 customers and 50 jobs a month')
        # Change the row; the page follows without anyone editing a template.
        SubscriptionPlan.objects.filter(slug='trial').update(
            max_customers=None, max_repairs_per_month=200, trial_days=14,
        )
        r = self.client.get('/help/trial-ending/')
        self.assertContains(r, 'Your 14 days, no strings')
        self.assertContains(r, 'room for unlimited customers and 200 jobs a month')

    def test_trial_guide_only_claims_starter_parity_when_true(self):
        SubscriptionPlan.objects.update_or_create(
            slug='starter',
            defaults={'name': 'Starter', 'monthly_price': Decimal('29.00'),
                      'max_customers': 50, 'max_repairs_per_month': 200, 'display_order': 1},
        )
        r = self.client.get('/help/trial-ending/')
        self.assertNotContains(r, 'same limits as the Starter plan')
        SubscriptionPlan.objects.filter(slug='trial').update(max_customers=50, max_repairs_per_month=200)
        r = self.client.get('/help/trial-ending/')
        self.assertContains(r, 'same limits as the Starter plan')

    def test_no_guide_renders_a_placeholder(self):
        from apps.support.views import HELP_TOPICS
        for slug in HELP_TOPICS:
            r = self.client.get(f'/help/{slug}/')
            self.assertEqual(r.status_code, 200, slug)
            self.assertNotContains(r, 'coming soon', msg_prefix=slug)
            self.assertNotContains(r, 'overdue reminder', msg_prefix=slug)

    def test_settings_billing_tab_renders_without_the_card(self):
        r = self.client.get('/owner/settings/?tab=billing')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Overdue Reminders')
