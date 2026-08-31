"""The landing page paints its content on arrival (UI_MAGIC_SESSIONS S16).

The page carried a scroll-reveal: every major block sat at `opacity: 0` with a
24px offset, and an IntersectionObserver at the bottom of the document added
`.revealed` once the block crossed 12% of the viewport. It was the page's only
motion and it was costing more than it paid.

Two ways it lost:

1. **A flick outruns it.** The fade is .6s and the observer does not fire until
   the block is already 12% on screen, so at real scroll speed you arrive on a
   section that is still a ghost of itself and watch it assemble.
2. **The nav's own anchors skip it entirely.** `#features` and `#pricing` in the
   nav jump the viewport instantly. Clicking "Pricing" — the page's primary
   conversion path — landed on three cards at opacity 0.28 with the prices
   unreadable, which is the one moment on this page where a shop owner is
   deciding something.

The rule this pins is not "don't use `data-reveal`", which is only the mechanism
that happened to be here. It is that **nothing on the landing page may ship
hidden and wait on script to become visible.** Any re-introduction — a different
attribute, a different observer, a CSS-only `animation-timeline` — trips the
same assertions, because they read the delivered CSS rather than the class name.

Hiding that does NOT trip this: Tailwind's responsive utilities (`hidden
md:flex` on the mobile menu) are in the linked stylesheet and are decided by the
viewport, not by a script that may not have run yet.
"""

import re

from django.test import TestCase
from django.urls import reverse

INLINE_STYLE = re.compile(r'<style\b[^>]*>(.*?)</style>', re.S)
INLINE_SCRIPT = re.compile(r'<script\b(?![^>]*\bsrc=)([^>]*)>(.*?)</script>', re.S)

# Declarations that make an element invisible. `display: none` is deliberately
# not here: an inline <style> has no business using it either, but Tailwind's
# own utilities are in app.css and this only ever reads inline blocks.
HIDES = re.compile(r'(?:^|[;{\s])(?:opacity\s*:\s*0(?![.\d])|visibility\s*:\s*hidden)', re.I)


class LandingPaintsOnArrivalTests(TestCase):
    """The landing page's content is visible in the first frame."""

    def setUp(self):
        self.html = self.client.get(reverse('home')).content.decode()

    def test_no_inline_style_ships_content_hidden(self):
        """No inline <style> starts anything at opacity 0 / visibility hidden."""
        for block in INLINE_STYLE.findall(self.html):
            offenders = [line.strip() for line in block.splitlines() if HIDES.search(line)]
            self.assertEqual(
                offenders, [],
                "The landing page ships content hidden and waits on script to "
                "reveal it. That is the scroll-reveal S16 deleted, in a new "
                f"costume:\n  " + "\n  ".join(offenders),
            )

    def test_no_script_gates_visibility_on_a_root_class(self):
        """No inline script flags <html> to switch on a hidden-until-seen rule.

        `document.documentElement.classList.add('js')` was how the reveal armed
        itself: the hidden state applied only once that class landed, so the
        page degraded gracefully without JS and badly *with* it.
        """
        for attrs, body in INLINE_SCRIPT.findall(self.html):
            if 'ld+json' in attrs:
                continue
            self.assertNotRegex(
                body, r'documentElement\.classList\.add',
                "An inline script is tagging <html> to arm a CSS rule. If that "
                "rule hides content until an observer fires, it is the S16 "
                "scroll-reveal again.",
            )

    def test_no_intersection_observer_reveals_content(self):
        """Nothing on the page waits for an element to scroll into view to show it."""
        for attrs, body in INLINE_SCRIPT.findall(self.html):
            if 'ld+json' in attrs:
                continue
            self.assertNotIn(
                'IntersectionObserver', body,
                "The landing page is observing scroll position again. Lazy "
                "*loading* is fine and belongs on the <img> tag; revealing "
                "already-delivered content is what S16 removed.",
            )

    def test_the_sections_the_reveal_used_to_hide_are_all_present(self):
        """A guard against 'fixing' the fade by deleting what it faded."""
        for needle in ('Simple, transparent pricing', 'The old way',
                       'With RS Systems', 'Everything you need'):
            self.assertIn(needle, self.html)
