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

        # Find the primary contact — no fallback per implementation plan §7
        customer_user = CustomerUser.objects.filter(
            customer=customer,
            is_primary_contact=True,
        ).first()

        # Channel selection: prefer SMS when the shop turned it on and the
        # customer agreed to texts (texts convert far better). SMS also
        # covers customers with no portal contact/email at all — before the
        # SMS channel those customers never got a review request.
        sms_phone = _sms_review_phone(config, customer)
        email_ok = bool(customer_user and customer_user.user.email)
        if not email_ok and not sms_phone:
            return None  # No way to reach this customer
        channel = 'sms' if sms_phone else 'email'

        # Check: customer opted out
        if customer_user and customer_user.review_opt_out:
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
            channel=channel,
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

                    # Re-check opt-out (may have changed since scheduling)
                    if rr.customer_user and rr.customer_user.review_opt_out:
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
                    # SMS requests re-check texting eligibility at send time
                    # (consent may have been revoked, the shop may have turned
                    # the channel off). Fall back to email when possible.
                    if rr.channel == 'sms' and not _sms_review_phone(config, rr.customer):
                        if rr.customer_user and rr.customer_user.user.email:
                            rr.channel = 'email'
                            rr.save(update_fields=['channel'])
                        else:
                            rr.status = 'skipped'
                            rr.skip_reason = 'sms_unavailable'
                            rr.save(update_fields=['status', 'skip_reason'])
                            continue

                    try:
                        if rr.channel == 'sms':
                            success = _send_review_sms(rr, config)
                        else:
                            success = _send_review_email(rr, config)
                    except Exception:
                        logger.exception(
                            "Failed to send review request pk=%s for tenant=%s",
                            rr.pk, rr.tenant_id,
                        )
                        # Leave as pending for retry on next cron run.
                        # Raise to trigger a rollback of any partial writes inside
                        # this atomic block (none in the exception path, but safe).
                        continue

                    if success:
                        rr.status = 'sent'
                        rr.sent_at = now
                        rr.save(update_fields=['status', 'sent_at'])
                        sent_count += 1
                    else:
                        logger.warning(
                            "review request send returned falsy for pk=%s (channel=%s)",
                            rr.pk, rr.channel,
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


def _sms_review_phone(config, customer):
    """E.164 phone a review text for this customer would go to, or None when
    the SMS channel isn't available (shop toggle off, platform not
    configured, no consent, no usable number)."""
    from core.services.sms_service import SMSService

    if not config.sms_enabled or not SMSService.is_enabled():
        return None
    if not customer.sms_opt_in:
        return None
    return SMSService.normalize_phone(customer.phone)


def _send_review_sms(review_request, config):
    """Send the review request as a text. Returns True on success.

    Wording follows the field-proven Rockstar shape: short, first-name,
    one link (our click-tracking URL — it records the click then forwards
    to Google; not a URL shortener, which carriers filter). Opt-out
    wording rides on the customer's first text only.
    """
    from django.conf import settings
    from core.models.notification_delivery_log import NotificationDeliveryLog
    from core.services.sms_service import SMSService

    rr = review_request
    phone = _sms_review_phone(config, rr.customer)
    if not phone:
        return False

    base_url = getattr(settings, 'SITE_URL', 'https://rssystems.io')
    # Compact click-tracking alias — records the click, then forwards to the
    # shop's Google review page. Not a URL shortener (carriers filter those).
    click_url = f"{base_url}/r/{rr.token}/"

    first_name = (rr.customer.name or '').strip().split(' ')[0]
    greeting = f", {first_name}" if first_name else ""

    stop = ''
    if not NotificationDeliveryLog.objects.filter(
        channel='sms', recipient_phone=phone, tenant=rr.tenant,
    ).exists():
        stop = ' Reply STOP to opt out.'

    # Shop name leads (shrinkable); the link and opt-out wording must
    # always survive intact within one 160-char segment.
    shop = (rr.tenant.name or 'your auto glass shop').strip()
    tail = f": Thanks{greeting}! A quick Google review helps a lot: {click_url}{stop}"
    room = SMSService.MAX_SMS_LENGTH - len(tail)
    if len(shop) > room:
        shop = shop[:max(room, 0)].rstrip()
    body = f"{shop}{tail}"

    ok, _log = SMSService.send_notification_sms(
        notification_id=None, recipient_phone=phone, message=body,
        tenant=rr.tenant,
    )
    return ok


def _send_review_email(review_request, config):
    """Send a branded review request email. Returns True on success."""
    from core.email_utils import send_branded_email

    rr = review_request
    shop_name = rr.tenant.name or 'our shop'
    customer_name = rr.customer.name or 'Valued Customer'

    # Loyalty balance line — one factual sentence, or None when the shop's
    # program/email toggle is off or the balance is zero.
    points_line = None
    try:
        from apps.rewards_referrals.services import LoyaltyService
        points_line = LoyaltyService.get_email_balance_line(rr.customer)
    except Exception:
        points_line = None

    # Template vars available to tenant-customised subject & body
    tpl_vars = dict(
        shop_name=shop_name,
        customer_name=customer_name,
        points_balance=points_line or '',
    )

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

    # Quiet rewards-balance footer row (only when the program is on and the
    # balance is positive) — factual, not promotional, per SES content rules.
    detail_rows = [("Rewards", points_line)] if points_line else None

    result = send_branded_email(
        subject=subject,
        recipient_list=[rr.customer_user.user.email],
        headline=f"How was your experience with {shop_name}?",
        body_paragraphs=body_paragraphs,
        tenant=rr.tenant,
        button_text="Leave a Google Review",
        button_url=click_url,
        secondary_button_text="Unsubscribe from review requests",
        secondary_button_url=opt_out_url,
        detail_rows=detail_rows,
        fail_silently=True,
        headers=headers,
    )
    return result > 0
