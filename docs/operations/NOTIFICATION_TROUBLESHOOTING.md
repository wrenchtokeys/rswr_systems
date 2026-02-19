# Notification System Troubleshooting Runbook

**Purpose**: Quick reference guide for diagnosing and resolving common notification system issues in production.

**Last Updated**: November 30, 2025
**Audience**: DevOps Engineers, On-Call Engineers, Backend Developers

---

## Quick Links

- [Emails Not Sending](#1-emails-not-sending)
- [High SMS Costs](#2-high-sms-costs)
- [Celery Workers Not Processing](#3-celery-workers-not-processing)
- [Notification Queue Backlog](#4-notification-queue-backlog)
- [Failed Deliveries Investigation](#5-failed-deliveries-investigation)
- [Performance Degradation](#6-performance-degradation)

---

## 1. Emails Not Sending

### Symptoms
- Notifications created but emails not received
- `email_sent=False` on Notification objects
- NotificationDeliveryLog shows `status='failed'` or `status='pending_retry'`
- CloudWatch alarm: `RS-Notifications-HighEmailFailureRate`

### Common Causes
1. **AWS SES credentials invalid** - Expired or incorrect SMTP credentials
2. **Email address not verified** - SES sandbox mode requires verification
3. **SES in sandbox mode** - Restricted to verified addresses only
4. **Celery worker not running** - Tasks queued but not processed
5. **Queue backed up** - Too many pending tasks
6. **Rate limiting** - Exceeding SES send rate (14 emails/second)
7. **SMTP authentication failure** - Wrong username/password

### Investigation Steps

**Step 1: Check Celery Worker Status**
```bash
# Check if workers are running
sudo systemctl status celery-worker

# Check active tasks
celery -A rs_systems inspect active

# View worker logs
sudo journalctl -u celery-worker -n 100 --no-pager
```

**Step 2: Check SES Configuration**
```bash
# Verify SES credentials environment variables
echo $AWS_SES_SMTP_USER
echo $AWS_SES_SMTP_PASSWORD

# Test SES directly
python manage.py test_ses admin@rockstarwindshield.repair

# Expected: " Email sent successfully!"
```

**Step 3: Check SES Sandbox Status**
```bash
# Check if SES is in sandbox mode
aws ses get-account-sending-enabled --region us-east-1

# List verified email addresses
aws ses list-verified-email-addresses --region us-east-1

# Check sending statistics
aws ses get-send-statistics --region us-east-1
```

**Step 4: Check Delivery Logs**
```bash
python manage.py shell

from core.models import NotificationDeliveryLog

# Get recent failed emails
failed_emails = NotificationDeliveryLog.objects.filter(
    channel='email',
    status__in=['failed', 'failed_permanent', 'pending_retry']
).order_by('-created_at')[:10]

for log in failed_emails:
    print(f"ID: {log.id}, Error: {log.error_message}")
```

### Resolution Steps

**For SES Sandbox Mode:**
```bash
# Request production access (AWS Console method)
# 1. Go to AWS Console  SES  Account dashboard
# 2. Click "Request production access"
# 3. Fill out form with use case
# 4. Wait for approval (usually 24 hours)
```

**For Invalid Credentials:**
```bash
# 1. Generate new SMTP credentials in SES console
# 2. Update environment variables
# 3. Restart Celery workers
sudo systemctl restart celery-worker
```

**For Celery Worker Issues:**
```bash
# Restart workers
sudo systemctl restart celery-worker
sudo systemctl restart celery-beat

# Check logs for startup
sudo journalctl -u celery-worker -f
```

**For Rate Limiting:**
```bash
# Temporarily reduce rate in settings
# Edit settings_aws.py:
# EMAIL_RATE_LIMIT = 10  # Reduce from 14

# Or add delay in Celery task routing
# CELERY_ANNOTATIONS = {
#     'core.tasks.send_notification_email': {'rate_limit': '10/s'}
# }
```

### Verification
```bash
# Send test notification
python manage.py shell
from core.services.notification_service import NotificationService
from apps.technician_portal.models import Technician

tech = Technician.objects.first()
NotificationService.create_notification(
    recipient=tech,
    template_name='repair_assigned',
    context={'repair_id': 'TEST-001', 'unit_number': '1234'}
)

# Check email received within 30 seconds
# Check Celery logs for delivery confirmation
```

---

## 2. High SMS Costs

### Symptoms
- CloudWatch alarm: `RS-Notifications-HighSMSCost` (>$20/hour)
- Unexpected AWS bill
- High volume of SMS deliveries

### Investigation Steps

**Step 1: Check Current SMS Cost**
```bash
# Query CloudWatch for hourly SMS costs
aws cloudwatch get-metric-statistics \
    --namespace RS_Systems/Notifications \
    --metric-name SMSCost \
    --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Sum \
    --region us-east-1
```

**Step 2: Identify SMS Volume**
```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.utils import timezone
from datetime import timedelta

# Get SMS count for last 24 hours
yesterday = timezone.now() - timedelta(days=1)
sms_count = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=yesterday
).count()

print(f"SMS sent in last 24 hours: {sms_count}")

# Identify top recipients
from django.db.models import Count
top_recipients = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=yesterday
).values('recipient_phone').annotate(
    count=Count('id')
).order_by('-count')[:10]

for recipient in top_recipients:
    print(f"{recipient['recipient_phone']}: {recipient['count']} SMS")
```

**Step 3: Check for Notification Loops**
```bash
# Look for repeated notifications to same recipient
from collections import Counter
recent_sms = NotificationDeliveryLog.objects.filter(
    channel='sms',
    created_at__gte=yesterday
).values_list('notification__title', 'recipient_phone')

# Check for duplicates
notification_counts = Counter(recent_sms)
duplicates = [(k, v) for k, v in notification_counts.items() if v > 5]

print("Potential loops (>5 identical notifications):")
for (title, phone), count in duplicates:
    print(f"  {title} to {phone}: {count} times")
```

### Resolution Steps

**Immediate Action (Cost Control):**
```bash
# Temporarily disable SMS for affected users
python manage.py shell

from core.models import TechnicianNotificationPreference

# Disable SMS for specific technician
tech_id = 123  # Replace with problematic technician ID
pref = TechnicianNotificationPreference.objects.get(technician_id=tech_id)
pref.receive_sms_notifications = False
pref.save()

# Or globally reduce SMS priority threshold (emergency only)
# This requires code change to NotificationService
```

**Root Cause Analysis:**
1. Check signal handlers for notification loops
2. Review notification creation code for unnecessary SMS triggers
3. Check if quiet hours are being respected
4. Verify rate limiting is working

**Long-term Solutions:**
```python
# Add SMS cost monitoring to NotificationService
# core/services/notification_service.py

def create_notification(self, recipient, template_name, context, **kwargs):
    # Before creating SMS, check daily cost limit
    from core.models import NotificationDeliveryLog
    from datetime import timedelta

    today_start = timezone.now().replace(hour=0, minute=0, second=0)
    today_sms_cost = NotificationDeliveryLog.objects.filter(
        channel='sms',
        created_at__gte=today_start,
        status='delivered'
    ).aggregate(total_cost=Sum('cost'))['total_cost'] or 0

    if today_sms_cost > Decimal('100.00'):  # $100 daily limit
        logger.warning(f"Daily SMS cost limit reached: ${today_sms_cost}")
        # Skip SMS, only send email
```

### Verification
```bash
# Monitor SMS cost for next hour
# Set up temporary alarm if not already triggered
```

---

## 3. Celery Workers Not Processing

### Symptoms
- Queue depth increasing
- Notifications created but not delivered
- CloudWatch alarm: `RS-Notifications-CeleryWorkerDown`
- No worker logs

### Investigation Steps

**Step 1: Check Worker Process**
```bash
# Check systemd status
sudo systemctl status celery-worker
sudo systemctl status celery-beat

# Check for worker processes
ps aux | grep celery | grep -v grep

# Expected output:
# user  12345  ... celery -A rs_systems worker ...
```

**Step 2: Check Redis Connection**
```bash
# Test Redis connectivity
redis-cli -h your-elasticache-endpoint ping

# Expected: PONG

# Check Redis memory usage
redis-cli -h your-elasticache-endpoint info memory

# Check if queue exists
redis-cli -h your-elasticache-endpoint llen celery

# If llen > 0, tasks are queued but not processed
```

**Step 3: Review Worker Logs**
```bash
# Check for errors
sudo journalctl -u celery-worker -n 200 | grep ERROR

# Common errors:
# - "Consumer: Cannot connect to redis://..."   Redis connectivity
# - "KeyError: 'exchange'"   Configuration issue
# - "Killed"   Out of memory
# - "ImportError: ..."   Code deployment issue
```

### Resolution Steps

**For Stopped Workers:**
```bash
# Restart Celery services
sudo systemctl restart celery-worker
sudo systemctl restart celery-beat

# Check startup
sudo journalctl -u celery-worker -f

# Should see:
# [INFO] Connected to redis://...
# [INFO] celery@hostname ready.
```

**For Redis Connection Issues:**
```bash
# Check security group allows port 6379
aws ec2 describe-security-groups --group-ids sg-xxxxx

# Check network connectivity
telnet your-elasticache-endpoint 6379

# Verify CELERY_BROKER_URL environment variable
echo $CELERY_BROKER_URL
```

**For Out of Memory:**
```bash
# Check memory usage
free -h

# Restart workers with lower concurrency
# Edit /etc/systemd/system/celery-worker.service
# Change: --concurrency=8  to  --concurrency=4

sudo systemctl daemon-reload
sudo systemctl restart celery-worker
```

**For Code Deployment Issues:**
```bash
# Ensure latest code deployed
cd /path/to/rs_systems
git pull

# Reinstall dependencies
pip install -r requirements.txt

# Restart workers
sudo systemctl restart celery-worker
```

### Verification
```bash
# Send test task
celery -A rs_systems inspect active

# Should show no errors

# Create test notification
python manage.py shell
# (Create notification as in Email troubleshooting)

# Monitor logs
sudo journalctl -u celery-worker -f
# Should show task execution within seconds
```

---

## 4. Notification Queue Backlog

### Symptoms
- CloudWatch alarm: `RS-Notifications-QueueBacklog` (>1,000 pending)
- Slow notification delivery (minutes instead of seconds)
- Increasing response times

### Investigation Steps

**Step 1: Check Queue Depth**
```bash
# Check Celery queue stats
celery -A rs_systems inspect stats

# Check Redis queue depth directly
redis-cli -h your-elasticache-endpoint llen celery

# If > 1000, backlog exists
```

**Step 2: Identify Slow Tasks**
```bash
# Check worker logs for slow tasks
sudo journalctl -u celery-worker | grep "succeeded in"

# Look for tasks taking >10 seconds
# Example: "Task core.tasks.send_notification_email[...] succeeded in 15.234s"
```

**Step 3: Check Worker Capacity**
```bash
# Check number of workers
celery -A rs_systems inspect active_queues

# Check concurrency
celery -A rs_systems inspect stats | grep pool

# Expected: "concurrency": 8
```

### Resolution Steps

**Immediate: Add More Workers**
```bash
# Option 1: Increase concurrency
# Edit /etc/systemd/system/celery-worker.service
# Change: --concurrency=8  to  --concurrency=16

sudo systemctl daemon-reload
sudo systemctl restart celery-worker

# Option 2: Add more worker instances (if using multiple EC2)
# Deploy to additional EC2 instances
```

**Medium-term: Optimize Task Performance**
```python
# Add database query optimizations (already done in Phase 6)
# Add caching (already done in Phase 6)

# Review slow tasks:
# 1. Check for N+1 queries
# 2. Add select_related/prefetch_related
# 3. Cache frequently accessed data
```

**Long-term: Scale Infrastructure**
```bash
# Use Auto Scaling Group for Celery workers
# Set up based on queue depth metric
# Scale out when queue > 500, scale in when < 100
```

### Purge Old Tasks (Emergency Only)**
```bash
#  WARNING: Only use if backlog is from old/stale tasks
# This will delete ALL pending tasks!

celery -A rs_systems purge

# Confirm when prompted

# Verify queue cleared
redis-cli -h your-elasticache-endpoint llen celery
# Should return: 0
```

---

## 5. Failed Deliveries Investigation

### Symptoms
- CloudWatch alarm: `RS-Notifications-HighErrorRate` (>10%)
- Multiple notifications with `status='failed_permanent'`

### Investigation Query
```bash
python manage.py shell

from core.models import NotificationDeliveryLog
from django.db.models import Count

# Group failures by error type
error_summary = NotificationDeliveryLog.objects.filter(
    status__in=['failed', 'failed_permanent']
).values('error_message').annotate(
    count=Count('id')
).order_by('-count')

print("Top Error Messages:")
for error in error_summary[:10]:
    print(f"{error['count']:4d}  {error['error_message'][:80]}")
```

### Common Error Patterns

**"SMTPAuthenticationError"**
- **Cause**: SES credentials invalid
- **Fix**: Regenerate SMTP credentials, update environment variables

**"Invalid email address"**
- **Cause**: Recipient email not valid format
- **Fix**: Add email validation in forms

**"Address not verified" (SES sandbox)**
- **Cause**: SES in sandbox mode, recipient not verified
- **Fix**: Request production access or verify recipient

**"Throttling" / "Rate exceeded"**
- **Cause**: Exceeding SES/SNS rate limits
- **Fix**: Reduce CELERY_ANNOTATIONS rate_limit

**"InvalidParameter: Phone number"**
- **Cause**: Phone not in E.164 format (+15551234567)
- **Fix**: Validate phone numbers at input

---

## 6. Performance Degradation

### Symptoms
- CloudWatch alarm: `RS-Notifications-HighLatency` (>30s average)
- Slow page loads on notification history
- High database CPU usage

### Investigation Steps

**Step 1: Check Database Query Performance**
```bash
# Enable query logging
python manage.py shell

from django.conf import settings
from django.db import connection
from django.test.utils import override_settings

# Run problematic view
# Then check query count
print(f"Queries executed: {len(connection.queries)}")

# Look for N+1 queries
for query in connection.queries:
    print(f"{query['time']}: {query['sql'][:100]}")
```

**Step 2: Check Cache Hit Rate**
```bash
redis-cli -h your-elasticache-endpoint info stats | grep hits

# Expected: keyspace_hits >> keyspace_misses
```

**Step 3: Check CloudWatch Latency Metrics**
```bash
aws cloudwatch get-metric-statistics \
    --namespace RS_Systems/Notifications \
    --metric-name DeliveryLatency \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Average,Maximum \
    --region us-east-1
```

### Resolution Steps

**Database Optimization:**
```bash
# Already implemented in Phase 6:
# - select_related() for notification queries
# - Database indexes on (recipient_type, recipient_id, read, -created_at)

# Verify indexes exist
python manage.py shell
from django.db import connection
cursor = connection.cursor()
cursor.execute("""
    SELECT indexname, indexdef
    FROM pg_indexes
    WHERE tablename = 'core_notification'
""")
for row in cursor.fetchall():
    print(row)
```

**Caching Optimization:**
```bash
# Already implemented in Phase 6:
# - Unread count caching (2 min TTL)
# - Automatic cache invalidation via signals

# Increase cache timeout if stale data acceptable
# Edit views.py: cache.set(cache_key, data, timeout=300)  # 5 min
```

---

## Escalation Procedures

### Severity Levels

**P1 (Critical)** - Immediate Response Required
- All emails/SMS failing (>50% failure rate)
- Celery workers down for >10 minutes
- Data loss or corruption
- SMS costs >$100/hour

**Action**: Page on-call engineer immediately, engage backend team

**P2 (High)** - Respond Within 1 Hour
- Email failure rate 10-50%
- Queue backlog >5,000
- Performance degradation (>60s latency)

**Action**: Notify team via Slack, investigate within 1 hour

**P3 (Medium)** - Respond Within 4 Hours
- Minor delivery failures (<10%)
- Queue backlog 1,000-5,000
- Cache misses high

**Action**: Create ticket, investigate during business hours

**P4 (Low)** - Respond Within 1 Week
- Optimization opportunities
- Documentation updates
- Feature requests

**Action**: Add to backlog

---

## Emergency Contacts

| Role | Primary | Secondary | PagerDuty |
|------|---------|-----------|-----------|
| **On-Call Engineer** | Team rotation | Backup rotation | #notifications-oncall |
| **Backend Lead** | Backend Team | DevOps Lead | N/A |
| **DevOps Lead** | DevOps Team | CTO | #devops-oncall |

**Slack Channels**:
- `#notifications-team` - General discussion
- `#incidents` - Active incidents
- `#alerts` - CloudWatch alarms

---

## Related Documentation

- [Deployment Guide](../deployment/NOTIFICATION_DEPLOYMENT.md)
- [CloudWatch Setup](../deployment/CLOUDWATCH_SETUP.md)
- [Operations Guide](./NOTIFICATION_OPERATIONS.md)
- [Phase 6 Production Readiness](../development/notifications/PHASE_6_PRODUCTION_READINESS.md)

---

**Document Version**: 1.0
**Last Updated**: November 30, 2025
**Maintained By**: DevOps Team
