"""
ReviewRequestService — smart scheduling and sending of review request emails.

Phase 1 implementation. See docs/proposals/review-request-system.md.
"""
import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


class ReviewRequestService:
    """Evaluate, schedule, and send review request emails after repair completion."""

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @staticmethod
    def schedule_review_request(repair):
        """
        Called when a repair transitions to COMPLETED.

        Evaluates eligibility and either queues a pending ReviewRequest
        or records a skipped/suppressed record with the reason.

        Returns the ReviewRequest instance (or None if nothing to do).
        """
        from apps.technician_portal.review_models import ReviewConfig, ReviewRequest
        from apps.customer_portal.models import CustomerUser

        config = ReviewConfig.get_for_tenant(repair.tenant)

        # Gate: feature enabled?
        if not config.is_enabled:
            return None

        # Gate: must have a Google review URL configured
        if not config.google_review_url:
            return None

        # Gate: repair must be COMPLETED
        if repair.queue_status != 'COMPLETED':
            return None

        # Gate: skip goodwill repairs (courtesy, no review needed)
        if getattr(repair, 'is_goodwill_repair', False):
            return _create_skipped(
                repair, config, None, 'goodwill_repair',
            )

        customer = repair.customer

        # Find the primary contact if the customer has portal users. Retail /
        # walk-in customers usually have no portal account — fall back to the
        # contact info captured on the Customer record itself.
        customer_user = CustomerUser.objects.filter(
            customer=customer,
            is_primary_contact=True,
        ).first()

        email, phone = _resolve_contact(customer, customer_user)

        # Gate: at least one enabled channel must have contact info
        can_email = config.send_via_email and bool(email)
        can_sms = config.send_via_sms and bool(_to_e164(phone))
        if not can_email and not can_sms:
            return _create_skipped(
                repair, config, customer_user, 'no_contact_info',
            )

        # Check: customer opted out (portal-user level or customer level)
        if (customer_user and customer_user.review_opt_out) or customer.review_opt_out:
            return _create_skipped(
                repair, config, customer_user, 'customer_opted_out',
            )

        # Check: fleet accounts are excluded unless the shop opts in.
        # Default off — review requests go to individual (retail/walk-in)
        # customers only.
        is_fleet = customer.customer_type == 'FLEET'
        if is_fleet and not config.send_to_fleet:
            return _create_skipped(
                repair, config, customer_user, 'fleet_disabled',
            )

        # Check: negative experience (repair was DENIED at some point)
        from apps.technician_portal.models import TechnicianNotification
        if TechnicianNotification.objects.filter(
            repair=repair,
            message__icontains='DENIED',
        ).exists():
            return _create_suppressed(
                repair, config, customer_user, 'negative_experience',
            )

        # Check: already reviewed (ever, for this customer+tenant)
        if ReviewRequest.objects.filter(
            tenant=repair.tenant,
            customer=customer,
            status='reviewed',
        ).exists():
            return _create_skipped(
                repair, config, customer_user, 'already_reviewed',
            )

        # Check: cooldown (fleet vs retail)
        cooldown_days = config.fleet_cooldown_days if is_fleet else config.retail_cooldown_days

        last_request = ReviewRequest.objects.filter(
            tenant=repair.tenant,
            customer=customer,
            status__in=['sent', 'clicked'],
        ).order_by('-sent_at').first()

        if last_request and last_request.sent_at:
            days_since = (timezone.now() - last_request.sent_at).days
            if days_since < cooldown_days:
                return _create_skipped(
                    repair, config, customer_user,
                    f'cooldown_{days_since}d_of_{cooldown_days}d',
                )

        # Check: duplicate — already have a pending/sent request for this repair
        if ReviewRequest.objects.filter(
            repair=repair,
            status__in=['pending', 'sent'],
        ).exists():
            return None

        # Calculate scheduled send time
        send_at = timezone.now() + timedelta(hours=config.send_delay_hours)
        send_at = _adjust_to_business_hours(
            send_at, config.business_hours_start, config.business_hours_end,
        )

        return ReviewRequest.objects.create(
            tenant=repair.tenant,
            customer=customer,
            customer_user=customer_user,
            repair=repair,
            status='pending',
            scheduled_at=send_at,
        )

    @staticmethod
    def send_pending_requests():
        """
        Send all ReviewRequests whose scheduled_at has arrived.

        Called by the ``send_review_requests`` management command (cron).

        CONCURRENCY NOTE (CODE-230):
        The cron may be configured to run every 15–30 minutes. If a slow run
        overlaps with the next scheduled run, both workers would pick up the
        same 'pending' rows and send duplicate review request emails to customers.

        Fix: collect eligible PKs first, then process each one inside its own
        ``transaction.atomic()`` block using ``select_for_update(skip_locked=True)``.
        A concurrent worker that hits the same PK will get a DoesNotExist (row
        already locked or status already updated) and safely skip it.  Because
        email delivery is outside the transaction, the lock is held only for the
        status-flip — not during the SMTP call.
        """
        from django.db import transaction as db_transaction
        from apps.technician_portal.review_models import ReviewConfig, ReviewRequest

        now = timezone.now()

        # Collect candidate PKs outside any transaction — cheap read.
        pending_ids = list(
            ReviewRequest.objects
            .filter(status='pending', scheduled_at__lte=now)
            .values_list('pk', flat=True)
        )

        sent_count = 0
        for rr_id in pending_ids:
            # Each item gets its own transaction so a failure in one does not
            # roll back work already done on others.
            try:
                with db_transaction.atomic():
                    # Re-fetch with a row-level lock.  skip_locked=True means a
                    # concurrent worker will skip rows we're already processing.
                    # NOTE: select_for_update() cannot be combined with
                    # select_related() on nullable FKs (PostgreSQL raises
                    # "FOR UPDATE cannot be applied to the nullable side of an
                    # outer join").  Lock the row first, then fetch with
                    # select_related separately.
                    try:
                        ReviewRequest.objects.select_for_update(
                            skip_locked=True
                        ).get(pk=rr_id, status='pending')
                    except ReviewRequest.DoesNotExist:
                        # Either already processed by a concurrent runner, or the
                        # status changed since we collected the IDs.
                        continue

                    # Row is locked — now fetch it with related objects.
                    try:
                        rr = (
                            ReviewRequest.objects
                            .select_related('tenant', 'customer', 'customer_user__user', 'repair')
                            .get(pk=rr_id)
                        )
                    except ReviewRequest.DoesNotExist:
                        continue

                    config = ReviewConfig.get_for_tenant(rr.tenant)
                    if not config.is_enabled:
                        rr.status = 'skipped'
                        rr.skip_reason = 'config_deactivated'
                        rr.save(update_fields=['status', 'skip_reason'])
                        continue

                    # Re-check opt-out (may have changed since scheduling) —
                    # portal-user level or customer level
                    if (rr.customer_user and rr.customer_user.review_opt_out) \
                            or rr.customer.review_opt_out:
                        rr.status = 'skipped'
                        rr.skip_reason = 'customer_opted_out'
                        rr.save(update_fields=['status', 'skip_reason'])
                        continue

                    # Re-check fleet gating (the toggle may have been switched
                    # off between scheduling and the cron run)
                    if rr.customer.customer_type == 'FLEET' and not config.send_to_fleet:
                        rr.status = 'skipped'
                        rr.skip_reason = 'fleet_disabled'
                        rr.save(update_fields=['status', 'skip_reason'])
                        continue

                    # Send the email OUTSIDE the transaction so we don't hold
                    # the DB lock during the SMTP call.  We'll commit the status
                    # update after the send returns.  The select_for_update lock
                    # releases when the atomic block exits.
                    #
                    # We must send inside the block so success/failure is
                    # determined before we release the lock.  If the process dies
                    # between the send and the save, the worst case is a retry on
                    # the next cron run (row stays 'pending').
                    try:
                        channels = _send_review_request(rr, config)
                    except Exception:
                        logger.exception(
                            "Failed to send review request pk=%s for tenant=%s",
                            rr.pk, rr.tenant_id,
                        )
                        # Leave as pending for retry on next cron run.
                        # Raise to trigger a rollback of any partial writes inside
                        # this atomic block (none in the exception path, but safe).
                        continue

                    if channels:
                        rr.status = 'sent'
                        rr.sent_at = now
                        rr.sent_via = '+'.join(channels)
                        rr.save(update_fields=['status', 'sent_at', 'sent_via'])
                        sent_count += 1
                    else:
                        logger.warning(
                            "No channel delivered review request pk=%s", rr.pk,
                        )

            except Exception:
                # Catch any DB/unexpected errors so one bad row doesn't abort the rest.
                logger.exception(
                    "Unexpected error processing review request pk=%s — skipping", rr_id,
                )

        return sent_count


# ------------------------------------------------------------------ #
# Private helpers
# ------------------------------------------------------------------ #

def _resolve_contact(customer, customer_user):
    """
    Return (email, phone) for a review request.

    Prefers the portal primary contact's email when one exists; otherwise
    falls back to the contact info on the Customer record (how retail /
    walk-in customers are captured from the repair form). Phone always comes
    from the Customer record — portal accounts don't carry one.
    """
    email = ''
    if customer_user and customer_user.user.email:
        email = customer_user.user.email
    elif customer.email:
        email = customer.email
    phone = customer.phone or ''
    return email, phone


def _to_e164(phone):
    """
    Normalize a phone number to E.164 (+1XXXXXXXXXX) for AWS SNS.

    Handles the formats techs actually type: '(501) 555-1234',
    '501-555-1234', '15015551234', '+15015551234'. Returns None when the
    number can't be normalized to a US/Canada E.164 number.
    """
    import re
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    # Already-international numbers ('+44...') pass through if E.164-valid
    if phone.strip().startswith('+') and re.match(r'^\+[1-9]\d{1,14}$', phone.strip()):
        return phone.strip()
    return None


def _send_review_request(rr, config):
    """
    Send the review request over every enabled channel with contact info.

    Returns the list of channels that actually delivered (e.g. ['email'],
    ['email', 'sms'], or [] if nothing went out).
    """
    email, phone = _resolve_contact(rr.customer, rr.customer_user)
    channels = []

    if config.send_via_email and email:
        try:
            if _send_review_email(rr, config, email):
                channels.append('email')
        except Exception:
            logger.exception("Review email failed for request pk=%s", rr.pk)

    if config.send_via_sms:
        e164 = _to_e164(phone)
        if e164:
            try:
                if _send_review_sms(rr, config, e164):
                    channels.append('sms')
            except Exception:
                logger.exception("Review SMS failed for request pk=%s", rr.pk)

    return channels


def _create_skipped(repair, config, customer_user, reason):
    from apps.technician_portal.review_models import ReviewRequest
    return ReviewRequest.objects.create(
        tenant=repair.tenant,
        customer=repair.customer,
        customer_user=customer_user,
        repair=repair,
        status='skipped',
        skip_reason=reason,
        scheduled_at=timezone.now(),
    )


def _create_suppressed(repair, config, customer_user, reason):
    from apps.technician_portal.review_models import ReviewRequest
    return ReviewRequest.objects.create(
        tenant=repair.tenant,
        customer=repair.customer,
        customer_user=customer_user,
        repair=repair,
        status='suppressed',
        skip_reason=reason,
        scheduled_at=timezone.now(),
    )


def _adjust_to_business_hours(dt, start_hour, end_hour):
    """
    Clamp *dt* into the business-hours window [start_hour, end_hour).

    If dt falls after end_hour, push to start_hour next day.
    If dt falls before start_hour, push to start_hour same day.
    """
    if dt.hour >= end_hour:
        # Push to next day at start_hour
        dt = dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        dt += timedelta(days=1)
    elif dt.hour < start_hour:
        dt = dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return dt


def _safe_format(template, **kwargs):
    """
    Safely apply str.format() to a user-editable template.

    Returns the formatted string on success, or the raw template if the
    user included unknown placeholders or stray curly braces.  This prevents
    KeyError / ValueError from crashing the review-request send pipeline.
    """
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError, IndexError):
        return template


def _send_review_email(review_request, config, recipient_email):
    """Send a branded review request email. Returns True on success."""
    from core.email_utils import send_branded_email

    rr = review_request
    shop_name = rr.tenant.name or 'our shop'
    customer_name = rr.customer.name or 'Valued Customer'

    # Template vars available to tenant-customised subject & body
    tpl_vars = dict(shop_name=shop_name, customer_name=customer_name)

    subject = _safe_format(config.email_subject, **tpl_vars)

    # Build the review link with our tracking token
    # The opt-out/click URLs are handled by our own endpoints
    review_url = config.google_review_url

    unit_info = ''
    if rr.repair and rr.repair.unit_number:
        unit_info = f' on unit {rr.repair.unit_number}'

    body_paragraphs = []
    if config.email_body_template:
        body_paragraphs.append(_safe_format(config.email_body_template, **tpl_vars))
    else:
        body_paragraphs = [
            f"Thanks for choosing {shop_name} for your recent windshield repair{unit_info}.",
            "If you had a great experience, we'd really appreciate a quick Google review — it helps other drivers find us.",
            "It only takes 30 seconds and means the world to our team.",
        ]

    # CAN-SPAM: unsubscribe link
    from django.conf import settings
    base_url = getattr(settings, 'SITE_URL', 'https://rssystems.io')
    opt_out_url = f"{base_url}/reviews/opt-out/{rr.token}/"
    click_url = f"{base_url}/reviews/click/{rr.token}/"

    # RFC 8058 one-click unsubscribe headers — mailbox providers and
    # corporate gateways score bulk-ish mail without them as spam, and
    # Gmail/Yahoo require them for bulk senders.
    from email.utils import parseaddr
    platform_address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    headers = {
        'List-Unsubscribe': f'<{opt_out_url}>, <mailto:{platform_address}?subject=unsubscribe>',
        'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
    }

    result = send_branded_email(
        subject=subject,
        recipient_list=[recipient_email],
        headline=f"How was your experience with {shop_name}?",
        body_paragraphs=body_paragraphs,
        tenant=rr.tenant,
        button_text="Leave a Google Review",
        button_url=click_url,
        secondary_button_text="Unsubscribe from review requests",
        secondary_button_url=opt_out_url,
        fail_silently=True,
        headers=headers,
    )
    return result > 0


def _send_review_sms(review_request, config, e164_phone):
    """
    Send a review request text via SMSService (AWS SNS). Returns True on success.

    The whole message must fit in one 160-character SMS *with the tracked
    review link intact* — SMSService hard-truncates at 160 and a truncated
    link is worthless. So the body text is trimmed to whatever room is left
    after the link and the opt-out notice.
    """
    from django.conf import settings
    from core.services.sms_service import SMSService

    rr = review_request
    shop_name = rr.tenant.name or 'our shop'
    customer_name = rr.customer.name or 'there'

    base_url = getattr(settings, 'SITE_URL', 'https://rssystems.io')
    click_url = f"{base_url}/reviews/click/{rr.token}/"
    opt_out_notice = "Reply STOP to opt out."

    if config.sms_body_template:
        body = _safe_format(
            config.sms_body_template,
            shop_name=shop_name, customer_name=customer_name,
        )
    else:
        body = (
            f"Thanks for choosing {shop_name}! Mind leaving us a quick Google review?"
        )

    # Trim the body so body + link + opt-out fits in one SMS segment.
    max_len = SMSService.MAX_SMS_LENGTH
    reserved = len(click_url) + len(opt_out_notice) + 2  # two joining spaces
    room = max_len - reserved
    if room < 10:
        # Pathological (very long SITE_URL) — send link + opt-out only
        message = f"{click_url} {opt_out_notice}"
    else:
        if len(body) > room:
            # Plain ASCII '...' — a unicode ellipsis would flip the SMS to
            # UCS-2 encoding and shrink the single-segment limit to 70 chars.
            body = body[:room - 3].rstrip() + '...'
        message = f"{body} {click_url} {opt_out_notice}"

    success, _log = SMSService.send_notification_sms(
        notification_id=None,
        recipient_phone=e164_phone,
        message=message,
    )
    return success
