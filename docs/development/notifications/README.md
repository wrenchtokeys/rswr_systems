# Notification System Documentation

**Status**: Complete | Notifications are synchronous (no Celery/Redis, no SMS)

> This is the canonical notification doc. The former `NOTIFICATION_CONFIGURATION_GUIDE.md`
> and `SIMPLE_TESTING_GUIDE.md` were merged into it (2026-07-10).

## Overview

Complete documentation for the RS Systems notification system. Notifications fire
**synchronously** — no Celery, no Redis, no background workers, no SMS. When a repair event
fires a Django signal, the notification service runs inline during the request and delivers via
Amazon SES email + in-app notification.

## Quick Navigation

- [Configuration](#configuration) — branding, contact info, preferences (below)
- [Admin Dashboard Guide](../ADMIN_DASHBOARD_GUIDE.md) — Django admin notification features
- [Operations Runbook](../../operations/NOTIFICATION_OPERATIONS.md) — daily ops, on-call, incident response
- [SES Operations Runbook](../../operations/SES_OPERATIONS.md) — email delivery, reputation, sending pauses

## Current Architecture

**4-Tier Priority System:**
- **URGENT**: Email + In-app (approvals, denials, critical assignments)
- **HIGH**: In-app + Email (new requests, completions, reassignments)
- **MEDIUM**: Email + In-app (status updates, photos, rewards)
- **LOW**: In-app only (notes, minor updates)

**Infrastructure:**
- **Amazon SES** (SMTP) for email delivery (`notifications@rssystems.io`)
- **In-app notifications** via database records
- **Signal-based triggers** — no task queue
- Customizable email templates with branding (`EmailBrandingConfig`)

8 repair-lifecycle templates are seeded via `python manage.py setup_notification_templates`
(see CLAUDE.md's "Notification System" section for the full list).

## Quick Start

```bash
# Run migrations
python manage.py migrate

# Create notification templates
python manage.py setup_notification_templates

# Start Django (just this — no background services needed)
python manage.py runserver
```

### Verify Setup

1. **Login**: http://localhost:8000/tech/login/
2. **Dashboard**: check notification bell icon in header
3. **Preferences**: http://localhost:8000/tech/notifications/preferences/
4. **Create test repair** in Django shell to trigger a notification
5. **Refresh dashboard** — bell icon should show unread count

### Testing

```bash
# Test Amazon SES delivery
python manage.py test_ses your@email.com

# Run test suite
python manage.py test core.tests

# Django checks
python manage.py check
```

**Quick developer workflow** (emails print to the console in development — watch the
runserver terminal):

1. Start Django: `python manage.py runserver`
2. Log in at http://localhost:8000/tech/
3. Create a repair in PENDING status, then approve it
4. Check the terminal output (console email backend), notification history at
   `/tech/notifications/history/`, and the admin at `/admin/core/notification/`

To send real email from development, set `USE_REAL_EMAIL=True` plus the SES SMTP credentials.

### Technician Portal URLs

| Path | Description |
|------|-------------|
| `/tech/` | Dashboard with notification bell |
| `/tech/notifications/preferences/` | Notification preferences |
| `/tech/notifications/history/` | Notification history |
| `/tech/notifications/<id>/mark-read/` | Mark single as read (POST) |
| `/tech/notifications/mark-all-read/` | Mark all as read (POST) |
| `/tech/notifications/unread-count/` | Unread count (GET, AJAX) |
| `/tech/verify-email/` | Send email verification |

### Security Notes

- **Development**: emails print to console (`USE_REAL_EMAIL=True` to send for real), DEBUG=True
- **Production**: real emails via Amazon SES, CSRF protection, HTTPS required, rate limiting

## Event-to-Priority Mapping Reference

| Event | Recipient | Priority | Channels | Template |
|-------|-----------|----------|----------|----------|
| Repair created (PENDING) | Customer | HIGH | Email + In-app | `repair_pending_approval` |
| Repair approved | Technician | URGENT | Email + In-app | `repair_approved` |
| Repair denied | Technician | URGENT | Email + In-app | `repair_denied` |
| Technician assigned | Technician | HIGH | Email + In-app | `repair_assigned` |
| Technician reassigned | Old Tech | MEDIUM | Email + In-app | `repair_reassigned_away` |
| Repair in progress | Customer | MEDIUM | Email + In-app | `repair_in_progress` |
| Repair completed | Customer | HIGH | Email + In-app | `repair_completed` |
| Batch approved | Technician | URGENT | Email + In-app | `batch_approved` |

## Configuration

### Email Branding

**URL**: http://localhost:8000/admin/core/emailbrandingconfig/ (staff/admin access;
singleton — edit the one existing config)

Configurable: company logo (max ~400px wide, JPG/PNG, auto-optimized), six brand colors
(primary, secondary, success, danger, text, background), company info (name, address,
support email/phone, website), optional social links, typography, and footer text.

After saving, verify with an email template preview (below).

### Email Template Previews

Staff-only preview URLs render the full branded HTML with sample repair data:

- http://localhost:8000/admin/email-preview/repair_approved/
- http://localhost:8000/admin/email-preview/repair_denied/
- http://localhost:8000/admin/email-preview/repair_assigned/
- http://localhost:8000/admin/email-preview/repair_completed/
- http://localhost:8000/admin/email-preview/batch_approved/

### User Contact Information

- **Customers**: http://localhost:8000/admin/core/customer/ — set email and phone
  (E.164 format, e.g. `+12025551234`) and check **Email Verified** to enable email
  notifications.
- **Technicians**: http://localhost:8000/admin/technician_portal/technician/ — same
  verification flags; the email address itself lives on the linked User account.

### Notification Preferences

**Technicians**: http://localhost:8000/tech/notifications/preferences/ — delivery channel
toggles (email/in-app), per-category preferences (status updates, assignments,
approvals/denials, reassignments, batch operations, rewards), quiet hours (held until
morning), and daily digest mode. Customers have equivalent options in the customer portal.

To silence a user: uncheck their verified flags in admin, or have them disable channels in
their own preferences.

### Environment Variables (email)

```bash
# Amazon SES over SMTP — SMTP credentials, NOT an AWS access key pair
EMAIL_HOST=email-smtp.us-east-1.amazonaws.com
EMAIL_HOST_USER=<SES SMTP username>
EMAIL_HOST_PASSWORD=<SES SMTP password>
DEFAULT_FROM_EMAIL=notifications@rssystems.io
```

Settings live in `rs_systems/settings/` — `base.py` holds the SMTP email config (env-driven,
no code change needed to rotate credentials or switch regions); `development.py` uses the
console backend by default; `production.py` sends for real. Enabling production email is:
generate SES SMTP credentials (SES Console → SMTP settings), `eb setenv` the variables above,
then verify with `python manage.py test_ses your@email.com`.

## Monitoring & Logs

- **All notifications**: http://localhost:8000/admin/core/notification/ — priority,
  category, read/unread, created date.
- **Delivery logs**: http://localhost:8000/admin/core/notificationdeliverylog/ — per-attempt
  status (sent/failed/pending_retry), recipient, error message, attempt number, next retry.
- **User-facing history**: http://localhost:8000/tech/notifications/history/

## Support & Troubleshooting

**Emails not sending?** Check `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` (the SES
SMTP credentials). Run `python manage.py test_ses your@email.com` to verify
connectivity. Send to `success@simulator.amazonses.com` to test without touching
your sender reputation. In development the console backend just prints — that is not
a failure.

**Notification created but not delivered?** Check delivery logs for errors, then the user's
preferences (channel may be disabled), verified flags, and quiet-hours settings.

**Notifications not triggering?** Verify signal handlers in `core/signals.py` are connected.
Check `INSTALLED_APPS` includes `core` with correct `AppConfig.ready()`.

**In-app notifications not showing?** Verify `NotificationTemplate` records exist:
`python manage.py setup_notification_templates`

**Phone number format errors?** Use E.164: `+12025551234` (not `202-555-1234`).

**Branding not updating?** Hard-refresh the preview page and confirm the admin save succeeded.

## Pre-Production Checklist

- [ ] Email branding configured (logo, colors, company info)
- [ ] Customer/technician contact info entered, verification flags set
- [ ] SES SMTP credentials configured (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`)
- [ ] `DEFAULT_FROM_EMAIL=notifications@rssystems.io`
- [ ] Templates previewed and approved
- [ ] `python manage.py test_ses` succeeds against a real inbox
- [ ] Delivery logs checked for errors

See [NOTIFICATION_OPERATIONS.md](../../operations/NOTIFICATION_OPERATIONS.md) for the full
on-call runbook.
