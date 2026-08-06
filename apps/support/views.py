"""
In-app help pages (Phase 2, launch readiness roadmap).

Plain-language guides distilled from docs/user-guides/ — template-only views
for now. Phase 3 adds the contact form (SupportMessage model) to this app.
"""

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

# Ordered registry driving both the help index and per-topic routing.
# Adding a page = add an entry here + a template in templates/support/.
HELP_TOPICS = {
    'first-job': {
        'title': 'Create your first job',
        'blurb': 'Log a repair or replacement and get paid — start to finish in under a minute.',
        'icon': 'fas fa-tools',
        'color': 'green',
        'video_label': 'Watch: your first job (2 min)',
    },
    'send-invoice': {
        'title': 'Send an invoice',
        'blurb': 'Turn finished work into an emailed invoice your customer can pay online.',
        'icon': 'fas fa-file-invoice-dollar',
        'color': 'blue',
        'video_label': 'Watch: invoicing basics (2 min)',
    },
    'invite-customers': {
        'title': 'Invite your customers',
        'blurb': 'Give fleets and regulars a portal to track work, approve jobs, and see invoices.',
        'icon': 'fas fa-user-plus',
        'color': 'purple',
        'video_label': 'Watch: the customer portal (90 sec)',
    },
    'multi-break': {
        'title': 'Multi-break repairs',
        'blurb': 'Several chips on one windshield? Log them together — pricing steps down automatically.',
        'icon': 'fas fa-star-half-alt',
        'color': 'amber',
        'video_label': 'Watch: multi-break entry (90 sec)',
    },
    'settings-explained': {
        'title': 'Settings, explained',
        'blurb': 'What every setting does, in plain words — prices, tax, invoicing, team, and branding.',
        'icon': 'fas fa-sliders-h',
        'color': 'gray',
        'video_label': 'Watch: a tour of Settings (3 min)',
    },
}


@login_required
def help_home(request):
    """GET /help/ — help hub listing every guide."""
    topics = [{'slug': slug, **topic} for slug, topic in HELP_TOPICS.items()]
    return render(request, 'support/index.html', {'topics': topics})


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
