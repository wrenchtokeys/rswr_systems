"""First-party analytics proxy — C3 of docs/strategy/IMPROVEMENT_SESSIONS.md.

The marketing site had no analytics of any kind, so there was no way to tell
whether anyone arrived, from where, or where they left. That is a poor position
to start spending on acquisition from.

WHY A PROXY AND NOT A SCRIPT TAG POINTING AT PLAUSIBLE
------------------------------------------------------
The CSP allowlist is `'self'` plus Cloudflare Turnstile, and keeping it that
small is the entire point of UI_MAGIC S1 and S17 on an app that takes card
payments. Adding `plausible.io` to `script-src` and `connect-src` means editing
`common/csp_middleware.py` and re-arguing both.

Plausible documents a first-party proxy for exactly this: we serve their script
from our own origin and forward the events ourselves, so every request a visitor
makes is to `rssystems.io`. The CSP does not move, there is no third-party DNS
hop before first paint, and no visitor IP reaches a third party except through
our own server (which is where the rest of their request already went).

Plausible is cookieless and stores no personal data, so this adds no consent
banner obligation. It is also why nothing here sets or reads a cookie: the
`@csrf_exempt` on the event view is safe because the view authenticates nothing
and mutates nothing of ours — it is a pipe to an outbound HTTP call.

OFF BY DEFAULT
--------------
With `PLAUSIBLE_DOMAIN` unset, `analytics.html` renders nothing and these views
return 404. Dev and the test suite therefore make no outbound calls and assert
no script, and production turns it on with a single `eb setenv`.

WHAT IS *NOT* HERE
------------------
Any tracking inside the authenticated app. C3 is about a stranger finding the
site and you knowing they did; the include is rendered by the public shells
only. If in-app product analytics is ever wanted, that is a separate decision
with a separate privacy answer, not a wider `{% include %}`.
"""

import logging

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

PLAUSIBLE_ORIGIN = 'https://plausible.io'

# The script is immutable for a given variant; Plausible ships changes as new
# filenames. An hour in our cache and an hour in the visitor's browser means one
# outbound fetch per instance per hour, and a cold start never blocks a page —
# the script is a separate request, so the worst case is one visitor whose
# pageview is missed.
_SCRIPT_CACHE_KEY = 'analytics:plausible-script'
_SCRIPT_CACHE_SECONDS = 3600
_BROWSER_CACHE_SECONDS = 3600

# Enough for a script fetch or an event POST to complete on a good day, short
# enough that a Plausible outage cannot pile up gunicorn workers.
_TIMEOUT_SECONDS = 5


def is_enabled():
    """True when a Plausible site has been configured for this deployment."""
    return bool(getattr(settings, 'PLAUSIBLE_DOMAIN', ''))


def _script_url():
    variant = getattr(settings, 'PLAUSIBLE_SCRIPT', 'script.js')
    return f'{PLAUSIBLE_ORIGIN}/js/{variant}'


def plausible_script(request):
    """GET /js/p.js — Plausible's tracker, served from our own origin.

    Fetched upstream and cached. On any upstream failure we return an empty
    200 rather than an error: a broken analytics script must never show up in a
    visitor's console on a page we are asking them to trust.
    """
    if not is_enabled():
        raise Http404('Analytics is not configured')

    body = cache.get(_SCRIPT_CACHE_KEY)
    if body is None:
        try:
            upstream = requests.get(_script_url(), timeout=_TIMEOUT_SECONDS)
            upstream.raise_for_status()
            body = upstream.content
            cache.set(_SCRIPT_CACHE_KEY, body, _SCRIPT_CACHE_SECONDS)
        except requests.RequestException as exc:
            logger.warning('analytics.script.fetch_failed %s', exc)
            # Not cached — the next request retries. No browser caching either,
            # or one bad minute blanks analytics for an hour.
            response = HttpResponse(b'', content_type='application/javascript')
            response['Cache-Control'] = 'no-store'
            return response

    response = HttpResponse(body, content_type='application/javascript')
    response['Cache-Control'] = f'public, max-age={_BROWSER_CACHE_SECONDS}'
    return response


def _client_ip(request):
    """The visitor's address, for Plausible's country and unique-visitor counts.

    Plausible derives both from the request IP, and the request it sees is
    ours — without this, every visitor is one visitor in Virginia.

    THE LAST XFF ENTRY, NOT THE FIRST. The EB load balancer *appends* the peer
    address to any `X-Forwarded-For` the client sent, so the right-most entry is
    the one the ALB vouched for and everything to its left is whatever the
    client typed. Reading `[0]` — the usual spelling, and the one
    `LoginAttempt.get_client_ip` uses — would let any visitor choose the country
    their pageview is counted in, which defeats the point of having analytics at
    all. REMOTE_ADDR covers a request that reached us with no proxy in front.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(',') if hop.strip()]
        if hops:
            return hops[-1]
    return request.META.get('REMOTE_ADDR', '')


@csrf_exempt
@require_POST
def plausible_event(request):
    """POST /pa/event — forward one pageview to Plausible.

    The tracker is pointed here with `data-api`. We pass the body through
    untouched and add the two headers Plausible cannot otherwise see, because
    from its side the client is our server.
    """
    if not is_enabled():
        raise Http404('Analytics is not configured')

    headers = {
        'Content-Type': request.META.get('CONTENT_TYPE', 'application/json'),
        'User-Agent': request.META.get('HTTP_USER_AGENT', ''),
        'X-Forwarded-For': _client_ip(request),
    }
    try:
        upstream = requests.post(
            f'{PLAUSIBLE_ORIGIN}/api/event',
            data=request.body,
            headers=headers,
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning('analytics.event.forward_failed %s', exc)
        # 202: we accepted it and it went nowhere. Telling the tracker it
        # failed buys nothing — it does not retry — and a 502 in the console of
        # a marketing page is worse than a missed pageview.
        return HttpResponse(status=202)

    return HttpResponse(
        upstream.content,
        status=upstream.status_code,
        content_type=upstream.headers.get('Content-Type', 'text/plain'),
    )
