"""
A dialog taller than the window must still be reachable from its first field.

`display: flex; align-items: center` on a scrollable overlay centres a panel
by overflowing it equally above and below — and the half above the top edge
is outside the scrollable area. On the multi-break form that put "Damage
Type", the one required field, 350px above a laptop window with no way to
scroll to it. Two shapes are safe and this suite accepts either:

  * the panel caps its own height and scrolls inside (`.modal-panel`,
    `max-h-*`, or the portal's `.modal-container`), or
  * the overlay aligns to the top and the panel centres with auto margins.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TEMPLATES = Path(settings.BASE_DIR) / 'templates'
CLASS_ATTR = re.compile(r'class\s*=\s*"([^"]*)"')
# How far below the overlay's opening tag the panel may sit (a backdrop
# sibling and a wrapper come first in a few of them).
PANEL_WINDOW = 10
HEIGHT_CAPPED = re.compile(r'\bmodal-panel\b|\bmodal-container\b|\bmax-h-')


def _is_centring_overlay(classes):
    tokens = classes.split()
    if 'modal-overlay' in tokens:
        return True
    return ('fixed' in tokens and 'inset-0' in tokens
            and any(t.split(':')[-1] == 'items-center' for t in tokens))


class CentredOverlayTests(SimpleTestCase):
    def test_every_centred_overlay_has_a_height_capped_panel(self):
        offenders = []
        for path in sorted(TEMPLATES.rglob('*.html')):
            if 'emails' in path.parts:
                continue
            lines = path.read_text(encoding='utf-8').splitlines()
            for number, line in enumerate(lines, start=1):
                if not any(_is_centring_overlay(m.group(1)) for m in CLASS_ATTR.finditer(line)):
                    continue
                window = '\n'.join(lines[number - 1:number - 1 + PANEL_WINDOW])
                if not HEIGHT_CAPPED.search(window):
                    offenders.append(f'{path.relative_to(TEMPLATES)}:{number}')
        self.assertEqual(
            offenders, [],
            'Vertically centred overlay with no height cap on its panel — on a '
            'short window the top of the dialog cannot be scrolled to. Give the '
            'panel `max-h-[90vh] overflow-y-auto` (or use .modal-panel).')


class MultiBreakDialogTests(SimpleTestCase):
    """This page hand-rolls `.modal`/`.active` instead of the shared skeleton."""

    def setUp(self):
        source = (TEMPLATES / 'technician_portal' / 'multi_break_repair_form.html').read_text(encoding='utf-8')
        self.active_rule = re.search(r'\.modal\.active\s*\{([^}]*)\}', source).group(1)
        self.panel_rule = re.search(r'\.modal\.active\s+\.modal-content\s*\{([^}]*)\}', source)

    def test_overlay_does_not_centre_with_align_items(self):
        self.assertNotRegex(self.active_rule, r'align-items:\s*center')

    def test_panel_centres_with_auto_margins(self):
        self.assertIsNotNone(self.panel_rule)
        self.assertRegex(self.panel_rule.group(1), r'margin-top:\s*auto')
        self.assertRegex(self.panel_rule.group(1), r'margin-bottom:\s*auto')
