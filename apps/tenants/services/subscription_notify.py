"""
Subscription lifecycle notifications: email AND in-app, from one call site.

Two problems this replaces.

**Email was the only channel.** Every subscription message -- payment
failed, subscription ended -- went out as email and nothing else. If it
landed in spam or the owner simply missed it, there was no second signal,
and the first thing they'd notice was losing write access. The SES bounce
handler already creates TechnicianNotification rows for exactly this reason
(apps/billing/webhooks.py); billing never did.

**The dunning copy was making things up.** It hardcoded `max_attempts = 4`
and told the shop "attempt N of 4" without reading Stripe's actual retry
configuration, which lives in the Dashboard and can be changed at any time.
Stripe hands us `next_payment_attempt` on every failed invoice: when it's
set, that's the real retry date; when it's null, that WAS the final attempt.
Say that instead of guessing.

Every notification here is (branded email to owners + managers) + (in-app
row for each active manager technician). In-app delivery is best-effort and
never blocks the email; email uses fail_silently so a dead SES connection
can't roll back the state change that triggered it.
"""

import logging
from datetime import datetime, timezone as dt_timezone

from django.conf import settings

logger = logging.getLogger(__name__)


def _base_url():
    return getattr(settings, 'BASE_URL', 'https://rssystems.io')


def _owner_name(tenant):
    owner = getattr(tenant, 'owner', None)
    return (owner.first_name if owner and owner.first_name else 'there')


def fmt_date(unix_ts):
    """Format a Stripe unix timestamp as a human date, '' when absent."""
    if not unix_ts:
        return ''
    try:
        return datetime.fromtimestamp(
            int(unix_ts), tz=dt_timezone.utc,
        ).strftime('%B %-d, %Y')
    except (TypeError, ValueError, OSError, OverflowError):
        return ''


def fmt_money(cents):
    if cents is None:
        return ''
    try:
        return f"${int(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return ''


def build_message(tenant, event_type, context):
    """Return the email/in-app content for a subscription event.

    Separated from delivery so the copy can be asserted in tests without
    mocking the mail backend.
    """
    name = tenant.name
    who = _owner_name(tenant)
    base = _base_url()

    if event_type == 'payment_failed':
        next_attempt = fmt_date(context.get('next_payment_attempt'))
        attempt = context.get('attempt_count', 1)
        if next_attempt:
            # Never invent an attempt count -- Stripe's retry schedule is
            # Dashboard config we don't read.
            retry_line = (
                f"We'll automatically try again on {next_attempt}. "
                "Updating your card now avoids any interruption."
            )
        else:
            retry_line = (
                "This was the final automatic attempt. Your subscription "
                "will be suspended unless the payment method is updated."
            )
        return {
            'subject': f'Payment failed for {name}',
            'headline': 'Payment Failed',
            'paragraphs': [
                f"Hi {who},",
                f"We were unable to process your payment for {name} "
                f"(attempt #{attempt}).",
                retry_line,
            ],
            'button_text': 'Update Payment Method',
            'button_url': f'{base}/owner/update-payment-method/',
            'in_app': (
                f"Subscription payment failed for {name}. "
                + (f"Stripe retries on {next_attempt}. " if next_attempt
                   else "This was the final attempt. ")
                + "Update your payment method in Settings > My Plan."
            ),
        }

    if event_type == 'payment_recovered':
        return {
            'subject': f'Payment successful for {name}',
            'headline': 'Good news!',
            'paragraphs': [
                f"Hi {who},",
                f"Your payment for {name} has been successfully processed. "
                "Your account is back to active status.",
                "No further action is needed — thank you for being a valued "
                "customer!",
            ],
            'button_text': 'Go to Dashboard',
            'button_url': f'{base}/owner/',
            'in_app': f"Subscription payment received — {name} is active again.",
        }

    if event_type == 'payment_action_required':
        return {
            'subject': f'Your bank needs to confirm a payment for {name}',
            'headline': 'Confirmation Needed',
            'paragraphs': [
                f"Hi {who},",
                f"Your bank is asking you to confirm the subscription payment "
                f"for {name} before it can complete.",
                "Until you confirm, the payment stays pending and the "
                "subscription may lapse.",
            ],
            'button_text': 'Confirm Payment',
            'button_url': context.get('hosted_invoice_url')
            or f'{base}/owner/billing/',
            'in_app': (
                f"Your bank needs you to confirm a payment for {name}. "
                "Until then the payment is not complete."
            ),
        }

    if event_type == 'renewal_upcoming':
        amount = fmt_money(context.get('amount_due'))
        when = fmt_date(context.get('next_payment_attempt'))
        amount_text = f" of {amount}" if amount else ""
        when_text = f" on {when}" if when else " shortly"
        return {
            'subject': f'Upcoming renewal for {name}',
            'headline': 'Upcoming Renewal',
            'paragraphs': [
                f"Hi {who},",
                f"Your subscription for {name} renews{when_text}"
                f"{f' and we will charge {amount}' if amount else ''}.",
                "No action is needed if your card on file is current.",
            ],
            'button_text': 'View Billing',
            'button_url': f'{base}/owner/billing/',
            'in_app': f"Subscription for {name} renews{when_text}{amount_text}.",
        }

    if event_type == 'past_due_reminder':
        days = context.get('days_past_due', 0)
        readonly_in = context.get('days_until_readonly')
        if readonly_in is not None and readonly_in > 0:
            urgency = (
                f"If the payment isn't resolved within {readonly_in} more "
                f"day{'s' if readonly_in != 1 else ''}, your shop moves to "
                "read-only — you'll still see everything, but you won't be "
                "able to log jobs or send invoices."
            )
        else:
            urgency = (
                "Your shop is now read-only until the payment is resolved."
            )
        return {
            'subject': f'Action needed: payment overdue for {name}',
            'headline': 'Payment Still Overdue',
            'paragraphs': [
                f"Hi {who},",
                f"We still haven't been able to process payment for {name} "
                f"({days} day{'s' if days != 1 else ''} overdue).",
                urgency,
            ],
            'button_text': 'Update Payment Method',
            'button_url': f'{base}/owner/update-payment-method/',
            'in_app': (
                f"Payment for {name} is {days} day"
                f"{'s' if days != 1 else ''} overdue. {urgency}"
            ),
        }

    if event_type == 'past_due_readonly':
        return {
            'subject': f'{name} is now read-only',
            'headline': 'Shop Is Read-Only',
            'paragraphs': [
                f"Hi {who},",
                f"We were not able to collect payment for {name}, so the shop "
                "has moved to read-only. Your data is all still here and "
                "nothing has been deleted.",
                "Updating your payment method restores full access "
                "immediately.",
            ],
            'button_text': 'Update Payment Method',
            'button_url': f'{base}/owner/update-payment-method/',
            'in_app': (
                f"{name} is now read-only because payment could not be "
                "collected. Update your payment method to restore access."
            ),
        }

    if event_type == 'subscription_ended':
        return {
            'subject': f'Your {name} subscription has ended',
            'headline': 'Subscription Ended',
            'paragraphs': [
                f"Hi {who},",
                f"Your subscription for {name} has ended.",
                "Your account is in read-only mode — you can view everything "
                "but not make changes. Nothing has been deleted.",
                "Resubscribe anytime to restore full access.",
            ],
            'button_text': 'Resubscribe',
            'button_url': f'{base}/owner/billing/',
            'in_app': (
                f"The subscription for {name} has ended. The shop is "
                "read-only until you resubscribe."
            ),
        }

    return {
        'subject': f'RS Systems notification for {name}',
        'headline': 'Account Notification',
        'paragraphs': [
            f"Hi {who},",
            f"A subscription event occurred for {name}.",
        ],
        'button_text': 'View Billing',
        'button_url': f'{base}/owner/billing/',
        'in_app': f"A subscription event occurred for {name}.",
    }


def create_in_app_notification(tenant, message):
    """Best-effort in-app notification for every active manager technician.

    Mirrors the SES bounce handler. Owners are managers, so this reaches
    them without a separate lookup. Never raises: an in-app failure must
    not cost us the email, nor roll back the state change that triggered it.
    """
    if not message:
        return 0
    try:
        from apps.technician_portal.models import Technician, TechnicianNotification

        managers = Technician.objects.filter(
            tenant=tenant, is_active=True, is_manager=True,
        )
        created = 0
        for tech in managers:
            TechnicianNotification.objects.create(
                technician=tech, message=message, read=False,
            )
            created += 1
        return created
    except Exception:
        logger.warning(
            "Could not create subscription TechnicianNotification for %s",
            getattr(tenant, 'slug', '?'), exc_info=True,
        )
        return 0


def notify_owners_and_managers(tenant, event_type, context=None):
    """Send a subscription notification by email and in-app.

    Never raises. The caller has already committed a state change; a mail
    failure must not undo it or trigger a Stripe retry.
    """
    context = context or {}
    try:
        from core.email_utils import send_branded_email
        from apps.tenants.webhooks import _get_owner_and_manager_emails

        msg = build_message(tenant, event_type, context)

        # In-app first: it's local and cannot fail slowly.
        create_in_app_notification(tenant, msg.get('in_app'))

        recipient_list = _get_owner_and_manager_emails(tenant)
        if not recipient_list:
            logger.warning(
                f"Cannot email owners/managers for tenant {tenant.slug}: "
                f"no addresses found"
            )
            return

        send_branded_email(
            subject=msg['subject'],
            recipient_list=recipient_list,
            headline=msg['headline'],
            body_paragraphs=msg['paragraphs'],
            button_text=msg.get('button_text'),
            button_url=msg.get('button_url'),
            tenant=tenant,
            # Subscription mail is from RS Systems, not the shop — the shop's
            # name goes on the right of the header, its brand colour nowhere.
            platform=True,
            fail_silently=True,
        )
        logger.info(
            f"Sent {event_type} notification to {recipient_list} "
            f"for tenant {tenant.slug}"
        )
    except Exception as e:
        logger.error(
            f"Failed to send {event_type} notification for tenant "
            f"{getattr(tenant, 'slug', '?')}: {e}"
        )
