"""
Which damage photos are still missing a human's mark.

This is P4a.1 (docs/strategy/PHOTO_ML_SESSIONS.md). The arc spent four
sessions building places to tap and none showing what a tap is worth, and
production answered with a marking rate of one photo in seventy-seven. P6
fixed the payoff — a marked break now frames the photo on the customer's
invoice and in their portal — and this module answers the other half: *which*
of the photos already sitting in the database are worth a human's fifteen
seconds, and in what order.

Three rules decide that, and all three are here rather than in the view:

1. **An "after" photo is never in the queue.** It labels ``not_applicable``
   (a resin-filled chip is a photo of the outcome, not the decision), and P6
   deliberately does not zoom it on any customer surface either — magnifying
   a repair's blemish shows the customer the scar instead of the fix. There
   is nothing at either end of the tap, so it is not offered.
2. **"Marked" means marked by a human.** A row the P3 sweep guessed at
   (``confirmed_by_human=False``) is excluded from the dataset export by
   design, so it still needs a person; it stays in the queue, ordered last,
   and opens with the machine's guess pre-placed so confirming is a glance.
3. **Trainable first.** A completed job's photo carries a real label today;
   an unfinished job's photo carries ``unknown`` until somebody finishes the
   work. Both are worth marking — the customer-facing close-up does not care
   about labels — but the completed ones are the ones this arc is short of.

The label rules themselves are NOT duplicated here: ``label_for_photo`` in
``photo_dataset`` is the single source, reached one step earlier than usual
because these photos have no crop row yet.
"""
import logging

from django.db.models import Case, Exists, IntegerField, OuterRef, Value, When

from apps.technician_portal.services.photo_dataset import (
    NOT_APPLICABLE, TRAINABLE_LABELS, UNKNOWN, label_for_photo,
)

logger = logging.getLogger(__name__)

# The two fields worth a human tap. `damage_photo_after` is deliberately
# absent — see rule 1 above.
MARKABLE_FIELDS = ('damage_photo_before', 'customer_submitted_photo')

# How many items one page of the queue holds, and the ceiling the entry-point
# count reports before it gives up and says "200+". A backlog this long is
# not a session's work anyway, and the page re-queries on every load, so
# finishing a page and reloading picks up the next batch.
QUEUE_LIMIT = 200

# Ordering tiers, lowest number first. Within a tier, newest job first.
_TIER_TRAINABLE = 0     # completed job: the label exists today
_TIER_UNKNOWN = 1       # job still open: labelled when the work finishes
_TIER_NOT_APPLICABLE = 2  # tempered glass; worth marking for the customer only

_PROMPTS = {
    'damage_photo_before': 'Tap the break',
    'customer_submitted_photo': 'Tap the break the customer photographed',
}


class BacklogItem:
    """One unmarked photo, with everything the queue page needs to show it.

    Deliberately not a model and not cached anywhere: the queue is a
    question about the current state of the database, asked fresh each time
    the page loads. A marked photo simply stops appearing.
    """

    __slots__ = ('job', 'kind', 'source_field', 'label', 'label_source', 'crop')

    def __init__(self, job, kind, source_field, label, label_source, crop=None):
        self.job = job
        self.kind = kind
        self.source_field = source_field
        self.label = label
        self.label_source = label_source
        self.crop = crop

    @property
    def tier(self):
        if self.label in TRAINABLE_LABELS:
            return _TIER_TRAINABLE
        if self.label == UNKNOWN:
            return _TIER_UNKNOWN
        return _TIER_NOT_APPLICABLE

    @property
    def sort_key(self):
        # Newest first inside a tier: a recent job is the one still on an
        # invoice somebody might look at.
        return (self.tier, -(self.job.service_date.timestamp()), -self.job.pk)

    @property
    def photo_url(self):
        # The shop-side route, not the storage URL — the queue is a shop
        # page and the media bucket's repair_photos/* prefix is private (P8).
        from apps.technician_portal.services.photo_serving import shop_photo_url
        return shop_photo_url(self.job, self.source_field)

    @property
    def prompt(self):
        return _PROMPTS.get(self.source_field, 'Tap the break')

    @property
    def title(self):
        """'Repair #12' / 'Replacement #4' — the job, not the customer."""
        return f"{self.kind.title()} #{self.job.pk}"

    @property
    def subtitle(self):
        """Customer and vehicle, in that order, dropping whatever is blank.

        ``get_vehicle_label()`` and not the raw ``unit_number`` column: an
        individual's is empty and printing "Unit #" with nothing after it is
        the documented fleet-vs-individual trap (CLAUDE.md).
        """
        parts = []
        customer = getattr(self.job, 'customer', None)
        if customer is not None and customer.name:
            parts.append(customer.name)
        vehicle = self.job.get_vehicle_label()
        if vehicle:
            parts.append(vehicle)
        return ' · '.join(parts)

    @property
    def why(self):
        """One short line saying what marking this photo is worth."""
        if self.label in TRAINABLE_LABELS:
            return 'Completed job'
        if self.label == UNKNOWN:
            return 'Job still open'
        return 'Tempered glass'


def _unmarked_for_field(model, kind, tenant, source_field, limit, detail=True):
    """Jobs of one model carrying a photo in ``source_field`` that no human
    has marked.

    ``confirmed_by_human=True`` — not merely "a crop row exists" — because a
    machine guess nobody has looked at is excluded from the dataset export
    and is exactly the thing this queue exists to put in front of a person.

    Bounded at the database, not in Python: a shop with thousands of
    unmarked photos must not load them all to render one page. Completed
    jobs come first so the slice keeps the photos whose label exists today,
    which is the same priority the Python tiering applies afterwards — on a
    backlog longer than ``limit`` the tiering therefore sorts the newest
    ``limit`` rather than the whole history, and the page says so.
    """
    from apps.technician_portal.models import RepairPhotoCrop

    if tenant is None:
        return model.objects.none()

    confirmed = RepairPhotoCrop.objects.filter(
        source_field=source_field,
        confirmed_by_human=True,
        **{kind: OuterRef('pk')},
    )
    qs = (
        model.objects
        .filter(tenant=tenant)
        .exclude(**{source_field: ''})
        .exclude(**{f'{source_field}__isnull': True})
        .annotate(_marked=Exists(confirmed))
        .filter(_marked=False)
        .annotate(_open=Case(
            When(queue_status='COMPLETED', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ))
        .order_by('_open', '-service_date', '-pk')
        # technician is needed by the permission check on every row, so the
        # join is cheaper than the N+1 it replaces.
        .select_related('technician')
    )
    if detail:
        qs = qs.select_related('customer').prefetch_related('photo_crops')
    return qs[:limit] if limit else qs


def _existing_crop(job, source_field):
    """The unconfirmed crop for this photo, if the sweep left one.

    Reads the prefetched rows rather than querying, so a page of 200 items
    costs the two prefetches the querysets already did.
    """
    for crop in job.photo_crops.all():
        if crop.source_field == source_field:
            return crop
    return None


def backlog_for(request, tenant, limit=QUEUE_LIMIT, include_not_applicable=True,
                detail=True):
    """The ordered worklist of photos needing a mark, for this user.

    Permission is checked with the same two helpers the crop endpoints use
    (``can_view_repair`` / ``_replacement_technician_access``) rather than a
    third copy: a queue that offers a job the save endpoint will refuse is a
    queue that hands a technician a 403 for doing what it asked.

    ``detail=False`` skips the joins only the rendered page needs — it is
    for the entry-point count, which runs on a page nobody came here to use.
    """
    from apps.saas.views import _replacement_technician_access
    from apps.technician_portal.decorators import is_tenant_admin
    from apps.technician_portal.models import Repair, Replacement, Technician
    from apps.technician_portal.views.repairs import can_view_repair

    if tenant is None:
        return []

    user_is_admin = is_tenant_admin(request.user, tenant=tenant)
    technician = Technician.objects.filter(
        user=request.user, tenant=tenant).first()

    items = []
    for model, kind in ((Repair, 'repair'), (Replacement, 'replacement')):
        for source_field in MARKABLE_FIELDS:
            unmarked = _unmarked_for_field(
                model, kind, tenant, source_field, limit, detail=detail)
            for job in unmarked:
                if kind == 'replacement':
                    allowed = _replacement_technician_access(
                        request, tenant, replacement=job)
                else:
                    allowed = can_view_repair(job, technician, user_is_admin)
                if not allowed:
                    continue
                label, label_source = label_for_photo(job, source_field)
                if label == NOT_APPLICABLE and not include_not_applicable:
                    continue
                items.append(BacklogItem(
                    job, kind, source_field, label, label_source,
                    crop=_existing_crop(job, source_field) if detail else None,
                ))

    items.sort(key=lambda item: item.sort_key)
    return items[:limit] if limit else items


def backlog_size(request, tenant, limit=QUEUE_LIMIT):
    """How many photos are waiting, capped at ``limit``.

    Runs the same query as ``backlog_for`` on purpose. A cheaper count that
    skipped the permission filter would tell a technician there are forty
    photos to mark and then show them three.
    """
    return len(backlog_for(request, tenant, limit=limit, detail=False))
