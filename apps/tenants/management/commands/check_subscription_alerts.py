"""
Management command: check_subscription_alerts

Scans all tenants and sends subscription lifecycle email notifications to
owners AND managers. Designed to be run via cron.

Emails sent:
- 7 days before trial expires
- 1 day before trial expires
- On trial/subscription expiry (subscription_status transitions)
- 15 days into grace period
- 5 days before grace period ends
- When grace period has ended

Uses tenant.subscription_alerts_sent (JSONField) to track sent alerts
and avoid duplicate emails.

Author: Amelia (Clawdbot AI)
"""

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from apps.tenants.models import Tenant, TenantMembership

logger = logging.getLogger(__name__)

# Alert type keys stored in subscription_alerts_sent
ALERT_TRIAL_7_DAYS = 'trial_expiry_7_days'
ALERT_TRIAL_1_DAY = 'trial_expiry_1_day'
ALERT_TRIAL_EXPIRED = 'trial_expired'
ALERT_SUB_EXPIRED = 'subscription_expired'
ALERT_GRACE_15_DAYS = 'grace_period_15_days'
ALERT_GRACE_5_DAYS = 'grace_period_5_days'
ALERT_GRACE_ENDED = 'grace_period_ended'
ALERT_TRIAL_PLAN_NUDGE = 'trial_plan_nudge'
# Dunning nudges. The webhook sends one email at the moment of failure and
# that was the whole dunning sequence -- easy to miss, and nothing followed
# up during Stripe's ~3-week retry window.
ALERT_PAST_DUE_3_DAYS = 'past_due_3_days'
ALERT_PAST_DUE_7_DAYS = 'past_due_7_days'
ALERT_PAST_DUE_READONLY = 'past_due_readonly'


def _base_url():
    """Button URLs were hardcoded to https://rssystems.io, so every link in
    every alert pointed at production regardless of environment."""
    return getattr(settings, 'BASE_URL', 'https://rssystems.io')


def _get_recipient_emails(tenant):
    """Get email addresses for all owners and managers of a tenant."""
    emails = set()
    if tenant.owner and tenant.owner.email:
        emails.add(tenant.owner.email)
    manager_emails = (
        TenantMembership.objects
        .filter(tenant=tenant, role='manager', is_active=True)
        .exclude(user__email='')
        .values_list('user__email', flat=True)
    )
    emails.update(manager_emails)
    return list(emails)


def _send_alert(tenant, alert_key, subject, body, dry_run=False,
                headline=None, paragraphs=None, button_text=None, button_url=None):
    """
    Send an alert email if it hasn't been sent already.

    If headline + paragraphs are provided, sends a branded HTML email.
    Otherwise falls back to plain text (for backwards compat).

    Returns True if the alert was sent (or would be sent in dry_run).
    """
    alerts_sent = tenant.subscription_alerts_sent or {}
    if alert_key in alerts_sent:
        logger.debug(f"Alert '{alert_key}' already sent for tenant {tenant.slug}, skipping.")
        return False

    recipients = _get_recipient_emails(tenant)
    if not recipients:
        logger.warning(f"No recipients for tenant {tenant.slug} alert '{alert_key}'")
        return False

    if dry_run:
        logger.info(
            f"[DRY RUN] Would send '{alert_key}' to {recipients} for tenant {tenant.slug}"
        )
        return True

    try:
        if headline and paragraphs:
            from core.email_utils import send_branded_email
            send_branded_email(
                subject=subject,
                recipient_list=recipients,
                headline=headline,
                body_paragraphs=paragraphs,
                button_text=button_text,
                button_url=button_url,
                tenant=tenant,
                # Billing mail is the platform's voice, never the shop's.
                platform=True,
            )
        else:
            # Fallback: wrap plain-text body in branded template
            from core.email_utils import send_branded_email
            send_branded_email(
                subject=subject,
                recipient_list=recipients,
                headline=subject,
                body_paragraphs=[body] if body else ['A subscription event occurred.'],
                tenant=tenant,
                platform=True,
            )
    except Exception as e:
        logger.error(
            f"Failed to send alert '{alert_key}' for tenant {tenant.slug}: {e}"
        )
        return False

    # Record the alert as sent — update both DB and in-memory object
    # so subsequent _send_alert calls in the same run see the updated dict.
    # Without updating tenant.subscription_alerts_sent, a None→{} fallback
    # creates an unlinked dict and later alerts overwrite earlier ones in the DB.
    alerts_sent[alert_key] = timezone.now().isoformat()
    tenant.subscription_alerts_sent = alerts_sent
    Tenant.objects.filter(pk=tenant.pk).update(subscription_alerts_sent=alerts_sent)
    logger.info(f"Sent alert '{alert_key}' to {recipients} for tenant {tenant.slug}")
    return True


def _owner_name(tenant):
    """Return the owner's first name (or 'there' if not set)."""
    if tenant.owner and tenant.owner.first_name:
        return tenant.owner.first_name
    return 'there'


class Command(BaseCommand):
    help = 'Check subscription lifecycle and send alert emails to owners and managers.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Log what would be sent without actually sending emails.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()
        today = now.date()

        if dry_run:
            self.stdout.write(self.style.WARNING('Running in DRY RUN mode — no emails will be sent.'))

        sent_count = 0
        tenant_count = 0

        # Process all tenants (active and inactive)
        for tenant in Tenant.objects.select_related('owner', 'subscription_plan').all():
            tenant_count += 1
            sent = self._check_tenant(tenant, now, today, dry_run)
            sent_count += sent

        sent_count += self._report_failed_webhooks(dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {tenant_count} tenants, sent {sent_count} alert emails."
            )
        )

    def _check_tenant(self, tenant, now, today, dry_run):
        """Check a single tenant and send any needed alerts. Returns number of alerts sent."""
        sent = 0

        # --- Trial expiry alerts ---
        if tenant.plan == 'trial' and tenant.trial_expiry and not tenant.is_trial_expired:
            days_until_expiry = (tenant.trial_expiry.date() - today).days

            if days_until_expiry <= 7:
                if _send_alert(
                    tenant, ALERT_TRIAL_7_DAYS,
                    subject=f"Your {tenant.name} trial ends in 7 days",
                    body='',
                    dry_run=dry_run,
                    headline='Your Trial Ends Soon',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"Your free trial for {tenant.name} ends in 7 days ({tenant.trial_expiry.strftime('%B %d, %Y')}).",
                        "Upgrade now to keep your data and avoid any service interruption.",
                    ],
                    button_text='Upgrade Now',
                    button_url=f'{_base_url()}/owner/billing/',
                ):
                    sent += 1

            if days_until_expiry <= 1:
                if _send_alert(
                    tenant, ALERT_TRIAL_1_DAY,
                    subject=f"Your {tenant.name} trial expires tomorrow!",
                    body='',
                    dry_run=dry_run,
                    headline='Trial Expires Tomorrow!',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"Your free trial for {tenant.name} expires tomorrow ({tenant.trial_expiry.strftime('%B %d, %Y')}).",
                        "Don't lose access to your shop data! Upgrade today.",
                    ],
                    button_text='Upgrade Today',
                    button_url=f'{_base_url()}/owner/billing/',
                ):
                    sent += 1

        # --- Nudge email for 'not sure' signups around day 20 ---
        if (tenant.plan == 'trial' and tenant.trial_expiry and not tenant.is_trial_expired
                and not tenant.intended_plan):
            days_until_expiry = (tenant.trial_expiry.date() - today).days
            if 0 < days_until_expiry <= 10:
                if _send_alert(
                    tenant, ALERT_TRIAL_PLAN_NUDGE,
                    subject=f"Which plan is right for {tenant.name}?",
                    body='',
                    dry_run=dry_run,
                    headline='Find Your Perfect Plan',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"Your trial has {days_until_expiry} day{'s' if days_until_expiry != 1 else ''} left.",
                        "We have options for shops of all sizes — from solo techs to large fleets. Browse our plans to find the right fit for your shop.",
                    ],
                    button_text='View Plans',
                    button_url=f'{_base_url()}/pricing/',
                ):
                    sent += 1

        # --- Trial just expired ---
        if tenant.plan == 'trial' and tenant.is_trial_expired:
            if not tenant.had_paid_subscription:
                alert_key = ALERT_TRIAL_EXPIRED
                subject = f"Your {tenant.name} free trial has expired"
                headline = 'Trial Expired'
                paragraphs = [
                    f"Hi {_owner_name(tenant)},",
                    f"Your free trial for {tenant.name} has expired.",
                    # D4: expired trials are blocked immediately (no grace
                    # period exists for trials — the trial itself was the
                    # grace). The old copy promised "30 days of read-only
                    # access" the middleware never granted.
                    "Your account is now locked, but your data is safe. Upgrade any time to pick up right where you left off.",
                ]
            else:
                alert_key = ALERT_SUB_EXPIRED
                subject = f"Your {tenant.name} subscription has ended"
                headline = 'Subscription Ended'
                paragraphs = [
                    f"Hi {_owner_name(tenant)},",
                    f"Your subscription for {tenant.name} has ended.",
                    "You have 30 days of read-only access to your data. Reactivate now to restore full access.",
                ]
            if _send_alert(tenant, alert_key, subject=subject, body='', dry_run=dry_run,
                           headline=headline, paragraphs=paragraphs,
                           button_text='Reactivate Now',
                           button_url=f'{_base_url()}/owner/billing/'):
                sent += 1

        # --- Subscription expired (paid subscription deleted via webhook) ---
        if tenant.subscription_status == 'expired' and tenant.had_paid_subscription:
            if _send_alert(
                tenant, ALERT_SUB_EXPIRED,
                subject=f"Your {tenant.name} subscription has expired",
                body='',
                dry_run=dry_run,
                headline='Subscription Expired',
                paragraphs=[
                    f"Hi {_owner_name(tenant)},",
                    f"Your RS Systems subscription for {tenant.name} has expired.",
                    "You have 30 days of read-only access to your data. Reactivate now to restore full access.",
                ],
                button_text='Reactivate Now',
                button_url=f'{_base_url()}/owner/billing/',
            ):
                sent += 1

        # --- Grace period alerts ---
        grace_end = tenant.effective_grace_period_end
        if grace_end and tenant.is_in_grace_period:
            days_remaining = tenant.grace_days_remaining

            if days_remaining <= 15:
                if _send_alert(
                    tenant, ALERT_GRACE_15_DAYS,
                    subject=f"15 days of read-only access remaining for {tenant.name}",
                    body='',
                    dry_run=dry_run,
                    headline='Read-Only Access Ending Soon',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"You have 15 days of read-only access remaining for {tenant.name}.",
                        f"After {grace_end.strftime('%B %d, %Y')}, your account will be fully locked and you'll need to contact support to recover your data.",
                    ],
                    button_text='Reactivate Now',
                    button_url=f'{_base_url()}/owner/billing/',
                ):
                    sent += 1

            if days_remaining <= 5:
                if _send_alert(
                    tenant, ALERT_GRACE_5_DAYS,
                    subject=f"Your read-only access ends in {days_remaining} days — {tenant.name}",
                    body='',
                    dry_run=dry_run,
                    headline=f'{days_remaining} Days Left',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"Your read-only access for {tenant.name} ends in {days_remaining} day{'s' if days_remaining != 1 else ''}.",
                        f"After {grace_end.strftime('%B %d, %Y')}, you will lose access to your shop's data entirely.",
                    ],
                    button_text='Upgrade Now',
                    button_url=f'{_base_url()}/owner/billing/',
                ):
                    sent += 1

        # --- Grace period ended ---
        if grace_end and not tenant.is_in_grace_period:
            is_expired = (
                tenant.subscription_status in ('expired', 'canceled')
                or (tenant.plan == 'trial' and tenant.is_trial_expired)
            )
            if is_expired:
                if _send_alert(
                    tenant, ALERT_GRACE_ENDED,
                    subject=f"Your read-only access has ended — {tenant.name}",
                    body='',
                    dry_run=dry_run,
                    headline='Access Ended',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"Your read-only access period for {tenant.name} has ended.",
                        "You no longer have access to your shop's data in RS Systems. Upgrade your subscription to regain access.",
                        "If you need help recovering your data, contact us at contact@rssystems.io",
                    ],
                    button_text='Reactivate',
                    button_url=f'{_base_url()}/owner/billing/',
                ):
                    sent += 1

        # --- Past-due dunning nudges ---
        #
        # The webhook fires one email at the moment of failure and that was
        # the entire sequence. One email is easy to miss, and nothing
        # followed up across Stripe's ~3-week retry window -- so the first
        # thing a shop noticed was losing write access.
        if tenant.subscription_status == 'past_due' and tenant.past_due_since:
            days = tenant.days_past_due
            until_readonly = tenant.past_due_days_until_read_only

            if tenant.past_due_is_read_only:
                if _send_alert(
                    tenant, ALERT_PAST_DUE_READONLY,
                    subject=f"{tenant.name} is now read-only",
                    body='',
                    dry_run=dry_run,
                    headline='Shop Is Read-Only',
                    paragraphs=[
                        f"Hi {_owner_name(tenant)},",
                        f"We still haven't been able to collect payment for "
                        f"{tenant.name}, so the shop has moved to read-only.",
                        "Your data is all still here and nothing has been "
                        "deleted. Updating your payment method restores full "
                        "access immediately.",
                    ],
                    button_text='Update Payment Method',
                    button_url=f'{_base_url()}/owner/update-payment-method/',
                ):
                    sent += 1
            else:
                for threshold, key in (
                    (7, ALERT_PAST_DUE_7_DAYS),
                    (3, ALERT_PAST_DUE_3_DAYS),
                ):
                    if days >= threshold:
                        if _send_alert(
                            tenant, key,
                            subject=f"Action needed: payment overdue for {tenant.name}",
                            body='',
                            dry_run=dry_run,
                            headline='Payment Still Overdue',
                            paragraphs=[
                                f"Hi {_owner_name(tenant)},",
                                f"We still haven't been able to process payment "
                                f"for {tenant.name} ({days} day"
                                f"{'s' if days != 1 else ''} overdue).",
                                f"If this isn't resolved within {until_readonly} "
                                f"more day{'s' if until_readonly != 1 else ''}, "
                                f"your shop moves to read-only — you'll still "
                                f"see everything, but you won't be able to log "
                                f"jobs or send invoices.",
                            ],
                            button_text='Update Payment Method',
                            button_url=f'{_base_url()}/owner/update-payment-method/',
                        ):
                            sent += 1
                        break

        return sent

    def _report_failed_webhooks(self, dry_run):
        """Digest of Stripe events that failed to process in the last 24h.

        These are events Stripe is still retrying, or has given up on. They
        used to be invisible: the endpoint returned 200 on every exception,
        so the Stripe Dashboard reported 100% delivery success while events
        were being dropped. Silent when there is nothing to report.
        """
        try:
            from apps.billing.services.webhook_log import recent_failures
            failures = list(recent_failures(hours=24)[:50])
        except Exception:
            logger.exception("Could not query failed webhook events")
            return 0

        if not failures:
            return 0

        alert_to = getattr(settings, 'PLATFORM_ALERT_EMAIL', '')
        if not alert_to:
            return 0

        lines = [
            f"{f.event_type} [{f.event_id}] attempts={f.attempts}: "
            f"{(f.last_error or '')[:200]}"
            for f in failures
        ]
        if dry_run:
            self.stdout.write(
                f"[dry run] would report {len(failures)} failed webhook event(s)"
            )
            return 0

        try:
            from core.email_utils import send_branded_email
            send_branded_email(
                subject=f"{len(failures)} Stripe webhook event(s) failed",
                recipient_list=[alert_to],
                headline='Stripe Webhook Failures',
                body_paragraphs=[
                    f"{len(failures)} Stripe event(s) failed to process in the "
                    f"last 24 hours. Stripe retries for about 3 days; after "
                    f"that they are lost.",
                    "Inspect them in Django admin under Stripe Webhook Events "
                    "(filter status=failed) — the full payload is stored for "
                    "replay.",
                ] + lines,
                fail_silently=True,
            )
        except Exception:
            logger.exception("Could not send failed-webhook digest")
            return 0
        return 1
