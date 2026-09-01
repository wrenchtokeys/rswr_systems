"""
Let a customer KEEP the photos, not just look at them (P7 of the photo-ML arc).

P6/P6.1/P6.2 made the damage photo *legible* — framed on the break, and a
job with both shots rendered as one exhibit. None of them made it
**keepable**. A fleet manager's record is not a web page they have to find
again; it is a file in a folder, per unit, per date. Today the only way to
save one is right-click on the public invoice page, one photo at a time,
landing in Downloads as `IMG_4686.jpg` — no invoice, no unit, no date.

This module is the substrate for that: it turns jobs into named photo
entries and those entries into a ZIP, so every surface (public invoice,
customer portal, shop) names files identically.

Three things here are deliberate:

* **Bytes come from storage, never from the photo's own URL.** The server
  re-fetching its own public S3 URL over HTTP would be an anonymous round
  trip for a file it already has — and it breaks the day the media bucket
  is closed (see PHOTO_ML_SESSIONS.md, "the photos are world-readable").
* **Names go through `get_vehicle_label()`, never the raw `unit_number`.**
  An individual has no unit, and `Unit_.jpg` is the filename version of the
  `Unit  — Before` bug P6 already fixed (the individual-vs-fleet rule in
  CLAUDE.md applies to a filename exactly as it does to an invoice line).
* **Nothing is written to media or S3.** The archive is built in memory and
  streamed; it is not an asset, it is a response.

A photo that will not open is skipped and the rest of the ZIP still
downloads — same habit as the invoice page, which has always tolerated a
missing file rather than 500ing on the customer.
"""
import logging
import os
import re
import unicodedata
import zipfile
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone

logger = logging.getLogger(__name__)

# Every photo a GlassService can carry, in the order a customer reads them,
# and the word each one is named by. `photo_crops.SOURCE_FIELDS` is the same
# three fields for the crop pipeline; this is the customer-facing naming of
# them, which is a different concern and allowed to drift.
PHOTO_LABELS = (
    ('damage_photo_before', 'Before'),
    ('damage_photo_after', 'After'),
    ('customer_submitted_photo', 'Customer-submitted'),
)

# JPEGs do not compress, so deflating them costs CPU on every download and
# saves nothing. The ZIP here is a container, not a compressor.
ZIP_METHOD = zipfile.ZIP_STORED

# A guard, not a product limit: ~30 full-resolution phone photos. A whole
# invoice's worth is normally a few megabytes. If it ever trips, the ZIP
# says so in a README rather than quietly handing over a partial archive.
MAX_ZIP_BYTES = 150 * 1024 * 1024


def _slug(value):
    """Free text -> a filename fragment that survives every filesystem.

    A vehicle label is whatever the technician typed, so it can contain a
    slash, a quote, or an emoji. Everything outside [A-Za-z0-9] collapses to
    a single dash: 'Unit #4521' -> 'Unit-4521', '2019 Ford F-150' ->
    '2019-Ford-F-150'.
    """
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = text.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^A-Za-z0-9]+', '-', text).strip('-')


def _extension(field):
    """The stored file's extension, lowercased, defaulting to .jpg."""
    ext = os.path.splitext(getattr(field, 'name', '') or '')[1].lower()
    return ext if re.fullmatch(r'\.[a-z0-9]{1,5}', ext or '') else '.jpg'


def _job_date(job):
    """The day the work happened, as the customer would file it."""
    when = getattr(job, 'service_date', None)
    if not when:
        return ''
    try:
        if timezone.is_aware(when):
            when = timezone.localtime(when)
        return when.strftime('%Y-%m-%d')
    except Exception:
        return ''


def entries_for_job(job, invoice_number=''):
    """``[(filename, FieldFile)]`` for one job's photos, in reading order.

    The filename answers "what am I looking at" without the folder it landed
    in: `INV-1042_Unit-4521_2026-08-14_Before.jpg`. Any part the job has not
    got is dropped rather than printed empty — an individual contributes no
    unit segment at all.
    """
    stem_parts = [_slug(invoice_number), _slug(job.get_vehicle_label()),
                  _job_date(job)]
    stem = '_'.join(part for part in stem_parts if part)

    entries = []
    for source_field, label in PHOTO_LABELS:
        field = getattr(job, source_field, None)
        if not field:
            continue
        name = f'{stem}_{label}' if stem else label
        entries.append((f'{name}{_extension(field)}', field))
    return entries


def entries_for_jobs(jobs, invoice_number=''):
    """Every job's entries, with collisions broken by a numeric suffix.

    Two repairs on one unit on one day — a multi-break session, which is a
    normal ticket here — produce the same name twice. A ZIP will happily
    hold both and the customer's unzipper silently keeps one.
    """
    entries = []
    seen = {}
    for job in jobs:
        for filename, field in entries_for_job(job, invoice_number=invoice_number):
            stem, ext = os.path.splitext(filename)
            count = seen.get(filename, 0) + 1
            seen[filename] = count
            if count > 1:
                filename = f'{stem}-{count}{ext}'
            entries.append((filename, field))
    return entries


def build_photo_zip(entries):
    """``(zip_bytes, written_names)`` for ``[(filename, FieldFile)]``.

    Reads through the storage backend — `field.open()`, not `field.url` —
    and skips anything that will not open, because one photo the shop
    deleted out of S3 must not cost the customer the other five.
    """
    buffer = BytesIO()
    written = []
    skipped = []
    total = 0
    with zipfile.ZipFile(buffer, 'w', ZIP_METHOD) as archive:
        for filename, field in entries:
            if total >= MAX_ZIP_BYTES:
                skipped.append(filename)
                continue
            try:
                with field.open('rb') as handle:
                    data = handle.read()
            except Exception as e:
                logger.warning(f"Photo archive: skipping {field.name!r}: {e}")
                skipped.append(filename)
                continue
            archive.writestr(filename, data)
            written.append(filename)
            total += len(data)
        if skipped and written:
            # Never hand over a partial archive that looks complete.
            archive.writestr(
                'README.txt',
                'Some photos could not be included in this download:\n\n'
                + '\n'.join(f'  {name}' for name in skipped)
                + '\n\nPlease contact the shop for these.\n'
            )
    return buffer.getvalue(), written


def photo_zip_response(entries, download_name):
    """A ZIP download, or ``None`` when nothing could be read.

    ``None`` is the caller's cue to 404 rather than to hand the customer an
    empty archive they have to open to discover is empty.
    """
    payload, written = build_photo_zip(entries)
    if not written:
        return None
    response = HttpResponse(payload, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{download_name}"'
    response['Content-Length'] = str(len(payload))
    return response


def zip_name_for_invoice(invoice):
    return f'Invoice_{_slug(invoice.invoice_number) or invoice.pk}_Photos.zip'


def zip_name_for_job(job):
    parts = [_slug(job.get_vehicle_label()), _job_date(job)]
    stem = '_'.join(part for part in parts if part)
    return f'{stem}_Photos.zip' if stem else f'Job_{job.pk}_Photos.zip'


def job_has_photos(job):
    """Whether a download control should render at all."""
    return any(getattr(job, field, None) for field, _ in PHOTO_LABELS)
