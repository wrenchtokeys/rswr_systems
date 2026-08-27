"""The Tailwind build's shape: source out of the served tree, font in the build.

Until S17 the Tailwind SOURCE lived at `static/css/src/input.css`, so
collectstatic collected it alongside the compiled `static/css/app.css` and
served it publicly. Worse, a relative `url()` then resolved against two
different directories — `css/` for the build, `css/src/` for the source — so
ManifestStaticFilesStorage hard-failed the deploy with

    ValueError: The file 'css/fonts/inter-variable-latin.woff2' could not be
    found with <ManifestStaticFilesStorage>

That is why the Inter `@font-face` spent two sessions inlined in
`head_assets.html`. The source now lives in `assets/css/`, which collectstatic
never walks, and the `@font-face` is back in the stylesheet where it belongs.

These assertions exist so the next person who "tidies" the source back under
`static/` finds out here rather than on a deploy.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

BASE_DIR = Path(settings.BASE_DIR)
INPUT_CSS = BASE_DIR / 'assets' / 'css' / 'input.css'
APP_CSS = BASE_DIR / 'static' / 'css' / 'app.css'
BUILD_SCRIPT = BASE_DIR / 'scripts' / 'build_css.sh'
HEAD_ASSETS = BASE_DIR / 'templates' / 'includes' / 'head_assets.html'
FONT = BASE_DIR / 'static' / 'fonts' / 'inter-variable-latin.woff2'


class TailwindSourceIsNotServedTests(TestCase):

    def test_the_source_lives_outside_static(self):
        self.assertTrue(INPUT_CSS.exists(), f'{INPUT_CSS} is the Tailwind source')

    def test_no_tailwind_source_under_static(self):
        """`STATICFILES_DIRS` is `static/`, so anything here is public.

        The directives are the tell: a file that says `@tailwind` or
        `@layer components` is uncompiled source, whatever it is named.
        """
        static_dir = BASE_DIR / 'static'
        offenders = []
        for css in static_dir.rglob('*.css'):
            if 'vendor' in css.parts:
                continue
            head = css.read_text(errors='ignore')[:4000]
            if '@tailwind ' in head:
                offenders.append(str(css.relative_to(BASE_DIR)))
        self.assertEqual(
            offenders, [],
            'uncompiled Tailwind source under static/ — collectstatic will '
            'serve it, and a relative url() in it breaks manifest storage. '
            'The source belongs in assets/css/.')

    def test_build_script_reads_the_source_from_assets(self):
        script = BUILD_SCRIPT.read_text()
        self.assertIn('-i assets/css/input.css', script)
        self.assertNotIn('static/css/src', script)


class FontFaceShipsInTheStylesheetTests(TestCase):

    def test_input_css_declares_the_font(self):
        self.assertIn('@font-face', INPUT_CSS.read_text())

    def test_compiled_css_carries_a_relative_font_url(self):
        """`../fonts/…` is relative to the BUILT file (static/css/app.css).

        Manifest storage rewrites it to the hashed name at collectstatic time;
        that rewrite is the whole reason the path has to resolve from exactly
        one directory.
        """
        css = APP_CSS.read_text().replace(' ', '')
        self.assertIn('@font-face', css,
                      'the Inter @font-face is missing from app.css — run '
                      './scripts/build_css.sh and commit the result')
        self.assertIn('url(../fonts/inter-variable-latin.woff2)', css)

    def test_the_font_file_is_actually_there(self):
        """A url() that resolves to nothing hard-fails collectstatic."""
        self.assertTrue(FONT.exists(), f'{FONT} — see scripts/vendor_assets.sh')

    def test_every_url_in_app_css_resolves_to_a_real_file(self):
        """This is the deploy failure, expressed as a unit test.

        ManifestStaticFilesStorage rewrites every `url()` in a collected
        stylesheet to the hashed filename, and raises if the referenced file
        is not there. It resolves the path against the collected stylesheet's
        OWN directory — `css/` — so this walks the same way. `data:` and
        absolute URLs are left alone by the post-processor, so they are here
        too.
        """
        css_dir = APP_CSS.parent
        static_dir = BASE_DIR / 'static'
        missing = []
        for raw in re.findall(r'url\(\s*([^)]+?)\s*\)', APP_CSS.read_text()):
            ref = raw.strip('\'"')
            if ref.startswith(('data:', 'http:', 'https:', '//', '#')):
                continue
            target = (css_dir / ref.split('?')[0].split('#')[0]).resolve()
            if not target.exists():
                missing.append(f'{ref} -> {target}')
            elif static_dir.resolve() not in target.parents:
                missing.append(f'{ref} escapes static/ -> {target}')
        self.assertEqual(
            missing, [],
            'collectstatic under manifest storage will raise ValueError on '
            'these: a url() in app.css is resolved against static/css/.')

    def test_head_assets_no_longer_inlines_the_font(self):
        """Two @font-face rules for one family is a second thing to keep in
        sync, and the inline copy was only ever a workaround for the path
        collision this session removed. The preload hint stays."""
        html = HEAD_ASSETS.read_text()
        # The rule, not the word — the template's comment names @font-face to
        # say where it went, and that mention should not fail this.
        self.assertIsNone(
            re.search(r'@font-face\s*\{', html),
            'head_assets.html declares an @font-face again — it belongs in '
            'assets/css/input.css, which ships compiled into app.css')
        self.assertIn("rel=\"preload\"", html)
        self.assertIn('inter-variable-latin.woff2', html)
