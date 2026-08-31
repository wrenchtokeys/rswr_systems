"""The blind crop is aimed where people actually tap (P6.1).

`object-fit: cover` on a damage photo crops to the middle of the frame, which
is the middle of the glass and not the break. P3.1 measured the 73 marks the
backlog queue produced and found technicians tap at **(41%, 61%)** — left of
centre and low, because a chip is photographed from the driver's seat.
Leave-one-out cross-validated, that constant halves the median framing error
against the browser default of `50% 50%` (9.3 vs 17.6) and wins on 65 of 72
photos, at zero computation and without opening the image.

So it becomes the default for every photo nobody ever marked, including all
future ones. A marked photo still wins — every surface emits its tap as an
inline `object-position`, which beats a stylesheet.

The value is authored once, in `BLIND_FOCUS_POSITION`. Two stylesheets repeat
it because neither can import Python: the customer portal's compiled Tailwind,
and the public invoice page, which is a standalone document with its own
`<style>` block. **These tests are the only thing keeping those copies
honest** — and the app.css assertion is the one that catches a Tailwind purge
quietly dropping the rule, which is the failure mode that produces no error
anywhere.

See docs/strategy/PHOTO_ML_SESSIONS.md §P6.1.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.technician_portal.services.photo_crops import (
    BLIND_FOCUS_POSITION, UNZOOMED_SOURCE_FIELDS,
)

BASE_DIR = Path(settings.BASE_DIR)
APP_CSS = BASE_DIR / 'static' / 'css' / 'app.css'
INPUT_CSS = BASE_DIR / 'static' / 'css' / 'src' / 'input.css'
INVOICE_PAGE = BASE_DIR / 'templates' / 'billing' / 'public_invoice_view.html'
PORTAL_PAGE = (
    BASE_DIR / 'templates' / 'customer_portal' / 'repair_detail.html')


def _css_variants(value):
    """`41% 61%` as a stylesheet may legitimately write it.

    The Tailwind build minifies, so whitespace around the colon disappears;
    the value itself keeps its single internal space.
    """
    return (f'object-position:{value}', f'object-position: {value}')


class BlindFocusConstantTests(SimpleTestCase):
    """One authored value, three files. Assert they have not drifted."""

    def test_the_constant_is_the_measured_pair(self):
        """A guard against someone 'tidying' it back to centre.

        If the corpus grows and this is re-derived, this test is meant to
        fail — update it together with P3.1's table in the living doc, and
        record the new sample size. Do not widen the assertion to make a
        future edit painless; the point is that the value is measured.
        """
        self.assertEqual(BLIND_FOCUS_POSITION, '41% 61%')

    def test_the_tailwind_source_carries_the_same_value(self):
        css = INPUT_CSS.read_text()
        self.assertIn('.photo-blind-focus', css)
        self.assertTrue(
            any(v in css for v in _css_variants(BLIND_FOCUS_POSITION)),
            f'static/css/src/input.css has .photo-blind-focus but not '
            f'{BLIND_FOCUS_POSITION!r} — it has drifted from '
            f'BLIND_FOCUS_POSITION in photo_crops.py.',
        )

    def test_the_compiled_css_still_has_the_rule(self):
        """app.css is the artifact that ships (it is committed — see CLAUDE.md).

        A rule present in the source but purged out of the build is exactly
        the bug worth catching: the page renders, the tests pass, and every
        unmarked photo silently goes back to being centre-cropped.
        """
        css = APP_CSS.read_text()
        self.assertIn(
            '.photo-blind-focus', css,
            'The purge dropped .photo-blind-focus from static/css/app.css. '
            'Re-run ./scripts/build_css.sh and commit app.css; if a template '
            'no longer references the class, safelist it in tailwind.config.js.',
        )
        self.assertTrue(
            any(v in css for v in _css_variants(BLIND_FOCUS_POSITION)),
            f'static/css/app.css is stale: it has .photo-blind-focus but not '
            f'{BLIND_FOCUS_POSITION!r}. Re-run ./scripts/build_css.sh.',
        )

    def test_the_public_invoice_page_carries_the_same_value(self):
        """That page has no access to app.css — it is a standalone document."""
        html = INVOICE_PAGE.read_text()
        self.assertIn('.photo-grid img.blind-focus', html)
        self.assertIn(
            '.photo-pair-shot img.blind-focus', html,
            'P6.2 moved a job with both photos out of .photo-grid and into '
            'a before/after pair. If the pair is not in this selector, every '
            'unmarked pair silently goes back to being centre-cropped and '
            'nothing anywhere reports it.',
        )
        self.assertTrue(
            any(v in html for v in _css_variants(BLIND_FOCUS_POSITION)),
            f'public_invoice_view.html has .blind-focus but not '
            f'{BLIND_FOCUS_POSITION!r} — it has drifted from '
            f'BLIND_FOCUS_POSITION in photo_crops.py.',
        )


class BlindFocusAppliesOnlyToDamageTests(SimpleTestCase):
    """The after photo is excluded, for the reason it is never reframed."""

    def test_the_after_photo_is_the_excluded_one(self):
        self.assertEqual(UNZOOMED_SOURCE_FIELDS, ('damage_photo_after',))

    def test_the_portal_aims_the_before_photo_and_leaves_the_after_alone(self):
        """A resin repair leaves a visible blemish. Aiming the after photo at
        the break would frame the scar instead of the fix — so the class goes
        on the before photo's tag only.

        Both photos sit in identical `object-cover` boxes a few lines apart,
        which is exactly how this gets undone by a well-meaning edit.
        """
        html = PORTAL_PAGE.read_text()

        before = [ln for ln in html.splitlines()
                  if 'repair.damage_photo_before.url' in ln and '<img' in ln]
        after = [ln for ln in html.splitlines()
                 if 'repair.damage_photo_after.url' in ln and '<img' in ln]
        self.assertEqual(len(before), 1, 'expected one before-photo <img>')
        self.assertEqual(len(after), 1, 'expected one after-photo <img>')

        self.assertIn('photo-blind-focus', before[0])
        self.assertNotIn(
            'photo-blind-focus', after[0],
            'The after photo must never be reframed — zooming a completed '
            'resin repair shows the customer the blemish, not the fix.',
        )
