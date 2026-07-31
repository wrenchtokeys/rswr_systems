"""
AWS SES delivery-event webhook (SNS → HTTPS).

SES publishes Send/Delivery/DeliveryDelay/Bounce/Complaint/Reject events for
the `rs-systems-default` configuration set (attached as the identity default,
so every SMTP send gets it) to the `rs-systems-ses-events` SNS topic; an
HTTPS subscription on that topic POSTs them here. Events are attributed to
invoices via the rs_invoice_id message tag (exact) or last_sent_to (fallback)
and persisted on Invoice.email_delivery_status, so the UI can show real
Delivered/Bounced state instead of trusting "SENT". Permanent bounces,
complaints, and rejects also alert the shop in-app and by email.

One-time AWS setup (see docs/deployment/SES_BOUNCE_NOTIFICATIONS.md):
  1. Create an SNS topic (e.g. rs-systems-ses-events).
  2. Create a SES configuration set with an SNS event destination for
     SEND, DELIVERY, BOUNCE, COMPLAINT, REJECT, DELIVERY_DELAY, and attach
     it to the rssystems.io identity as the default configuration set.
  3. `eb setenv SES_WEBHOOK_SECRET=<long random string>`.
  4. Subscribe the topic to
     https://rssystems.io/api/billing/webhooks/ses/<SES_WEBHOOK_SECRET>/
     (HTTPS). This endpoint auto-confirms the subscription.

The URL secret is the auth: without it the endpoint 404s. A forged POST with
the secret could at worst generate a spurious "email bounced" alert or flip
an invoice's advisory delivery-status field.
"""

import hmac
import json
import logging
import os
import urllib.request

from django.http import Http404, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

# Only match invoices sent recently — a bounce for a months-old address
# shouldn't page the shop about long-paid invoices.
MATCH_WINDOW_DAYS = 14


@csrf_exempt
@require_POST
def ses_event_webhook(request, secret):
    """Receive SNS-delivered SES bounce/complaint notifications."""
    expected = os.environ.get('SES_WEBHOOK_SECRET', '')
    if not expected or not hmac.compare_digest(secret, expected):
        raise Http404

    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return HttpResponse(status=400)

    msg_type = payload.get('Type') or request.headers.get('x-amz-sns-message-type', '')

    if msg_type == 'SubscriptionConfirmation':
        _confirm_subscription(payload.get('SubscribeURL', ''))
        return HttpResponse(status=200)

    if msg_type == 'Notification':
        try:
            message = json.loads(payload.get('Message') or '{}')
        except (ValueError, TypeError):
            return HttpResponse(status=200)
        _handle_ses_event(message)

    # Always 200 — SNS retries aggressively on anything else, and a
    # notification we can't use isn't an error worth retrying.
    return HttpResponse(status=200)


def _confirm_subscription(url):
    """Auto-confirm the SNS subscription handshake (SNS-hosted URLs only)."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ''
        if url.startswith('https://') and (
                host.startswith('sns.') and host.endswith('.amazonaws.com')):
            urllib.request.urlopen(url, timeout=10)
            logger.info("Confirmed SES/SNS webhook subscription")
        else:
            logger.warning(f"Refusing to confirm non-SNS SubscribeURL: {url[:100]}")
    except Exception:
        logger.warning("Could not confirm SNS subscription", exc_info=True)


# Later statuses may not regress to earlier ones: a late "Send" event must
# never overwrite "delivered", and "delivered" must not mask a subsequent
# complaint. Equal-rank transitions are allowed (a re-bounce refreshes detail).
_STATUS_RANK = {
    '': 0,
    'sent': 1,
    'delayed': 2,
    'delivered': 3,
    'bounced': 4,
    'complained': 4,
    'rejected': 4,
}


def _handle_ses_event(message):
    """Route a decoded SES event to status tracking + shop alerting.

    Handles both the configuration-set event format (eventType, includes
    mail.tags) and the legacy identity-notification format (notificationType).
    Every event is logged with its recipients — this log is the per-message
    delivery audit trail ("did Penske's server accept it?").
    """
    event_type = message.get('notificationType') or message.get('eventType') or ''
    mail = message.get('mail') or {}
    recipients = []
    status = None
    detail = ''
    alert_reason = None

    if event_type == 'Send':
        recipients = mail.get('destination') or []
        status = 'sent'
        logger.info(f"SES accepted send to {', '.join(recipients)}")
    elif event_type == 'Delivery':
        delivery = message.get('delivery') or {}
        recipients = delivery.get('recipients') or []
        status = 'delivered'
        logger.info(
            f"SES delivery confirmed to {', '.join(recipients)} "
            f"(mta={delivery.get('reportingMTA', '?')})"
        )
    elif event_type == 'DeliveryDelay':
        delay = message.get('deliveryDelay') or {}
        recipients = [r.get('emailAddress', '')
                      for r in delay.get('delayedRecipients', [])]
        status = 'delayed'
        detail = delay.get('delayType', 'delivery delayed')
        logger.warning(
            f"SES delivery delayed for {', '.join(filter(None, recipients))} "
            f"(type={delay.get('delayType', '?')})"
        )
    elif event_type == 'Bounce':
        bounce = message.get('bounce') or {}
        bounced = bounce.get('bouncedRecipients', [])
        recipients = [r.get('emailAddress', '') for r in bounced]
        diagnostics = '; '.join(filter(None, (
            r.get('diagnosticCode', '') for r in bounced)))[:255]
        logger.warning(
            f"SES {bounce.get('bounceType', '?')} bounce for "
            f"{', '.join(filter(None, recipients)) or 'unknown recipient'} "
            f"(subType={bounce.get('bounceSubType', '?')}) {diagnostics}"
        )
        # Transient bounces (mailbox full, greylisting) usually self-resolve;
        # only hard/permanent bounces mean "this address doesn't work".
        if bounce.get('bounceType') == 'Transient':
            status = 'delayed'
            detail = diagnostics or 'temporary delivery problem'
        else:
            status = 'bounced'
            detail = diagnostics or 'could not be delivered'
            alert_reason = 'bounced (could not be delivered)'
    elif event_type == 'Complaint':
        complaint = message.get('complaint') or {}
        recipients = [r.get('emailAddress', '')
                      for r in complaint.get('complainedRecipients', [])]
        status = 'complained'
        detail = complaint.get('complaintFeedbackType', '') or 'marked as spam'
        alert_reason = 'was marked as spam by the recipient'
        logger.warning(
            f"SES complaint (marked as spam) from "
            f"{', '.join(filter(None, recipients)) or 'unknown recipient'}"
        )
    elif event_type == 'Reject':
        reject = message.get('reject') or {}
        recipients = mail.get('destination') or []
        status = 'rejected'
        detail = reject.get('reason', '') or 'rejected by SES'
        alert_reason = f"was rejected before sending ({detail})"
        logger.warning(
            f"SES rejected message to {', '.join(recipients)}: {detail}"
        )
    else:
        return

    _update_invoice_delivery_status(message, recipients, status, detail)

    if alert_reason:
        for email in filter(None, recipients):
            _alert_shops_for_recipient(email, alert_reason)


def _resolve_event_invoices(message, recipients):
    """Find the Invoice(s) an SES event belongs to.

    Preferred: the rs_invoice_id message tag we set at send time
    (X-SES-MESSAGE-TAGS), echoed back in mail.tags by configuration-set
    events — exact attribution. Fallback: recipient match against
    recently-sent invoices (last_sent_to), for mail sent before tagging
    existed or via paths that don't tag.
    """
    from apps.billing.models import Invoice

    tags = (message.get('mail') or {}).get('tags') or {}
    tag_values = tags.get('rs_invoice_id') or []
    invoice_ids = [v for v in tag_values if str(v).isdigit()]
    if invoice_ids:
        return list(
            Invoice.all_objects.filter(pk__in=invoice_ids)
        )

    emails = [e for e in recipients if e]
    if not emails:
        return []
    cutoff = timezone.now() - timezone.timedelta(days=MATCH_WINDOW_DAYS)
    return list(
        Invoice.objects.filter(
            last_sent_to__in=emails,
            last_sent_at__gte=cutoff,
        ).exclude(status='CANCELLED')
    )


def _update_invoice_delivery_status(message, recipients, status, detail):
    """Persist a delivery-status transition, guarding against regressions."""
    if not status:
        return
    from apps.billing.models import Invoice

    try:
        invoices = _resolve_event_invoices(message, recipients)
    except Exception:
        logger.warning("Could not resolve invoices for SES event", exc_info=True)
        return

    new_rank = _STATUS_RANK.get(status, 0)
    now = timezone.now()
    for invoice in invoices:
        current_rank = _STATUS_RANK.get(invoice.email_delivery_status, 0)
        if new_rank < current_rank:
            continue
        # Queryset update: no save() side effects, no clobbering concurrent
        # payment edits, and the same regression guard applied atomically.
        allowed_current = [
            s for s, rank in _STATUS_RANK.items() if rank <= new_rank
        ]
        Invoice.all_objects.filter(
            pk=invoice.pk,
            email_delivery_status__in=allowed_current,
        ).update(
            email_delivery_status=status,
            email_delivery_status_at=now,
            email_delivery_detail=(detail or '')[:255],
        )
        logger.info(
            f"Invoice {invoice.invoice_number}: email delivery status → {status}"
        )


def _alert_shops_for_recipient(email, reason):
    """Find recently sent invoices addressed to this email and alert each
    invoice's shop (in-app notification to managers + email to the owner)."""
    from apps.billing.models import Invoice

    cutoff = timezone.now() - timezone.timedelta(days=MATCH_WINDOW_DAYS)
    invoices = (
        Invoice.objects.filter(
            last_sent_to__iexact=email,
            sent_at__gte=cutoff,
        )
        .exclude(status='CANCELLED')
        .select_related('tenant', 'customer')
    )

    if not invoices:
        # Surfaced in logs so a bounce that can't be matched (send path
        # predating last_sent_to, or outside the match window) is still
        # visible when debugging "customer says they never got it".
        logger.warning(
            f"SES event for {email} ({reason}) matched no recently-sent "
            f"invoice — no shop alerted"
        )
        return

    for invoice in invoices:
        try:
            _notify_shop_delivery_failure(invoice, email, reason)
        except Exception:
            logger.warning(
                f"Failed to notify shop about bounced invoice {invoice.invoice_number}",
                exc_info=True,
            )


def _notify_shop_delivery_failure(invoice, email, reason):
    tenant = invoice.tenant
    summary = (
        f"⚠️ Invoice {invoice.invoice_number} for {invoice.customer.name} "
        f"did not reach {email} — the email {reason}. "
        f"Check the address and re-send."
    )
    logger.warning(summary)

    # In-app: notify manager technicians (owner is one of them).
    try:
        from apps.technician_portal.models import Technician, TechnicianNotification
        managers = Technician.objects.filter(
            tenant=tenant, is_active=True, is_manager=True,
        )
        for tech in managers:
            TechnicianNotification.objects.create(
                technician=tech, message=summary, read=False,
            )
    except Exception:
        logger.warning("Could not create bounce TechnicianNotification", exc_info=True)

    # Email the shop's business address (and owner) about the failure.
    try:
        from django.conf import settings
        from core.email_utils import send_branded_email

        recipients = []
        if tenant and tenant.business_email:
            recipients.append(tenant.business_email)
        owner_email = getattr(getattr(tenant, 'owner', None), 'email', '')
        if owner_email and owner_email not in recipients:
            recipients.append(owner_email)
        if not recipients:
            return

        base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
        send_branded_email(
            subject=f"Invoice {invoice.invoice_number} could not be delivered",
            recipient_list=recipients,
            headline="Invoice Email Not Delivered",
            body_paragraphs=[
                f"The invoice email for {invoice.customer.name} "
                f"(invoice {invoice.invoice_number}) {reason}.",
                f"It was sent to {email}. Double-check the customer's email "
                f"address, then open the invoice and use Email Invoice to "
                f"re-send it.",
            ],
            detail_rows=[
                ('Invoice', invoice.invoice_number),
                ('Customer', invoice.customer.name),
                ('Sent to', email),
                ('Amount due', f"${invoice.amount_due:,.2f}"),
            ],
            button_text="Open Invoice",
            button_url=f"{base_url}/owner/invoices/{invoice.id}/",
            tenant=tenant,
            fail_silently=True,
        )
    except Exception:
        logger.warning("Could not send bounce alert email to shop", exc_info=True)
