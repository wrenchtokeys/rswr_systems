"""A stranger can find RS Systems, and we can tell that they did (C3).

The 2026-09-17/18 readiness audit found the marketing site was five indexable
URLs with no analytics, eighteen pages of real content behind a login, no
`og:image`, and meta tags on the landing page only. Each of those is a silent
failure — nothing 500s, nothing looks broken, the site is just invisible — so
each one needs a test that fails when it comes back.

The four things guarded here:

1. **The published guides stay public and the rest stay gated.** One `public`
   flag decides both, and the sitemap and robots.txt read the same flag, so a
   guide cannot be published in one place and gated in another.
2. **A published guide never shows a signed-out reader a link they cannot
   follow.** The deep links into Settings, the guide hub and the gated guides
   are all authenticated-only; a visitor bounced to `/login/` from a page they
   arrived at from Google is a lost visitor.
3. **Every public page has a description, a canonical and a large share card.**
4. **Analytics is first-party.** The CSP allowlist must not grow a host, and
   the tracker must be off when unconfigured.

Every loop here collects its offenders and asserts once at the end rather than
using `subTest`. That reads better on a failure — you get the whole list, not
the first one — and it is also the only shape that survives `--parallel`: a
`subTest` failure inside a `TestCase` that has used `self.client` pickles the
test case back to the parent process, the client drags the middleware chain
along, and the run dies with `cannot pickle 'module' object` having reported
nothing at all.
"""

import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.support.views import HELP_TOPICS, public_topics
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'SITE_URL': 'https://rssystems.io',
}

# The public pages a crawler and a share are supposed to reach, by URL name.
PUBLIC_PAGE_NAMES = ['home', 'pricing', 'terms_of_service', 'privacy_policy',
                     'sms_program', 'public_contact']


def _make_owner(name='Findable Shop', username='find_owner'):
    trial, _ = SubscriptionPlan.objects.update_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'), 'trial_days': 30,
            'max_customers': 50, 'max_repairs_per_month': 200, 'display_order': 0,
        },
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Test', last_name='Owner')
    tenant = Tenant.objects.create(
        name=name, slug=username, subdomain=username, owner=user,
        subscription_plan=trial, plan='trial', subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_SETTINGS)
class PublishedGuideTests(TestCase):
    """The five published guides answer to a signed-out visitor; the rest don't."""

    def setUp(self):
        self.client = Client()

    def test_every_public_guide_returns_200_to_a_visitor(self):
        published = [slug for slug, _t in public_topics()]
        self.assertTrue(published, 'Nothing is published — C3 published five guides.')
        bad = {slug: self.client.get(reverse('help_topic', args=[slug])).status_code
               for slug in published}
        self.assertEqual({s: c for s, c in bad.items() if c != 200}, {})

    def test_gated_guides_still_ask_a_visitor_to_sign_in(self):
        gated = [s for s, t in HELP_TOPICS.items() if not t.get('public')]
        self.assertTrue(gated, 'Everything is published — that was not the decision.')
        leaked, no_next = [], []
        for slug in gated:
            url = reverse('help_topic', args=[slug])
            response = self.client.get(url)
            if response.status_code != 302:
                leaked.append(f'{slug} → {response.status_code}')
            # `?next=` intact: the decorator's behaviour, kept by hand.
            elif f'next={url}' not in response['Location']:
                no_next.append(f'{slug} → {response["Location"]}')
        self.assertEqual(leaked, [], 'gated guides answered a signed-out visitor')
        self.assertEqual(no_next, [], 'sign-in redirect lost ?next=')

    def test_the_guide_hub_is_still_signed_in_only(self):
        # The hub lists every guide including the gated ones; publishing it
        # would advertise thirteen pages a visitor cannot open.
        response = self.client.get(reverse('help_home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_a_visitor_is_never_shown_a_link_they_cannot_follow(self):
        """No deep link into the app, the hub, or a gated guide.

        This is the failure that made C1's switching section useless for four
        months: the one call to action on the page pointed at a `@login_required`
        URL, so the visitor it was written for hit a sign-in wall.
        """
        gated_urls = {reverse('help_topic', args=[slug])
                      for slug, t in HELP_TOPICS.items() if not t.get('public')}
        forbidden = gated_urls | {
            reverse('help_home'), reverse('owner_settings'),
            reverse('owner_invoice_list'), reverse('create_multi_break_repair'),
            reverse('help_contact'),
        }
        offenders = []
        for slug, _topic in public_topics():
            html = self.client.get(reverse('help_topic', args=[slug])).content.decode()
            offenders += [f'{slug} links to {url}' for url in sorted(forbidden)
                          if f'href="{url}"' in html]
        self.assertEqual(offenders, [],
                         'a published guide sends a visitor somewhere they cannot go')

    def test_a_visitor_gets_the_public_shell_and_a_way_in(self):
        html = self.client.get(reverse('help_topic', args=['sales-tax'])).content.decode()
        self.assertIn(f'href="{reverse("signup")}"', html)
        self.assertIn(f'href="{reverse("pricing")}"', html)
        self.assertIn(f'href="{reverse("public_contact")}"', html)
        # The thumbs POST to a signed-in endpoint; showing them to a visitor
        # would be a button that silently redirects to the login page.
        self.assertNotIn('id="guide-feedback"', html)

    def test_a_signed_in_reader_still_gets_the_app_shell(self):
        user, tenant = _make_owner()
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()

        html = self.client.get(reverse('help_topic', args=['sales-tax'])).content.decode()
        self.assertIn('id="guide-feedback"', html)
        self.assertIn(f'href="{reverse("help_home")}"', html)
        # The deep link into Settings is the reason an owner opens this page.
        self.assertIn(reverse('owner_settings'), html)

    def test_every_published_guide_has_its_template(self):
        missing = [slug for slug, _t in public_topics()
                   if not os.path.exists(os.path.join(REPO, 'templates', 'support',
                                                      f'{slug}.html'))]
        self.assertEqual(missing, [], 'published with no template')


@override_settings(**TEST_SETTINGS)
class SitemapAndRobotsTests(TestCase):
    """Both files are generated from the URL conf and one registry, not typed."""

    def setUp(self):
        self.client = Client()

    def _sitemap_paths(self):
        body = self.client.get('/sitemap.xml').content.decode()
        return [line.split('<loc>')[1].split('</loc>')[0].replace(settings.SITE_URL, '')
                for line in body.splitlines() if '<loc>' in line]

    def test_every_url_in_the_sitemap_actually_resolves(self):
        """The bug this exists for: the sitemap once advertised a 404 /register/.

        A hand-written list drifts from the URL conf silently — a crawler is the
        only thing that reads it, and it does not report back.
        """
        broken = []
        for path in self._sitemap_paths():
            code = self.client.get(path).status_code
            if code in (404, 302):
                broken.append(f'{path} → {code}')
        self.assertEqual(broken, [],
                         'the sitemap advertises URLs a crawler cannot fetch')

    def test_published_guides_are_in_the_sitemap(self):
        paths = self._sitemap_paths()
        for slug, _topic in public_topics():
            self.assertIn(reverse('help_topic', args=[slug]), paths)

    def test_gated_guides_are_not_in_the_sitemap(self):
        paths = self._sitemap_paths()
        for slug, topic in HELP_TOPICS.items():
            if not topic.get('public'):
                self.assertNotIn(reverse('help_topic', args=[slug]), paths)

    def test_sitemap_uses_site_url_not_a_hardcoded_domain(self):
        with override_settings(SITE_URL='https://staging.example.com'):
            body = self.client.get('/sitemap.xml').content.decode()
        self.assertIn('https://staging.example.com/', body)
        self.assertNotIn('rssystems.io', body)

    def test_robots_keeps_crawlers_out_of_the_token_routes(self):
        """Nothing leaks — every one is gated or HMAC-tokened — but a token
        route is a customer's own invoice, quote or payment page."""
        body = self.client.get('/robots.txt').content.decode()
        for path in ('/quote/', '/invoice/', '/pay/', '/app/', '/tech/', '/owner/', '/admin/'):
            self.assertIn(f'Disallow: {path}', body)

    def test_robots_does_not_name_paths_the_app_does_not_serve(self):
        body = self.client.get('/robots.txt').content.decode()
        for ghost in ('/portal/', '/customer/', '/setup-database/'):
            self.assertNotIn(ghost, body)

    def test_robots_allows_exactly_the_published_guides(self):
        body = self.client.get('/robots.txt').content.decode()
        self.assertIn('Disallow: /help/', body)
        allowed = {line.split('Allow: ')[1] for line in body.splitlines()
                   if line.startswith('Allow: /help/')}
        self.assertEqual(
            allowed,
            {reverse('help_topic', args=[slug]) for slug, _t in public_topics()},
        )


@override_settings(**TEST_SETTINGS)
class PageMetaTests(TestCase):
    """Every public page carries a description, a canonical and a large card."""

    def setUp(self):
        self.client = Client()

    def _html(self, name):
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200, name)
        return response.content.decode()

    def test_every_public_page_has_a_description_and_a_canonical(self):
        missing = []
        for name in PUBLIC_PAGE_NAMES:
            html = self._html(name)
            if '<meta name="description"' not in html:
                missing.append(f'{name}: no description')
            if f'<link rel="canonical" href="{settings.SITE_URL}{reverse(name)}"' not in html:
                missing.append(f'{name}: no canonical')
        self.assertEqual(missing, [])

    def test_descriptions_are_not_all_the_same_sentence(self):
        """/pricing/ is the second-most-likely page to rank; the site-wide
        fallback there is a wasted snippet."""
        from core.templatetags.seo import DEFAULT_DESCRIPTION
        generic = [name for name in ('pricing', 'terms_of_service', 'privacy_policy',
                                     'sms_program', 'public_contact')
                   if DEFAULT_DESCRIPTION in self._html(name)]
        self.assertEqual(generic, [], 'these pages fall back to the site-wide sentence')

    def test_every_public_page_shares_as_a_large_image_card(self):
        offenders = []
        for name in PUBLIC_PAGE_NAMES:
            html = self._html(name)
            if '<meta name="twitter:card" content="summary_large_image">' not in html:
                offenders.append(f'{name}: not a large-image card')
            if 'og:image' not in html:
                offenders.append(f'{name}: no og:image')
            # The small `summary` card is a favicon beside a line of text.
            if 'content="summary"' in html:
                offenders.append(f'{name}: still the small summary card')
        self.assertEqual(offenders, [])

    def test_the_share_card_image_is_committed_at_open_graph_dimensions(self):
        from core.templatetags.seo import (OG_IMAGE_HEIGHT, OG_IMAGE_PATH,
                                           OG_IMAGE_WIDTH)
        path = os.path.join(REPO, 'static', OG_IMAGE_PATH)
        self.assertTrue(os.path.exists(path),
                        'Run scripts/og_card.py and commit the output.')
        from PIL import Image
        with Image.open(path) as image:
            self.assertEqual(image.size, (OG_IMAGE_WIDTH, OG_IMAGE_HEIGHT))

    def test_a_published_guide_describes_itself(self):
        html = self.client.get(reverse('help_topic', args=['warranty'])).content.decode()
        self.assertIn(HELP_TOPICS['warranty']['blurb'], html)
        self.assertIn(f'<link rel="canonical" href="{settings.SITE_URL}/help/warranty/"', html)

    def test_the_rich_snippet_price_range_tracks_the_plan_rows(self):
        """The JSON-LD AggregateOffer is what Google may print beside the result.

        C1 flagged it as a rich-snippet liability and C2's lesson is that plan
        data drifts — a $49–$249 snippet under a page selling $79–$299 is a
        wrong price in a search result, which is the one place nobody looks.
        """
        import json

        SubscriptionPlan.objects.all().delete()
        for slug, price, order in (('starter', '79.00', 1), ('pro', '149.00', 2),
                                   ('enterprise', '299.00', 3)):
            SubscriptionPlan.objects.create(
                slug=slug, name=slug.title(), monthly_price=Decimal(price),
                display_order=order, is_active=True,
            )
        # A trial row is excluded from the cards, so it must not set the floor.
        SubscriptionPlan.objects.create(slug='trial', name='Trial',
                                        monthly_price=Decimal('0.00'),
                                        display_order=0, is_active=True)

        html = self._html('home')
        block = html.split('application/ld+json">')[1].split('</script>')[0]
        offers = json.loads(block)['offers']
        self.assertEqual(offers['lowPrice'], '79')
        self.assertEqual(offers['highPrice'], '299')
        self.assertEqual(offers['offerCount'], '3')

    def test_search_console_meta_tag_renders_only_when_configured(self):
        self.assertNotIn('google-site-verification', self._html('pricing'))
        with override_settings(GOOGLE_SITE_VERIFICATION='abc123'):
            self.assertIn('<meta name="google-site-verification" content="abc123">',
                          self._html('pricing'))


@override_settings(**TEST_SETTINGS)
class AnalyticsTests(TestCase):
    """First-party or not at all — the CSP allowlist is the whole argument."""

    def setUp(self):
        self.client = Client()

    def test_nothing_is_tracked_until_a_site_is_configured(self):
        self.assertEqual(settings.PLAUSIBLE_DOMAIN, '',
                         'The test suite must not be pointed at a live Plausible site.')
        html = self.client.get(reverse('pricing')).content.decode()
        self.assertNotIn('data-domain', html)
        self.assertEqual(self.client.get(reverse('plausible_script')).status_code, 404)
        self.assertEqual(self.client.post(reverse('plausible_event')).status_code, 404)

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io')
    def test_the_tracker_is_served_from_our_own_origin(self):
        offenders = []
        for name in ('home', 'pricing'):
            html = self.client.get(reverse(name)).content.decode()
            for needle in ('data-domain="rssystems.io"',
                           f'src="{reverse("plausible_script")}"',
                           f'data-api="{reverse("plausible_event")}"'):
                if needle not in html:
                    offenders.append(f'{name}: missing {needle}')
            # A third-party host here is the thing this design exists to
            # avoid; it would need a CSP change to work at all.
            if 'plausible.io' in html:
                offenders.append(f'{name}: names plausible.io directly')
        self.assertEqual(offenders, [])

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io')
    def test_a_visitor_is_measured_and_a_signed_in_user_is_not(self):
        """The rule is "measure signed-out visitors", not "measure the public
        shell" — /onboarding/ and a signed-in owner reading a guide both wear
        that shell, and neither is a stranger arriving from somewhere."""
        guide = self.client.get(reverse('help_topic', args=['sales-tax'])).content.decode()
        self.assertIn('data-domain=', guide)

        user, tenant = _make_owner('Untracked Shop', 'untracked_owner')
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()
        for name in ('owner_dashboard', 'onboarding', 'pricing'):
            html = self.client.get(reverse(name), follow=True).content.decode()
            self.assertNotIn('data-domain=', html, f'{name} tracks a signed-in user')
        signed_in_guide = self.client.get(
            reverse('help_topic', args=['sales-tax'])).content.decode()
        self.assertNotIn('data-domain=', signed_in_guide)

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io')
    def test_the_csp_allowlist_does_not_grow_a_host(self):
        from common.csp_middleware import build_policy
        policy = ' '.join(build_policy('test-nonce'))
        self.assertNotIn('plausible.io', policy)

    def test_the_analytics_script_carries_no_nonce(self):
        """CLAUDE.md: an external `<script src=…>` never gets one — it is
        covered by 'self', and tests/test_csp.py enforces the converse."""
        source = open(os.path.join(REPO, 'templates', 'includes', 'analytics.html'),
                      encoding='utf-8').read()
        tags = [line for line in source.splitlines() if line.startswith('<script')]
        self.assertEqual(len(tags), 1, source)
        self.assertNotIn('nonce', tags[0])


class AnalyticsProxyTests(SimpleTestCase):
    """The proxy's failure modes, which are the whole reason it is not one line."""

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io', **TEST_SETTINGS)
    def test_an_upstream_outage_serves_an_empty_script_not_an_error(self):
        from unittest.mock import patch

        import requests

        with patch('common.analytics.requests.get',
                   side_effect=requests.RequestException('boom')):
            response = self.client.get(reverse('plausible_script'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'')
        # Not cached: one bad minute must not blank analytics for an hour.
        self.assertEqual(response['Cache-Control'], 'no-store')

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io', **TEST_SETTINGS)
    def test_the_visitors_address_is_forwarded_not_ours(self):
        """Plausible derives country and unique visitors from the request IP,
        and the request it sees is our server's.

        The address taken is the RIGHT-most hop — the one the load balancer
        appended. Everything to its left is whatever the client typed, so
        reading `[0]` would let a visitor pick the country they are counted in.
        """
        from unittest.mock import MagicMock, patch

        upstream = MagicMock(status_code=202, content=b'ok', headers={})
        with patch('common.analytics.requests.post', return_value=upstream) as post:
            self.client.post(
                reverse('plausible_event'),
                data='{"n":"pageview"}', content_type='application/json',
                HTTP_X_FORWARDED_FOR='198.51.100.7, 203.0.113.9',
                HTTP_USER_AGENT='Mozilla/5.0 (test)',
            )
        headers = post.call_args.kwargs['headers']
        self.assertEqual(headers['X-Forwarded-For'], '203.0.113.9')
        self.assertEqual(headers['User-Agent'], 'Mozilla/5.0 (test)')

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io', **TEST_SETTINGS)
    def test_a_direct_request_falls_back_to_remote_addr(self):
        from unittest.mock import MagicMock, patch

        upstream = MagicMock(status_code=202, content=b'ok', headers={})
        with patch('common.analytics.requests.post', return_value=upstream) as post:
            self.client.post(reverse('plausible_event'), data='{}',
                             content_type='application/json',
                             REMOTE_ADDR='192.0.2.44')
        self.assertEqual(post.call_args.kwargs['headers']['X-Forwarded-For'],
                         '192.0.2.44')

    @override_settings(PLAUSIBLE_DOMAIN='rssystems.io', **TEST_SETTINGS)
    def test_a_failed_forward_is_accepted_quietly(self):
        from unittest.mock import patch

        import requests

        with patch('common.analytics.requests.post',
                   side_effect=requests.RequestException('boom')):
            response = self.client.post(reverse('plausible_event'), data='{}',
                                        content_type='application/json')
        self.assertEqual(response.status_code, 202)
