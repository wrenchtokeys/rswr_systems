"""
Tap-to-crop for repair damage photos.

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


def process_tap_coordinates(repair, post_data, technician=None,
                            key_prefix='', key_suffix=''):
    """Create crops for whichever crop_x_/crop_y_ pairs are in the POST.

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
                "Ignoring unparseable tap coords for repair %s %s: %r/%r",
                repair.pk, source_field, raw_x, raw_y,
            )
            continue
        try:
            save_crop_for(
                repair, source_field, center_x_pct, center_y_pct,
                technician=technician,
            )
        except Exception:
            logger.exception(
                "Tap-to-crop failed for repair %s %s", repair.pk, source_field,
            )


def save_crop_for(repair, source_field, center_x_pct, center_y_pct,
                  technician=None, confirmed_by_human=True, suggestion=None):
    """Crop a square around the tap point and upsert the RepairPhotoCrop.

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

    photo = getattr(repair, source_field, None)
    if not photo:
        return None

    defaults = {
        'tenant': repair.tenant,
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
            "Could not crop %s of repair %s; recording tap only",
            source_field, repair.pk,
        )

    crop, created = RepairPhotoCrop.objects.update_or_create(
        repair=repair, source_field=source_field, defaults=defaults,
    )
    if not created and crop.cropped_image:
        crop.cropped_image.delete(save=False)
        crop.cropped_image = None
    if content is not None:
        crop.cropped_image.save(
            f'repair{repair.pk}_{source_field}.jpg', content, save=True,
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
        crop.repair, crop.source_field,
        crop.center_x_pct, crop.center_y_pct,
        technician=crop.created_by,
        confirmed_by_human=crop.confirmed_by_human,
        suggestion=suggestion,
    )
    return bool(refreshed and refreshed.cropped_image)


def delete_crops_for(repair, source_field):
    """Remove the crop (row and file) when its source photo is deleted."""
    for crop in repair.photo_crops.filter(source_field=source_field):
        if crop.cropped_image:
            crop.cropped_image.delete(save=False)
        crop.delete()


def apply_suggestion(repair, source_field, suggestion=None):
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

    if not getattr(repair, source_field, None):
        return None
    if repair.photo_crops.filter(source_field=source_field).exists():
        return None
    if suggestion is None:
        suggestion = suggest_for(repair, source_field)
    if suggestion is None:
        return None
    return save_crop_for(
        repair, source_field, suggestion.x_pct, suggestion.y_pct,
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
