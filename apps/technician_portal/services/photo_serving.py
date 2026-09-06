"""
Serve a damage photo through the app, not from a public bucket (P8).

Until this module existed every `<img>` of a customer's damage photo pointed
straight at S3, and the bucket policy made `media/*` world-readable. The
invoice's HMAC token protected the *page*, not the photos on it: anybody who
guessed a filename — and the filenames were the technician's phone's
sequential originals — got the photo. These are real customers' vehicles,
photographed at their homes and yards, in a database that also knows the
plate, the unit and the company.

So a photo is now a *route*, and the route is gated exactly like the P7 ZIP
on the same surface:

* the shop — `_job_access`, the gate the crop endpoints already use;
* the customer portal — `customer=`/`tenant=` scoping, like the detail page;
* the public invoice — `_resolve_public_invoice` and the job must be billed
  on that invoice.

That is what lets the bucket's `repair_photos/*` prefix go private without
breaking a single surface. Three things here are deliberate:

* **Bytes come from storage (`field.open()`), never from the photo's URL.**
  The server re-fetching its own S3 URL over HTTP is the anonymous round
  trip this session exists to close.
* **App-served, not presigned.** A signed URL expires; this repository has
  already paid for that once (photos were pulled from the repair-completed
  email for exactly that reason). A route does not expire, `img-src` stays
  `'self'`, and the gate is the same code that decides who may download the
  ZIP, so the two cannot disagree.
* **The URL carries a version, so a browser may cache it.** Every route
  answers on a stable path for the *field* — `/photos/damage_photo_before/`
  — and a technician can replace that photo. The `?v=` is derived from the
  stored filename, which changes when the file does, so `Cache-Control:
  private` is safe and a replaced photo is never served stale.

Shop logos are NOT served here. They are `<img src>` in email, opened days
later on a machine with no session, and stay on their public prefix.
"""
import hashlib
import logging
import os

from django.http import FileResponse, Http404
from django.urls import reverse

from apps.technician_portal.services.photo_crops import SOURCE_FIELDS

logger = logging.getLogger(__name__)

# What a browser may do with an authenticated photo: keep it for itself, for
# a day. `private` keeps it out of any shared cache — the URL of the public
# invoice route carries the invoice's token, and a proxy must not hold it.
CACHE_CONTROL = 'private, max-age=86400'


def kind_of(job):
    """'repair' or 'replacement' — the word the URL patterns use."""
    from apps.technician_portal.models import Replacement
    return 'replacement' if isinstance(job, Replacement) else 'repair'


def version_of(field):
    """A short token that changes when the stored file does.

    The route path names the *field*, not the file, so this is what stops a
    browser showing the old photo after a technician uploads a new one.
    """
    name = getattr(field, 'name', '') or ''
    return hashlib.sha1(name.encode('utf-8')).hexdigest()[:8]


def _versioned(url, field):
    return f'{url}?v={version_of(field)}'


def shop_photo_url(job, field_name):
    """The shop-side route for one of a job's photos, or '' when it has none."""
    field = getattr(job, field_name, None)
    if not field or field_name not in SOURCE_FIELDS or not getattr(job, 'pk', None):
        return ''
    url = reverse(f'{kind_of(job)}_photo', args=[job.pk, field_name])
    return _versioned(url, field)


def shop_crop_url(crop):
    """The shop-side route for a crop's close-up thumbnail, or ''.

    Versioned by the row's `updated_at` rather than the filename: a re-tap
    rewrites the crop at the same name, so the name alone would never change.
    """
    if crop is None or not crop.cropped_image:
        return ''
    job = crop.service
    if job is None or not getattr(job, 'pk', None):
        return ''
    url = reverse(f'{kind_of(job)}_crop_thumb', args=[job.pk, crop.source_field])
    stamp = int(crop.updated_at.timestamp()) if crop.updated_at else 0
    return f'{url}?v={stamp}'


def customer_photo_url(job, field_name):
    """The customer-portal route for one of a job's photos, or ''."""
    field = getattr(job, field_name, None)
    if not field or field_name not in SOURCE_FIELDS or not getattr(job, 'pk', None):
        return ''
    url = reverse(f'customer_{kind_of(job)}_photo', args=[job.pk, field_name])
    return _versioned(url, field)


def public_photo_url(invoice_id, token, job, field_name):
    """The token-gated route for a photo on the public invoice page, or ''."""
    field = getattr(job, field_name, None)
    if not field or field_name not in SOURCE_FIELDS:
        return ''
    url = reverse('public_invoice_photo',
                  args=[invoice_id, token, kind_of(job), job.pk, field_name])
    return _versioned(url, field)


def photo_response(field):
    """Stream one stored photo, or 404.

    Reads through the storage backend — `field.open()`, not `field.url` —
    the way the P7 ZIP does. A file that will not open is a 404 on this
    route, never a 500 on the page that embeds it.
    """
    if not field:
        raise Http404("No photo.")
    try:
        handle = field.open('rb')
    except Exception as e:
        logger.warning(f"Photo serving: could not open {field.name!r}: {e}")
        raise Http404("Photo unavailable.")
    response = FileResponse(
        handle,
        filename=os.path.basename(field.name or ''),
        as_attachment=False,
    )
    response['Cache-Control'] = CACHE_CONTROL
    return response


def crop_for(job, field_name):
    """The crop row for one of a job's photos, or None."""
    return job.photo_crops.filter(source_field=field_name).first()
