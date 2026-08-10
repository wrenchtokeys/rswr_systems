"""
In-app help pages (Phase 2) + contact form (Phase 3, launch readiness roadmap).

Plain-language guides distilled from docs/user-guides/ — template-only views
plus GuideFeedback (thumbs) and SupportMessage (/help/contact/).
"""

import logging

from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
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
        'blurb': 'Overdue reminders, fleet batch invoicing, statements, and who-owes-you at a glance.',
        'icon': 'fas fa-hourglass-half',
        'color': 'green',
        'video_label': 'Watch: chasing less, collecting more (2 min)',
        'keywords': 'overdue late reminder aging owed batch monthly statement collect',
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

    return render(request, f'support/{slug}.html', {
        'topic': topic,
        'slug': slug,
        'next_topic': next_topic,
    })


@login_required
@ratelimit(key='user', rate='10/h', method='POST', block=False)
def contact(request):
    """GET/POST /help/contact/ — write to a real person.

    Record-first: the SupportMessage row is saved BEFORE the notification
    email is attempted, so an SES outage can't lose a message — it still
    lands in the admin (emailed_ok=False) and the sender still sees success.
    The path is subscription-middleware-exempt: a shop whose trial just
    expired is exactly who needs this form to work.
    """
    from .models import SupportMessage

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
    }

    if request.method != 'POST':
        return render(request, 'support/contact.html', ctx)

    if getattr(request, 'limited', False):
        ctx['error'] = "You've sent quite a few messages in the last hour — give us a moment to catch up, then try again."
        return render(request, 'support/contact.html', ctx, status=429)

    topic = request.POST.get('topic', 'question')
    if topic not in dict(SupportMessage.TOPIC_CHOICES):
        topic = 'question'
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

    record = SupportMessage.objects.create(
        tenant=tenant,
        user=request.user,
        name=request.user.get_full_name() or request.user.username,
        email=email,
        topic=topic,
        message=message,
        page=page,
    )

    role = get_user_role(request.user, tenant)
    body = (
        f"From: {record.name} <{email}>\n"
        f"Shop: {tenant.name if tenant else '(no tenant)'}\n"
        f"Role: {role or 'unknown'}\n"
        f"Topic: {record.get_topic_display()}\n"
        f"Page: {page or '(not recorded)'}\n\n"
        f"{message}\n\n"
        f"—\nReply to this email to answer them directly. "
        f"Admin: {settings.BASE_URL}/admin/support/supportmessage/{record.pk}/change/"
    )
    try:
        EmailMessage(
            subject=f"Support: {record.get_topic_display()} — {tenant.name if tenant else record.name}",
            body=body,
            to=[addr for _name, addr in settings.ADMINS],
            reply_to=[email],
        ).send()
        record.emailed_ok = True
        record.save(update_fields=['emailed_ok'])
    except Exception:
        # Row is already saved — the admin sweep catches emailed_ok=False.
        logger.exception('Support notification email failed (message #%s)', record.pk)

    request.session['support_sent_to'] = email
    return redirect(f"{reverse('help_contact')}?sent=1")


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
