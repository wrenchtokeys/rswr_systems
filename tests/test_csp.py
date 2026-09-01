"""Content-Security-Policy (UI_MAGIC_SESSIONS S18).

Most of this file is `SimpleTestCase` on purpose. Only `ResponseHeaderTests`
needs a database, because only it renders a real view — the rest read templates
off disk, build the policy, or post to an endpoint that must never touch the
DB. 37 tests in ~0.5s instead of paying 204 migrations for markup assertions.

Everything here guards a failure that is silent in exactly one direction. A CSP
that is too LOOSE breaks nothing and shows nothing — it just quietly stops being
a defence, which is what happens the first time someone adds an inline
`<script>` without a nonce, or re-adds a third-party host. A CSP that is too
TIGHT does break the page, but under report-only it does not, so the breakage
surfaces on the day someone flips the header to enforcing.

So the tests come in three groups:

1. **The header exists and says what we think it says** — on real responses,
   through the real middleware, not by reading the settings module back.
2. **The nonce is real** — present, per-response, and actually on every inline
   block the templates ship. A nonce in the header with no nonce in the markup
   is worse than no policy at all: it silently disables `'unsafe-inline'`.
3. **The staging is deliberate** — report-only stays report-only while inline
   `on*` handlers exist, because CLAUDE.md requires them on optimistic rows.
   This test is the tripwire on somebody "finishing" S18 without doing S18b.
"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from common import csp_views
from common.csp_middleware import build_policy

TEMPLATE_ROOT = Path(settings.BASE_DIR) / 'templates'

# Email templates are rendered into a message body, never served over HTTP.
# A nonce there would be meaningless at best and leak a per-request secret into
# somebody's inbox at worst.
EMAIL_DIR = TEMPLATE_ROOT / 'emails'

INLINE_SCRIPT = re.compile(r'<script(?![^>]*\ssrc=)[^>]*>')
STYLE = re.compile(r'<style[^>]*>')
NONCE_ATTR = 'nonce="{{ csp_nonce }}"'


def _served_templates():
    """Every template that actually reaches a browser."""
    return [p for p in sorted(TEMPLATE_ROOT.rglob('*.html'))
            if EMAIL_DIR not in p.parents]


def _directives(header_value):
    """The header parsed into {name: [values]}."""
    out = {}
    for chunk in header_value.split(';'):
        parts = chunk.strip().split()
        if parts:
            out[parts[0]] = parts[1:]
    return out


class PolicyContentTests(SimpleTestCase):
    """What the policy says, independent of any request."""

    def test_the_dangerous_directives_are_locked(self):
        directives = _directives('; '.join(build_policy('abc')))

        self.assertEqual(directives['default-src'], ["'self'"])
        self.assertEqual(directives['object-src'], ["'none'"])
        self.assertEqual(directives['base-uri'], ["'self'"])
        self.assertEqual(directives['form-action'], ["'self'"])
        self.assertEqual(directives['frame-ancestors'], ["'none'"])

    def test_no_script_directive_is_ever_unsafe(self):
        """The whole point. A nonce is ignored the moment 'unsafe-inline'
        lands beside it, so this is the test that keeps the policy a policy."""
        directives = _directives('; '.join(build_policy('abc')))
        for name, values in directives.items():
            if name.startswith('script-src') or name == 'default-src':
                self.assertNotIn("'unsafe-inline'", values, name)
                self.assertNotIn("'unsafe-eval'", values, name)
        self.assertNotIn("'unsafe-eval'", '; '.join(build_policy('abc')))

    def test_style_elements_stay_strict_and_only_attributes_are_relaxed(self):
        """The one relaxation in the policy, pinned so it stays the one.

        `style="..."` cannot carry a nonce and there are 226 of them, many
        dynamic — so style-src-attr is 'unsafe-inline' on purpose. If that ever
        leaks into style-src-elem, every un-nonced <style> block goes silently
        unguarded and nothing else would notice.
        """
        directives = _directives('; '.join(build_policy('abc')))
        self.assertEqual(directives['style-src-attr'], ["'unsafe-inline'"])
        self.assertNotIn("'unsafe-inline'", directives['style-src-elem'])
        self.assertNotIn("'unsafe-inline'", directives['style-src'])

    def test_script_attributes_are_closed_so_the_report_names_them(self):
        """script-src-attr 'none' is what makes an `on*` handler show up as
        its own directive instead of as an anonymous script-src violation."""
        directives = _directives('; '.join(build_policy('abc')))
        self.assertEqual(directives['script-src-attr'], ["'none'"])

    def test_the_csp2_fallbacks_are_still_present(self):
        """A browser without -elem/-attr support falls back to these. Drop them
        and the policy silently stops applying there rather than failing."""
        directives = _directives('; '.join(build_policy('abc')))
        self.assertIn('script-src', directives)
        self.assertIn('style-src', directives)

    @override_settings(MEDIA_URL='/media/', STATIC_URL='/static/')
    def test_the_only_third_party_host_is_turnstile(self):
        """S1's dividend. If this fails, a CDN came back — see CLAUDE.md.

        Pinned to the same-origin asset config so the assertion is about the
        policy rather than about whichever bucket the test run happened to
        have configured.
        """
        hosts = re.findall(r'https?://[^\s;]+', '; '.join(build_policy('abc')))
        self.assertEqual(set(hosts), {'https://challenges.cloudflare.com'})

    def test_turnstile_gets_both_script_and_frame(self):
        """api.js is a script; the widget it renders is an iframe. Both or neither."""
        directives = _directives('; '.join(build_policy('abc')))
        self.assertIn('https://challenges.cloudflare.com', directives['script-src'])
        self.assertIn('https://challenges.cloudflare.com', directives['script-src-elem'])
        self.assertIn('https://challenges.cloudflare.com', directives['frame-src'])

    def test_the_nonce_reaches_every_element_directive(self):
        directives = _directives('; '.join(build_policy('THE-NONCE')))
        for name in ('script-src', 'style-src', 'script-src-elem', 'style-src-elem'):
            self.assertIn("'nonce-THE-NONCE'", directives[name], name)

    def test_canvas_images_survive(self):
        """image_compress / photo_tap_crop / multi_break hand blobs to an <img>.

        `img-src 'self'` alone passes every test in CI and breaks photo upload
        preview on a phone, which is the one place it is used.
        """
        directives = _directives('; '.join(build_policy('abc')))
        self.assertIn('data:', directives['img-src'])
        self.assertIn('blob:', directives['img-src'])

    @override_settings(MEDIA_URL='https://bucket.s3.amazonaws.com/media/')
    def test_img_src_follows_media_url_to_s3(self):
        """USE_S3 moves repair photos to another origin. img-src has to follow.

        Nothing else in the suite would catch this: MEDIA_URL is `/media/` in
        every test run and only becomes an S3 host on a deployed environment.
        """
        directives = _directives('; '.join(build_policy('abc')))
        self.assertIn('https://bucket.s3.amazonaws.com', directives['img-src'])

    @override_settings(MEDIA_URL='/media/', STATIC_URL='/static/')
    def test_same_origin_assets_add_no_host(self):
        directives = _directives('; '.join(build_policy('abc')))
        self.assertEqual(directives['img-src'], ["'self'", 'data:', 'blob:'])
        self.assertEqual(directives['font-src'], ["'self'"])

    @override_settings(STATIC_URL='https://cdn.example.com/static/')
    def test_a_static_cdn_reaches_every_directive_that_would_break(self):
        """STATIC_URL is read from the environment. Switch it to a CDN and a
        policy hardcoded to 'self' takes out every script, stylesheet and font
        in the app — on the deployed environment only, where nothing is
        watching. Nobody has done this; the point is that they can."""
        directives = _directives('; '.join(build_policy('abc')))
        for name in ('script-src', 'style-src', 'script-src-elem',
                     'style-src-elem', 'font-src', 'img-src'):
            self.assertIn('https://cdn.example.com', directives[name], name)

    @override_settings(STATIC_URL='https://cdn.example.com/static/')
    def test_a_static_cdn_does_not_loosen_the_script_attribute_rule(self):
        directives = _directives('; '.join(build_policy('abc')))
        self.assertEqual(directives['script-src-attr'], ["'none'"])


class ResponseHeaderTests(TestCase):
    """The header on real responses, through the real middleware."""

    def test_html_response_carries_the_report_only_header(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Content-Security-Policy-Report-Only', response)
        self.assertNotIn(
            'Content-Security-Policy', response,
            'enforcing header shipped while inline on* handlers still exist',
        )

    def test_the_report_endpoint_is_advertised(self):
        response = self.client.get('/')
        self.assertIn('report-uri /csp-report/',
                      response['Content-Security-Policy-Report-Only'])

    def test_report_to_only_ships_over_https(self):
        """Chrome ignores report-uri as soon as report-to appears, and its
        Reporting API will not deliver over plain HTTP — so sending both on an
        http:// dev server means Chrome delivers NOTHING and the endpoint looks
        broken. Verified against real Chrome, not read off a spec."""
        insecure = self.client.get('/')
        self.assertNotIn('report-to', insecure['Content-Security-Policy-Report-Only'])
        self.assertNotIn('Reporting-Endpoints', insecure)

        secure = self.client.get('/', secure=True)
        header = secure['Content-Security-Policy-Report-Only']
        self.assertIn('report-to csp-endpoint', header)
        self.assertIn('report-uri /csp-report/', header)  # Firefox and Safari
        self.assertIn('csp-endpoint="/csp-report/"', secure['Reporting-Endpoints'])

    def test_the_nonce_in_the_header_is_the_nonce_in_the_markup(self):
        """The two halves are set in different files; nothing else pairs them."""
        response = self.client.get('/')
        header = response['Content-Security-Policy-Report-Only']
        nonce = re.search(r"'nonce-([^']+)'", header).group(1)
        self.assertIn(f'nonce="{nonce}"', response.content.decode())

    def test_the_nonce_is_not_reused_between_responses(self):
        """A nonce that repeats is a static token an injected script can read."""
        first = self.client.get('/')['Content-Security-Policy-Report-Only']
        second = self.client.get('/')['Content-Security-Policy-Report-Only']
        self.assertNotEqual(
            re.search(r"'nonce-([^']+)'", first).group(1),
            re.search(r"'nonce-([^']+)'", second).group(1),
        )

    def test_non_html_responses_are_left_alone(self):
        response = self.client.get('/health/')
        self.assertNotIn('Content-Security-Policy-Report-Only', response)

    @override_settings(CSP_ENABLED=False)
    def test_the_kill_switch_works(self):
        """One env var has to be able to turn this off on a live environment."""
        response = self.client.get('/')
        self.assertNotIn('Content-Security-Policy-Report-Only', response)


class TemplateNonceCoverageTests(SimpleTestCase):
    """Every inline block a browser gets must carry the nonce.

    Read from disk rather than from a rendered page: most of these templates
    need a logged-in user with a tenant to render at all, and the failure this
    guards is somebody adding a 56th inline `<script>` without the attribute.
    """

    def test_every_inline_script_has_a_nonce(self):
        missing = []
        for path in _served_templates():
            for tag in INLINE_SCRIPT.findall(path.read_text()):
                if 'nonce=' not in tag:
                    missing.append(f'{path.relative_to(TEMPLATE_ROOT)}: {tag}')
        self.assertEqual(missing, [], f'inline <script> without a nonce:\n' + '\n'.join(missing))

    def test_every_inline_style_has_a_nonce(self):
        missing = []
        for path in _served_templates():
            for tag in STYLE.findall(path.read_text()):
                if 'nonce=' not in tag:
                    missing.append(f'{path.relative_to(TEMPLATE_ROOT)}: {tag}')
        self.assertEqual(missing, [], f'inline <style> without a nonce:\n' + '\n'.join(missing))

    def test_the_nonce_is_spelled_the_one_way_the_context_processor_provides(self):
        """`{{ request.csp_nonce }}` also works — until a fragment renders
        without a request. One spelling, so there is one thing to grep."""
        wrong = []
        for path in _served_templates():
            for tag in INLINE_SCRIPT.findall(path.read_text()) + STYLE.findall(path.read_text()):
                if 'nonce=' in tag and NONCE_ATTR not in tag:
                    wrong.append(f'{path.relative_to(TEMPLATE_ROOT)}: {tag}')
        self.assertEqual(wrong, [], f'unexpected nonce spelling:\n' + '\n'.join(wrong))

    def test_email_templates_never_get_a_nonce(self):
        """An email is not an HTTP response. A nonce there is a leaked secret."""
        for path in sorted(EMAIL_DIR.rglob('*.html')):
            self.assertNotIn('csp_nonce', path.read_text(),
                             f'{path.relative_to(TEMPLATE_ROOT)} carries a CSP nonce')

    def test_external_scripts_are_not_given_a_nonce(self):
        """They are covered by 'self'. A nonce on them is noise that hides the
        one place a nonce means something."""
        offenders = []
        for path in _served_templates():
            for tag in re.findall(r'<script[^>]*\ssrc=[^>]*>', path.read_text()):
                if 'nonce=' in tag:
                    offenders.append(f'{path.relative_to(TEMPLATE_ROOT)}: {tag}')
        self.assertEqual(offenders, [])


class PythonEmittedStyleTests(SimpleTestCase):
    """The <style> block no template sweep can reach.

    `{% tenant_brand_css %}` builds its block in Python and only renders it for
    a shop that HAS a brand colour — so a strict style-src would have dropped
    every branded shop back to the default palette while every unbranded dev
    and test shop stayed perfectly green. Nothing in the template-coverage
    tests above can see this one.
    """

    def test_the_branding_block_carries_the_request_nonce(self):
        from django.template import Context, Template

        class Req:
            csp_nonce = 'BRAND-NONCE'
            branding_enabled = True

        request = Req()
        request.tenant = self._branded_tenant()
        html = Template('{% load branding_tags %}{% tenant_brand_css %}').render(
            Context({'request': request})
        )
        self.assertIn('--brand-500:', html)
        self.assertIn('nonce="BRAND-NONCE"', html)

    def test_it_does_not_crash_without_a_nonce(self):
        """Rendered outside a request (management commands, previews) it must
        still produce a block rather than raise."""
        from django.template import Context, Template

        class Req:
            branding_enabled = True

        request = Req()
        request.tenant = self._branded_tenant()
        html = Template('{% load branding_tags %}{% tenant_brand_css %}').render(
            Context({'request': request})
        )
        self.assertIn('nonce=""', html)

    def _branded_tenant(self):
        class Tenant:
            branding_enabled = True
            brand_color = '#3b82f6'
        return Tenant()


class ReportEndpointTests(SimpleTestCase):
    """The endpoint exists so report-only is worth shipping at all.

    `SimpleTestCase` is not a speed trick here, it is the assertion: it raises
    on any database query, and this endpoint must never make one. It is
    unauthenticated, CSRF-exempt, and anybody on the internet can POST to it in
    a loop — a DB round-trip on that path is a denial-of-service lever handed
    out for free. If a later change adds a query, this suite goes red.
    """

    def setUp(self):
        self.url = reverse('csp_report')
        # The dedupe window is per-process and outlives a test method.
        csp_views._seen.clear()

    def _post(self, payload, content_type='application/csp-report'):
        return self.client.post(self.url, data=json.dumps(payload),
                                content_type=content_type)

    def test_a_report_uri_payload_is_accepted(self):
        response = self._post({'csp-report': {
            'document-uri': 'https://rssystems.io/tech/',
            'violated-directive': 'script-src',
            'blocked-uri': 'inline',
        }})
        self.assertEqual(response.status_code, 204)

    def test_a_report_to_payload_is_accepted(self):
        """Chrome posts a LIST under application/reports+json, with camelCase
        keys. Handling only the report-uri shape means Chrome reports vanish."""
        response = self._post([{
            'type': 'csp-violation',
            'body': {
                'documentURL': 'https://rssystems.io/tech/',
                'effectiveDirective': 'script-src-elem',
                'blockedURL': 'inline',
            },
        }], content_type='application/reports+json')
        self.assertEqual(response.status_code, 204)

    def test_garbage_does_not_raise(self):
        response = self.client.post(self.url, data='not json',
                                    content_type='application/csp-report')
        self.assertEqual(response.status_code, 400)

    def test_it_needs_no_csrf_token_and_no_login(self):
        """The browser posts this, not a form. Enforced by posting from a
        client that has never seen a CSRF cookie."""
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post(self.url, data=json.dumps({'csp-report': {}}),
                               content_type='application/csp-report')
        self.assertEqual(response.status_code, 204)

    def test_extension_noise_is_dropped(self):
        with self.assertLogs('csp', level='WARNING') as logs:
            self._post({'csp-report': {'blocked-uri': 'https://evil.example/x.js',
                                       'violated-directive': 'script-src'}})
            self._post({'csp-report': {'blocked-uri': 'chrome-extension://abc/x.js',
                                       'violated-directive': 'script-src'}})
        self.assertEqual(len(logs.output), 1)
        self.assertIn('evil.example', logs.output[0])

    def test_the_same_violation_is_logged_once_per_window(self):
        """Without this, ~195 known inline handlers x every page load x every
        visitor bury the violations nobody has written down yet."""
        report = {'csp-report': {'blocked-uri': 'inline',
                                 'effective-directive': 'script-src-attr',
                                 'source-file': 'https://rssystems.io/tech/jobs/',
                                 'line-number': 157}}
        with self.assertLogs('csp', level='WARNING') as logs:
            self._post(report)
            for _ in range(20):
                self._post(report)
        self.assertEqual(len(logs.output), 1)

    def test_a_different_violation_still_gets_through(self):
        """Dedupe on the violation, not on the endpoint — otherwise the first
        report of a page silences every later one."""
        with self.assertLogs('csp', level='WARNING') as logs:
            self._post({'csp-report': {'blocked-uri': 'inline',
                                       'effective-directive': 'script-src-attr',
                                       'line-number': 1}})
            self._post({'csp-report': {'blocked-uri': 'inline',
                                       'effective-directive': 'style-src-elem',
                                       'line-number': 2}})
        self.assertEqual(len(logs.output), 2)

    def test_a_new_violation_still_lands_once_the_window_is_full(self):
        """The dedupe cap must never be the reason an unseen violation is
        dropped — that is the one thing this endpoint exists to surface."""
        for i in range(csp_views.DEDUPE_MAX_KEYS + 50):
            self._post({'csp-report': {'blocked-uri': f'https://x.example/{i}',
                                       'effective-directive': 'script-src-elem'}})
        self.assertLessEqual(len(csp_views._seen), csp_views.DEDUPE_MAX_KEYS)
        with self.assertLogs('csp', level='WARNING') as logs:
            self._post({'csp-report': {'blocked-uri': 'https://brand-new.example/x.js',
                                       'effective-directive': 'script-src-elem'}})
        self.assertEqual(len(logs.output), 1)
        self.assertIn('brand-new.example', logs.output[0])

    def test_a_report_cannot_flood_a_log_line(self):
        """The payload is attacker-controlled: anyone can POST here."""
        with self.assertLogs('csp', level='WARNING') as logs:
            self._post({'csp-report': {'blocked-uri': 'https://x.example/' + 'A' * 5000,
                                       'violated-directive': 'script-src'}})
        self.assertLess(len(logs.output[0]), 2000)


class StagingTests(SimpleTestCase):
    """S18 ships report-only ON PURPOSE. This is the tripwire on forgetting why."""

    def test_report_only_while_inline_handlers_remain(self):
        """CLAUDE.md requires inline `onclick` on optimistic rows, because
        Optimistic.rollback restores innerHTML and drops bound listeners. A
        nonce cannot cover an inline handler, so enforcing the policy today
        breaks every optimistic row in the app.

        When S18b has migrated the handlers to delegated listeners this test
        goes green on its own and CSP_REPORT_ONLY can default to False.
        """
        handler = re.compile(r'\son[a-z]+\s*=\s*"')
        remaining = sum(len(handler.findall(p.read_text())) for p in _served_templates())

        if remaining:
            self.assertTrue(
                settings.CSP_REPORT_ONLY,
                f'{remaining} inline on* handlers still in the templates — '
                'the policy cannot be enforced until S18b removes them',
            )
