"""
The repair page must never scroll sideways on a phone (field report, Oct 2026).

The Photo Documentation header holds a title, a count badge, "Download all"
and "Hide Photos". As a non-wrapping flex row it was wider than a phone and,
because a flex row does not shrink below its content, it pushed the whole
page sideways — every card above it ran off the right edge. The row has to
wrap, and the control group has to stay intact when it does.
"""

import re

from django.test import SimpleTestCase


class PhotoHeaderWrapsTests(SimpleTestCase):
    template = 'templates/technician_portal/repair_detail.html'

    def _header_row(self):
        src = open(self.template, encoding='utf-8').read()
        start = src.index('<!-- Photo Documentation Section -->')
        end = src.index('id="photoContent"', start)
        return src[start:end]

    def test_header_row_can_wrap(self):
        row = self._header_row()
        m = re.search(r'<div class="([^"]*justify-between[^"]*)"', row)
        self.assertIsNotNone(m, 'photo header row not found')
        self.assertIn('flex-wrap', m.group(1).split())

    def test_controls_stay_together_and_the_toggle_is_tappable(self):
        row = self._header_row()
        m = re.search(r'<div class="([^"]*)">\s*{% comment %}\s*The shop is who', row)
        self.assertIsNotNone(m, 'control group not found')
        classes = m.group(1).split()
        self.assertIn('shrink-0', classes)
        self.assertNotIn('flex-wrap', classes, 'buttons must not stack into a column')
        toggle = re.search(r'id="photoToggleBtn"\s+class="([^"]*)"', row)
        self.assertIn('min-h-11', toggle.group(1).split())
