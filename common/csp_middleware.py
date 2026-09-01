"""
Content-Security-Policy middleware — S18 of docs/strategy/UI_MAGIC_SESSIONS.md.

Phase 1 removed every third-party asset host and S17 removed the last inline
`<style>` that had to carry a font declaration, so a real policy is finally
possible. The allowlist is genuinely small: ourselves, plus Cloudflare Turnstile
on the signup captcha. Stripe is server-side here — no template loads its SDK.

WHY THIS SHIPS REPORT-ONLY FIRST
--------------------------------
`script-src` cannot drop `'unsafe-inline'` yet. CLAUDE.md requires optimistic
rows to use inline `onclick` rather than `addEventListener`, because
`Optimistic.rollback` restores a row's saved `innerHTML` and throws away any
listener bound to the old nodes. A nonce does NOT cover inline event handlers,
so the ~173 `on*` attributes in the templates are in direct conflict with a
strict `script-src` and have to be migrated to delegated listeners first (S18b).

Until then `Content-Security-Policy-Report-Only` is the honest header: it breaks
nothing and tells us exactly what is left. Flip `CSP_REPORT_ONLY = False` only
when the report endpoint has gone quiet on a real production sample.

A NONCE IS NOT ADDITIVE
-----------------------
Once a nonce appears in `script-src`, browsers IGNORE `'unsafe-inline'` in that
directive. That is the point — it is what makes the report meaningful — but it
also means the report-only run WILL flag every `on*` handler and every
`javascript:` href. Those are expected findings, not surprises; see S18b.

AND A NONCE CANNOT COVER AN ATTRIBUTE
-------------------------------------
`style="..."` is an inline style and a strict `style-src` blocks it just as it
blocks a `<style>` block — the nonce is no help, because there is nowhere on an
attribute to put one. The first real Chrome run against this policy reported
that on the landing page alone; there are 226 of them across the templates and
plenty are dynamic (`style="width: {{ pct }}%"`). Hence the -elem/-attr split
below: the elements stay strict, the style attributes are allowed on purpose,
and the script attributes stay closed so the report still names them.
"""
import base64
import secrets
from urllib.parse import urlsplit

from django.conf import settings

# Only HTML carries scripts and styles. A JSON API response or an S3 redirect
# gains nothing from the header and would just pay for the bytes.
HTML_CONTENT_TYPES = ('text/html', 'application/xhtml+xml')

# Cloudflare Turnstile (the signup captcha) is the one third-party script left
# in the templates. It loads api.js and then renders the widget in an iframe of
# its own, so it needs both script-src and frame-src.
TURNSTILE_ORIGIN = 'https://challenges.cloudflare.com'


def _origin(url):
    """The scheme://host of an absolute URL, or None for a relative one.

    MEDIA_URL is `/media/` on a filesystem deploy and
    `https://<bucket>.s3.amazonaws.com/media/` when USE_S3 is on, so img-src
    has to be derived at runtime rather than written down. Getting this wrong
    does not fail a test — it fails repair photos on production only.
    """
    if not url:
        return None
    parts = urlsplit(str(url))
    if not parts.scheme or not parts.netloc:
        return None
    return f'{parts.scheme}://{parts.netloc}'


def build_policy(nonce):
    """The policy as a list of directives, given this request's nonce.

    Kept separate from the middleware so a test can assert on the directives
    without building a request/response pair.
    """
    media_origin = _origin(getattr(settings, 'MEDIA_URL', None))
    # STATIC_URL is `/static/` today but is read from the environment, so a CDN
    # can be switched on without touching this file. Derive it for the same
    # reason as MEDIA_URL: the day someone does, the failure is every script,
    # stylesheet and font in the app, on production only.
    static_origin = _origin(getattr(settings, 'STATIC_URL', None))

    # data: and blob: are load-bearing, not laziness: image_compress.js,
    # photo_tap_crop.js and multi_break.js all draw to a canvas and hand the
    # result back to an <img> as an object URL before it is ever uploaded.
    img_src = ["'self'", 'data:', 'blob:']
    for origin in (media_origin, static_origin):
        if origin and origin not in img_src:
            img_src.append(origin)

    font_src = ["'self'"] + ([static_origin] if static_origin else [])
    script_src = ["'self'", f"'nonce-{nonce}'", TURNSTILE_ORIGIN]
    style_src = ["'self'", f"'nonce-{nonce}'"]
    if static_origin:
        script_src.append(static_origin)
        style_src.append(static_origin)

    directives = [
        ("default-src", ["'self'"]),
        ("base-uri", ["'self'"]),
        ("form-action", ["'self'"]),
        # No page here is meant to be framed, and X_FRAME_OPTIONS already says
        # DENY in production — this is the modern spelling of the same rule.
        ("frame-ancestors", ["'none'"]),
        ("object-src", ["'none'"]),
        ("img-src", img_src),
        ("font-src", font_src),
        ("connect-src", ["'self'"]),
        # The CSP2 spellings, for browsers that do not implement -elem/-attr.
        # Where both are understood these are ignored in favour of the pair
        # below; where they are not, this is the whole policy.
        ("script-src", script_src),
        ("style-src", style_src),
        # -elem covers <script>/<style>/<link>; -attr covers `on*` and `style=`
        # attributes. Splitting them is what makes the report readable: an
        # element violation is a bug, an attribute violation is known work.
        ("script-src-elem", script_src),
        ("style-src-elem", style_src),
        # The 195 inline `on*` handlers land here and nowhere else. 'none'
        # rather than a nonce because a nonce CANNOT cover an attribute — see
        # the module docstring and S18b.
        ("script-src-attr", ["'none'"]),
        # DELIBERATE, and the one relaxation in the policy. 226 `style="..."`
        # attributes are in the templates and many are genuinely dynamic
        # (`style="width: {{ pct }}%"`), so this is not a sweep anyone finishes.
        # The trade is defensible in a way `script-src-attr 'unsafe-inline'`
        # would not be: a style attribute cannot execute code. It can leak
        # through a crafted background-image URL, which is why connect-src and
        # img-src stay closed. Revisit if S18c ever clears the attributes.
        ("style-src-attr", ["'unsafe-inline'"]),
        ("frame-src", [TURNSTILE_ORIGIN]),
    ]
    return [f'{name} {" ".join(values)}' for name, values in directives]


class ContentSecurityPolicyMiddleware:
    """Mint a per-request nonce and attach the policy to HTML responses.

    Sits after WhiteNoise so static files short-circuit before we look at them,
    and before everything that can render a template. `request.csp_nonce` is set
    on the way IN, so error handlers and views that render early still have it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 128 bits, fresh per response. A nonce that repeats is not a nonce, so
        # nothing here may be cached or precomputed at startup.
        request.csp_nonce = base64.b64encode(secrets.token_bytes(16)).decode()

        response = self.get_response(request)

        if not self._applies_to(request, response):
            return response

        report_only = getattr(settings, 'CSP_REPORT_ONLY', True)
        header = (
            'Content-Security-Policy-Report-Only' if report_only
            else 'Content-Security-Policy'
        )
        if header in response:  # a view set its own; don't fight it
            return response

        directives = build_policy(request.csp_nonce)

        report_uri = getattr(settings, 'CSP_REPORT_URI', '')
        if report_uri:
            # report-uri is deprecated but is still the only thing Firefox and
            # Safari honour, so it always ships.
            directives.append(f'report-uri {report_uri}')

            # report-to is what Chrome honours — and the moment it is present
            # Chrome IGNORES report-uri entirely. The Reporting API also
            # refuses to deliver over plain HTTP, so sending both on a local
            # http:// dev server means Chrome delivers nothing at all and the
            # endpoint looks broken when it is fine. Verified against Chrome
            # by removing this pair and watching the reports arrive. Gate it on
            # the scheme: production gets report-to, dev keeps report-uri.
            if request.is_secure():
                directives.append('report-to csp-endpoint')
                response['Reporting-Endpoints'] = f'csp-endpoint="{report_uri}"'

        response[header] = '; '.join(directives)
        return response

    def _applies_to(self, request, response):
        if not getattr(settings, 'CSP_ENABLED', True):
            return False

        # Django's admin is not ours to make CSP-clean, and its own inline
        # scripts would drown out the signal we actually want from the report.
        # This also covers /admin/email-preview/, which serves an EMAIL shell
        # over HTTP — inline styles and all — and would otherwise report
        # violations against templates that are deliberately un-nonced.
        excluded = getattr(settings, 'CSP_EXCLUDE_PREFIXES', ('/admin/',))
        if request.path.startswith(tuple(excluded)):
            return False

        content_type = response.get('Content-Type', '').split(';')[0].strip()
        return content_type in HTML_CONTENT_TYPES
