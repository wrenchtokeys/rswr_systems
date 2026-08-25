"""Auth pages are a focused funnel, not a marketing surface (UI_MAGIC_SESSIONS S12).

Three things regress silently the moment someone copies an existing auth
template or "fixes" one by reaching for the familiar `saas/base_public.html`:

1. **The marketing nav comes back.** `base_public.html` ships a Pricing link, a
   "Start Free Trial" CTA and a full site footer. On a login page that is three
   more ways to leave than to log in.
2. **The brand gets said again.** The nav wordmark, the site footer wordmark and
   the in-card copy each repeat "RS Systems" — the page said it five times
   before this session. The rule is once per page, per breakpoint.
3. **The split stops mid-viewport.** `min-h-[calc(100vh-4rem)]` was subtracting
   the nav that is now gone, leaving a strip of dead page under the fold.

Terms/Privacy are the one thing `base_public.html` was legitimately providing,
so `includes/auth_footer.html` carries them and the test pins them down.
"""

import re

from django.test import TestCase
from django.urls import reverse

# Only text nodes, so the `RS Systems` inside <title> (never painted) and the
# wordmark inside the logo <svg> don't count against the budget.
BODY = re.compile(r'<body\b.*?</body>', re.S)
TAGS = re.compile(r'<(script|style|svg|title)\b.*?</\1>', re.S)


def visible_text(html):
    body = BODY.search(html)
    return re.sub(r'<[^>]+>', ' ', TAGS.sub(' ', body.group(0) if body else html))


class AuthShellTests(TestCase):
    """Every page in the login funnel wears the auth shell, not the public one."""

    # (url, how many visible "RS Systems" the page is allowed)
    # /login/ gets two: the desktop brand panel and the `lg:hidden` mobile
    # heading are both in the markup, but only ever one of them is painted.
    PAGES = [
        ('/login/', 2),
        ('/password-reset/', 1),
        ('/password-reset/done/', 1),
        ('/password-reset/complete/', 1),
        ('/password-reset/confirm/MQ/bogus-token/', 1),
    ]

    def test_no_marketing_chrome(self):
        for url, _ in self.PAGES:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn('<nav', html, 'marketing nav is back on an auth page')
                self.assertNotIn('<footer', html, 'site footer is back on an auth page')
                self.assertNotIn('Start Free Trial', html)

    def test_brand_is_said_once(self):
        for url, budget in self.PAGES:
            with self.subTest(url=url):
                said = visible_text(self.client.get(url).content.decode()).count('RS Systems')
                self.assertLessEqual(
                    said, budget,
                    f'{url} says the brand {said}x, budget is {budget}',
                )
                self.assertGreaterEqual(said, 1, f'{url} never says the brand at all')

    def test_split_runs_full_height(self):
        html = self.client.get('/login/').content.decode()
        self.assertIn('min-h-screen', html)
        self.assertNotIn('min-h-[calc(100vh-', html,
                         'height is still compensating for a nav that is gone')

    def test_legal_links_survive_the_nav_removal(self):
        for url, _ in self.PAGES:
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertIn(reverse('terms_of_service'), html)
                self.assertIn(reverse('privacy_policy'), html)
