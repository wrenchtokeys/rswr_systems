# Notification System Operations Guide

**Purpose**: Daily, weekly, and monthly operational procedures for the RS Systems notification system.

**Last Updated**: November 30, 2025
**Audience**: DevOps Team, Backend Engineers, On-Call Engineers

---

## Table of Contents

1. [Daily Monitoring Tasks](#daily-monitoring-tasks)
2. [Weekly Review Procedures](#weekly-review-procedures)
3. [Monthly Maintenance Tasks](#monthly-maintenance-tasks)
4. [Incident Response Procedures](#incident-response-procedures)
5. [Maintenance Windows](#maintenance-windows)
6. [Health Check Dashboard](#health-check-dashboard)
7. [Performance Baselines](#performance-baselines)

---

## Daily Monitoring Tasks

**Time Required**: 15-20 minutes
**When**: First thing in the morning (9:00 AM)
**Owner**: On-call engineer or designated team member

### 1. Check CloudWatch Dashboard

**Dashboard URL**: https://console.aws.amazon.com/cloudwatch/

**Metrics to Review**:

```bash
# Quick check via CLI (optional)
aws cloudwatch get-metric-statistics \
    --namespace RS_Systems/Notifications \
    --metric-name NotificationCreated \
    --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Sum \
    --region us-east-1
```

**Key Indicators**:
-  **NotificationCreated**: Should show steady daily volume (baseline: 50-200/day)
-  **NotificationDelivered**: Should be 95% of created notifications
-  **NotificationFailed**: Should be <5% of created notifications
-  **DeliveryLatency**: Average should be <5 seconds
-  **SMSCost**: Daily total should be <$50
-  **QueueDepth**: Should be <100 pending tasks

**Red Flags**:
-  NotificationFailed spike (>10% of total)
-  SMSCost >$50 in 24 hours
-  QueueDepth >500 for >10 minutes
-  DeliveryLatency >30 seconds average

### 2. Review CloudWatch Alarms

**Check Alarm Status**:
```bash
aws cloudwatch describe-alarms \
    --alarm-name-prefix RS-Notifications- \
    --state-value ALARM \
    --region us-east-1
```

**Expected**: All alarms in `OK` state

**If ALARM State**:
1. Click alarm name to see details
2. Review graph to understand trigger
3. Follow [Troubleshooting Runbook](./NOTIFICATION_TROUBLESHOOTING.md)
4. Document incident (see [Incident Response](#incident-response-procedures))

### 3. Check Sentry for Errors

**Dashboard URL**: https://sentry.io/organizations/your-org/issues/

**Review**:
-  **New Issues**: Should be 0-2 new issues per day
-  **Event Volume**: Check for unusual spikes
-  **Performance**: Review slow transactions (>5s)

**Action Items**:
- Triage new issues (assign severity P1-P4)
- Resolve or snooze known issues
- Create tickets for recurring issues

### 4. Verify Celery Workers Healthy

**Check Worker Status**:
```bash
# SSH to production server
ssh ec2-user@your-production-server

# Check systemd services
sudo systemctl status celery-worker
sudo systemctl status celery-beat

# Check active tasks
celery -A rs_systems inspect active

# Check worker stats
celery -A rs_systems inspect stats
```

**Expected Output**:
```
celery-worker.service - Celery Worker for RS Systems
   Active: active (running) since [timestamp]

celery@hostname:
  - pool: prefork
  - concurrency: 8
  - autoscaler: off
```

**Red Flags**:
-  Service status: `inactive (dead)`
-  No worker processes running
-  Worker restarted recently (<1 hour ago)

### 5. Check Delivery Success Rates

**Query Database**:
```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta

yesterday = timezone.now() - timedelta(days=1)

# Email success rate
email_total = NotificationDeliveryLog.objects.filter(
    channel='email',
    created_at__gte=yesterday
).count()

email_delivered = NotificationDeliveryLog.objects.filter(
    channel='email',
    created_at__gte=yesterday,
    status='delivered'
).count()

email_rate = (email_delivered / email_total * 100) if email_total > 0 else 0
print(f"Email Delivery Rate (24h): {email_rate:.1f}%")

# SMS success rate
sms_total = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=yesterday
).count()

sms_delivered = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=yesterday,
    status='delivered'
).count()

sms_rate = (sms_delivered / sms_total * 100) if sms_total > 0 else 0
print(f"SMS Delivery Rate (24h): {sms_rate:.1f}%")
```

**Target Rates**:
-  Email: 95%
-  SMS: 98%

**If Below Target**:
- Review failed delivery logs
- Check for common error patterns
- Follow troubleshooting runbook

### 6. Quick Log Review

**Check for Errors**:
```bash
# Check Celery worker logs
sudo journalctl -u celery-worker --since "1 hour ago" | grep ERROR

# Check Django application logs
sudo journalctl -u gunicorn --since "1 hour ago" | grep ERROR

# Check for repeated errors
sudo journalctl -u celery-worker --since "24 hours ago" | grep ERROR | sort | uniq -c | sort -rn | head -10
```

**No errors**:  Proceed
**Errors found**: Investigate and create tickets as needed

---

## Weekly Review Procedures

**Time Required**: 45-60 minutes
**When**: Monday morning (10:00 AM)
**Owner**: Backend team lead or DevOps lead

### 1. Analyze SMS Cost Trends

**Weekly Cost Report**:
```bash
# Get SMS costs for past 7 days
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import pandas as pd

week_ago = timezone.now() - timedelta(days=7)

# Daily SMS costs
daily_costs = []
for i in range(7):
    day_start = week_ago + timedelta(days=i)
    day_end = day_start + timedelta(days=1)

    cost = NotificationDeliveryLog.objects.filter(
        channel='sms',
        created_at__gte=day_start,
        created_at__lt=day_end,
        status='delivered'
    ).aggregate(total=Sum('cost'))['total'] or Decimal('0')

    daily_costs.append({
        'date': day_start.date(),
        'cost': float(cost),
        'count': NotificationDeliveryLog.objects.filter(
            channel='sms',
            created_at__gte=day_start,
            created_at__lt=day_end
        ).count()
    })

for day in daily_costs:
    print(f"{day['date']}: ${day['cost']:.2f} ({day['count']} SMS)")

weekly_total = sum(d['cost'] for d in daily_costs)
print(f"\nWeekly Total: ${weekly_total:.2f}")
print(f"Monthly Projection: ${weekly_total * 4.3:.2f}")
```

**Action Items**:
-  Document weekly cost
-  Compare to previous week (trend analysis)
-  Flag if monthly projection >$1,500
-  Identify cost optimization opportunities

### 2. Review Notification Volume Patterns

**Volume Analysis**:
```bash
python manage.py shell

from core.models import Notification
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

week_ago = timezone.now() - timedelta(days=7)

# Notifications by category
category_breakdown = Notification.objects.filter(
    created_at__gte=week_ago
).values('category').annotate(
    count=Count('id')
).order_by('-count')

print("Weekly Notifications by Category:")
for cat in category_breakdown:
    print(f"  {cat['category']}: {cat['count']}")

# Notifications by priority
priority_breakdown = Notification.objects.filter(
    created_at__gte=week_ago
).values('priority').annotate(
    count=Count('id')
).order_by('-count')

print("\nWeekly Notifications by Priority:")
for pri in priority_breakdown:
    print(f"  {pri['priority']}: {pri['count']}")
```

**Questions to Ask**:
- Are volume patterns expected?
- Any unexpected spikes in certain categories?
- Is URGENT priority being overused? (should be <10% of total)
- Any notification loops detected?

### 3. Failed Delivery Analysis

**Review Top Failure Reasons**:
```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

week_ago = timezone.now() - timedelta(days=7)

# Top error messages
error_summary = NotificationDeliveryLog.objects.filter(
    created_at__gte=week_ago,
    status__in=['failed', 'failed_permanent']
).values('error_message').annotate(
    count=Count('id')
).order_by('-count')[:10]

print("Top Failure Reasons (Past Week):")
for i, error in enumerate(error_summary, 1):
    print(f"{i}. {error['count']:3d}  {error['error_message'][:70]}")
```

**Action Items**:
- Document recurring errors
- Create tickets for fixable issues
- Update validation logic if needed
- Improve error messages for users

### 4. Performance Review

**Check Average Delivery Times**:
```bash
# Query CloudWatch for weekly latency stats
aws cloudwatch get-metric-statistics \
    --namespace RS_Systems/Notifications \
    --metric-name DeliveryLatency \
    --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 86400 \
    --statistics Average,Maximum,Minimum \
    --region us-east-1
```

**Targets**:
- Average: <5 seconds
- P95: <10 seconds
- Maximum: <30 seconds

**If Degraded**: Investigate database query performance, caching, worker capacity

### 5. Review and Close Sentry Issues

**Sentry Triage**:
1. Review all open issues in Sentry
2. Categorize by severity:
   - **Critical**: Affecting >10% of users  Fix immediately
   - **High**: Affecting <10% users  Fix this sprint
   - **Medium**: Edge cases  Schedule for next sprint
   - **Low**: Enhancement/optimization  Backlog
3. Resolve or snooze issues
4. Update documentation for known issues

**Goal**: <5 open high-priority issues

---

## Monthly Maintenance Tasks

**Time Required**: 2-3 hours
**When**: First Monday of each month
**Owner**: Backend team + DevOps team

### 1. Performance Optimization Review

**Database Performance**:
```bash
# Check slow queries (if slow query log enabled)
# Or use Django Debug Toolbar in staging

python manage.py shell

from django.db import connection
from django.test.utils import override_settings

# Test notification history view performance
# Count queries (should be <10 after Phase 6 optimizations)
with override_settings(DEBUG=True):
    # Simulate view logic
    from apps.technician_portal.views import notification_history
    # ... test query count

print(f"Total queries: {len(connection.queries)}")
```

**Action Items**:
- Review slow query log
- Add missing indexes if identified
- Optimize views with high query counts
- Test caching effectiveness

### 2. Cost Analysis and Forecasting

**Monthly Cost Report**:
```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

month_ago = timezone.now() - timedelta(days=30)

# Email costs (essentially free with SES)
email_count = NotificationDeliveryLog.objects.filter(
    channel='email',
    created_at__gte=month_ago,
    status='delivered'
).count()

# SMS costs
sms_cost = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=month_ago,
    status='delivered'
).aggregate(total=Sum('cost'))['total'] or Decimal('0')

sms_count = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=month_ago
).count()

print(f"30-Day Summary:")
print(f"  Emails Sent: {email_count}")
print(f"  SMS Sent: {sms_count}")
print(f"  SMS Cost: ${float(sms_cost):.2f}")
print(f"  Average Cost/SMS: ${float(sms_cost/sms_count):.4f}" if sms_count > 0 else "  Average: N/A")

# Project next month
print(f"\nNext Month Projection:")
print(f"  Estimated SMS Cost: ${float(sms_cost):.2f}")
```

**Budget Review**:
- Target: <$1,500/month for SMS
- If over budget: Review SMS usage, consider email-only for LOW priority

### 3. Review and Update CloudWatch Alarms

**Alarm Tuning**:
```bash
# List current alarm thresholds
aws cloudwatch describe-alarms \
    --alarm-name-prefix RS-Notifications- \
    --region us-east-1 \
    --query 'MetricAlarms[*].[AlarmName,Threshold]' \
    --output table
```

**Questions**:
- Are alarm thresholds still appropriate based on actual metrics?
- Too many false positives? (increase threshold)
- Missing real issues? (decrease threshold)
- Need new alarms for emerging patterns?

**Action**: Update thresholds as needed using CloudWatch console or script

### 4. Test Disaster Recovery Procedures

**Backup Validation**:
```bash
# Verify automated backups are working
aws rds describe-db-snapshots \
    --db-instance-identifier your-rds-instance \
    --query 'DBSnapshots[*].[DBSnapshotIdentifier,SnapshotCreateTime]' \
    --output table

# Should show recent automated backups
```

**Recovery Test** (in staging):
1. Create manual backup
2. Simulate notification system failure
3. Restore from backup
4. Verify functionality
5. Document recovery time

**Goal**: Recovery Time Objective (RTO) <2 hours

### 5. Database Cleanup and Maintenance

**Clean Old Delivery Logs**:
```bash
# Automated cleanup task should run weekly
# Verify it's working:
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta

# Check oldest delivery log
oldest = NotificationDeliveryLog.objects.order_by('created_at').first()
print(f"Oldest delivery log: {oldest.created_at}")

# Should not be >90 days old (cleanup task deletes older logs)
age_days = (timezone.now() - oldest.created_at).days
print(f"Age: {age_days} days")

if age_days > 95:
    print(" WARNING: Cleanup task may not be running!")
```

**Manual Cleanup** (if needed):
```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta

cutoff = timezone.now() - timedelta(days=90)

# Delete old successful deliveries only (keep failures for analysis)
deleted_count, _ = NotificationDeliveryLog.objects.filter(
    created_at__lt=cutoff,
    status='delivered'
).delete()

print(f"Deleted {deleted_count} old delivery logs")
```

### 6. Documentation Updates

**Review and Update**:
-  This operations guide (add new procedures learned)
-  Troubleshooting runbook (add new error patterns)
-  Deployment guide (incorporate lessons learned)
-  Performance baselines (update with current metrics)

---

## Incident Response Procedures

### Incident Classification

**P1 (Critical) - Page Immediately**
- **Definition**: System down or severely degraded affecting >50% of users
- **Examples**:
  - All emails failing (>50% failure rate)
  - Celery workers completely down for >10 minutes
  - Data loss or corruption
  - SMS costs >$100/hour (runaway costs)
- **Response Time**: Immediate (15 minutes)
- **Escalation**: Page on-call engineer + backend lead
- **Communication**: Post in #incidents channel immediately

**P2 (High) - Alert Team**
- **Definition**: Significant degradation affecting <50% of users
- **Examples**:
  - Email failure rate 10-50%
  - Queue backlog >5,000 for >30 minutes
  - Performance degradation (>60s latency)
  - SMS costs >$50/hour
- **Response Time**: 1 hour
- **Escalation**: Notify team in #notifications-team
- **Communication**: Status update every 30 minutes

**P3 (Medium) - Create Ticket**
- **Definition**: Minor issues with workarounds available
- **Examples**:
  - Minor delivery failures (<10%)
  - Queue backlog 1,000-5,000
  - Cache hit rate low
  - Single component degraded
- **Response Time**: 4 hours (during business hours)
- **Escalation**: Create ticket, assign to team
- **Communication**: Update ticket progress

**P4 (Low) - Backlog**
- **Definition**: Non-urgent improvements or enhancements
- **Examples**:
  - Optimization opportunities
  - Documentation gaps
  - Feature requests
  - Code refactoring
- **Response Time**: 1 week or next sprint
- **Escalation**: Add to backlog
- **Communication**: Discuss in weekly planning

### Incident Response Steps

**1. Acknowledge Incident**
- Acknowledge alert in PagerDuty/CloudWatch
- Post in #incidents Slack channel
- Note incident start time

**2. Initial Assessment**
- Determine severity (P1-P4)
- Identify affected components
- Check CloudWatch metrics for scope
- Review recent deployments/changes

**3. Stabilize System**
- Follow troubleshooting runbook for specific issue
- Implement quick fixes (restart workers, clear queues, etc.)
- Consider rollback if recent deployment caused issue

**4. Communicate Status**
- Update #incidents channel with findings
- Notify affected users if customer-facing impact
- Provide ETA for resolution

**5. Resolve Root Cause**
- Fix underlying issue
- Verify fix in staging (if possible)
- Deploy fix to production
- Monitor for 30 minutes post-fix

**6. Document and Follow Up**
- Document incident in incident log
- Create post-mortem (for P1/P2)
- Create tickets for preventative measures
- Update runbooks with lessons learned

### Post-Mortem Template (P1/P2 Incidents)

```markdown
# Incident Post-Mortem: [Brief Description]

**Date**: YYYY-MM-DD
**Duration**: X hours Y minutes
**Severity**: P1/P2
**Responders**: [Names]

## Summary
Brief description of what happened

## Timeline
- HH:MM - Event started (alert triggered)
- HH:MM - Team notified
- HH:MM - Root cause identified
- HH:MM - Fix deployed
- HH:MM - Incident resolved

## Root Cause
Detailed explanation of what caused the incident

## Impact
- Users affected: X
- Notifications failed: Y
- Revenue impact: $Z (if applicable)

## Resolution
What was done to fix the issue

## Action Items
- [ ] Ticket #123: Prevent similar issues (owner: @person)
- [ ] Update monitoring/alerts
- [ ] Update documentation

## Lessons Learned
What we learned and how we can improve
```

---

## Maintenance Windows

### Scheduled Maintenance

**When**: Second Sunday of each month, 2:00 AM - 6:00 AM EST
**Duration**: 4 hours max
**Notification**: 1 week advance notice to users

**Typical Activities**:
- Database maintenance (vacuum, reindex)
- Dependency updates (pip packages)
- Infrastructure upgrades (EC2, RDS)
- Major configuration changes

**Procedures**:
1. **Pre-Maintenance** (1 week before):
   - Announce maintenance window
   - Create backup
   - Test changes in staging
   - Prepare rollback plan

2. **During Maintenance**:
   - Put notification system in maintenance mode
   - Apply updates
   - Run smoke tests
   - Monitor logs

3. **Post-Maintenance**:
   - Verify all services healthy
   - Run full test suite
   - Monitor for 24 hours
   - Document changes made

---

## Health Check Dashboard

### Quick Health Check URL

**Endpoint**: `/health/` (if implemented)

**Expected Response**:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-30T10:00:00Z",
  "components": {
    "database": "healthy",
    "redis": "healthy",
    "celery_worker": "healthy",
    "celery_beat": "healthy",
    "ses": "healthy",
    "sns": "healthy"
  }
}
```

**Alternative**: Manual checks via systemctl/celery commands

---

## Performance Baselines

**Updated**: November 30, 2025

### Current Baselines (Production)

| Metric | Baseline | Warning | Critical |
|--------|----------|---------|----------|
| Email Delivery Rate | 97% | <95% | <90% |
| SMS Delivery Rate | 99% | <98% | <95% |
| Average Latency | 3.2s | >10s | >30s |
| Queue Depth | 20-50 | >500 | >1,000 |
| Daily Notifications | 120 | N/A | N/A |
| Daily SMS Cost | $15 | >$30 | >$50 |
| Worker CPU Usage | 25% | >60% | >80% |
| Database Connections | 15 | >40 | >50 |
| Cache Hit Rate | 75% | <50% | <30% |

**Review baselines monthly** and adjust based on growth

---

## Related Documentation

- [Troubleshooting Runbook](./NOTIFICATION_TROUBLESHOOTING.md)
- [Deployment Guide](../deployment/NOTIFICATION_DEPLOYMENT.md)
- [CloudWatch Setup](../deployment/CLOUDWATCH_SETUP.md)
- [Phase 6 Production Readiness](../development/notifications/PHASE_6_PRODUCTION_READINESS.md)

---

**Document Version**: 1.0
**Last Updated**: November 30, 2025
**Next Review**: December 31, 2025
**Maintained By**: DevOps Team + Backend Team
