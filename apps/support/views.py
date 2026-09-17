"""
In-app help pages (Phase 2) + contact form (Phase 3, launch readiness roadmap).

Plain-language guides distilled from docs/user-guides/ — template-only views
plus GuideFeedback (thumbs) and SupportMessage (/help/contact/).
"""

import logging

from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from common.auth import get_user_role

logger = logging.getLogger(__name__)

# Section order for the help index.
HELP_SECTIONS = [
    ('start', 'Getting started'),
    ('money', 'Billing & getting paid'),
    ('team', 'Your team'),
    ('customers', 'Your customers'),
    ('grow', 'Grow your business'),
    ('fix', 'When something looks wrong'),
]

# Ordered registry driving both the help index and per-topic routing.
# Adding a page = add an entry here + a template in templates/support/.
#   keywords — extra search terms for the /help/ filter box (title + blurb
#              are always searched; keywords catch the words people actually
#              type, e.g. "chip" for multi-break).
#   owner_only — True hides the card from technicians on the index (guides
#              whose content lives behind Settings they can't open). Direct
#              links still work for everyone.
HELP_TOPICS = {
    # --- Getting started ---------------------------------------------------
    'first-job': {
        'section': 'start',
        'title': 'Create your first job',
        'blurb': 'Log a repair or replacement and get paid — start to finish in under a minute.',
        'icon': 'fas fa-tools',
        'color': 'green',
        'video_label': 'Watch: your first job (2 min)',
        'keywords': 'repair replacement ticket new log work order windshield',
    },
    'multi-break': {
        'section': 'start',
        'title': 'Multi-break repairs',
        'blurb': 'Several chips on one windshield? Log them together — pricing steps down automatically.',
        'icon': 'fas fa-star-half-alt',
        'color': 'amber',
        'video_label': 'Watch: multi-break entry (90 sec)',
        'keywords': 'chip chips crack cracks batch several multiple discount',
    },
    'settings-explained': {
        'section': 'start',
        'title': 'Settings, explained',
        'blurb': 'What every setting does, in plain words — prices, tax, invoicing, team, and branding.',
        'icon': 'fas fa-sliders-h',
        'color': 'gray',
        'video_label': 'Watch: a tour of Settings (3 min)',
        'keywords': 'configure setup options branding logo color prices',
        'owner_only': True,
    },
    'trial-ending': {
        'section': 'start',
        'title': 'What happens when my trial ends',
        'blurb': 'The timeline, what each person on your team sees, and how nothing gets lost.',
        'icon': 'fas fa-hourglass-end',
        'color': 'blue',
        'video_label': 'Watch: after the trial (90 sec)',
        'keywords': 'trial expired subscription upgrade plan grace period locked read only data safe billing',
    },

    # --- Billing & getting paid --------------------------------------------
    'send-invoice': {
        'section': 'money',
        'title': 'Send an invoice',
        'blurb': 'Turn finished work into an emailed invoice your customer can pay online.',
        'icon': 'fas fa-file-invoice-dollar',
        'color': 'blue',
        'video_label': 'Watch: invoicing basics (2 min)',
        'keywords': 'bill email pdf pay online send customer',
    },
    'card-payments': {
        'section': 'money',
        'title': 'Take card payments online',
        'blurb': 'Add a Pay Now button to every invoice — money goes straight to your bank.',
        'icon': 'fas fa-credit-card',
        'color': 'blue',
        'video_label': 'Watch: connecting card payments (2 min)',
        'keywords': 'stripe credit debit bank payout pay now connect',
        'owner_only': True,
    },
    'sales-tax': {
        'section': 'money',
        'title': 'Sales tax',
        'blurb': 'Answer the tax question once and every invoice comes out right.',
        'icon': 'fas fa-percent',
        'color': 'amber',
        'video_label': 'Watch: setting up sales tax (90 sec)',
        'keywords': 'tax rate exempt no tax percent',
        'owner_only': True,
    },
    'progressive-pricing': {
        'section': 'money',
        'title': 'How progressive pricing works',
        'blurb': 'Repeat repairs on the same vehicle cost less — here’s the ladder, and how to change it.',
        'icon': 'fas fa-layer-group',
        'color': 'green',
        'video_label': 'Watch: progressive pricing (90 sec)',
        'keywords': 'price ladder step down discount flat rate per repair cost cheaper custom',
    },
    'paid-on-time': {
        'section': 'money',
        'title': 'Get paid on time',
        'blurb': 'Who owes you at a glance, fleet batch invoicing, and one payment across many invoices.',
        'icon': 'fas fa-hourglass-half',
        'color': 'green',
        'video_label': 'Watch: chasing less, collecting more (2 min)',
        'keywords': 'overdue late aging owed batch monthly collect check receive payment',
        'owner_only': True,
    },

    # --- Your team -----------------------------------------------------------
    'team-roles': {
        'section': 'team',
        'title': 'Add your team & roles',
        'blurb': 'Invite techs and managers, and control who can do repairs, replacements, or run the shop.',
        'icon': 'fas fa-users',
        'color': 'purple',
        'video_label': 'Watch: building your team (2 min)',
        'keywords': 'technician manager invite employee staff permission access',
        'owner_only': True,
    },
    'for-technicians': {
        'section': 'team',
        'title': 'For technicians: your day in RS Systems',
        'blurb': 'Your queue, logging jobs in the field, photos from your phone, and resin suggestions.',
        'icon': 'fas fa-hard-hat',
        'color': 'green',
        'video_label': 'Watch: a technician’s day (2 min)',
        'keywords': 'tech queue field mobile phone photos camera resin viscosity',
    },

    # --- Your customers -------------------------------------------------------
    'invite-customers': {
        'section': 'customers',
        'title': 'Invite your customers',
        'blurb': 'Give fleets and regulars a portal to track work, approve jobs, and see invoices.',
        'icon': 'fas fa-user-plus',
        'color': 'purple',
        'video_label': 'Watch: the customer portal (90 sec)',
        'keywords': 'fleet portal invitation email account login access',
        'owner_only': True,
    },
    'customer-portal': {
        'section': 'customers',
        'title': 'What your customers see',
        'blurb': 'A walkthrough of the portal from your customer’s side — approvals, requests, invoices, rewards.',
        'icon': 'fas fa-eye',
        'color': 'blue',
        'video_label': 'Watch: the portal, customer’s-eye view (2 min)',
        'keywords': 'portal approve deny request fleet view',
    },

    # --- Grow your business ---------------------------------------------------
    'loyalty-referrals': {
        'section': 'grow',
        'title': 'Loyalty & referrals',
        'blurb': 'Points that keep fleets coming back, and referral bonuses that bring new ones in.',
        'icon': 'fas fa-gift',
        'color': 'purple',
        'video_label': 'Watch: the loyalty program (2 min)',
        'keywords': 'points rewards redeem referral bonus program',
        'owner_only': True,
    },
    'review-requests': {
        'section': 'grow',
        'title': 'Google review requests',
        'blurb': 'A polite "how’d we do?" email after each job — reviews on autopilot.',
        'icon': 'fas fa-star',
        'color': 'amber',
        'video_label': 'Watch: review requests (90 sec)',
        'keywords': 'google stars rating feedback reputation email automatic',
        'owner_only': True,
    },
    'warranty': {
        'section': 'grow',
        'title': 'Warranty',
        'blurb': 'Put your guarantee in writing on every invoice — repairs and replacements.',
        'icon': 'fas fa-shield-alt',
        'color': 'gray',
        'video_label': 'Watch: setting your warranty (90 sec)',
        'keywords': 'guarantee policy coverage lifetime promise',
        'owner_only': True,
    },

    # --- When something looks wrong -------------------------------------------
    'troubleshooting': {
        'section': 'fix',
        'title': 'Troubleshooting & FAQ',
        'blurb': 'Quick answers for the "why didn’t..." moments — email, tax, prices, points, and more.',
        'icon': 'fas fa-life-ring',
        'color': 'amber',
        'video_label': None,
        'keywords': (
            'faq problem wrong missing didn’t receive spam email invoice tax '
            'replacement price locked paid review points deleted restore undo '
            'login error help stuck'
        ),
    },
}


# Settings tabs, for describe_page(). Keep in step with owner_settings.html.
SETTINGS_TABS = {
    'general': 'Settings → General',
    'team': 'Settings → Team',
    'billing': 'Settings → Pricing & Invoicing',
    'payments': 'Settings → Card Payments',
    'reviews': 'Settings → Reviews',
    'warranty': 'Settings → Warranty',
    'parts': 'Settings → Parts',
}


def describe_page(url):
    """A referrer URL → what a person would call that page.

    SupportMessage.page stores document.referrer. In the admin it reads as
    a URL; this turns /help/sales-tax/ into "Guide: Sales tax" and
    /owner/settings/?tab=billing into "Settings → Pricing & Invoicing" so
    "which page were they on" needs no decoding. Unknown paths come back
    as the path itself; empty stays empty.
    """
    from urllib.parse import parse_qs, urlsplit

    if not url:
        return ''
    parts = urlsplit(url)
    path = parts.path or '/'
    query = parse_qs(parts.query)
    segments = [seg for seg in path.split('/') if seg]
    if segments[:1] == ['help']:
        if len(segments) == 1:
            return 'Help hub'
        if segments[1] == 'contact':
            return 'Contact form'
        topic = HELP_TOPICS.get(segments[1])
        return f"Guide: {topic['title']}" if topic else path
    if segments[:2] == ['owner', 'settings']:
        tab = (query.get('tab') or ['general'])[0]
        return SETTINGS_TABS.get(tab, f'Settings → {tab}')
    return path


def _limit_text(value):
    return 'unlimited' if value is None else f'{value:,}'


def trial_facts():
    """What the trial guide is allowed to say, read from where it is decided.

    The guide used to say "30-day grace period" while settings said 14, and
    nothing noticed for six weeks. Every number on that page now comes from
    settings or the trial plan row, and tests/test_help_truth.py asserts the
    rendered page agrees with both.
    """
    from apps.tenants.models import SubscriptionPlan

    trial = SubscriptionPlan.objects.filter(slug='trial').first()
    starter = SubscriptionPlan.objects.filter(slug='starter').first()
    facts = {
        'trial_days': (trial.trial_days if trial and trial.trial_days else 30),
        'trial_grace_days': getattr(settings, 'TRIAL_GRACE_DAYS', 14),
        'trial_max_customers': _limit_text(trial.max_customers if trial else None),
        'trial_max_jobs': _limit_text(trial.max_repairs_per_month if trial else None),
        'trial_matches_starter': bool(
            trial and starter
            and trial.max_customers == starter.max_customers
            and trial.max_repairs_per_month == starter.max_repairs_per_month
        ),
    }
    return facts


def _is_owner_or_manager(request):
    role = get_user_role(request.user, getattr(request, 'tenant', None))
    return role in ('superuser', 'owner', 'manager')


def _visible_topics(request):
    """Ordered (slug, topic) pairs this user should see on the index."""
    show_all = _is_owner_or_manager(request)
    return [
        (slug, topic)
        for slug, topic in HELP_TOPICS.items()
        if show_all or not topic.get('owner_only')
    ]


@login_required
def help_home(request):
    """GET /help/ — help hub, guides grouped by section, filter-as-you-type."""
    visible = _visible_topics(request)
    sections = []
    for key, label in HELP_SECTIONS:
        topics = [
            {'slug': slug, **topic}
            for slug, topic in visible
            if topic['section'] == key
        ]
        if topics:
            sections.append({'key': key, 'label': label, 'topics': topics})
    return render(request, 'support/index.html', {'sections': sections})


@login_required
def help_topic(request, slug):
    """GET /help/<slug>/ — one plain-language guide."""
    topic = HELP_TOPICS.get(slug)
    if topic is None:
        raise Http404('Unknown help topic')

    # "Next up →" — the guide after this one in the same section, respecting
    # the reader's role, so each section reads like a short course.
    next_topic = None
    section_slugs = [
        s for s, t in _visible_topics(request) if t['section'] == topic['section']
    ]
    if slug in section_slugs:
        idx = section_slugs.index(slug)
        if idx + 1 < len(section_slugs):
            next_slug = section_slugs[idx + 1]
            next_topic = {'slug': next_slug, **HELP_TOPICS[next_slug]}

    context = {
        'topic': topic,
        'slug': slug,
        'next_topic': next_topic,
    }
    if slug == 'trial-ending':
        context.update(trial_facts())
    return render(request, f'support/{slug}.html', context)


@login_required
@ratelimit(key='user', rate='10/h', method='POST', block=False)
def contact(request):
    """GET/POST /help/contact/ — write to a real person.

    Record-first: the SupportMessage row is saved BEFORE the notification
    email is attempted, so an SES outage can't lose a message — it still
    lands in the admin (emailed_ok=False) and the sender still sees success.
    The path is subscription-middleware-exempt: a shop whose trial just
    expired is exactly who needs this form to work.

    Under the form: the signed-in user's own past messages, so "did that go
    through?" answers itself. Not a ticket system — no replies in-app.
    """
    from .models import SupportMessage
    from .services import submit_support_message

    tenant = getattr(request, 'tenant', None)
    default_email = (request.user.email or '').strip()
    ctx = {
        'topics': SupportMessage.TOPIC_CHOICES,
        'form_email': default_email,
        'form_topic': 'question',
        'form_message': '',
        'sent': request.GET.get('sent') == '1',
        # Popped so a bookmark of ?sent=1 shows the generic success line, not
        # a stale address; the query string never carries the email itself.
        'sent_to': request.session.pop('support_sent_to', ''),
        'my_messages': SupportMessage.objects.filter(user=request.user)[:20],
    }

    if request.method != 'POST':
        return render(request, 'support/contact.html', ctx)

    if getattr(request, 'limited', False):
        ctx['error'] = "You've sent quite a few messages in the last hour — give us a moment to catch up, then try again."
        return render(request, 'support/contact.html', ctx, status=429)

    topic = request.POST.get('topic', 'question')
    message = request.POST.get('message', '').strip()
    email = request.POST.get('email', '').strip() or default_email
    page = request.POST.get('page', '').strip()[:500]
    ctx.update({'form_topic': topic, 'form_message': message, 'form_email': email})

    if not message:
        ctx['error'] = "Tell us what's going on — the message box is empty."
        return render(request, 'support/contact.html', ctx, status=400)
    try:
        validate_email(email)
    except ValidationError:
        ctx['error'] = "That email doesn't look right — double-check it so our reply can reach you."
        return render(request, 'support/contact.html', ctx, status=400)

    submit_support_message(
        tenant=tenant,
        user=request.user,
        name=request.user.get_full_name() or request.user.username,
        email=email,
        topic=topic,
        message=message,
        page=page,
        source='app',
        role=get_user_role(request.user, tenant) or '',
    )

    request.session['support_sent_to'] = email
    return redirect(f"{reverse('help_contact')}?sent=1")


@ratelimit(key='ip', rate='5/h', method='POST', block=False)
def public_contact(request):
    """GET/POST /contact/ — the form a stranger can use.

    The landing page used to send prospects to /help/contact/, which is
    @login_required, so the path a prospect actually takes dead-ended on the
    sign-in page. This is the same record-first path with no account: name
    becomes a field, Turnstile (the one third-party script the CSP allows)
    plus a honeypot stand in for the login, and the rate limit is per IP.

    A signed-in user who lands here is recorded with their tenant and user,
    so nothing is lost if the two forms are ever confused.
    """
    from .models import SupportMessage
    from .services import submit_support_message
    from apps.saas.views import _verify_turnstile

    user = request.user if request.user.is_authenticated else None
    tenant = getattr(request, 'tenant', None) if user else None
    ctx = {
        'topics': SupportMessage.TOPIC_CHOICES,
        'form_name': (user.get_full_name() if user else '') or '',
        'form_email': (user.email if user else '') or '',
        'form_topic': 'question',
        'form_message': '',
        'sent': request.GET.get('sent') == '1',
        'sent_to': request.session.pop('support_sent_to', ''),
    }

    if request.method != 'POST':
        return render(request, 'support/public_contact.html', ctx)

    if getattr(request, 'limited', False):
        ctx['error'] = "That's quite a few messages in the last hour — give us a moment to catch up, then try again."
        return render(request, 'support/public_contact.html', ctx, status=429)

    name = request.POST.get('name', '').strip()
    topic = request.POST.get('topic', 'question')
    message = request.POST.get('message', '').strip()
    email = request.POST.get('email', '').strip()
    page = request.POST.get('page', '').strip()[:500]
    ctx.update({'form_name': name, 'form_topic': topic, 'form_message': message, 'form_email': email})

    # Honeypot: a real browser never fills a field it cannot see. A bot that
    # does gets the success page and nothing else — no row, no email.
    if request.POST.get('website', '').strip():
        return redirect(f"{reverse('public_contact')}?sent=1")

    if not name:
        ctx['error'] = "Tell us your name so the reply isn't addressed to nobody."
        return render(request, 'support/public_contact.html', ctx, status=400)
    if not message:
        ctx['error'] = "Tell us what's going on — the message box is empty."
        return render(request, 'support/public_contact.html', ctx, status=400)
    try:
        validate_email(email)
    except ValidationError:
        ctx['error'] = "That email doesn't look right — double-check it so our reply can reach you."
        return render(request, 'support/public_contact.html', ctx, status=400)
    if not _verify_turnstile(request):
        ctx['error'] = "We couldn't confirm you're a person — please try again."
        return render(request, 'support/public_contact.html', ctx, status=400)

    submit_support_message(
        tenant=tenant,
        user=user,
        name=name,
        email=email,
        topic=topic,
        message=message,
        page=page,
        source='public',
        role=(get_user_role(user, tenant) or '') if user else '',
    )

    request.session['support_sent_to'] = email
    return redirect(f"{reverse('public_contact')}?sent=1")


@require_POST
@login_required
def guide_feedback(request, slug):
    """POST /help/<slug>/feedback/ — thumbs up/down on a guide.

    One vote per user per guide; voting again overwrites (people change
    their minds after re-reading). Answer is 'yes' or 'no'.
    """
    from .models import GuideFeedback

    if slug not in HELP_TOPICS:
        raise Http404('Unknown help topic')
    answer = request.POST.get('helpful')
    if answer not in ('yes', 'no'):
        return JsonResponse({'ok': False, 'error': 'helpful must be yes or no'}, status=400)

    GuideFeedback.objects.update_or_create(
        user=request.user,
        slug=slug,
        defaults={
            'helpful': answer == 'yes',
            'tenant': getattr(request, 'tenant', None),
        },
    )
    return JsonResponse({'ok': True})
