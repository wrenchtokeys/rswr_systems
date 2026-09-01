"""
The CSP violation report endpoint — the whole point of shipping report-only.

A report-only policy that reports into a void tells you nothing, so this exists
before the policy does. It logs to the `csp` logger and answers 204; it stores
nothing and answers nothing back to the browser.

IT DEDUPLICATES, AND THAT IS NOT OPTIONAL. The report-only run flags all ~195
inline `on*` handlers, on every page load, for every visitor. Logging each one
would bury the violations we have not already written down — and production's
cache is a DatabaseCache, so a cache-based limiter would put a DB write on the
path of every one of them. The window is per-process and in-memory: it costs
nothing, and losing it on a restart is a cost of exactly one extra log line.
"""
import json
import logging
import threading
import time

from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger('csp')

# Browser extensions inject scripts into every page and every one of them is
# reported against OUR policy. This is the single largest source of noise in a
# public CSP endpoint and none of it is actionable.
EXTENSION_SCHEMES = (
    'chrome-extension', 'moz-extension', 'safari-extension',
    'safari-web-extension', 'webkit-masked-url', 'about',
)

# A report is attacker-controlled input posted by anyone who can reach the URL.
# Truncate every field before it reaches a log line.
MAX_FIELD = 300

# How long one distinct violation stays quiet after it has been logged once,
# and how many distinct violations we track. The cap is the backstop against
# someone posting unbounded junk to grow the dict.
DEDUPE_WINDOW_SECONDS = 600
DEDUPE_MAX_KEYS = 500

_seen = {}
_seen_lock = threading.Lock()


def _first_sighting(key):
    """True if this violation has not been logged inside the window."""
    now = time.monotonic()
    with _seen_lock:
        if len(_seen) >= DEDUPE_MAX_KEYS:
            for stale in [k for k, t in _seen.items()
                          if now - t > DEDUPE_WINDOW_SECONDS]:
                del _seen[stale]
            # Still full of live entries: evict the oldest rather than refuse.
            # Refusing would silently drop the violations nobody has seen yet,
            # which is the one thing this endpoint exists to surface — the cost
            # of evicting is a repeat log line, and that is the cheaper mistake.
            while len(_seen) >= DEDUPE_MAX_KEYS:
                del _seen[min(_seen, key=_seen.get)]
        last = _seen.get(key)
        if last is not None and now - last < DEDUPE_WINDOW_SECONDS:
            return False
        _seen[key] = now
        return True


def _clip(value):
    text = str(value or '')
    return text[:MAX_FIELD]


def _normalise(report):
    """Flatten either report format into the fields worth logging.

    `report-uri` sends `{"csp-report": {"blocked-uri": ...}}` with hyphenated
    keys; `report-to` sends a list of `{"type": "csp-violation", "body":
    {"blockedURL": ...}}` with camelCase ones. Same violation, two spellings.
    """
    body = report.get('csp-report') or report.get('body') or report
    return {
        'directive': _clip(
            body.get('effective-directive')
            or body.get('effectiveDirective')
            or body.get('violated-directive')
        ),
        'blocked': _clip(body.get('blocked-uri') or body.get('blockedURL')),
        'document': _clip(body.get('document-uri') or body.get('documentURL')),
        'source': _clip(body.get('source-file') or body.get('sourceFile')),
        'line': _clip(body.get('line-number') or body.get('lineNumber')),
        'sample': _clip(body.get('script-sample') or body.get('sample')),
    }


@csrf_exempt
@require_POST
def csp_report(request):
    """Receive a CSP violation report. Always 204, even on garbage."""
    try:
        payload = json.loads(request.body.decode('utf-8', errors='replace'))
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest('malformed report')

    reports = payload if isinstance(payload, list) else [payload]
    for report in reports:
        if not isinstance(report, dict):
            continue
        fields = _normalise(report)
        if fields['blocked'].split(':', 1)[0] in EXTENSION_SCHEMES:
            continue
        # Not the document URL: the same handler on the same page is one
        # finding whether it fired for one visitor or a thousand.
        if not _first_sighting((fields['directive'], fields['blocked'],
                                fields['source'], fields['line'],
                                fields['sample'])):
            continue
        logger.warning(
            'CSP violation: %s blocked=%s document=%s source=%s:%s sample=%s',
            fields['directive'], fields['blocked'], fields['document'],
            fields['source'], fields['line'], fields['sample'],
        )

    return HttpResponse(status=204)
