"""
AWS SES delivery-event webhook (bounces / complaints via SNS).

When an invoice email bounces, the shop currently finds out never — the
invoice sits "SENT" while the customer never got it. SES publishes bounce
and complaint events to an SNS topic; an HTTPS subscription on that topic
POSTs them here. We match the bounced recipient to recently sent invoices
(Invoice.last_sent_to) and alert the shop in-app and by email.

One-time AWS setup (see docs/deployment/SES_BOUNCE_NOTIFICATIONS.md):
  1. Create an SNS topic (e.g. rs-systems-ses-events).
  2. SES console → verified identity (or configuration set) → set Bounce and
     Complaint feedback notifications to that topic.
  3. Subscribe the topic to
     https://rssystems.io/api/billing/webhooks/ses/<SES_WEBHOOK_SECRET>/
     (HTTPS). This endpoint auto-confirms the subscription.
  4. `eb setenv SES_WEBHOOK_SECRET=<long random string>`.

The URL secret is the auth: without it the endpoint 404s. A forged POST with
the secret could at worst generate a spurious "email bounced" alert.
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


def _handle_ses_event(message):
    """Route a decoded SES notification to bounce/complaint handling.

    Every event type is logged with its recipients — this log is the
    per-message delivery audit trail ("did Penske's server accept it?"),
    which SES otherwise provides nowhere queryable.
    """
    event_type = message.get('notificationType') or message.get('eventType') or ''
    if event_type == 'Bounce':
        bounce = message.get('bounce') or {}
        recipients = [r.get('emailAddress', '')
                      for r in bounce.get('bouncedRecipients', [])]
        logger.warning(
            f"SES {bounce.get('bounceType', '?')} bounce for "
            f"{', '.join(filter(None, recipients)) or 'unknown recipient'} "
            f"(subType={bounce.get('bounceSubType', '?')})"
        )
        # Transient bounces (mailbox full, greylisting) usually self-resolve;
        # only hard/permanent bounces mean "this address doesn't work".
        if bounce.get('bounceType') == 'Transient':
            return
        reason = 'bounced (could not be delivered)'
    elif event_type == 'Complaint':
        complaint = message.get('complaint') or {}
        recipients = [r.get('emailAddress', '')
                      for r in complaint.get('complainedRecipients', [])]
        logger.warning(
            f"SES complaint (marked as spam) from "
            f"{', '.join(filter(None, recipients)) or 'unknown recipient'}"
        )
        reason = 'was marked as spam by the recipient'
    elif event_type == 'Delivery':
        delivery = message.get('delivery') or {}
        recipients = delivery.get('recipients') or []
        logger.info(
            f"SES delivery confirmed to {', '.join(recipients)} "
            f"(mta={delivery.get('reportingMTA', '?')})"
        )
        return
    else:
        return

    for email in filter(None, recipients):
        _alert_shops_for_recipient(email, reason)


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
