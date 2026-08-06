"""
In-app help pages (Phase 2, launch readiness roadmap).

Plain-language guides distilled from docs/user-guides/ — template-only views
for now. Phase 3 adds the contact form (SupportMessage model) to this app.
"""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

# Section order for the help index.
HELP_SECTIONS = [
    ('start', 'Getting started'),
    ('money', 'Billing & getting paid'),
    ('team', 'Your team'),
    ('customers', 'Your customers'),
    ('grow', 'Grow your business'),
]

# Ordered registry driving both the help index and per-topic routing.
# Adding a page = add an entry here + a template in templates/support/.
HELP_TOPICS = {
    # --- Getting started ---------------------------------------------------
    'first-job': {
        'section': 'start',
        'title': 'Create your first job',
        'blurb': 'Log a repair or replacement and get paid — start to finish in under a minute.',
        'icon': 'fas fa-tools',
        'color': 'green',
        'video_label': 'Watch: your first job (2 min)',
    },
    'multi-break': {
        'section': 'start',
        'title': 'Multi-break repairs',
        'blurb': 'Several chips on one windshield? Log them together — pricing steps down automatically.',
        'icon': 'fas fa-star-half-alt',
        'color': 'amber',
        'video_label': 'Watch: multi-break entry (90 sec)',
    },
    'settings-explained': {
        'section': 'start',
        'title': 'Settings, explained',
        'blurb': 'What every setting does, in plain words — prices, tax, invoicing, team, and branding.',
        'icon': 'fas fa-sliders-h',
        'color': 'gray',
        'video_label': 'Watch: a tour of Settings (3 min)',
    },

    # --- Billing & getting paid --------------------------------------------
    'send-invoice': {
        'section': 'money',
        'title': 'Send an invoice',
        'blurb': 'Turn finished work into an emailed invoice your customer can pay online.',
        'icon': 'fas fa-file-invoice-dollar',
        'color': 'blue',
        'video_label': 'Watch: invoicing basics (2 min)',
    },
    'card-payments': {
        'section': 'money',
        'title': 'Take card payments online',
        'blurb': 'Add a Pay Now button to every invoice — money goes straight to your bank.',
        'icon': 'fas fa-credit-card',
        'color': 'blue',
        'video_label': 'Watch: connecting card payments (2 min)',
    },
    'sales-tax': {
        'section': 'money',
        'title': 'Sales tax',
        'blurb': 'Answer the tax question once and every invoice comes out right.',
        'icon': 'fas fa-percent',
        'color': 'amber',
        'video_label': 'Watch: setting up sales tax (90 sec)',
    },
    'paid-on-time': {
        'section': 'money',
        'title': 'Get paid on time',
        'blurb': 'Overdue reminders, fleet batch invoicing, statements, and who-owes-you at a glance.',
        'icon': 'fas fa-hourglass-half',
        'color': 'green',
        'video_label': 'Watch: chasing less, collecting more (2 min)',
    },

    # --- Your team -----------------------------------------------------------
    'team-roles': {
        'section': 'team',
        'title': 'Add your team & roles',
        'blurb': 'Invite techs and managers, and control who can do repairs, replacements, or run the shop.',
        'icon': 'fas fa-users',
        'color': 'purple',
        'video_label': 'Watch: building your team (2 min)',
    },
    'for-technicians': {
        'section': 'team',
        'title': 'For technicians: your day in RS Systems',
        'blurb': 'Your queue, logging jobs in the field, photos from your phone, and resin suggestions.',
        'icon': 'fas fa-hard-hat',
        'color': 'green',
        'video_label': 'Watch: a technician’s day (2 min)',
    },

    # --- Your customers -------------------------------------------------------
    'invite-customers': {
        'section': 'customers',
        'title': 'Invite your customers',
        'blurb': 'Give fleets and regulars a portal to track work, approve jobs, and see invoices.',
        'icon': 'fas fa-user-plus',
        'color': 'purple',
        'video_label': 'Watch: the customer portal (90 sec)',
    },
    'customer-portal': {
        'section': 'customers',
        'title': 'What your customers see',
        'blurb': 'A walkthrough of the portal from your customer’s side — approvals, requests, invoices, rewards.',
        'icon': 'fas fa-eye',
        'color': 'blue',
        'video_label': 'Watch: the portal, customer’s-eye view (2 min)',
    },

    # --- Grow your business ---------------------------------------------------
    'loyalty-referrals': {
        'section': 'grow',
        'title': 'Loyalty & referrals',
        'blurb': 'Points that keep fleets coming back, and referral bonuses that bring new ones in.',
        'icon': 'fas fa-gift',
        'color': 'purple',
        'video_label': 'Watch: the loyalty program (2 min)',
    },
    'review-requests': {
        'section': 'grow',
        'title': 'Google review requests',
        'blurb': 'A polite "how’d we do?" email after each job — reviews on autopilot.',
        'icon': 'fas fa-star',
        'color': 'amber',
        'video_label': 'Watch: review requests (90 sec)',
    },
    'warranty': {
        'section': 'grow',
        'title': 'Warranty',
        'blurb': 'Put your guarantee in writing on every invoice — repairs and replacements.',
        'icon': 'fas fa-shield-alt',
        'color': 'gray',
        'video_label': 'Watch: setting your warranty (90 sec)',
    },
}


@login_required
def help_home(request):
    """GET /help/ — help hub, guides grouped by section."""
    sections = []
    for key, label in HELP_SECTIONS:
        topics = [
            {'slug': slug, **topic}
            for slug, topic in HELP_TOPICS.items()
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
    return render(request, f'support/{slug}.html', {
        'topic': topic,
        'slug': slug,
    })
