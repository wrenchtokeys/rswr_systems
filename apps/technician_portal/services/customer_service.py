"""
Individual (non-fleet) customer creation and lookup.

One home for the two flows that used to disagree: the quick job form errored
on a duplicate name while the repair form silently created "John Smith (2)".
The new contract: individuals are searchable, duplicates are SUGGESTED to the
tech (with job history context), and a confirmed submit may create a second
person with the same name — people share names, the DB constraint only forces
uniqueness for FLEET business names.
"""

import re

from django.db.models import Count, Max, Q

from core.models import Customer

# RETAIL and WALK_IN are both "Individual" in the UI; new ones are RETAIL.
INDIVIDUAL_TYPES = ('RETAIL', 'WALK_IN')


def normalize_phone(phone):
    """Digits only, for comparing phone numbers written different ways."""
    return re.sub(r'\D', '', phone or '')


def individuals_queryset(tenant):
    """All individuals for a shop, annotated with job history context."""
    return (
        Customer.objects
        .filter(tenant=tenant, customer_type__in=INDIVIDUAL_TYPES)
        .annotate(
            # Repairs soft-delete via deleted_at; the reverse relation sees
            # every row, so filter deleted ones out of the history counts.
            repair_count=Count(
                'repair', distinct=True,
                filter=Q(repair__deleted_at__isnull=True)),
            replacement_count=Count('replacement', distinct=True),
            last_repair=Max(
                'repair__service_date',
                filter=Q(repair__deleted_at__isnull=True)),
            last_replacement=Max('replacement__service_date'),
        )
    )


def find_individual_matches(tenant, name='', phone=''):
    """Existing individuals that look like the one about to be created.

    Matched on exact (case-insensitive) name or same phone digits. Used to
    suggest "this person already exists" before creating a duplicate.
    """
    name = (name or '').strip()
    digits = normalize_phone(phone)

    q = Q()
    if name:
        q |= Q(name__iexact=name)
    if digits:
        # Phone is stored formatted; compare a digits-only version
        q |= Q(phone__isnull=False) & ~Q(phone='')
    if not q:
        return Customer.objects.none()

    candidates = individuals_queryset(tenant).filter(q)
    if digits and not name:
        return [c for c in candidates if normalize_phone(c.phone) == digits]
    if digits:
        return [
            c for c in candidates
            if c.name.lower() == name.lower() or normalize_phone(c.phone) == digits
        ]
    return list(candidates)


def create_individual(tenant, name, phone=None, email=None):
    """Create a new individual (RETAIL) customer. No suffixing, no dedupe —
    callers run find_individual_matches() first and confirm with the tech."""
    return Customer.objects.create(
        tenant=tenant,
        name=(name or '').strip(),
        phone=(phone or '').strip() or None,
        email=(email or '').strip() or None,
        customer_type='RETAIL',
    )


def service_summary(customer):
    """Human line for suggestion cards / search results:
    "3 previous jobs · last visit May 12, 2026" (empty string when no jobs).

    Works on customers annotated by individuals_queryset(); falls back to
    querying when the annotations are missing.
    """
    repair_count = getattr(customer, 'repair_count', None)
    if repair_count is None:
        repair_count = customer.repair_set.count()
        replacement_count = customer.replacement_set.count()
        last_repair = customer.repair_set.aggregate(m=Max('service_date'))['m']
        last_replacement = customer.replacement_set.aggregate(m=Max('service_date'))['m']
    else:
        replacement_count = customer.replacement_count or 0
        last_repair = customer.last_repair
        last_replacement = customer.last_replacement

    total = (repair_count or 0) + (replacement_count or 0)
    if not total:
        return ''
    last = max(d for d in (last_repair, last_replacement) if d is not None)
    job_word = 'job' if total == 1 else 'jobs'
    return f"{total} previous {job_word} · last visit {last.strftime('%b %-d, %Y')}"
