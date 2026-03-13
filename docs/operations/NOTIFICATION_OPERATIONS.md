# Notification System Operations Guide

**Purpose**: Daily, weekly, and monthly operational procedures for the RS Systems notification system.

**Last Updated**: March 2026
**Audience**: DevOps Team, Backend Engineers, On-Call Engineers

> **Architecture**: Notifications are **synchronous** — no Celery workers, no Redis, no background queues.
> Emails deliver inline via SendGrid during the request. Billing tasks run as management commands
> via EB cron (not notification tasks).

---

## Table of Contents

1. [Daily Monitoring Tasks](#daily-monitoring-tasks)
2. [Weekly Review Procedures](#weekly-review-procedures)
3. [Monthly Maintenance Tasks](#monthly-maintenance-tasks)
4. [Incident Response Procedures](#incident-response-procedures)
5. [Health Check Dashboard](#health-check-dashboard)
6. [Performance Baselines](#performance-baselines)
7. [Troubleshooting Runbook](#troubleshooting-runbook)

---

## Daily Monitoring Tasks

**Time Required**: 10-15 minutes
**When**: Morning (9:00 AM)
**Owner**: On-call engineer

### 1. Check Application Health

```bash
# Production health check
curl -s https://rssystems.io/health/

# Expected: {"status": "healthy"}
```

### 2. Review CloudWatch Alarms

```bash
aws cloudwatch describe-alarms \
    --alarm-name-prefix RS-Systems- \
    --state-value ALARM \
    --region us-east-1
```

**Expected**: All alarms in `OK` state.

### 3. Check Delivery Success Rates

```bash
cd /var/app/current
source /var/app/venv/*/bin/activate
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta

yesterday = timezone.now() - timedelta(days=1)

email_total = NotificationDeliveryLog.objects.filter(channel='email', created_at__gte=yesterday).count()
email_delivered = NotificationDeliveryLog.objects.filter(channel='email', created_at__gte=yesterday, status='delivered').count()
email_rate = (email_delivered / email_total * 100) if email_total > 0 else 0
print(f"Email Delivery Rate (24h): {email_rate:.1f}% ({email_delivered}/{email_total})")
```

**Target**: Email ≥ 95%

### 4. Check EB Cron (Billing Tasks)

Verify billing management commands ran:

```bash
eb logs | grep -E "(process_batch_invoices|process_overdue_invoices|generate_aging_report)"
```

Or check the EB cron log directly:

```bash
eb ssh
sudo tail -50 /var/log/eb-activity.log | grep billing
```

---

## Weekly Review Procedures

**Time Required**: 30-45 minutes
**When**: Monday morning

### 1. Analyze Notification Volume

```bash
python manage.py shell

from core.models import Notification
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

week_ago = timezone.now() - timedelta(days=7)

category_breakdown = Notification.objects.filter(
    created_at__gte=week_ago
).values('category').annotate(count=Count('id')).order_by('-count')

print("Weekly Notifications by Category:")
for cat in category_breakdown:
    print(f"  {cat['category']}: {cat['count']}")
```

### 2. Failed Delivery Analysis

```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

week_ago = timezone.now() - timedelta(days=7)

errors = NotificationDeliveryLog.objects.filter(
    created_at__gte=week_ago,
    status__in=['failed', 'failed_permanent']
).values('error_message').annotate(count=Count('id')).order_by('-count')[:10]

print("Top Failure Reasons (Past Week):")
for e in errors:
    print(f"  {e['count']:3d}  {e['error_message'][:70]}")
```

### 3. Database Cleanup Check

```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone

oldest = NotificationDeliveryLog.objects.order_by('created_at').first()
if oldest:
    age = (timezone.now() - oldest.created_at).days
    print(f"Oldest delivery log: {age} days old")
    if age > 95:
        print("WARNING: Cleanup task may not be running")
```

---

## Monthly Maintenance Tasks

**Time Required**: 1-2 hours
**When**: First Monday of each month

### 1. Database Cleanup

```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta

cutoff = timezone.now() - timedelta(days=90)
deleted_count, _ = NotificationDeliveryLog.objects.filter(
    created_at__lt=cutoff,
    status='delivered'
).delete()
print(f"Deleted {deleted_count} old delivery logs")
```

### 2. Test Backup Recovery (Staging)

```bash
# Verify automated backups
aws rds describe-db-snapshots \
    --db-instance-identifier rs-systems-production-db \
    --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime]' \
    --output table
```

### 3. Verify EB Cron Configuration

```bash
eb ssh
cat /etc/cron.d/billing_tasks
```

Expected entries:
- `0 6 * * * process_batch_invoices`
- `0 8 * * * process_overdue_invoices`
- `0 9 * * * generate_aging_report`

---

## Incident Response Procedures

### Incident Classification

| Level | Definition | Response Time |
|-------|-----------|---------------|
| P1 Critical | App down, emails failing >50%, data loss | Immediate (15 min) |
| P2 High | Email failure 10-50%, performance degradation | 1 hour |
| P3 Medium | <10% failures, minor issues | 4 hours |
| P4 Low | Optimization, enhancement | 1 week |

### Response Steps

1. **Acknowledge** — Post in #incidents, note start time
2. **Assess** — Check `/health/`, CloudWatch, EB logs
3. **Stabilize** — Restart EB environment if needed (`eb restart`)
4. **Communicate** — Update stakeholders every 30 min for P1/P2
5. **Resolve** — Fix root cause, verify fix
6. **Document** — Post-mortem for P1/P2

### Post-Mortem Template

```markdown
# Incident: [Brief Description]
**Date**: YYYY-MM-DD | **Duration**: X hr Y min | **Severity**: P1/P2

## Summary
## Timeline
## Root Cause
## Impact
## Resolution
## Action Items
- [ ] Ticket: preventative measure (owner: @person)
```

---

## Health Check Dashboard

**Endpoint**: `https://rssystems.io/health/`

**Expected Response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-03-12T10:00:00Z",
  "components": {
    "database": "healthy"
  }
}
```

**Alternative**: `eb health` from CLI

---

## Performance Baselines

*Updated March 2026*

| Metric | Baseline | Warning | Critical |
|--------|----------|---------|----------|
| Email Delivery Rate | 97% | <95% | <90% |
| Average Send Latency | <3s (inline) | >10s | >30s |
| Daily Notifications | 50-200 | N/A | N/A |
| Database Connections | 15 | >40 | >50 |

---

## Troubleshooting Runbook

### 1. Emails Not Sending

**Symptoms**: `email_sent=False` on notifications, delivery logs show `failed`.

**Investigation**:
```bash
# Test SendGrid connectivity
python manage.py test_ses admin@rssystems.io

# Check delivery logs
python manage.py shell -c "
from core.models import NotificationDeliveryLog
for log in NotificationDeliveryLog.objects.filter(status__in=['failed','failed_permanent']).order_by('-created_at')[:10]:
    print(f'Error: {log.error_message}')
"
```

**Resolution**: Check `SENDGRID_API_KEY` env var in EB (`eb printenv | grep SENDGRID`). Update with `eb setenv SENDGRID_API_KEY=SG....`

### 2. EB Cron Not Running

**Symptoms**: Batch invoices not generating, overdue invoices not updating.

```bash
eb ssh
sudo crontab -l
cat /etc/cron.d/billing_tasks
sudo tail -100 /var/log/cron
```

**Resolution**: Redeploy — EB cron is set via `.ebextensions/11_billing_cron.config`. Check that file exists and `eb deploy` was run.

### 3. Notifications Not Triggering

**Symptoms**: Repairs complete but no notifications created.

```bash
python manage.py shell -c "
from core.models import Notification
from django.utils import timezone
from datetime import timedelta
recent = Notification.objects.filter(created_at__gte=timezone.now()-timedelta(hours=2))
print(f'Notifications in last 2h: {recent.count()}')
"
```

**Resolution**: Check signal handlers in `core/signals.py`. Verify `core` app is in `INSTALLED_APPS` with correct `AppConfig`. Run `python manage.py check`.

### 4. Failed Deliveries

```bash
python manage.py shell -c "
from core.models import NotificationDeliveryLog
from django.db.models import Count
errors = NotificationDeliveryLog.objects.filter(status__in=['failed','failed_permanent']).values('error_message').annotate(count=Count('id')).order_by('-count')[:10]
for e in errors:
    print(f'{e[\"count\"]:4d}  {e[\"error_message\"][:80]}')
"
```

---

## Related Documentation

- [Deployment Guide](../deployment/AWS_DEPLOYMENT.md)
- [Notification System Docs](../development/notifications/README.md)
- [Billing Roadmap](../../BILLING_ROADMAP.md)

---

**Document Version**: 2.0
**Last Updated**: March 2026
**Maintained By**: DevOps Team + Backend Team
