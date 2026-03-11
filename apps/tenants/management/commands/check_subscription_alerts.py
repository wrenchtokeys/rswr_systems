"""
Management command: check_subscription_alerts

Scans all tenants and sends subscription lifecycle email notifications to
owners AND managers. Designed to be run via cron or Celery Beat.

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


def _send_alert(tenant, alert_key, subject, body, dry_run=False):
    """
    Send an alert email if it hasn't been sent already.

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

    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'notifications@rssystems.io')
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=recipients,
            fail_silently=False,
        )
    except Exception as e:
        logger.error(
            f"Failed to send alert '{alert_key}' for tenant {tenant.slug}: {e}"
        )
        return False

    # Record the alert as sent
    alerts_sent[alert_key] = timezone.now().isoformat()
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
                    body=(
                        f"Hi {_owner_name(tenant)},\n\n"
                        f"Your free trial for {tenant.name} ends in 7 days "
                        f"({tenant.trial_expiry.strftime('%B %d, %Y')}).\n\n"
                        f"Upgrade now to keep your data and avoid any service interruption:\n"
                        f"https://rssystems.io/owner/billing/\n\n"
                        f"— RS Systems"
                    ),
                    dry_run=dry_run,
                ):
                    sent += 1

            if days_until_expiry <= 1:
                if _send_alert(
                    tenant, ALERT_TRIAL_1_DAY,
                    subject=f"Your {tenant.name} trial expires tomorrow!",
                    body=(
                        f"Hi {_owner_name(tenant)},\n\n"
                        f"Your free trial for {tenant.name} expires tomorrow "
                        f"({tenant.trial_expiry.strftime('%B %d, %Y')}).\n\n"
                        f"Don't lose access to your shop data! Upgrade today:\n"
                        f"https://rssystems.io/owner/billing/\n\n"
                        f"— RS Systems"
                    ),
                    dry_run=dry_run,
                ):
                    sent += 1

        # --- Trial just expired ---
        if tenant.plan == 'trial' and tenant.is_trial_expired:
            # Distinguish real trial expiry from post-cancellation revert
            if not tenant.had_paid_subscription:
                alert_key = ALERT_TRIAL_EXPIRED
                subject = f"Your {tenant.name} free trial has expired"
                body = (
                    f"Hi {_owner_name(tenant)},\n\n"
                    f"Your free trial for {tenant.name} has expired.\n\n"
                    f"You have 30 days of read-only access to your data before your account "
                    f"is fully locked. Upgrade now to restore full access:\n"
                    f"https://rssystems.io/owner/billing/\n\n"
                    f"— RS Systems"
                )
            else:
                alert_key = ALERT_SUB_EXPIRED
                subject = f"Your {tenant.name} subscription has ended"
                body = (
                    f"Hi {_owner_name(tenant)},\n\n"
                    f"Your subscription for {tenant.name} has ended.\n\n"
                    f"You have 30 days of read-only access to your data. "
                    f"Reactivate now to restore full access:\n"
                    f"https://rssystems.io/owner/billing/\n\n"
                    f"— RS Systems"
                )
            if _send_alert(tenant, alert_key, subject=subject, body=body, dry_run=dry_run):
                sent += 1

        # --- Subscription expired (paid subscription deleted via webhook) ---
        if tenant.subscription_status == 'expired' and tenant.had_paid_subscription:
            if _send_alert(
                tenant, ALERT_SUB_EXPIRED,
                subject=f"Your {tenant.name} subscription has expired",
                body=(
                    f"Hi {_owner_name(tenant)},\n\n"
                    f"Your RS Systems subscription for {tenant.name} has expired.\n\n"
                    f"You have 30 days of read-only access to your data. "
                    f"Reactivate now to restore full access:\n"
                    f"https://rssystems.io/owner/billing/\n\n"
                    f"— RS Systems"
                ),
                dry_run=dry_run,
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
                    body=(
                        f"Hi {_owner_name(tenant)},\n\n"
                        f"You have 15 days of read-only access remaining for {tenant.name}.\n\n"
                        f"After {grace_end.strftime('%B %d, %Y')}, your account will be fully "
                        f"locked and you'll need to contact support to recover your data.\n\n"
                        f"Reactivate your subscription now:\n"
                        f"https://rssystems.io/owner/billing/\n\n"
                        f"— RS Systems"
                    ),
                    dry_run=dry_run,
                ):
                    sent += 1

            if days_remaining <= 5:
                if _send_alert(
                    tenant, ALERT_GRACE_5_DAYS,
                    subject=f"⚠️ Your read-only access ends in {days_remaining} days — {tenant.name}",
                    body=(
                        f"Hi {_owner_name(tenant)},\n\n"
                        f"Your read-only access for {tenant.name} ends in {days_remaining} "
                        f"day{'s' if days_remaining != 1 else ''}.\n\n"
                        f"After {grace_end.strftime('%B %d, %Y')}, you will lose access to "
                        f"your shop's data entirely. Upgrade now to avoid this:\n"
                        f"https://rssystems.io/owner/billing/\n\n"
                        f"— RS Systems"
                    ),
                    dry_run=dry_run,
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
                    body=(
                        f"Hi {_owner_name(tenant)},\n\n"
                        f"Your read-only access period for {tenant.name} has ended.\n\n"
                        f"You no longer have access to your shop's data in RS Systems. "
                        f"Upgrade your subscription to regain access:\n"
                        f"https://rssystems.io/owner/billing/\n\n"
                        f"If you need help recovering your data, contact us at "
                        f"support@rssystems.io\n\n"
                        f"— RS Systems"
                    ),
                    dry_run=dry_run,
                ):
                    sent += 1

        return sent
