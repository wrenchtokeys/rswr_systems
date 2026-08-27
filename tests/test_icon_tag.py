"""The `{% icon %}` tag and the vocabulary behind it (UI_MAGIC S13).

This tag ships *before* the Font Awesome migration, on purpose: the `fas fa-`
count in this repo grew 1,281 -> 1,303 in sixteen days with nobody touching
icons deliberately, because every new surface reaches for the vocabulary that
already exists. The tag's whole job is to be the thing a fresh session reaches
for instead — which only works if it is genuinely a drop-in.

So the tests here are mostly about the properties that make it drop-in, and
the ones that rot silently:

1. **The geometry rules hold for every entry.** A stroke set is only as good as
   its worst icon; one filled shape or one stroke-width-1.5 path and the whole
   set reads as broken. Nothing in review catches that reliably, a loop does.
2. **The `.icon` rule survives the purge.** It is emitted from Python, not from
   a template, so the Tailwind extractor has nothing to anchor it to. Without
   the safelist entry every icon in the app renders 0x0 — invisible, with a
   perfectly valid `<svg>` in the DOM to confuse whoever debugs it.
3. **Decorative by default.** An icon beside its own text label is noise to a
   screen reader. The failure is invisible to everyone who can see the screen.
4. **Aliases resolve.** People will type `fa-times`; the tag accepts it rather
   than making the migration a rename exercise.
"""

import re

from django.conf import settings
from django.template import Context, Template, TemplateSyntaxError
from django.test import SimpleTestCase, override_settings

from core.icons import ALIASES, ICONS, resolve


# SVG path numbers: `-.5`, `.5`, `5`, `5.5` — and they may run together with no
# separator at all, which is why this is anchored per-token rather than split on
# whitespace.
NUMBER = re.compile(r'-?(?:\d+\.?\d*|\.\d+)')


def render(src, **ctx):
    return Template('{% load ui %}' + src).render(Context(ctx))


class IconVocabularyTests(SimpleTestCase):
    """core/icons.py — the drawing rules, enforced on every entry."""

    # Anything that paints an area rather than a line. `fill="none"` lives on
    # the wrapper, so an entry only breaks the set by overriding it.
    FILL = re.compile(r'fill="(?!none)')
    # A per-path stroke override is the other way weights drift apart.
    STROKE = re.compile(r'stroke-width=')

    def test_no_entry_paints_a_fill(self):
        for name, body in ICONS.items():
            with self.subTest(icon=name):
                self.assertIsNone(
                    self.FILL.search(body),
                    f"{name} sets its own fill — the set is stroke-only",
                )

    def test_no_entry_overrides_stroke_width(self):
        for name, body in ICONS.items():
            with self.subTest(icon=name):
                self.assertIsNone(
                    self.STROKE.search(body),
                    f"{name} sets its own stroke-width — 2 is the set's weight",
                )

    def test_no_entry_hardcodes_a_colour(self):
        for name, body in ICONS.items():
            with self.subTest(icon=name):
                self.assertNotIn('#', body, f"{name} hardcodes a colour")
                self.assertNotIn('rgb(', body, f"{name} hardcodes a colour")

    def test_every_entry_draws_something(self):
        shapes = ('<path', '<circle', '<line', '<polyline', '<polygon', '<rect')
        for name, body in ICONS.items():
            with self.subTest(icon=name):
                self.assertTrue(
                    any(s in body for s in shapes), f"{name} draws nothing"
                )

    def test_geometry_stays_inside_the_24_box(self):
        """Coordinates are drawn on the box, never scaled by hand.

        A stray 40 in a path is the cheapest possible mistake to make and the
        most annoying to spot: the icon renders, just clipped or tiny.

        Path data has to be scanned with a real SVG number grammar, not
        `\\d+\\.\\d+`: `c.18-.98.65-1.74` is three numbers with no separators
        between them, and a regex that insists on a leading digit reads the
        middle two as one bogus `98.65`.
        """
        for name, body in ICONS.items():
            with self.subTest(icon=name):
                for raw in NUMBER.findall(body):
                    self.assertLessEqual(
                        abs(float(raw)), 30,
                        f"{name} has a coordinate ({raw}) outside the 24 box",
                    )

    def test_aliases_point_at_real_icons(self):
        for alias, target in ALIASES.items():
            with self.subTest(alias=alias):
                self.assertIn(target, ICONS, f"alias {alias} -> missing {target}")

    def test_no_alias_shadows_a_real_icon(self):
        """An alias that is also a key would silently win or lose by ordering."""
        self.assertEqual(set(ALIASES) & set(ICONS), set())

    def test_resolve_accepts_font_awesome_spelling(self):
        """Pasting `fa-times` off an old surface does the obvious thing.

        The migration is 1,300 call sites; making people also translate the
        names would be a second reason not to start.
        """
        self.assertEqual(resolve('fa-times'), ICONS['x'])
        self.assertEqual(resolve('times'), ICONS['x'])
        self.assertEqual(resolve('X'), ICONS['x'])
        self.assertEqual(resolve('  check  '), ICONS['check'])

    def test_resolve_returns_none_for_unknown(self):
        self.assertIsNone(resolve('definitely-not-an-icon'))
        self.assertIsNone(resolve(''))
        self.assertIsNone(resolve(None))

    def test_the_vocabulary_covers_the_common_surfaces(self):
        """The names the top ~40 `fas fa-` usages in this repo map onto.

        Not a coverage target for its own sake: if one of these is missing when
        someone reaches for it, they reach for `<i class="fas">` instead and the
        burn-up continues. Removing an entry here should be a deliberate act.
        """
        expected = {
            'check', 'check-circle', 'info', 'x', 'arrow-right', 'arrow-left',
            'alert-circle', 'alert-triangle', 'plus', 'send', 'save', 'clock',
            'user', 'gift', 'wrench', 'users', 'lock', 'receipt', 'phone',
            'mail', 'lightbulb', 'shield', 'chevron-right', 'car', 'camera',
            'x-circle', 'eye', 'user-plus', 'layers', 'dollar-sign', 'truck',
            'search', 'map-pin', 'building', 'rotate-ccw', 'trash', 'star',
            'minus', 'credit-card', 'bell', 'pen', 'home', 'help-circle',
        }
        self.assertEqual(expected - set(ICONS), set())


class IconTagTests(SimpleTestCase):
    """{% icon %} — the markup contract call sites depend on."""

    def test_renders_the_stroke_only_frame(self):
        out = render("{% icon 'check' %}")
        self.assertIn('viewBox="0 0 24 24"', out)
        self.assertIn('fill="none"', out)
        self.assertIn('stroke="currentColor"', out)
        self.assertIn('stroke-width="2"', out)
        self.assertIn('stroke-linecap="round"', out)
        self.assertIn(ICONS['check'], out)

    def test_carries_the_icon_class(self):
        """`.icon` is what makes it 1em and therefore drop-in. See the safelist."""
        self.assertIn('class="icon"', render("{% icon 'check' %}"))

    def test_extra_classes_are_appended_not_replaced(self):
        out = render("{% icon 'trash' class='w-5 h-5 text-red-600' %}")
        self.assertIn('class="icon w-5 h-5 text-red-600"', out)

    def test_decorative_by_default(self):
        out = render("{% icon 'check' %}")
        self.assertIn('aria-hidden="true"', out)
        self.assertNotIn('role="img"', out)

    def test_label_makes_it_an_image_with_a_name(self):
        out = render("{% icon 'trash' label='Delete job' %}")
        self.assertIn('role="img"', out)
        self.assertIn('aria-label="Delete job"', out)
        self.assertNotIn('aria-hidden', out)

    def test_label_and_class_are_escaped(self):
        """Both can carry model data — a shop name, a status label."""
        out = render('{% icon "check" label=evil %}', evil='" onload="x()')
        self.assertNotIn('onload="x()"', out)
        self.assertIn('&quot;', out)

    def test_accepts_a_dynamic_name(self):
        """Several templates already pass icon names through context."""
        self.assertIn(ICONS['car'], render('{% icon name %}', name='car'))
        self.assertIn(ICONS['car-side'], render('{% icon name %}', name='fa-car-side'))

    @override_settings(DEBUG=True)
    def test_unknown_name_raises_in_debug(self):
        with self.assertRaises(TemplateSyntaxError):
            render("{% icon 'not-a-real-icon' %}")

    @override_settings(DEBUG=False)
    def test_unknown_name_does_not_500_a_page_in_production(self):
        """A typo in a decoration must not take the page down with it.

        It still renders the sized box, so the layout does not jump while
        someone works out why the glyph is missing.
        """
        with self.assertLogs('core.templatetags.ui', level='WARNING'):
            out = render("{% icon 'not-a-real-icon' %}")
        self.assertIn('class="icon"', out)
        self.assertIn('</svg>', out)


class IconCssTests(SimpleTestCase):
    """The `.icon` rule has to survive the Tailwind purge to mean anything."""

    def test_icon_is_safelisted(self):
        with open(settings.BASE_DIR / 'tailwind.config.js', encoding='utf-8') as fh:
            config = fh.read()
        self.assertIn("'icon',", config)

    def test_icon_rule_is_in_the_built_stylesheet(self):
        """Guards the whole vocabulary against a silent 0x0 render.

        `.icon` is emitted from Python, so nothing in a template anchors it and
        a purge would take it while every `<svg class="icon">` stayed perfectly
        valid in the DOM. Same failure shape as the `bg-yellow-200` pill that
        #206 lost, and just as hard to see from the markup.
        """
        with open(settings.BASE_DIR / 'static' / 'css' / 'app.css', encoding='utf-8') as fh:
            css = fh.read()
        self.assertRegex(
            css, r'\.icon\{[^}]*width:1em',
            "`.icon` is missing from app.css — run ./scripts/build_css.sh",
        )
