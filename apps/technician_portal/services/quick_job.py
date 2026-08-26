"""
Quick job creation — the one place a shop-created job is built.

Extracted from `views/jobs.py::job_create` (FIELD_OPS S10) so the schedule
page's quick-add endpoint can create a job without owning a second copy of
this logic. There is exactly one thing worth protecting here and it is not
the field mapping: it is that **a job is created through `save()`**. Pricing
(`calculate_repair_cost`), tax (`TaxService`) and the auto-approve decision
(`resolve_initial_shop_status`) all run inside the model's `save()`, so a
creation path that builds rows any other way silently diverges on money and
on status. The no-`save()` house rule that governs `schedule_swap` and
`schedule_booking` applies to moving a *time*, never to creating a job.

What stayed behind in the view on purpose: completion, invoicing,
`send_and_invoice`, `messages`, and every redirect. Those are the view's
job. This module raises `QuickJobError` and lets each caller render it —
`messages.warning` + redirect for the form, JSON for the endpoint.
"""

import logging
from decimal import Decimal

from django.db import transaction

from apps.technician_portal.models import Replacement, Repair, Technician

logger = logging.getLogger(__name__)


class QuickJobError(Exception):
    """A refusal the caller renders. `.status` is the HTTP status a JSON
    caller should use; `.suggestions` carries the duplicate-customer picks
    when the refusal is "did you mean this person?"."""

    def __init__(self, message, *, status=400, suggestions=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.suggestions = suggestions or []


def allowed_service_types(tenant):
    """The service types this shop sells, in display order.

    One definition. The form, the view and the endpoint all gate on this, and
    a shop that only does repairs must never be handed a 'replacement'.
    """
    types = []
    if tenant.offers_repairs:
        types.append('repair')
    if tenant.offers_replacements:
        types.append('replacement')
    return types


def shop_tax_state(tenant):
    """(enabled, rate) for the shop — drives the "Charge sales tax" box.

    Returns rate None when tax is off, so a caller can tell "no tax
    configured" from "configured at 0%".
    """
    from apps.billing.services.tax_service import TaxService

    svc = TaxService(tenant=tenant)
    enabled = svc.is_tax_enabled()
    rate = svc.calculate_tax(subtotal=Decimal('0'))['rate'] if enabled else None
    return enabled, rate


def resolve_technician(tenant, actor_user, service_type, customer=None):
    """The tech to assign a quick-created job to, and whether anyone chose them.

    Returns `(technician, needs_assignment)`. The order is:

    1. The actor's own profile, if it can do this kind of work. A tech
       logging the walk-in they just handled keeps it — rotating their own
       job away to a colleague is never what the shop meant.
    2. Otherwise the shop's `assignment_strategy` — the same decision the
       customer portal makes, so a dispatcher creating a job in-app gets the
       shop's configured behaviour instead of an arbitrary first row. This is
       the half the setting used to skip entirely. (CODE-279)
    3. Otherwise any active tech with the matching ability, flagged
       `needs_assignment` — `technician` is NOT NULL, so somebody has to go
       on the row; the flag says nobody picked them.

    Returns `(None, True)` only for a shop with no technicians at all, which
    is a real problem for the caller to report.
    """
    from apps.tenants.services.assignment_service import select_technician

    tech = Technician.objects.filter(user=actor_user, tenant=tenant).first()
    if tech and _can_perform(tech, service_type):
        return tech, False

    strategy_pick = select_technician(
        tenant, customer=customer, service_type=service_type)
    if strategy_pick:
        return strategy_pick, False

    qs = Technician.objects.filter(tenant=tenant, is_active=True)
    ability_qs = (
        qs.filter(can_replace=True) if service_type == 'replacement'
        else qs.filter(can_repair=True)
    )
    return (ability_qs.first() or qs.first()), True


def _can_perform(technician, service_type):
    """Is this tech allowed to do this kind of work?

    An inactive or ability-less profile falls through to the shop strategy
    rather than taking the job: assigning work to a deactivated tech or one
    with `can_repair=False` makes it invisible to the people who can do it
    (the CODE-160 failure, from the other direction).
    """
    if not technician.is_active:
        return False
    return (technician.can_replace if service_type == 'replacement'
            else technician.can_repair)


def resolve_customer(tenant, data, actor_user):
    """An existing pick, or a new individual created inline.

    Raises QuickJobError(409, suggestions=[...]) when the typed name looks
    like somebody already on file. That is a question, not an error: the
    caller shows the matches and resubmits with `confirmed_new_customer` when
    the shop says "no, different person".
    """
    from apps.tenants.services.usage_service import UsageService
    from apps.technician_portal.services.customer_service import (
        create_individual, find_individual_matches, service_summary,
    )

    customer = data.get('customer')
    if customer is not None:
        return customer

    can_add, add_msg = UsageService(tenant).can_add_customer()
    if not can_add:
        raise QuickJobError(add_msg, status=403)

    if not data.get('confirmed_new_customer'):
        matches = find_individual_matches(
            tenant,
            name=data['new_customer_name'],
            phone=data.get('new_customer_phone'),
        )
        if matches:
            raise QuickJobError(
                f"Looks like {data['new_customer_name']} is already a customer.",
                status=409,
                suggestions=[{
                    'id': m.id,
                    'name': m.name,
                    'phone': m.phone or '',
                    'summary': service_summary(m),
                } for m in matches[:3]],
            )

    return create_individual(
        tenant,
        name=data['new_customer_name'],
        phone=data.get('new_customer_phone'),
        email=data.get('new_customer_email'),
    )


def build_job(*, tenant, data, customer, technician, shop_tax_enabled):
    """The unsaved Repair/Replacement for `data` — no side effects.

    Split out from create_job so the field mapping is readable and testable
    on its own; everything that touches the database lives in create_job.
    """
    common = dict(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number=data.get('unit_number') or '',
        cost_override=data.get('price'),
        # Only meaningful when the shop charges tax: unchecking the "Charge
        # sales tax" box marks the job no-tax (cash deal). When shop tax is
        # off the box isn't rendered, so leave no_tax False — enabling tax
        # later behaves normally.
        no_tax=shop_tax_enabled and not data.get('charge_tax'),
        vehicle_year=data.get('vehicle_year'),
        vehicle_make=data.get('vehicle_make') or '',
        vehicle_model=data.get('vehicle_model') or '',
        customer_notes=data.get('customer_notes') or '',
        internal_notes=data.get('internal_notes') or '',
        damage_photo_before=data.get('damage_photo_before'),
        damage_photo_after=data.get('damage_photo_after'),
        insurance_claim=data.get('insurance_claim') or False,
        insurance_company=data.get('insurance_company') or '',
        claim_number=data.get('claim_number') or '',
        deductible=data.get('deductible'),
        # Booking time — the form clears it for already-completed jobs, so a
        # walk-in never lands in a schedule bucket. The quick-add endpoint
        # leaves this None and books through confirm_appointment instead, so
        # that scheduled_window_end gets set like every other booked job.
        scheduled_for=data.get('scheduled_for'),
        # Service location — the form blanks an untouched prefill (== the
        # customer's address), so only real overrides land.
        service_address=data.get('service_address') or '',
        service_city=data.get('service_city') or '',
        service_state=data.get('service_state') or '',
        service_zip=data.get('service_zip') or '',
    )
    if data['service_type'] == 'repair':
        return Repair(
            technician_notes=data.get('work_done') or '',
            damage_type=data.get('damage_type') or '',
            damage_location_x=data.get('damage_location_x'),
            damage_location_y=data.get('damage_location_y'),
            windshield_temperature=data.get('windshield_temperature'),
            resin_viscosity=data.get('resin_viscosity') or '',
            drilled_before_repair=data.get('drilled_before_repair') or False,
            **common,
        )
    return Replacement(
        description=data.get('work_done') or '',
        glass_position=data.get('glass_position') or '',
        glass_type=data.get('glass_type') or '',
        nags_number=data.get('nags_number') or '',
        requires_adas_calibration=data.get('requires_adas_calibration') or False,
        adas_calibration_cost=data.get('adas_calibration_cost'),
        **common,
    )


def save_extra_charges(service, charges, tenant, taxable=True):
    """Replace the job's extra charges (trip fee etc.) with the parsed rows.

    These must exist before any complete/invoice step so auto-invoicing picks
    them up.
    """
    from apps.technician_portal.models import JobCharge

    service.extra_charges.all().delete()
    field = 'replacement' if isinstance(service, Replacement) else 'repair'
    for desc, amount in charges:
        JobCharge.objects.create(
            tenant=tenant,
            description=desc,
            amount=amount,
            taxable=taxable,
            **{field: service},
        )


@transaction.atomic
def create_job(*, tenant, actor_user, data, charges=None,
               notify_assignment=True):
    """Create one shop job from validated QuickJobForm data.

    `data` is `QuickJobForm.cleaned_data`. Returns the saved Repair or
    Replacement. Raises QuickJobError for every refusal a caller has to
    render: plan limits (403), an unconfirmed duplicate customer (409, with
    `.suggestions`), and a shop with no technician (400).

    `notify_assignment=False` suppresses the "you've been assigned" message —
    used when the caller is about to send a better one (an already-completed
    walk-in has nothing to announce, and quick-add lets the booking
    notification carry the news so one motion sends one message).
    """
    from apps.tenants.services.usage_service import UsageService

    can_create, limit_msg = UsageService(tenant).can_create_repair()
    if not can_create:
        raise QuickJobError(limit_msg, status=403)

    customer = resolve_customer(tenant, data, actor_user)

    # An explicit pick from "More details" wins; otherwise fall back to the
    # shop's assignment strategy.
    technician = data.get('technician')
    needs_assignment = False
    if technician is None:
        technician, needs_assignment = resolve_technician(
            tenant, actor_user, data['service_type'], customer=customer)
    if technician is None:
        raise QuickJobError(
            'No active technician found for this shop. '
            'Add one under Team settings first.',
            status=400,
        )

    shop_tax_enabled, _ = shop_tax_state(tenant)
    service = build_job(
        tenant=tenant, data=data, customer=customer,
        technician=technician, shop_tax_enabled=shop_tax_enabled,
    )

    # Assignment signal: notify the assigned tech when someone else created
    # the job for them — but not about their own creations. A job nobody
    # picked notifies the managers instead (see notify_needs_assignment).
    service.needs_assignment = needs_assignment
    service._assignment_actor_user_id = actor_user.id
    if not notify_assignment:
        service._skip_assignment_notifications = True
    service.save()

    if needs_assignment:
        from apps.technician_portal.services.assignments import (
            notify_needs_assignment,
        )
        notify_needs_assignment(service)

    if charges:
        save_extra_charges(
            service, charges, tenant, taxable=not service.no_tax,
        )

    return service
