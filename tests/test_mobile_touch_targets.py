"""Mobile/touch guarantees that are invisible until someone is in the field.

Every assertion here guards a failure mode that produces no error anywhere:
the page renders, the tests pass, and the tech just quietly mis-taps or gets
their viewport zoomed into a corner.

The compiled `static/css/app.css` is the artifact that actually ships (it is
committed — see CLAUDE.md), so these read it rather than the Tailwind source.
A rule present in `assets/css/input.css` but purged out of `app.css` is
exactly the bug worth catching.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

BASE_DIR = Path(settings.BASE_DIR)
APP_CSS = BASE_DIR / 'static' / 'css' / 'app.css'
INPUT_CSS = BASE_DIR / 'assets' / 'css' / 'input.css'
HEAD_ASSETS = BASE_DIR / 'templates' / 'includes' / 'head_assets.html'


class CompiledCssTests(TestCase):
    """app.css is a build artifact — assert the mobile rules survived the purge."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = APP_CSS.read_text()

    def test_app_css_carries_the_touch_rules_from_its_source(self):
        """A stale app.css ships the old rules no matter what input.css says.

        This compares CONTENT, not mtimes. The obvious check —
        `app.css newer than input.css` — fails spuriously on any git operation
        that rewrites both files (checkout, stash pop, rebase, fresh clone),
        because git sets mtime to checkout time in no guaranteed order.

        Caveat worth knowing: this catches a stale build only for the
        declarations listed here. It cannot notice a brand-new rule added to
        input.css and never compiled — nothing short of running the Tailwind
        CLI can, and `bin/tailwindcss` is gitignored. Add a marker below when
        you add a rule you want guarded.
        """
        source = INPUT_CSS.read_text()
        markers = [
            'min-height: 2.75rem',
            'font-size: 16px !important',
            'touch-action: manipulation',
            'env(safe-area-inset-bottom',
        ]
        compiled = self.css.replace(' ', '')
        for marker in markers:
            self.assertIn(marker, source, f'{marker!r} vanished from input.css')
            self.assertIn(
                marker.replace(' ', ''), compiled,
                f'{marker!r} is in input.css but not in the compiled app.css — '
                f'run ./scripts/build_css.sh and commit the result.')

    def test_coarse_pointer_block_survives(self):
        """The whole touch layer is gated on this one media query."""
        self.assertIn('pointer:coarse', self.css.replace(' ', ''))

    def test_form_controls_are_16px_on_touch(self):
        """Under 16px, iOS Safari zooms the viewport on focus and stays zoomed.

        Every form in this app styles its inputs `text-sm`. The override has to
        beat that utility, so it carries !important on purpose.
        """
        coarse = self._coarse_block()
        self.assertRegex(
            coarse.replace(' ', ''),
            r'font-size:16px!important',
            'coarse-pointer inputs must be forced to 16px')

    def test_buttons_have_a_44px_floor_on_touch(self):
        coarse = self._coarse_block().replace(' ', '')
        self.assertIn('min-height:2.75rem', coarse)

    def test_safe_area_classes_are_defined(self):
        """These were REFERENCED by base_customer.html and defined nowhere, so
        the fixed bottom tab bar sat under the iPhone home indicator."""
        for cls_name in ('safe-area-bottom', 'safe-area-x'):
            self.assertIn(f'.{cls_name}', self.css, f'.{cls_name} missing from app.css')
        self.assertIn('safe-area-inset-bottom', self.css)

    def test_modal_panels_use_dynamic_viewport_height(self):
        """90vh measures the URL-bar-collapsed viewport, so a full modal's
        buttons land off screen on a phone."""
        self.assertIn('90dvh', self.css)

    def _coarse_block(self):
        """Every `@media (pointer:coarse){...}` body, concatenated.

        The minifier splits one authored block into several, so reading only
        the first would assert against an arbitrary slice of the rules.
        """
        bodies = []
        for match in re.finditer(r'@media\s*\(pointer:\s*coarse\)\s*\{', self.css):
            start = match.end()
            depth, i = 1, start
            while i < len(self.css) and depth:
                if self.css[i] == '{':
                    depth += 1
                elif self.css[i] == '}':
                    depth -= 1
                i += 1
            bodies.append(self.css[start:i - 1])
        self.assertTrue(bodies, 'no (pointer: coarse) block in app.css')
        return '\n'.join(bodies)


class ViewportMetaTests(TestCase):
    """The <meta name="viewport"> every shell shares."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        html = HEAD_ASSETS.read_text()
        # The meta tag itself, not the {% comment %} above it explaining why
        # the blocked-zoom directives are absent.
        match = re.search(r'<meta name="viewport"[^>]*>', html)
        assert match, 'no viewport meta in head_assets.html'
        cls.html = match.group(0)

    def test_viewport_fit_cover_is_set(self):
        """Without it, env(safe-area-inset-*) reports 0 and every
        `.safe-area-*` class in app.css is a no-op."""
        self.assertIn('viewport-fit=cover', self.html)

    def test_zoom_is_never_blocked(self):
        """Pinch-zoom on a damage photo in bright sun is a feature, and
        disabling it is an accessibility failure. The iOS focus-zoom
        annoyance is solved with 16px inputs instead."""
        self.assertNotIn('user-scalable=no', self.html)
        self.assertNotIn('maximum-scale', self.html)


class StickyOffsetTests(TestCase):
    """Sticky sub-headers are positioned against the navbar's height by hand,
    so the two have to be changed together. base_app.html is `h-16 sm:h-20`."""

    def test_sticky_bars_track_the_navbar_height(self):
        shell = (BASE_DIR / 'templates' / 'base_app.html').read_text()
        self.assertIn('h-16 sm:h-20', shell)
        for name in ('technician_portal/repair_detail.html', 'saas/owner_invoices.html'):
            html = (BASE_DIR / 'templates' / name).read_text()
            self.assertIn(
                'top-16 sm:top-20', html,
                f'{name} pins a sticky bar under the navbar; its offset must '
                f'match base_app.html (h-16 sm:h-20)')
