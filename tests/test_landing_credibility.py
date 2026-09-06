"""The landing page tells the truth (IMPROVEMENT_SESSIONS C1; UI_MAGIC S14/S15).

Before this session the page undersold the product and oversold the traction:
a four-stat "trust bar" of small or non-statistics ("500+ Jobs Tracked",
"24/7 Access Anywhere"), a hand-built HTML imitation of the dashboard with
hardcoded numbers that had drifted from the real screen twice, and the only
testimonial — the founder's — buried below the features.

What this pins:

1. **No filler statistics.** No "N+" counters, no "24/7", no "100%". A claim on
   this page is something a visitor can check.
2. **Real product imagery.** The hero and the product section reference
   screenshots under ``static/images/landing/`` that exist on disk and were
   produced by ``scripts/landing_shots.py``. No hand-built dashboard markup.
3. **Founder story above the fold.** The founder's note appears before the
   features section, and is labelled as a founder's note.
4. **Switching is addressed.** There is a section about moving from paper,
   spreadsheets or another system.
5. **The structured data agrees with the plan cards** on the same page.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.tenants.models import SubscriptionPlan

LANDING_IMAGES = Path(settings.BASE_DIR) / 'static' / 'images' / 'landing'

# Every capture scripts/landing_shots.py produces. The list here and SHOTS in
# the script must agree; if you add a shot, add it here too.
EXPECTED_SHOTS = [
    'owner-dashboard.webp',
    'jobs-list.webp',
    'job-form-phone.webp',
    'customer-portal-phone.webp',
]

# Marketing filler that used to sit under the hero. Any of these coming back
# means someone re-added a stat that is either unverifiable or not a statistic.
FILLER = [
    'Jobs Tracked',
    '$50K',
    '24/7',
    '100% Mobile',
    re.compile(r'\b\d{2,}\+\s*(?:jobs|shops|customers|invoices|repairs)', re.I),
]

# The old mock's hardcoded numbers. A hand-built dashboard is exactly the
# thing that drifts; the page must show a capture of the real one.
MOCK_TELLS = ['$8,420', '47 of 200 used', '3 of 5 seats', '12 of 50 accounts',
              'Revenue This Month']


class LandingCredibilityTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        for slug, name, price, order in [
            ('trial', 'Trial', '0.00', 0),
            ('starter', 'Starter', '49.00', 1),
            ('pro', 'Pro', '99.00', 2),
            ('enterprise', 'Enterprise', '249.00', 3),
        ]:
            SubscriptionPlan.objects.get_or_create(
                slug=slug, defaults={'name': name, 'monthly_price': Decimal(price),
                                     'trial_days': 30 if slug == 'trial' else 0,
                                     'is_active': True, 'display_order': order})

    def setUp(self):
        self.html = self.client.get(reverse('home')).content.decode()

    # --- 1. no filler statistics ------------------------------------------

    def test_no_filler_statistics(self):
        for tell in FILLER:
            if isinstance(tell, str):
                self.assertNotIn(tell, self.html, f'filler statistic back on the landing page: {tell!r}')
            else:
                self.assertIsNone(tell.search(self.html),
                                  f'a "N+ things" counter is back on the landing page: {tell.pattern}')

    def test_no_hand_built_dashboard_mock(self):
        for tell in MOCK_TELLS:
            self.assertNotIn(tell, self.html, f'the hand-built dashboard mock is back: {tell!r}')

    def test_no_invented_crowd(self):
        """No 'shop owners love it' until shop owners other than the founder say so."""
        self.assertNotRegex(self.html, r'(?i)shop owners (love|trust|rely on)')

    # --- 2. real product imagery -------------------------------------------

    def test_every_capture_exists_on_disk(self):
        missing = [name for name in EXPECTED_SHOTS if not (LANDING_IMAGES / name).is_file()]
        self.assertEqual(missing, [], 'run `python scripts/landing_shots.py` and commit the output')

    def test_landing_references_every_capture(self):
        for name in EXPECTED_SHOTS:
            self.assertIn(f'images/landing/{name}', self.html,
                          f'{name} is captured but the landing page does not show it')

    def test_captures_are_real_images_with_dimensions(self):
        """Each <img> names its size (no layout shift) and has a real alt text."""
        imgs = re.findall(r'<img\b[^>]*images/landing/[^>]*>', self.html)
        self.assertEqual(len(imgs), len(EXPECTED_SHOTS))
        for tag in imgs:
            self.assertRegex(tag, r'\bwidth="\d+"', tag)
            self.assertRegex(tag, r'\bheight="\d+"', tag)
            alt = re.search(r'\balt="([^"]*)"', tag)
            self.assertIsNotNone(alt, tag)
            self.assertGreater(len(alt.group(1).split()), 6, f'alt text is a label, not a description: {tag}')

    def test_hero_shot_is_the_owner_dashboard(self):
        """The first image a visitor sees is the real dashboard, loaded eagerly."""
        first = re.search(r'<img\b[^>]*images/landing/[^>]*>', self.html).group(0)
        self.assertIn('owner-dashboard.webp', first)
        self.assertIn('fetchpriority="high"', first)
        self.assertNotIn('loading="lazy"', first)

    # --- 3. founder story above the fold ------------------------------------

    def test_founder_note_precedes_features(self):
        note = self.html.find('A note from the founder')
        features = self.html.find('id="features"')
        self.assertGreater(note, -1, 'the founder note is gone')
        self.assertGreater(features, -1)
        self.assertLess(note, features, 'the founder note has moved below the features again')

    def test_founder_is_named_in_the_hero(self):
        hero_end = self.html.find('A note from the founder')
        hero = self.html[:hero_end]
        self.assertIn('shop owner', hero)
        self.assertIn('Arkansas', hero)

    # --- 4. switching -------------------------------------------------------

    def test_switching_section_exists(self):
        self.assertIn('id="switching"', self.html)
        self.assertRegex(self.html, r'(?i)spreadsheets?')
        self.assertIn('/help/contact/', self.html)

    # --- 5. structured data agrees with the cards ---------------------------

    def test_json_ld_prices_match_the_plans_on_the_page(self):
        block = re.search(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', self.html, re.S)
        self.assertIsNotNone(block)
        data = json.loads(block.group(1))
        offers = data['offers']
        shown = SubscriptionPlan.objects.filter(is_active=True).exclude(slug='trial')
        prices = [p.monthly_price for p in shown]
        self.assertEqual(Decimal(offers['lowPrice']), min(prices))
        self.assertEqual(Decimal(offers['highPrice']), max(prices))
        self.assertEqual(int(offers['offerCount']), shown.count())
