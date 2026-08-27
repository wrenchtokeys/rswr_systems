"""
Tap-to-crop for glass-damage photos.

Works on a *job*: a Repair or a Replacement. Both inherit the photo fields
from GlassService, and both are needed — a crop can only be a training
example if the other class exists too, and replacements are the only place
the "not repairable" class comes from.

The technician taps the break on the photo in the upload flow; the tap
arrives as crop_x_<field>/crop_y_<field> POST values (percent of the
displayed image, which browsers render EXIF-upright). This module crops a
square around that point and stores it on a RepairPhotoCrop row alongside
the untouched original.

Everything here fails open: a crop must never block saving a job in the
field. See docs/strategy/PHOTO_ML_SESSIONS.md for the arc this feeds
(these crops are training data for a repairable-vs-not classifier).
"""
import logging
from io import BytesIO

from django.core.files.base import ContentFile

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Square crop: side = CROP_FRACTION of the shorter image dimension, but at
# least MIN_CROP_PX, clamped to the image. Generous on purpose — a loose
# crop still trains; a tight one that misses the break doesn't.
CROP_FRACTION = 0.35
MIN_CROP_PX = 300
CROP_JPEG_QUALITY = 90

SOURCE_FIELDS = (
    'damage_photo_before',
    'damage_photo_after',
    'customer_submitted_photo',
)


def job_kind(job):
    """'repair' or 'replacement' for any GlassService subclass."""
    from apps.technician_portal.models import Replacement
    return 'replacement' if isinstance(job, Replacement) else 'repair'


def _crop_fk(job):
    """The RepairPhotoCrop FK kwargs addressing this job.

    Exactly one of repair/replacement is ever set (a CheckConstraint on the
    model enforces it), so this is the only place that decides which.
    """
    return {job_kind(job): job}


# ---------------------------------------------------------------------------
# Showing the mark (P6)
# ---------------------------------------------------------------------------
# A tap is worth a technician's fifteen seconds only if it does something the
# customer can see. Every surface that shows a damage photo in a fixed-size
# box already crops it — `object-fit: cover` centres on the middle of the
# frame, which is usually the middle of the glass and not the break. These
# two helpers turn a stored tap into the `object-position` that reframes it,
# without touching the original file or the derived close-up.

# The *after* photo of a repair is deliberately never reframed: a resin
# repair leaves a visible blemish, so zooming it shows the customer the scar
# instead of the fix. Before and customer-submitted photos are of the damage
# itself, which is the thing worth looking at closely.
UNZOOMED_SOURCE_FIELDS = ('damage_photo_after',)


def focus_position(crop):
    """CSS `object-position` for a marked break, or '' when nothing is marked.

    With `object-fit: cover`, `object-position: X% Y%` lines the X% point of
    the photo up with the X% point of the box, so a marked break is always in
    frame instead of wherever the blind centre-crop happened to land.

    This reads the tap coordinates only. A crop whose derived close-up failed
    to render (unreadable original, null box) still reframes correctly, and
    the file served is the untouched original either way.
    """
    if crop is None:
        return ''
    x, y = crop.center_x_pct, crop.center_y_pct
    if x is None or y is None:
        return ''
    x = min(100.0, max(0.0, float(x)))
    y = min(100.0, max(0.0, float(y)))
    return f'{x:.2f}% {y:.2f}%'


def focus_positions_for(job):
    """{source_field: 'x% y%'} for one job's marked photos.

    Fields nobody marked are absent, so a template's `{% if %}` degrades to
    exactly today's rendering. Uses the job's prefetched `photo_crops`, so a
    caller that prefetched pays no query per job.
    """
    positions = {}
    for crop in job.photo_crops.all():
        if crop.source_field in UNZOOMED_SOURCE_FIELDS:
            continue
        position = focus_position(crop)
        if position:
            positions[crop.source_field] = position
    return positions


def process_tap_coordinates(job, post_data, technician=None,
                            key_prefix='', key_suffix=''):
    """Create crops for whichever crop_x_/crop_y_ pairs are in the POST.

    ``job`` is a Repair or a Replacement.

    Deliberately touches Pillow only when a tap was actually made, so photo
    uploads without a tap never open the image server-side.

    ``key_prefix``/``key_suffix`` wrap the field names for forms that
    namespace their inputs — the multi-break form posts one set per break as
    ``breaks[0][crop_x_damage_photo_before]``.
    """
    for source_field in SOURCE_FIELDS:
        raw_x = post_data.get(f'{key_prefix}crop_x_{source_field}{key_suffix}', '')
        raw_y = post_data.get(f'{key_prefix}crop_y_{source_field}{key_suffix}', '')
        if raw_x == '' or raw_y == '':
            continue
        try:
            center_x_pct = min(max(float(raw_x), 0.0), 100.0)
            center_y_pct = min(max(float(raw_y), 0.0), 100.0)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring unparseable tap coords for %s %s %s: %r/%r",
                job_kind(job), job.pk, source_field, raw_x, raw_y,
            )
            continue
        try:
            save_crop_for(
                job, source_field, center_x_pct, center_y_pct,
                technician=technician,
            )
        except Exception:
            logger.exception(
                "Tap-to-crop failed for %s %s %s",
                job_kind(job), job.pk, source_field,
            )


def save_crop_for(job, source_field, center_x_pct, center_y_pct,
                  technician=None, confirmed_by_human=True, suggestion=None):
    """Crop a square around the tap point and upsert the RepairPhotoCrop.

    ``job`` is a Repair or a Replacement — the row hangs off whichever it
    is, and the crop filename is namespaced by kind so a repair and a
    replacement sharing an id can't collide in the same bucket prefix.

    Re-tapping the same photo replaces the previous crop (latest wins —
    history would only add noise to the dataset). Returns the crop row, or
    None when there is no photo on the field.

    ``confirmed_by_human`` is what separates a technician's tap from a
    machine's guess: pass False only from the suggestion sweep, which writes
    coordinates nobody has looked at. ``suggestion`` (a
    photo_suggest.Suggestion, or None) is recorded alongside the final
    coordinates even when a technician moves the mark — the gap between the
    two is how the suggester gets scored. See MAX_SPREAD in photo_suggest.
    """
    from apps.technician_portal.models import RepairPhotoCrop

    photo = getattr(job, source_field, None)
    if not photo:
        return None

    defaults = {
        'tenant': job.tenant,
        'center_x_pct': center_x_pct,
        'center_y_pct': center_y_pct,
        'crop_left': None,
        'crop_top': None,
        'crop_right': None,
        'crop_bottom': None,
        'natural_width': None,
        'natural_height': None,
        'created_by': technician,
        'confirmed_by_human': confirmed_by_human,
        'suggested_x_pct': suggestion.x_pct if suggestion else None,
        'suggested_y_pct': suggestion.y_pct if suggestion else None,
        'suggested_by': suggestion.engine if suggestion else '',
        'suggestion_score': suggestion.score if suggestion else None,
    }

    content = None
    try:
        with photo.open('rb'):
            img = Image.open(photo)
            # Browsers display per EXIF orientation and the tap happened on
            # that upright rendering — measure and crop upright too.
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            box = _crop_box(width, height, center_x_pct, center_y_pct)
            cropped = img.crop(box).convert('RGB')
            buffer = BytesIO()
            cropped.save(buffer, format='JPEG',
                         quality=CROP_JPEG_QUALITY, optimize=True)
            content = ContentFile(buffer.getvalue())
            defaults.update({
                'crop_left': box[0],
                'crop_top': box[1],
                'crop_right': box[2],
                'crop_bottom': box[3],
                'natural_width': width,
                'natural_height': height,
            })
    except Exception:
        # Unreadable image (fake test bytes, truncated upload, exotic
        # format): keep the tap on record so the crop can be retried.
        logger.exception(
            "Could not crop %s of %s %s; recording tap only",
            source_field, job_kind(job), job.pk,
        )

    crop, created = RepairPhotoCrop.objects.update_or_create(
        source_field=source_field, defaults=defaults, **_crop_fk(job),
    )
    if not created and crop.cropped_image:
        crop.cropped_image.delete(save=False)
        crop.cropped_image = None
    if content is not None:
        crop.cropped_image.save(
            f'{job_kind(job)}{job.pk}_{source_field}.jpg', content, save=True,
        )
    else:
        crop.save(update_fields=['cropped_image'])
    return crop


def retry_crop(crop):
    """Re-run a crop that only ever recorded the tap (no derived image).

    The original may have been unreadable when the tap was saved (a truncated
    upload, an S3 write still in flight) and be perfectly fine now. The tap is
    stored as a percentage, so it still means the same point on the photo.
    Returns True when the retry produced an image.
    """
    # Carry the provenance across — a retry re-derives the image, it does
    # not re-label the photo. Losing confirmed_by_human here would quietly
    # demote every technician's tap that had to be retried.
    suggestion = None
    if crop.suggested_by:
        from apps.technician_portal.services.photo_suggest import Suggestion
        suggestion = Suggestion(
            crop.suggested_x_pct, crop.suggested_y_pct,
            crop.suggestion_score, engine=crop.suggested_by,
        )
    refreshed = save_crop_for(
        crop.service, crop.source_field,
        crop.center_x_pct, crop.center_y_pct,
        technician=crop.created_by,
        confirmed_by_human=crop.confirmed_by_human,
        suggestion=suggestion,
    )
    return bool(refreshed and refreshed.cropped_image)


def delete_crops_for(job, source_field):
    """Remove the crop (row and file) when its source photo is deleted."""
    for crop in job.photo_crops.filter(source_field=source_field):
        if crop.cropped_image:
            crop.cropped_image.delete(save=False)
        crop.delete()


def apply_suggestion(job, source_field, suggestion=None):
    """Save a machine-suggested crop for a photo nobody has marked.

    Used by ``manage.py suggest_photo_crops``. The row is stored with
    ``confirmed_by_human=False`` — it is a weaker label than a tap and P4's
    export must be able to tell them apart. **The original photo is never
    touched**: the crop is a separate derived file, exactly as with a tap.

    Refuses to overwrite an existing crop, so a sweep can never trample a
    technician's work. Returns the crop row, or None if there was nothing to
    do (no photo, no confident suggestion, or already marked).
    """
    from apps.technician_portal.services.photo_suggest import suggest_for

    if not getattr(job, source_field, None):
        return None
    if job.photo_crops.filter(source_field=source_field).exists():
        return None
    if suggestion is None:
        suggestion = suggest_for(job, source_field)
    if suggestion is None:
        return None
    return save_crop_for(
        job, source_field, suggestion.x_pct, suggestion.y_pct,
        technician=None, confirmed_by_human=False, suggestion=suggestion,
    )


def _crop_box(width, height, center_x_pct, center_y_pct):
    """Square box around the tap, shifted (not shrunk) to stay in bounds."""
    side = min(max(MIN_CROP_PX, int(CROP_FRACTION * min(width, height))),
               min(width, height))
    center_x = int(center_x_pct / 100.0 * width)
    center_y = int(center_y_pct / 100.0 * height)
    left = min(max(center_x - side // 2, 0), width - side)
    top = min(max(center_y - side // 2, 0), height - side)
    return (left, top, left + side, top + side)
