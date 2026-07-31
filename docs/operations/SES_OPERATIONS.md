# Amazon SES Operations Runbook

**Scope:** Email delivery for RS Systems production (rssystems.io). All outbound email —
invoices, repair lifecycle notifications, subscription alerts, password resets, welcome
emails — goes through Amazon SES. **Email is the only invoice delivery channel.** If SES
stops sending, invoices and notifications silently stop.

## How Sending Works

- Django's SMTP backend (`django.core.mail.backends.smtp.EmailBackend`, set in
  `rs_systems/settings/base.py`) connects to `email-smtp.us-east-1.amazonaws.com:587` (TLS).
- Credentials are **SES SMTP credentials** (NOT an AWS access key pair), generated at
  SES Console → SMTP settings → Create SMTP credentials, and stored as Elastic Beanstalk
  env vars: `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`.
  Rotation/region change is `eb setenv`, not a deploy.
- From address: `notifications@rssystems.io` with display name `"<Shop> via RS Systems"`
  (`core/email_utils.py:shop_sender`). One address for all mail — one coherent domain
  reputation.
- **Authentication (2026-07-30):** Easy DKIM (2048-bit) + custom MAIL FROM
  `mail.rssystems.io` → SPF and DKIM both DMARC-aligned. DMARC is `p=none` with
  `rua=mailto:dmarc@rssystems.io`; tighten to `p=quarantine` after 2–4 clean weeks
  of reports.
- **Default configuration set `rs-systems-default`** is attached to the rssystems.io
  identity, so every SMTP send publishes SEND/DELIVERY/BOUNCE/COMPLAINT/REJECT/
  DELIVERY_DELAY events to SNS topic `rs-systems-ses-events`.
- `EMAIL_TIMEOUT=10` caps SMTP connect time so a slow provider can't hang web workers.
- Development uses the console backend unless `USE_REAL_EMAIL=True` **and**
  `EMAIL_HOST_PASSWORD` are set (`rs_systems/settings/development.py`).
- SES production access granted 2026-07-09 (50,000 msgs/day, 14 msgs/sec quota at grant time).

## Bounce / Complaint / Delivery Handling Today

- **SES event webhook** (`apps/billing/webhooks.py`, route
  `POST /api/billing/webhooks/ses/<SES_WEBHOOK_SECRET>/`) receives all configuration-set
  events via SNS. It attributes events to invoices via the `rs_invoice_id` message tag
  (set as `X-SES-MESSAGE-TAGS` at send time) or `last_sent_to` fallback, and stamps
  `Invoice.email_delivery_status` (sent → delivered / delayed / bounced / complained /
  rejected) — shown in the owner invoice list and detail pages.
- Permanent bounces, complaints, and rejects also alert the shop in-app and by email.
- **Account-level suppression list** (SES default) still suppresses hard-bounced or
  complained addresses account-wide.
- `NotificationDeliveryLog.STATUS_BOUNCED` is still never set (repair notifications
  aren't tagged yet) — see follow-ups.

## The Danger: Reputation-Based Sending Pause

SES tracks bounce and complaint rates account-wide. **Bounce rate above ~5% or complaint
rate above ~0.1%** puts the account under review; sustained bad rates lead SES to **pause
sending entirely**. A pause is silent from the app's perspective — SMTP sends start failing,
and every invoice email and repair notification stops. There is no fallback channel.

Common causes to watch: typo'd customer emails at signup (no verification loop), bulk
invoice runs to stale fleet contact lists, and test sends to fake addresses in production.

## What to Monitor

- **SES Console → Account dashboard (Reputation)** in `us-east-1`: bounce rate, complaint
  rate, account status. Check weekly, and before/after large batch invoice runs.
- **CloudWatch metrics** (namespace `AWS/SES`): `Bounce`, `Complaint`, `Send`, `Reject`.
  No alarms are configured yet — see follow-ups.
- **In-app:** `/admin/core/notificationdeliverylog/` shows per-attempt SMTP results
  (sent/failed + error message). It will NOT show bounces (see above).

## If Sending Is Paused (or Under Review)

1. Confirm in SES Console → Account dashboard (status banner) and check email from AWS
   to the account root address.
2. Stop the bleeding: pause batch invoice / reminder cron runs if a bad list caused it.
3. Open an **AWS Support case** (SES review/pause always comes with a case or the ability
   to open one). Explain cause and remediation; AWS typically wants proof you've removed
   bad addresses and added bounce handling.
4. **Interim workaround: none.** Email is the only invoice channel. Time-critical invoices
   would have to be downloaded from the app and sent manually from another mailbox.

## Testing Delivery

```bash
python manage.py test_ses your@email.com
```

Prints backend/host/from config and sends a real message via the configured backend.
To test without touching reputation, use the SES mailbox simulator:
`success@simulator.amazonses.com` (delivery) or `bounce@simulator.amazonses.com`
(exercises a bounce safely).

## Follow-Ups (not yet done)

- [ ] `eb setenv SES_WEBHOOK_SECRET=<random>` and subscribe the SNS topic to the webhook
      URL (topic + config set exist; subscription needs the secret live first)
- [ ] Tighten DMARC to `p=quarantine` after 2–4 clean weeks of rua reports
- [ ] Set `NotificationDeliveryLog.STATUS_BOUNCED` from SES events (field already exists;
      repair notifications need message tags first)
- [ ] Per-recipient suppression in-app: stop emailing addresses that hard-bounced
- [ ] CloudWatch alarms on Bounce/Complaint rates (alert well below 5% / 0.1%)
- [ ] Email verification loop at customer signup to prevent typo'd addresses
