"""`{% page_meta %}` — the head tags a public page needs to be findable and shareable.

C3 of docs/strategy/IMPROVEMENT_SESSIONS.md found that only the landing page
carried meta at all: `/pricing/`, `/terms/`, `/privacy/` and `/sms/` had a
`<title>` and nothing else, so Google wrote its own snippet for the second-most
likely page to rank. The landing page's own set was hand-written, had no
`og:image`, and used the small Twitter card, so every share of rssystems.io —
in a Facebook group of glass shops, a LinkedIn post, an iMessage to another
owner — rendered as a bare text link.

ONE CALL PER PAGE
-----------------
    {% load seo %}
    {% page_meta description="…" %}

is the whole interface. Description, canonical, Open Graph and the Twitter card
all come out of that one argument, which is why they cannot drift from each
other the way three hand-written copies of a sentence do. `title` defaults to
the page's `<title>`-worthy name via the `title` kwarg; pass it when the share
card should read differently from the browser tab.

Pages that do not call it get the defaults from `base_public.html`, so a new
public page is never meta-less — it is only generic, which is a smaller bug.

CANONICAL
---------
Derived from `SITE_URL` plus the request path, never hardcoded: a hardcoded
rssystems.io makes a staging deploy advertise production's URLs to a crawler
that reaches it. Query strings are excluded — `/pricing/?utm_source=x` and
`/pricing/` are the same page.
"""

from django import template
from django.conf import settings
from django.templatetags.static import static
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# The share card: a real capture of the owner dashboard, cropped to Open Graph's
# 1200x630 by scripts/og_card.py. For a product whose pitch is "look at the real
# app", showing the real app in every share is free distribution.
OG_IMAGE_PATH = 'images/og-card.jpg'
OG_IMAGE_WIDTH = 1200
OG_IMAGE_HEIGHT = 630
OG_IMAGE_ALT = 'The RS Systems owner dashboard: jobs, invoices and money owed.'

TWITTER_SITE = '@wrenchtokeys'

DEFAULT_DESCRIPTION = (
    'Windshield repair management software for glass shops. Track repairs, '
    'generate invoices, manage fleet customers. Built by a shop owner for '
    'shop owners.'
)


@register.simple_tag(takes_context=True)
def page_meta(context, description='', title='', image='', canonical='',
              og_type='website', noindex=False):
    """Render description, canonical, Open Graph and Twitter card tags.

    description — one sentence. Falls back to the site-wide line.
    title       — share-card headline. Defaults to the site name.
    image       — static path for a page-specific card. Defaults to the
                  dashboard capture.
    canonical   — absolute URL, when a page's canonical is not its own path
                  (an alias, or a paginated view).
    noindex     — a public page we do not want in an index (a thank-you page).
    """
    request = context.get('request')
    site_url = (getattr(settings, 'SITE_URL', '') or '').rstrip('/')

    description = description or DEFAULT_DESCRIPTION
    title = title or 'RS Systems — Windshield Repair & Replacement Software'
    if not canonical:
        path = request.path if request is not None else '/'
        canonical = f'{site_url}{path}'
    image_url = f'{site_url}{static(image or OG_IMAGE_PATH)}'

    tags = [
        f'<meta name="description" content="{escape(description)}">',
        f'<link rel="canonical" href="{escape(canonical)}">',
    ]
    if noindex:
        tags.append('<meta name="robots" content="noindex, follow">')

    tags += [
        f'<meta property="og:title" content="{escape(title)}">',
        f'<meta property="og:description" content="{escape(description)}">',
        f'<meta property="og:url" content="{escape(canonical)}">',
        f'<meta property="og:type" content="{escape(og_type)}">',
        '<meta property="og:site_name" content="RS Systems">',
        f'<meta property="og:image" content="{escape(image_url)}">',
        f'<meta property="og:image:width" content="{OG_IMAGE_WIDTH}">',
        f'<meta property="og:image:height" content="{OG_IMAGE_HEIGHT}">',
        f'<meta property="og:image:alt" content="{escape(OG_IMAGE_ALT)}">',
        # summary_large_image, not summary: the small card is a favicon beside a
        # line of text, which is what every share looked like before C3.
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:site" content="{TWITTER_SITE}">',
        f'<meta name="twitter:title" content="{escape(title)}">',
        f'<meta name="twitter:description" content="{escape(description)}">',
        f'<meta name="twitter:image" content="{escape(image_url)}">',
    ]

    verification = getattr(settings, 'GOOGLE_SITE_VERIFICATION', '')
    if verification:
        tags.append(
            '<meta name="google-site-verification" '
            f'content="{escape(verification)}">'
        )

    return mark_safe('\n    '.join(tags))
