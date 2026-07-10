# Admin Dashboard Enhancement Guide

**Status:** Complete
**Last Updated:** November 30, 2025
**Phase:** 6 - Production Readiness

---

## Overview

The Django admin interface for the notification system has been enhanced with professional statistics dashboards, bulk actions, and operational tools to support efficient notification management in production.

---

## Features Implemented

### 1. Notification Admin Dashboard

**Location:** `/admin/core/notification/`

#### Statistics Dashboard

Professional gradient cards displaying real-time notification metrics:

- **Total Notifications** - All-time notification count (purple gradient)
- **Unread** - Notifications awaiting action (pink/red gradient)
- **Urgent** - High-priority notifications (pink/yellow gradient)
- **Email Sent** - Email delivery count (blue gradient)
- **SMS Sent** - SMS delivery count (green/teal gradient)

#### Quick Actions

Fast-access buttons for common tasks:
-  Create Notification
-  View Unread (filters to unread notifications)
-  View Urgent (filters to urgent priority)
-  View Delivery Logs (navigates to delivery log admin)

#### Performance Insights

Automatic calculation of key metrics:
- **Email Delivery Rate** - % of notifications delivered via email
- **SMS Delivery Rate** - % of notifications delivered via SMS
- **Unread Rate** - % of unread notifications
- **Urgent Priority** - % of urgent-priority notifications

### 2. Enhanced List Display

**Notification Admin** (`core/admin.py:20-150`)

**Columns:**
- ID
- Title (truncated to 50 chars)
- Recipient (with ContentType model name)
- Priority Badge (color-coded: URGENT=red, HIGH=orange, MEDIUM=blue, LOW=gray)
- Category
- Delivery Status ( email,  SMS,  read)
- Created At
- Read Status

**Filters:**
- Priority level
- Category type
- Read/unread status
- Email sent status
- SMS sent status
- Creation date

**Search Fields:**
- Title
- Message content
- Recipient ID

### 3. Bulk Actions

#### Mark as Read
**Action:** `mark_as_read`
**Description:** Marks selected notifications as read with timestamp
**Implementation:** Calls `notification.mark_as_read()` method for each selected notification

#### Mark as Unread
**Action:** `mark_as_unread`
**Description:** Resets read status and clears read timestamp
**Implementation:** Updates `read=False` and `read_at=None`

#### Retry Delivery
**Action:** `retry_delivery`
**Description:** Re-attempts synchronous delivery for failed notifications
**Logic:**
- Only retries notifications that failed email or SMS delivery
- Checks `should_send_email()` and `should_send_sms()` methods
- Calls delivery functions directly (synchronous — no task queue)
- Shows success message with count of retried notifications

---

## NotificationDeliveryLog Admin

**Location:** `/admin/core/notificationdeliverylog/`

### Enhanced Features

#### List Display Columns
- ID
- Notification ID (link to parent notification)
- Channel (email/sms)
- Status Badge (color-coded: sent=green, failed=red, pending=orange, bounced=red, opted_out=gray, skipped=blue)
- Recipient (email or phone)
- Attempt Number
- **Cost Display** (NEW - shows cost with 4 decimal places, e.g., $0.0075)
- Created At

#### Bulk Action: Retry Failed Deliveries

**Action:** `retry_failed_deliveries`
**Description:** Re-attempts synchronous delivery for failed delivery logs
**Logic:**
- Filters to only failed deliveries with attempt_number < 3
- Calls delivery functions directly based on channel (email or sms)
- Prevents retry loops by checking attempt limit

---

## Custom Template Implementation

**File:** `templates/admin/core/notification/change_list.html`

### Template Structure

```django
{% extends "admin/change_list.html" %}

{% block content_title %}
    <!-- Statistics Dashboard Cards -->
    <div style="display: flex; gap: 20px; margin: 20px 0; flex-wrap: wrap;">
        <!-- 5 gradient cards with metrics -->
    </div>

    <!-- Quick Actions Section -->
    <div style="background: #f8f9fa; ...">
        <!-- 4 action buttons with links -->
    </div>

    <!-- Performance Insights -->
    {% if stats.total > 0 %}
    <div style="background: #e7f3ff; ...">
        <!-- 4 calculated metrics using widthratio -->
    </div>
    {% endif %}
{% endblock %}
```

### Statistics Calculation

Stats are aggregated in `changelist_view()`:

```python
def changelist_view(self, request, extra_context=None):
    extra_context = extra_context or {}

    stats = Notification.objects.aggregate(
        total=Count('id'),
        unread=Count('id', filter=Q(read=False)),
        urgent=Count('id', filter=Q(priority='URGENT')),
        email_sent=Count('id', filter=Q(email_sent=True)),
        sms_sent=Count('id', filter=Q(sms_sent=True)),
    )

    extra_context['stats'] = stats
    return super().changelist_view(request, extra_context)
```

---

## Notification Model Helper Methods

**File:** `core/models/notification.py`

### should_send_email()

**Purpose:** Determine if notification should be sent via email based on priority
**Returns:** Boolean
**Logic:** Checks if 'email' is in `get_delivery_channels()`

```python
def should_send_email(self):
    """Check if this notification should be sent via email based on priority"""
    return 'email' in self.get_delivery_channels()
```

**Used by:** Admin retry_delivery action to validate email re-queueing

### should_send_sms()

**Purpose:** Determine if notification should be sent via SMS based on priority
**Returns:** Boolean
**Logic:** Checks if 'sms' is in `get_delivery_channels()`

```python
def should_send_sms(self):
    """Check if this notification should be sent via SMS based on priority"""
    return 'sms' in self.get_delivery_channels()
```

**Used by:** Admin retry_delivery action to validate SMS re-queueing

---

## Usage Guide

### Accessing the Admin Dashboard

1. Navigate to `/admin/` and log in with superuser credentials
2. Click "Notifications" under the "CORE" section
3. View the statistics dashboard at the top of the page

### Retrying Failed Notifications

**Scenario:** Email delivery failed for urgent notifications due to SES rate limiting

**Steps:**
1. Navigate to Notifications admin
2. Use filters to show notifications with `email_sent = False`
3. Select the failed notifications (checkbox on left)
4. Choose "Retry delivery for selected notifications" from Actions dropdown
5. Click "Go"
6. Verify success message in admin

**Expected Output:**
```
Retried 15 notification delivery/deliveries.
```

### Retrying Failed Delivery Logs

**Scenario:** SMS delivery failed with rate limit error, need to retry

**Steps:**
1. Navigate to Notification delivery logs admin (`/admin/core/notificationdeliverylog/`)
2. Filter by `status = failed` and `channel = sms`
3. Select the failed logs
4. Choose "Retry failed deliveries" from Actions dropdown
5. Click "Go"
6. Monitor CloudWatch for SMS delivery success

### Viewing Performance Metrics

**Quick Checks:**
- **Email delivery rate low?** Check SES credentials and sandbox status
- **High unread rate?** Users may be missing notifications - check in-app UI
- **Urgent priority spike?** Investigate if threshold logic is correct

---

## File Modifications Summary

### Files Modified

1. **`core/admin.py`**
   - Added `retry_delivery` action to NotificationAdmin (lines 107-136)
   - Added `cost_display` method to DeliveryLogAdmin (lines 266-271)
   - Enhanced `retry_failed_deliveries` with synchronous retry logic (lines 273-303)

2. **`core/models/notification.py`**
   - Added `should_send_email()` method (lines 187-189)
   - Added `should_send_sms()` method (lines 191-193)

### Files Created

3. **`templates/admin/core/notification/change_list.html`** (NEW)
   - Professional statistics dashboard with gradient cards
   - Quick actions section with 4 common operations
   - Performance insights with calculated delivery rates

---

## Testing the Enhancements

### Manual Testing

**Test 1: Statistics Display**
```bash
# Create test notifications
python manage.py shell

from core.services.notification_service import NotificationService
from apps.technician_portal.models import Technician

tech = Technician.objects.first()

# Create 5 notifications with different priorities
for i in range(5):
    NotificationService.create_notification(
        recipient=tech,
        template_name='repair_assigned',
        context={'repair_id': f'TEST-{i}', 'unit_number': '1234'}
    )
```

Then navigate to `/admin/core/notification/` and verify:
-  Total Notifications shows 5
-  Unread shows 5
-  Cards display correctly with gradients

**Test 2: Retry Delivery Action**
```python
# Mark some notifications as failed
from core.models import Notification

Notification.objects.filter(id__in=[1, 2, 3]).update(email_sent=False)
```

Then in admin:
1. Select the 3 notifications
2. Run "Retry delivery" action
3. Verify success message: `Retried X notification delivery/deliveries.`

**Test 3: Cost Display**
```python
from core.models import NotificationDeliveryLog

# Create delivery log with cost
log = NotificationDeliveryLog.objects.filter(channel='sms').first()
log.cost = 0.0075
log.save()
```

Then navigate to `/admin/core/notificationdeliverylog/` and verify:
-  Cost column shows "$0.0075"

---

## Production Considerations

### Performance

**Query Optimization:**
- Statistics aggregation uses efficient `Count()` with filters
- No N+1 queries in list display
- All foreign keys use `select_related()` (from previous Phase 6 optimization)

**Caching:**
- Statistics are calculated on each page load (acceptable for admin interface)
- For high-volume systems, consider caching stats for 5 minutes

### Security

**Permissions:**
- Only superusers and staff with `core.view_notification` permission can access
- Bulk actions require `core.change_notification` permission
- Retry actions validate notification priority before queueing

**Audit Trail:**
- All bulk actions logged via Django admin action framework
- Celery tasks logged with notification IDs for traceability

### Cost Management

**SMS Retry Limits:**
- Retry action only queues for attempt_number < 3
- Prevents infinite retry loops on failed SMS
- Cost displayed in admin for transparency

---

## Troubleshooting

### Issue: Statistics not showing

**Symptoms:** Dashboard shows "0" for all metrics despite notifications existing

**Investigation:**
```python
python manage.py shell

from core.models import Notification
from django.db.models import Count, Q

# Manually run aggregation
stats = Notification.objects.aggregate(
    total=Count('id'),
    unread=Count('id', filter=Q(read=False)),
)
print(stats)
```

**Resolution:**
- Check that notifications exist in database
- Verify Django version supports `filter` parameter in `Count()` (Django 2.0+)
- Clear browser cache and refresh

### Issue: Retry action not working

**Symptoms:** Click "Retry delivery" but no deliveries succeed

**Investigation:**
```bash
# Check SES SMTP credentials
eb printenv | grep EMAIL_HOST

# Check notification priority
python manage.py shell
>>> from core.models import Notification
>>> n = Notification.objects.get(id=123)
>>> n.should_send_email()  # Should return True/False
```

**Resolution:**
- Verify `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` are set correctly
- Check Django logs for exceptions during delivery
- Verify notification priority allows email delivery

### Issue: Template not rendering

**Symptoms:** Statistics dashboard not showing, seeing default admin changelist

**Investigation:**
```bash
# Check template exists
ls -la templates/admin/core/notification/change_list.html

# Check template path in settings.py
python manage.py shell
>>> from django.conf import settings
>>> print(settings.TEMPLATES[0]['DIRS'])
```

**Resolution:**
- Verify template directory structure: `templates/admin/core/notification/`
- Ensure `TEMPLATES` setting includes project templates directory
- Run `python manage.py collectstatic` if using static files
- Clear Django template cache: `python manage.py shell -c "from django.core.cache import cache; cache.clear()"`

---

## Future Enhancements

### Phase 7+ Ideas

1. **Real-time Dashboard Updates**
   - WebSocket integration for live statistics
   - Auto-refresh every 30 seconds without page reload

2. **Advanced Filtering**
   - Date range picker for created_at
   - Recipient type filter (Technician vs Customer)
   - Template name filter

3. **Export Functionality**
   - CSV export of notification data
   - PDF reports for delivery metrics
   - CloudWatch integration for long-term analytics

4. **Notification Preview**
   - Modal to preview email/SMS content before sending
   - Template variable substitution preview
   - Mobile device preview simulation

5. **Bulk Scheduling**
   - Schedule notifications for future delivery
   - Recurring notification campaigns
   - Quiet hours enforcement

---

## Team Training

### For Administrators

**Key Actions to Know:**
1. Monitoring daily notification volume (check Total card)
2. Investigating failed deliveries (filter by email_sent=False or sms_sent=False)
3. Retrying failed notifications (use bulk action)
4. Checking delivery costs (view delivery logs for SMS costs)

### For Developers

**Code Patterns:**
1. Adding new statistics to dashboard (modify `changelist_view()`)
2. Creating new bulk actions (follow pattern in `retry_delivery()`)
3. Customizing admin templates (extend `change_list.html`)
4. Adding new helper methods to models (see `should_send_email()`)

---

## Conclusion

The admin dashboard enhancements provide production-grade operational tools for managing the notification system at scale. The combination of real-time statistics, bulk actions, and professional UI design enables efficient troubleshooting, monitoring, and manual intervention when needed.

**Key Benefits:**
-  Visual statistics reduce time to understand system state
-  Bulk retry actions minimize manual work during incidents
-  Cost visibility prevents surprise SMS charges
-  Professional design improves team confidence in system

**Production Readiness:**  COMPLETE

The admin dashboard is ready for production use and supports all operational requirements defined in Phase 6.

---

**Document Version:** 1.0
**Last Updated:** November 30, 2025
**Next Review:** After 1 month in production (January 2026)
