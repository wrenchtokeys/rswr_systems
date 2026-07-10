# Notification System Documentation

**Status**: Complete | Notifications are synchronous (no Celery/Redis, no SMS)

## Overview

Complete documentation for the RS Systems notification system. Notifications fire
**synchronously** — no Celery, no Redis, no background workers, no SMS. When a repair event
fires a Django signal, the notification service runs inline during the request and delivers via
Amazon SES email + in-app notification.

## Quick Navigation

- [Configuration Guide](NOTIFICATION_CONFIGURATION_GUIDE.md) — branding, settings, phone numbers
- [Simple Testing Guide](SIMPLE_TESTING_GUIDE.md) — quick developer reference
- [Admin Dashboard Guide](ADMIN_DASHBOARD_GUIDE.md) — Django admin notification features
- [Operations Runbook](../../operations/NOTIFICATION_OPERATIONS.md) — daily ops, on-call, incident response

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

## Support & Troubleshooting

**Emails not sending?** Check `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` (the SES
SMTP credentials). Run `python manage.py test_ses your@email.com` to verify
connectivity. Send to `success@simulator.amazonses.com` to test without touching
your sender reputation.

**Notifications not triggering?** Verify signal handlers in `core/signals.py` are connected.
Check `INSTALLED_APPS` includes `core` with correct `AppConfig.ready()`.

**In-app notifications not showing?** Verify `NotificationTemplate` records exist:
`python manage.py setup_notification_templates`

See [NOTIFICATION_OPERATIONS.md](../../operations/NOTIFICATION_OPERATIONS.md) for the full
on-call runbook.
