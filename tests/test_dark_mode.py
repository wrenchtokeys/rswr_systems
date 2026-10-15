"""Dark mode for the staff app: light by default, the palette flips, not the templates.

The design is in scripts/dark_palette.py. What these tests hold still:

* light mode is Tailwind's own palette, byte for byte — turning dark mode on
  for one person must not move a pixel for everybody else;
* every status pill and every shop's brand colour stays readable in the dark;
* the switch is server-rendered from a cookie, defaults to light, and only the
  two staff shells listen to it — public pages, the customer portal, emails
  and PDFs never go dark.
"""
import importlib.util
import re
from pathlib import Path

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.tenants.branding import (
    RAISED, WHITE, brand_shades_dark, contrast, hex_to_rgb,
)
from common.context_processors import ui_theme
from core.templatetags import ui as ui_tags

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / 'static' / 'css' / 'app.css'
TEMPLATES = ROOT / 'templates'


def _load_palette():
    spec = importlib.util.spec_from_file_location(
        'dark_palette', ROOT / 'scripts' / 'dark_palette.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


palette = _load_palette()


def _rgb(channels):
    return tuple(int(c) for c in channels.split())


def _dark_vars():
    """{name: 'r g b'} for every channel variable the dark theme sets."""
    out = {}
    for decl in palette.dark_declarations():
        m = re.match(r'--([\w-]+): (\d+ \d+ \d+);$', decl)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _dark_color(utility, dark):
    """The colour `bg-green-100` / `text-green-800` resolves to in the dark."""
    kind, fam, shade = re.match(r'(bg|text)-(\w+)-(\d+)$', utility).groups()
    if kind == 'text':
        return _rgb(dark.get(f'tx-{fam}-{shade}') or dark[f'c-{fam}-{shade}'])
    return _rgb(dark[f'c-{fam}-{shade}'])


class PaletteFileTests(SimpleTestCase):
    def test_generated_file_is_current(self):
        self.assertEqual(
            palette.main(['--check']), 0,
            'assets/css/palette.css is stale — run python scripts/dark_palette.py '
            'then ./scripts/build_css.sh')

    def test_light_values_are_tailwinds_own(self):
        """The first :root block in the build is the light palette."""
        css = APP_CSS.read_text()
        for fam, hexes in palette.TAILWIND.items():
            for shade, hx in zip(palette.SHADES, hexes):
                expected = '{} {} {}'.format(*hex_to_rgb(hx))
                first = re.search(rf'--c-{fam}-{shade}:([\d ]+?)[;}}]', css)
                self.assertIsNotNone(first, f'--c-{fam}-{shade} missing from app.css')
                self.assertEqual(first.group(1).strip(), expected,
                                 f'light {fam}-{shade} drifted from Tailwind')

    def test_dark_theme_is_in_the_build_for_both_switches(self):
        css = APP_CSS.read_text()
        self.assertIn(':root[data-theme=dark]', css)
        self.assertIn(':root[data-theme=system]', css)
        self.assertIn('prefers-color-scheme:dark', css)

    def test_text_and_surface_use_separate_variables(self):
        """`text-gray-900` goes light while `bg-gray-900` stays a dark chip."""
        css = APP_CSS.read_text()
        self.assertIn('.text-gray-900{', css)
        self.assertRegex(css, r'\.text-gray-900\{[^}]*var\(--tx-gray-900,var\(--c-gray-900\)\)')
        self.assertRegex(css, r'\.bg-gray-900\{[^}]*var\(--c-gray-900\)')
        self.assertRegex(css, r'\.text-brand-600\{[^}]*var\(--brand-tx-600,var\(--brand-600\)\)')

    def test_no_dark_variant_utilities(self):
        """Flip the palette, not the templates: a `dark:` class is the start of
        the half-converted-page sweep this design exists to avoid."""
        offenders = [
            str(p.relative_to(ROOT)) for p in TEMPLATES.rglob('*.html')
            if re.search(r'class="[^"]*\bdark:', p.read_text())
        ]
        self.assertEqual(offenders, [])


class DarkReadabilityTests(SimpleTestCase):
    def test_every_status_pill_reads_in_the_dark(self):
        dark = _dark_vars()
        tables = [ui_tags.SERVICE_STATUS_STYLES, ui_tags.INVOICE_STATUS_STYLES,
                  ui_tags.QUOTE_STATUS_STYLES, ui_tags.CLAIM_STATUS_STYLES]
        pairs = {style for table in tables for style, _ in table.values()}
        pairs.add(ui_tags._DEFAULT_STYLE[0])
        pairs |= {'bg-purple-100 text-purple-800', 'bg-sky-100 text-sky-800'}
        for classes in sorted(pairs):
            bg, text = classes.split()
            ratio = contrast(_dark_color(bg, dark), _dark_color(text, dark))
            self.assertGreaterEqual(ratio, 4.5, f'{classes}: {ratio:.2f}:1 in dark')

    def test_body_text_reads_on_a_dark_card(self):
        dark = _dark_vars()
        card = hex_to_rgb(RAISED)
        for shade in (500, 600, 700, 800, 900):
            ratio = contrast(_rgb(dark[f'tx-gray-{shade}']), card)
            self.assertGreaterEqual(ratio, 4.5, f'text-gray-{shade}: {ratio:.2f}:1')

    def test_money_and_alert_text_reads_on_a_dark_card(self):
        dark = _dark_vars()
        card = hex_to_rgb(RAISED)
        for fam in ('green', 'red', 'amber', 'blue'):
            for shade in (600, 700, 800):
                ratio = contrast(_rgb(dark[f'tx-{fam}-{shade}']), card)
                self.assertGreaterEqual(ratio, 4.5, f'text-{fam}-{shade}: {ratio:.2f}:1')

    def test_saturated_buttons_keep_white_text(self):
        """`bg-red-600 text-white` must still be a red button in the dark."""
        dark = _dark_vars()
        for fam in ('red', 'green', 'blue'):
            self.assertEqual(dark[f'c-{fam}-600'],
                             '{} {} {}'.format(*hex_to_rgb(palette.TAILWIND[fam][6])))

    def test_any_shop_colour_survives_the_dark(self):
        # Default blue, navy, near-black, red, teal, yellow, near-white.
        card = hex_to_rgb(RAISED)
        for brand in ('#3b82f6', '#1e3a8a', '#111111', '#000000', '#b91c1c',
                      '#0f766e', '#facc15', '#f5f5f5'):
            bg, tx = brand_shades_dark(brand)
            fill = _rgb(bg[600])
            link = _rgb(tx[600])
            self.assertGreaterEqual(contrast(fill, card), 3.0,
                                    f'{brand} button vanishes on the card')
            self.assertGreaterEqual(contrast(link, card), 4.5,
                                    f'{brand} link text unreadable on the card')

    def test_a_dark_brand_keeps_white_button_text(self):
        for brand in ('#1e3a8a', '#000000', '#b91c1c', '#0f766e'):
            bg, _ = brand_shades_dark(brand)
            self.assertGreaterEqual(contrast(_rgb(bg[600]), WHITE), 4.5, brand)

    def test_malformed_colour_gives_nothing(self):
        self.assertEqual(brand_shades_dark(''), ({}, {}))
        self.assertEqual(brand_shades_dark('red'), ({}, {}))


class BrandCssDarkTests(SimpleTestCase):
    def _render(self, color):
        class Tenant:
            branding_enabled = True
            brand_color = color

        class Req:
            tenant = Tenant()
            csp_nonce = 'n0nce'
        return Template('{% load branding_tags %}{% tenant_brand_css %}').render(
            Context({'request': Req()}))

    def test_emits_light_dark_and_system_rules_in_one_nonced_block(self):
        html = self._render('#1e3a8a')
        self.assertEqual(html.count('<style'), 1)
        self.assertIn('nonce="n0nce"', html)
        self.assertIn(':root { --brand-50:', html)
        self.assertIn(':root[data-theme="dark"] { --brand-50:', html)
        self.assertIn('@media (prefers-color-scheme: dark) { :root[data-theme="system"] {', html)
        self.assertIn('--brand-tx-600:', html)
        self.assertNotIn('{{', html)

    def test_nothing_without_a_colour(self):
        self.assertEqual(self._render(''), '')


class ThemeSwitchTests(SimpleTestCase):
    def _theme(self, cookie=None):
        request = RequestFactory().get('/')
        if cookie is not None:
            request.COOKIES['rs_theme'] = cookie
        return ui_theme(request)['ui_theme']

    def test_light_is_the_default(self):
        self.assertEqual(self._theme(), 'light')

    def test_known_values_pass_through(self):
        for value in ('light', 'dark', 'system'):
            self.assertEqual(self._theme(value), value)

    def test_anything_else_is_light(self):
        for value in ('', 'DARK', 'dark"><script>', 'auto'):
            self.assertEqual(self._theme(value), 'light')

    def test_only_the_staff_shells_carry_the_attribute(self):
        carriers = sorted(
            str(p.relative_to(TEMPLATES)) for p in TEMPLATES.rglob('*.html')
            if 'data-theme="{{ ui_theme' in p.read_text())
        self.assertEqual(carriers, ['base_app.html', 'base_auth.html'])

    def test_never_dark_surfaces_do_not_read_the_switch(self):
        for rel in ('landing.html', 'saas/base_public.html',
                    'customer_portal/base_customer.html', 'emails/base.html'):
            path = TEMPLATES / rel
            if path.exists():
                self.assertNotIn('data-theme', path.read_text(), rel)

    def test_switch_uses_delegation_not_onclick(self):
        shell = (TEMPLATES / 'base_app.html').read_text()
        self.assertIn("js/theme.js", shell)
        for button in re.findall(r'<button[^>]*data-theme-choice[^>]*>', shell):
            self.assertNotIn('onclick', button)
        self.assertEqual(len(re.findall(r'data-theme-choice="(light|dark|system)"', shell)), 3)


class ThemeRenderTests(TestCase):
    """The attribute reaches a real page, and never reaches a public one."""

    def test_login_page_follows_the_cookie(self):
        self.client.cookies['rs_theme'] = 'dark'
        html = self.client.get('/login/').content.decode()
        self.assertIn('<html lang="en" data-theme="dark">', html)

    def test_login_page_is_light_without_a_cookie(self):
        html = self.client.get('/login/').content.decode()
        self.assertIn('<html lang="en" data-theme="light">', html)

    def test_landing_page_ignores_the_cookie(self):
        self.client.cookies['rs_theme'] = 'dark'
        html = self.client.get('/').content.decode()
        self.assertNotIn('data-theme="dark"', html)


class HandWrittenCssTests(SimpleTestCase):
    """CSS the palette cannot reach.

    The palette flips every Tailwind utility, but a stylesheet linked AFTER
    app.css, or a `<style>` block in a template, out-ranks it with whatever
    literal it carries. On 2026-10-15 the Edit Repair form's own stylesheet
    painted its fields `background-color: white`, which in the dark meant light
    field text on a white box. The rule: hand-written staff CSS uses the
    palette variables (`--c-*`, `--tx-*`, `--surface-field`), never a literal.
    """

    LITERAL = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:white|black)\b')
    NEVER_DARK = ('customer_portal', 'admin', 'emails', 'saas/base_public',
                  'landing', 'billing/public_')
    # Templates whose <style> block has been converted; add one when you
    # convert it, so it cannot drift back to literals.
    CONVERTED_STYLE_BLOCKS = (
        'technician_portal/update_profile.html',
    )

    @staticmethod
    def _strip_comments(css):
        return re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    def _staff_stylesheets(self):
        """Every static stylesheet a staff page links besides app.css + vendor."""
        found = set()
        for path in TEMPLATES.rglob('*.html'):
            rel = path.relative_to(TEMPLATES).as_posix()
            if rel.startswith(self.NEVER_DARK):
                continue
            for href in re.findall(r"\{%\s*static\s+'(css/[^']+\.css)'\s*%\}", path.read_text()):
                if href == 'css/app.css' or href.startswith('css/vendor/'):
                    continue
                found.add(href)
        return sorted(found)

    def test_field_well_token_exists_in_both_themes(self):
        css = APP_CSS.read_text()
        values = set(re.findall(r'--surface-field:\s*([^;]+);', css))
        # the minifier shortens #ffffff; either spelling is the light well
        self.assertTrue(values & {'#fff', '#ffffff'}, values)
        self.assertIn(palette.FIELD, values)

    def test_staff_stylesheets_carry_no_colour_literals(self):
        sheets = self._staff_stylesheets()
        self.assertIn('css/components/form-fields.css', sheets)
        for href in sheets:
            body = self._strip_comments((ROOT / 'static' / href).read_text())
            self.assertEqual(
                self.LITERAL.findall(body), [],
                f'static/{href} is linked after app.css and carries a colour literal; '
                'use rgb(var(--c-…)) / rgb(var(--tx-…)) / var(--surface-field).')

    def test_converted_style_blocks_stay_on_tokens(self):
        for rel in self.CONVERTED_STYLE_BLOCKS:
            html = (TEMPLATES / rel).read_text()
            blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, flags=re.S)
            self.assertTrue(blocks, rel)
            for block in blocks:
                self.assertEqual(self.LITERAL.findall(self._strip_comments(block)), [],
                                 f'{rel}: <style> block went back to a colour literal')

    def test_toast_stacks_above_every_modal(self):
        """A toast from a dialog's own Save button must not render behind it."""
        css = APP_CSS.read_text()
        m = re.search(r'\.toast-stack\{[^}]*z-index:\s*(\d+)', css)
        self.assertIsNotNone(m, '.toast-stack has no z-index in the build')
        toast_z = int(m.group(1))
        highest = 0
        for path in TEMPLATES.rglob('*.html'):
            for block in re.findall(r'<style[^>]*>(.*?)</style>', path.read_text(), flags=re.S):
                for z in re.findall(r'z-index:\s*(\d+)', block):
                    highest = max(highest, int(z))
        self.assertGreater(toast_z, highest,
                           f'.toast-stack z-index {toast_z} is not above a template modal at {highest}')
