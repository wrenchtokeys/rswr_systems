"""
Single write path for assigning technicians to jobs (fieldops N1).

Every place that changes who a Repair or Replacement belongs to should go
through ``assign_job`` (views) or rely on the model signals, which delegate
to ``notify_assignment_change`` here. Before this service existed there were
five hand-rolled assignment paths that each wrote a display-only
TechnicianNotification row and never touched NotificationService — so an
assigned tech got no email, no bell, nothing.

Notification rules (shared by helper and signals):

- The new technician gets ``repair_assigned`` (bell + email; SMS once live),
  unless they performed the assignment themselves.
- The old technician gets ``repair_reassigned_away``, unless they performed
  the reassignment themselves.
- No assignment notification while a job is REQUESTED — the request-submitted
  notification covers that stage, and "you're assigned" would be premature
  for work the shop hasn't accepted. The notification fires when the job
  leaves REQUESTED for APPROVED/IN_PROGRESS instead.
- Nothing fires for COMPLETED/DENIED jobs (logging history isn't assigning
  work).
"""

import logging

logger = logging.getLogger(__name__)

# Statuses in which telling a tech "this job is now yours" makes sense.
NOTIFIABLE_STATUSES = ('PENDING', 'APPROVED', 'IN_PROGRESS')


def _is_replacement(job):
    from apps.technician_portal.models import Replacement
    return isinstance(job, Replacement)


def _job_action_url(job):
    if _is_replacement(job):
        return f'/tech/replacement/{job.pk}/'
    return f'/tech/repairs/{job.pk}/'


def _job_label(job):
    return 'Replacement' if _is_replacement(job) else 'Repair'


def _booked_when(job):
    """'Tue Aug 19, 8:00 AM – 12:00 PM' for a job that has a time, else ''.

    Assignment emails carry the booked time whenever there is one (fieldops
    S5): the dispatch board can set who and when in a single click, and
    sending "you have a new job" followed by "your job has a time" is two
    messages for one decision. An assignment with no time renders nothing —
    the row is guarded in both templates.
    """
    from django.utils import timezone
    from django.utils.dateformat import format as format_date

    if not job.scheduled_for:
        return ''
    local_start = timezone.localtime(job.scheduled_for)
    when = f"{format_date(local_start, 'D M j')}, {format_date(local_start, 'g:i A')}"
    if job.scheduled_window_end:
        when += f" – {format_date(timezone.localtime(job.scheduled_window_end), 'g:i A')}"
    return when


def _assignment_context(job):
    """Flat, JSON-serializable context for the assignment templates."""
    customer_name = job.customer.name if job.customer else 'Unknown'
    tech = job.technician
    return {
        'scheduled_when': _booked_when(job),
        'repair_id': job.pk,
        'job_id': job.pk,
        'job_type': _job_label(job),
        'unit_number': job.unit_number or '',
        'customer_name': customer_name,
        'status': job.get_queue_status_display(),
        'technician_name': (
            (tech.user.get_full_name() or tech.user.username) if tech else ''
        ),
        'description': getattr(job, 'description', '') or '',
        'cost': float(job.cost or 0),
        'action_url': _job_action_url(job),
    }


def assign_job(job, new_technician, *, assigned_by=None, queue_status=None,
               notify=True, force_notify_new=False):
    """Assign/reassign a Repair or Replacement and notify the right techs.

    Args:
        job: Repair or Replacement instance.
        new_technician: Technician to assign (may equal the current one).
        assigned_by: the acting User — used to skip notifying someone about
            their own action.
        queue_status: optional new queue status set in the same save
            (assign_repair moves REQUESTED → APPROVED).
        notify: set False to suppress per-job notifications (bulk flows send
            one summary instead via notify_bulk_assignment).
        force_notify_new: notify the new tech even if the technician did not
            change — used when accepting a REQUESTED job that was already
            provisionally assigned to them.
    """
    old_technician = job.technician
    job.technician = new_technician
    if queue_status:
        job.queue_status = queue_status
    # The post_save signal is the fallback for paths that don't use this
    # helper; suppress it so helper calls decide notifications exactly once.
    job._assignment_notifications_handled = True
    job.save()

    if notify:
        notify_assignment_change(
            job, old_technician, new_technician,
            assigned_by=assigned_by, force_notify_new=force_notify_new,
        )
    return job


def notify_assignment_change(job, old_technician, new_technician, *,
                             assigned_by=None, force_notify_new=False):
    """Send assignment notifications for a technician change on *job*.

    Writes both the dashboard TechnicianNotification row and the real
    core.Notification (bell + email/SMS channels).
    """
    from apps.technician_portal.models import TechnicianNotification
    from core.services.notification_service import NotificationService

    actor_id = assigned_by.id if assigned_by is not None else None
    changed = (new_technician is not None
               and (old_technician is None or old_technician.pk != new_technician.pk))
    status_ok = job.queue_status in NOTIFIABLE_STATUSES
    context = _assignment_context(job)
    is_repair = not _is_replacement(job)

    # --- new technician ---------------------------------------------------
    if (new_technician is not None and status_ok
            and (changed or force_notify_new)
            and new_technician.user_id != actor_id):
        TechnicianNotification.objects.create(
            technician=new_technician,
            message=(
                f"You have been assigned {_job_label(job)} #{job.pk} for "
                f"{context['customer_name']} - Unit {context['unit_number']}"
            ),
            read=False,
            repair=job if is_repair else None,
        )
        try:
            NotificationService.create_notification(
                recipient=new_technician,
                template_name='repair_assigned',
                context=dict(context),
                repair=job if is_repair else None,
                customer=job.customer,
                action_url=context['action_url'],
            )
        except Exception:
            logger.exception(
                "Failed to send assignment notification for %s #%s",
                _job_label(job), job.pk,
            )

    # --- old technician ---------------------------------------------------
    # REQUESTED is excluded here too: the provisional tech was never told the
    # request was "theirs" (suppressed above), so "reassigned away" would be
    # the first they hear of it.
    if (changed and old_technician is not None
            and old_technician.user_id != actor_id
            and job.queue_status in NOTIFIABLE_STATUSES):
        new_tech_name = (
            new_technician.user.get_full_name() or new_technician.user.username
        )
        # Their unread rows about this job are stale now.
        if is_repair:
            TechnicianNotification.objects.filter(
                technician=old_technician, repair=job, read=False,
            ).update(read=True)
        TechnicianNotification.objects.create(
            technician=old_technician,
            message=(
                f"{_job_label(job)} #{job.pk} for {context['customer_name']} - "
                f"Unit {context['unit_number']} has been reassigned to {new_tech_name}"
            ),
            read=False,
            repair=job if is_repair else None,
        )
        try:
            NotificationService.create_notification(
                recipient=old_technician,
                template_name='repair_reassigned_away',
                context=dict(context, new_technician_name=new_tech_name),
                repair=job if is_repair else None,
                customer=job.customer,
                action_url=context['action_url'],
            )
        except Exception:
            logger.exception(
                "Failed to send reassigned-away notification for %s #%s",
                _job_label(job), job.pk,
            )


def notify_schedule_swap(job_a, job_b, *, actor_user=None):
    """Tell the assigned tech their two jobs traded times (fieldops S7).

    Both jobs belong to the same technician — the swap endpoint refuses
    cross-tech drops — so this is exactly one notification, and none at all
    when the tech performed the swap themselves. No customer is notified;
    telling a customer their time moved is S4's job, not a side effect of a
    manager's drag.

    Call this from ``transaction.on_commit`` only: NotificationService sends
    email synchronously and re-raises, and the caller holds two row locks.
    """
    from apps.technician_portal.models import TechnicianNotification
    from core.services.notification_service import NotificationService
    from django.utils import timezone
    from django.utils.dateformat import format as format_date

    technician = job_a.technician
    if technician is None:
        return
    actor_id = actor_user.id if actor_user is not None else None
    if technician.user_id == actor_id:
        return
    if job_a.queue_status not in NOTIFIABLE_STATUSES:
        return

    def when(job):
        return format_date(timezone.localtime(job.scheduled_for), 'g:i A')

    def label(job):
        name = job.customer.name if job.customer_id else 'Walk-in'
        unit = job.unit_number or ''
        return f"{name} (Unit {unit})" if unit else name

    day = format_date(timezone.localtime(job_a.scheduled_for), 'D M j')
    summary = (
        f"{label(job_a)} is now at {when(job_a)} and "
        f"{label(job_b)} at {when(job_b)}"
    )

    # TechnicianNotification carries only a `repair` FK, so a swap between two
    # replacements gets a dashboard row with no link — its action_url still
    # works, and the bell notification below is unaffected.
    linked_repair = None
    for job in (job_a, job_b):
        if not _is_replacement(job):
            linked_repair = job
            break

    TechnicianNotification.objects.create(
        technician=technician,
        message=f"Schedule change for {day}: {summary}",
        read=False,
        repair=linked_repair,
    )

    context = {
        'day': day,
        'summary': summary,
        'lead': 'Two of your jobs traded times. Nothing was added or removed.',
        'technician_name': (
            technician.user.get_full_name() or technician.user.username
        ),
        'first_job': label(job_a),
        'first_time': when(job_a),
        'second_job': label(job_b),
        'second_time': when(job_b),
        # Link to the day that changed, not to "today" — the tech may read
        # this tomorrow morning about a job the day after.
        'action_url': (
            '/tech/schedule/?date='
            + timezone.localtime(job_a.scheduled_for).date().isoformat()
        ),
    }
    try:
        NotificationService.create_notification(
            recipient=technician,
            template_name='job_rescheduled',
            context=context,
            repair=linked_repair,
            action_url=context['action_url'],
        )
    except Exception:
        logger.exception(
            "Failed to send schedule-swap notification to technician %s",
            technician.pk,
        )


def notify_appointment_set(job, *, job_count=1, actor_user=None):
    """Tell the assigned tech a time was booked onto their job (fieldops S4).

    Reuses S7's ``job_rescheduled`` template rather than adding a second
    schedule-change stream: it is category ``assignment`` (so the existing
    TechnicianNotificationPreference opt-out covers it) and priority MEDIUM on
    purpose — HIGH maps to ``['in_app', 'sms']`` and excludes email entirely.

    No customer is notified here. Echoing a confirmed time back to the
    customer is a deliberate product decision, not a side effect of a
    manager's click — the portal shows the booked time instead.

    Call from ``transaction.on_commit`` only: NotificationService sends email
    synchronously and re-raises, and the caller holds row locks.
    """
    from apps.technician_portal.models import TechnicianNotification
    from core.services.notification_service import NotificationService
    from django.utils import timezone
    from django.utils.dateformat import format as format_date

    technician = job.technician
    if technician is None or job.scheduled_for is None:
        return
    actor_id = actor_user.id if actor_user is not None else None
    if technician.user_id == actor_id:
        return
    if job.queue_status not in NOTIFIABLE_STATUSES:
        return

    local_start = timezone.localtime(job.scheduled_for)
    day = format_date(local_start, 'D M j')
    start = format_date(local_start, 'g:i A')
    if job.scheduled_window_end:
        end = format_date(timezone.localtime(job.scheduled_window_end), 'g:i A')
        when = f"{day}, {start}–{end}"
    else:
        when = f"{day}, {start}"

    name = job.customer.name if job.customer_id else 'Walk-in'
    unit = job.unit_number or ''
    who = f"{name} (Unit {unit})" if unit else name
    breaks = f" — {job_count} breaks, one visit" if job_count > 1 else ''
    summary = f"{who} is booked for {when}{breaks}"

    is_repair = not _is_replacement(job)
    TechnicianNotification.objects.create(
        technician=technician,
        message=f"Scheduled: {summary}",
        read=False,
        # TechnicianNotification carries only a `repair` FK, so a booked
        # replacement gets a dashboard row with no link — its action_url in
        # the bell notification below still works.
        repair=job if is_repair else None,
    )

    context = {
        'day': day,
        'summary': summary,
        'lead': (
            'A job on your schedule now has a time. Nothing else moved.'
            if job_count == 1 else
            f'A {job_count}-break job on your schedule now has a time — '
            'one visit. Nothing else moved.'
        ),
        'technician_name': (
            technician.user.get_full_name() or technician.user.username
        ),
        'first_job': who,
        'first_time': start,
        # The template renders a second job for the swap case; a booking has
        # only one, so these stay blank rather than repeating the first.
        'second_job': '',
        'second_time': '',
        # Link to the day that changed, not to "today" — the tech may read
        # this the morning before a job two days out.
        'action_url': '/tech/schedule/?date=' + local_start.date().isoformat(),
    }
    try:
        NotificationService.create_notification(
            recipient=technician,
            template_name='job_rescheduled',
            context=context,
            repair=job if is_repair else None,
            action_url=context['action_url'],
        )
    except Exception:
        logger.exception(
            "Failed to send booking notification to technician %s",
            technician.pk,
        )


def notify_assignment_from_signal(job, old_technician, old_status, created,
                                  actor_user_id=None):
    """Signal-side decision: does this save amount to an assignment event?

    Fires notify_assignment_change when either the technician changed, or the
    job just crossed REQUESTED → APPROVED/IN_PROGRESS with a technician
    attached (the customer-request auto-accept path: the tech was
    provisionally set while the job was still REQUESTED, so the change-based
    trigger never fires for them).
    """
    if job.technician is None and old_technician is None:
        return
    if getattr(job, '_skip_assignment_notifications', False):
        return

    changed = (job.technician is not None
               and (old_technician is None
                    or old_technician.pk != job.technician.pk))
    accepted = (not created
                and old_status == 'REQUESTED'
                and job.queue_status in ('APPROVED', 'IN_PROGRESS')
                and job.technician is not None)

    if not changed and not accepted:
        return

    assigned_by = None
    if actor_user_id is not None:
        # notify_assignment_change compares user ids; wrap in a shim.
        class _Actor:
            id = actor_user_id
        assigned_by = _Actor()

    notify_assignment_change(
        job, old_technician, job.technician,
        assigned_by=assigned_by,
        force_notify_new=accepted,
    )


def notify_bulk_assignment(new_technician, jobs, *, assigned_by=None,
                           reassigned_away=None):
    """One summary notification per tech for a bulk reassign.

    Args:
        new_technician: Technician who received the jobs.
        jobs: list of jobs that actually changed hands to them.
        assigned_by: acting User (skip self-notification).
        reassigned_away: optional dict {Technician: [jobs]} of previous
            owners to notify with one summary each.
    """
    from core.services.notification_service import NotificationService

    actor_id = assigned_by.id if assigned_by is not None else None

    def summary(job_list):
        units = [f"#{j.pk} (Unit {j.unit_number or '?'})" for j in job_list[:5]]
        text = ', '.join(units)
        if len(job_list) > 5:
            text += f" and {len(job_list) - 5} more"
        return text

    if jobs and new_technician is not None and new_technician.user_id != actor_id:
        try:
            NotificationService.create_notification(
                recipient=new_technician,
                template_name='jobs_bulk_assigned',
                context={
                    'job_count': len(jobs),
                    'job_summary': summary(jobs),
                    'technician_name': (
                        new_technician.user.get_full_name()
                        or new_technician.user.username
                    ),
                    'action_url': '/tech/jobs/',
                },
                action_url='/tech/jobs/',
            )
        except Exception:
            logger.exception("Failed to send bulk assignment notification")

    for old_tech, lost_jobs in (reassigned_away or {}).items():
        if not lost_jobs or old_tech.user_id == actor_id:
            continue
        new_name = (
            new_technician.user.get_full_name() or new_technician.user.username
        )
        try:
            NotificationService.create_notification(
                recipient=old_tech,
                template_name='jobs_bulk_reassigned_away',
                context={
                    'job_count': len(lost_jobs),
                    'job_summary': summary(lost_jobs),
                    'new_technician_name': new_name,
                    'action_url': '/tech/jobs/',
                },
                action_url='/tech/jobs/',
            )
        except Exception:
            logger.exception("Failed to send bulk reassigned-away notification")
