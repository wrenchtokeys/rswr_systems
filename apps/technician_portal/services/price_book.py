"""
Shop-owned price book — learning, lookup, rebuild (B6).

See apps/technician_portal/price_book_models.py for what a row means. This
module is the only writer of PriceBookEntry outside the owner's edit page,
and the only reader the forms use.

    learn_from_job(job)            Replacement.save on COMPLETED
    learn_from_job(job, source=QUOTE)   Mygrant apply (a quote, not a charge)
    rebuild_for_tenant(tenant)     seed_price_book / "Rebuild from history"
    suggest(tenant, ...)           the form endpoint; never writes
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.technician_portal.price_book_models import ANY_YEAR, PriceBookEntry, normalize_key

logger = logging.getLogger(__name__)

MATCH_EXACT = 'exact'
MATCH_ANY_YEAR = 'any_year'
MATCH_NEAREST_YEAR = 'nearest_year'


# --- what a job says ----------------------------------------------------------

def list_price_of(job):
    """The pre-discount price a replacement was charged, or None.

    cost_override is what the shop typed as "the price" (save() discounts it
    afterwards, so it is the right thing to remember). Without one the price
    is parts + labor + ADAS, the same sum Replacement.save uses. Zero and
    negative mean "not priced" — a customer-portal request the shop has not
    priced yet must not teach the book that this glass is free.
    """
    if job.cost_override is not None:
        price = Decimal(job.cost_override)
    else:
        price = PriceBookEntry.total_of(
            job.parts_cost, job.labor_cost,
            job.adas_calibration_cost if job.requires_adas_calibration else None,
        )
    return price if price > 0 else None


def _key_of(job):
    return dict(
        tenant=job.tenant,
        make_key=normalize_key(job.vehicle_make),
        model_key=normalize_key(job.vehicle_model),
        vehicle_year=job.vehicle_year or ANY_YEAR,
        glass_position=job.glass_position or '',
    )


def learn_from_job(job, *, source=PriceBookEntry.SOURCE_LEARNED, count=True):
    """Record what `job` charged for its vehicle + glass. Returns the row or None.

    Idempotent per job: `count` says whether this call is the job's first
    completion (bump times_used) or a later re-save of the same job (only
    refresh the price if this job is the one the row was learned from — a
    price correction propagates, an older job re-saved does not clobber a
    newer price).
    """
    if job.tenant_id is None or not (job.vehicle_make and job.vehicle_model):
        return None
    price = list_price_of(job)
    if price is None:
        return None
    key = _key_of(job)
    values = dict(
        vehicle_make=job.vehicle_make,
        vehicle_model=job.vehicle_model,
        parts_cost=job.parts_cost,
        labor_cost=job.labor_cost,
        adas_calibration_cost=(
            job.adas_calibration_cost if job.requires_adas_calibration else None
        ),
        price=price,
        last_job=job,
        last_used_at=timezone.now(),
    )
    with transaction.atomic():
        entry = (
            PriceBookEntry.objects.select_for_update()
            .filter(**key).first()
        )
        if entry is None:
            return PriceBookEntry.objects.create(
                source=source, times_used=1 if source != PriceBookEntry.SOURCE_QUOTE else 0,
                **key, **values,
            )
        if entry.is_pinned:
            # The owner's number wins. Still count the job so the row shows
            # it is in use.
            if source == PriceBookEntry.SOURCE_LEARNED and count:
                entry.times_used += 1
                entry.last_job = job
                entry.last_used_at = values['last_used_at']
                entry.save(update_fields=['times_used', 'last_job', 'last_used_at'])
            return entry
        if source == PriceBookEntry.SOURCE_QUOTE:
            if entry.source != PriceBookEntry.SOURCE_QUOTE:
                return entry     # a charge is never replaced by a quote
        elif not count and entry.last_job_id not in (None, job.pk):
            return entry         # a re-save of an older job; keep the newer price
        for field, value in values.items():
            setattr(entry, field, value)
        entry.source = source
        if count and source == PriceBookEntry.SOURCE_LEARNED:
            entry.times_used += 1
        entry.save()
        return entry


def rebuild_for_tenant(tenant):
    """Replay every completed replacement into LEARNED rows, oldest first.

    Pinned rows are kept (learning respects them); stale LEARNED and QUOTE
    rows are dropped first so a deleted job's price does not linger. Returns
    (jobs_read, rows_after).
    """
    from apps.technician_portal.models import Replacement

    jobs = (
        Replacement.objects.filter(tenant=tenant, queue_status='COMPLETED')
        .exclude(vehicle_make='').exclude(vehicle_model='')
        .order_by('service_date', 'pk')
    )
    with transaction.atomic():
        PriceBookEntry.objects.filter(tenant=tenant).exclude(
            source=PriceBookEntry.SOURCE_PINNED,
        ).delete()
        # Pinned rows restart their counts so the replay is the whole truth.
        PriceBookEntry.objects.filter(tenant=tenant).update(times_used=0, last_job=None)
        read = 0
        for job in jobs.iterator():
            read += 1
            learn_from_job(job, count=True)
    return read, PriceBookEntry.objects.filter(tenant=tenant).count()


# --- lookup --------------------------------------------------------------------

def resolve_vehicle(tenant, *, customer_id=None, unit_number='', year=None, make='', model=''):
    """Fill blank year/make/model from what the shop has on file for this unit.

    The job form keeps year/make/model behind "More details", so a fleet
    tech usually types only the unit number. The vehicle behind that unit
    is on every earlier job for the same customer + unit (both kinds — a
    windshield repaired last spring taught us it is a 2019 F-150).
    """
    make, model = (make or '').strip(), (model or '').strip()
    if (make and model) or not customer_id or not (unit_number or '').strip():
        return year, make, model
    from apps.technician_portal.models import Repair, Replacement
    unit = unit_number.strip()
    for model_cls in (Replacement, Repair):
        prior = (
            model_cls.objects.filter(
                tenant=tenant, customer_id=customer_id, unit_number__iexact=unit,
            )
            .exclude(vehicle_make='').exclude(vehicle_model='')
            .order_by('-service_date', '-pk')
            .values('vehicle_year', 'vehicle_make', 'vehicle_model')
            .first()
        )
        if prior:
            return (
                year or prior['vehicle_year'],
                make or prior['vehicle_make'],
                model or prior['vehicle_model'],
            )
    return year, make, model


def suggest(tenant, *, year=None, make='', model='', glass_position=''):
    """The row to offer for this vehicle + glass, or None.

    Returns {'entry', 'match'} where match is exact / any_year / nearest_year.
    """
    make_key, model_key = normalize_key(make), normalize_key(model)
    if not (tenant and make_key and model_key):
        return None
    vehicle_rows = PriceBookEntry.objects.filter(
        tenant=tenant, make_key=make_key, model_key=model_key,
    )
    rows = list(vehicle_rows.filter(glass_position=glass_position or ''))
    if not rows and not glass_position:
        # The job form leaves "Glass position" optional, so a blank request
        # is "the usual glass", not "glass with no position". A windshield is
        # the usual; failing that, whatever this shop did on this vehicle
        # last. The note names the glass either way, so nothing is silent.
        rows = list(vehicle_rows.filter(glass_position='WINDSHIELD'))
        if not rows:
            rows = list(vehicle_rows.order_by('-last_used_at', '-pk'))
    if not rows:
        return None
    try:
        year = int(year) if year not in (None, '') else None
    except (TypeError, ValueError):
        year = None
    if year:
        for entry in rows:
            if entry.vehicle_year == year:
                return {'entry': entry, 'match': MATCH_EXACT}
    for entry in rows:
        if entry.is_any_year:
            return {'entry': entry, 'match': MATCH_ANY_YEAR if year else MATCH_EXACT}
    dated = [e for e in rows if not e.is_any_year]
    if year:
        dated.sort(key=lambda e: (abs(e.vehicle_year - year), -(e.last_used_at.timestamp() if e.last_used_at else 0)))
    else:
        dated.sort(key=lambda e: -(e.last_used_at.timestamp() if e.last_used_at else 0))
    return {'entry': dated[0], 'match': MATCH_NEAREST_YEAR if year else MATCH_EXACT}


def describe(found, *, requested_year=None):
    """One sentence a tech can read: where the number came from."""
    entry, match = found['entry'], found['match']
    what = f'{entry.vehicle_label} {entry.glass_label.lower()}'
    if entry.is_pinned:
        head = f'Your price book lists {what} at ${entry.price:,.2f}'
    elif entry.source == PriceBookEntry.SOURCE_QUOTE:
        head = f'Supplier quote on file for {what}: ${entry.price:,.2f}'
    else:
        n = entry.times_used
        head = (
            f'You charged ${entry.price:,.2f} for {what}'
            + (f' ({n} jobs)' if n > 1 else ' last time')
        )
    if match == MATCH_NEAREST_YEAR and requested_year:
        head += f' — closest year to {requested_year} in your book'
    elif match == MATCH_ANY_YEAR:
        head += ' — any year'
    return head + '.'


def serialize(found, *, requested_year=None):
    entry = found['entry']
    return {
        'success': True,
        'found': True,
        'entry_id': entry.pk,
        'match': found['match'],
        'price': str(entry.price),
        'parts_cost': str(entry.parts_cost) if entry.parts_cost is not None else None,
        'labor_cost': str(entry.labor_cost) if entry.labor_cost is not None else None,
        'adas_calibration_cost': (
            str(entry.adas_calibration_cost)
            if entry.adas_calibration_cost is not None else None
        ),
        'has_breakdown': entry.has_breakdown,
        'source': entry.source,
        'times_used': entry.times_used,
        'vehicle': entry.vehicle_label,
        'glass': entry.glass_label,
        'note': describe(found, requested_year=requested_year),
    }


NOT_FOUND = {'success': True, 'found': False}
