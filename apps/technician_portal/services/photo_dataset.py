"""
Turn tap-to-crop rows into a training dataset.

This is the export half of P4 (docs/strategy/PHOTO_ML_SESSIONS.md). It does
no ML. Its whole job is to answer, honestly, two questions:

  1. What labeled examples do we actually have, and of which class?
  2. Is the P3 suggester any good?

Both answers have been guesses until now. The first one was structurally
unanswerable before P4a, because crops could only hang off a Repair — and a
crop of a repair is by definition a photo of damage that WAS repaired, so
the corpus was 100% positive class no matter how long it accumulated.

**The label comes from what the shop did, not from what the photo looks
like.** That is the only ground truth available and it is a good one: a
technician who replaced a windshield decided, with the glass in front of
them, that the damage was not repairable.
"""
import math

# Deliberately coarse. The classifier's question is "can this be repaired",
# so anything whose outcome is not yet decided is `unknown` and gets
# excluded from a training split rather than guessed at.
REPAIRABLE = 'repairable'
NOT_REPAIRABLE = 'not_repairable'
UNKNOWN = 'unknown'
NOT_APPLICABLE = 'not_applicable'

TRAINABLE_LABELS = (REPAIRABLE, NOT_REPAIRABLE)


def phase_of(source_field):
    """Which moment in the job this photo is from."""
    if source_field == 'damage_photo_after':
        return 'after'
    if source_field == 'customer_submitted_photo':
        return 'customer'
    return 'before'


def label_for(crop):
    """(label, label_source) for one crop row.

    ``label_source`` names the rule that fired, so a training run can drop a
    rule it doesn't trust without re-deriving any of this.
    """
    return label_for_photo(crop.service, crop.source_field)


def label_for_photo(job, source_field):
    """(label, label_source) for a photo that may not have a crop yet.

    Same rules as ``label_for``, reached one step earlier — the backfill
    queue (P4a.1) needs to know what a photo *would* be worth before anybody
    has marked it, so it can put the trainable ones in front of a human
    first. Two copies of these rules would drift, and the point of
    ``label_source`` is that a training run can trust which rule fired.
    """
    from apps.technician_portal.services.photo_crops import job_kind

    if job is None:  # defended by a CheckConstraint; belt and braces
        return UNKNOWN, 'no_job'

    # An "after" photo is a repaired break. It is a photo of the outcome,
    # not of the decision, and training on it would teach the model that
    # resin-filled chips are the repairable ones.
    if source_field == 'damage_photo_after':
        return NOT_APPLICABLE, 'after_photo'

    completed = job.queue_status == 'COMPLETED'
    if job_kind(job) == 'repair':
        if completed:
            return REPAIRABLE, 'repair_completed'
        return UNKNOWN, f'repair_{job.queue_status.lower()}'

    # Replacements. Side and rear glass is tempered — it shatters, and it is
    # always replaced no matter what hit it. Only a windshield replacement
    # carries the judgment "this damage could not be repaired".
    position = (getattr(job, 'glass_position', '') or '').upper()
    if position and position != 'WINDSHIELD':
        return NOT_APPLICABLE, 'replacement_non_windshield'
    if not completed:
        return UNKNOWN, f'replacement_{job.queue_status.lower()}'
    if not position:
        # Blank is common and usually means a windshield, but "usually" is
        # not a label. Kept in the negative class with a distinct source so
        # a training run can drop it in one line.
        return NOT_REPAIRABLE, 'replacement_completed_glass_unspecified'
    return NOT_REPAIRABLE, 'replacement_completed_windshield'


def suggestion_error_pct(crop):
    """How far the machine's guess was from the human's mark, or None.

    Distance in percentage points of the image (its diagonal is ~141), which
    keeps it comparable across photos of different sizes — the same
    convention MAX_SPREAD uses in photo_suggest.

    Only meaningful where a human confirmed the final mark; an unconfirmed
    row's "correction" is a distance of zero from itself, and averaging
    those in would report the suggester as perfect.
    """
    if not crop.confirmed_by_human:
        return None
    if crop.suggested_x_pct is None or crop.suggested_y_pct is None:
        return None
    return math.hypot(
        crop.center_x_pct - crop.suggested_x_pct,
        crop.center_y_pct - crop.suggested_y_pct,
    )


def record_for(crop, image_name):
    """The JSONL row for one crop.

    Anonymised on purpose: ids only. No customer name, unit number, plate,
    address or note text ever reaches the bundle — the shop whose photos
    these are is a real business with real customers, and a dataset that
    travels is a dataset that leaks.
    """
    job = crop.service
    label, label_source = label_for(crop)
    error = suggestion_error_pct(crop)
    return {
        'crop_id': crop.pk,
        'tenant_id': crop.tenant_id,
        'job_kind': crop.service_kind,
        'job_id': job.pk if job else None,
        'image': image_name,
        'label': label,
        'label_source': label_source,
        'trainable': label in TRAINABLE_LABELS,
        'phase': phase_of(crop.source_field),
        'source_field': crop.source_field,
        'confirmed_by_human': crop.confirmed_by_human,
        'damage_type': getattr(job, 'damage_type', '') or '',
        'glass_position': (getattr(job, 'glass_position', '') or ''),
        'center_x_pct': crop.center_x_pct,
        'center_y_pct': crop.center_y_pct,
        'crop_box': (
            [crop.crop_left, crop.crop_top, crop.crop_right, crop.crop_bottom]
            if crop.crop_left is not None else None
        ),
        'natural_width': crop.natural_width,
        'natural_height': crop.natural_height,
        'suggested_x_pct': crop.suggested_x_pct,
        'suggested_y_pct': crop.suggested_y_pct,
        'suggested_by': crop.suggested_by or None,
        'suggestion_score': crop.suggestion_score,
        'suggestion_error_pct': round(error, 3) if error is not None else None,
        'created_at': crop.created_at.date().isoformat() if crop.created_at else None,
    }
