"""
Burn down the photos nobody ever marked.

P4a.1 (docs/strategy/PHOTO_ML_SESSIONS.md). Marking a break one job at a
time works — that is what the detail page has done since P2 — but there are
seventy-seven photos in production and exactly one of them is marked, and
nobody is going to open seventy-seven jobs.

So: one page, one photo at a time, tap and advance. No new endpoint (the
tap POSTs to the same ``save_photo_crop`` the detail page uses), no new
model, no queue state stored anywhere. The worklist is a question about the
database asked fresh on every load — a photo that has been marked simply
stops being in it, which is also what makes the page safe to run twice, or
from two devices, or halfway and then again tomorrow.
"""
from django.shortcuts import render
from django.urls import reverse

from apps.technician_portal.decorators import technician_required
from apps.technician_portal.services.photo_backlog import (
    QUEUE_LIMIT, backlog_for,
)
from apps.technician_portal.services.photo_dataset import TRAINABLE_LABELS


def _payload(item):
    """One queue entry, as the page's JS needs it.

    The endpoint is reversed per item rather than templated once: the queue
    mixes repairs and replacements, and they answer on different URLs under
    different permission checks.
    """
    save_url = (
        reverse('save_replacement_photo_crop', args=[item.job.pk])
        if item.kind == 'replacement'
        else reverse('save_photo_crop', args=[item.job.pk])
    )
    detail_url = (
        reverse('replacement_detail', args=[item.job.pk])
        if item.kind == 'replacement'
        else reverse('repair_detail', args=[item.job.pk])
    )
    entry = {
        'kind': item.kind,
        'id': item.job.pk,
        'field': item.source_field,
        'src': item.photo_url,
        'save_url': save_url,
        'detail_url': detail_url,
        'title': item.title,
        'subtitle': item.subtitle,
        'prompt': item.prompt,
        'why': item.why,
        'trainable': item.label in TRAINABLE_LABELS,
        'at': None,
    }
    # A crop the P3 sweep guessed at opens on its own guess, so confirming
    # it is a glance rather than a fresh hunt — and the guess rides back to
    # the server with the tap, which is how the suggester ever gets scored.
    crop = item.crop
    if crop is not None:
        entry['at'] = {
            'x': round(crop.center_x_pct, 2),
            'y': round(crop.center_y_pct, 2),
        }
        if crop.suggested_by:
            entry['suggested'] = {
                'x': round(crop.suggested_x_pct, 2),
                'y': round(crop.suggested_y_pct, 2),
                'by': crop.suggested_by,
                'score': round(crop.suggestion_score or 0.0, 3),
            }
    return entry


@technician_required
def photo_backfill_queue(request):
    """The unmarked-photo queue.

    Read-only itself: every write goes through the existing crop endpoint,
    one tap at a time, so this view can never damage a photo or a crop even
    if the page is wrong about what needs marking.
    """
    tenant = getattr(request, 'tenant', None)
    items = backlog_for(request, tenant, limit=QUEUE_LIMIT)
    queue = [_payload(item) for item in items]

    # `queue` goes through the template's json_script filter, which escapes
    # it properly — the payload carries customer names and free-text vehicle
    # descriptions straight into a <script> block.
    return render(request, 'technician_portal/photo_backfill.html', {
        'queue': queue,
        'queue_count': len(queue),
        'trainable_count': sum(1 for entry in queue if entry['trainable']),
        'at_limit': len(queue) >= QUEUE_LIMIT,
    })
