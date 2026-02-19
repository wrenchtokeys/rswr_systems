#  Notification System - Quick Start

**Phases Completed:** 1-5 (Foundation  User Preferences)
**Status:**  Ready for Testing
**Last Updated:** November 30, 2025

---

##  Quick Start (3 Steps)

### 1. Run Setup Script

This will set up the database, install dependencies, and create test data:

```bash
bash setup_notifications.sh
```

### 2. Start All Services

**Option A: Automatic (using tmux - recommended)**

```bash
bash start_notifications.sh
```

This starts all services in one terminal window with tmux. Use `Ctrl+b` then `0-4` to switch between windows.

**Option B: Manual (4 separate terminals)**

```bash
# Terminal 1
python manage.py runserver

# Terminal 2
celery -A rs_systems worker --loglevel=info

# Terminal 3
celery -A rs_systems beat --loglevel=info

# Terminal 4 (optional)
celery -A rs_systems flower
```

### 3. Test the System

1. **Login:** http://localhost:8000/tech/login/
   - Username: `testtech`
   - Password: `testpass123`

2. **View Dashboard:** http://localhost:8000/tech/
   - Check notification bell icon in header

3. **Manage Preferences:** http://localhost:8000/tech/notifications/preferences/
   - Toggle notification settings
   - Configure quiet hours
   - Verify contact info

4. **Create Test Notification:**
   ```bash
   python manage.py shell
   ```
   ```python
   from apps.technician_portal.models import Repair, Technician
   from core.models import Customer

   tech = Technician.objects.first()
   customer = Customer.objects.first()

   repair = Repair.objects.create(
       technician=tech,
       customer=customer,
       unit_number='TEST-001',
       queue_status='PENDING',
       cost=75.00
   )

   print(f"Created repair #{repair.id}")
   ```

5. **Check Notification Created:**
   - Refresh dashboard
   - Bell icon should show unread count
   - Click bell to see notification
   - Visit notification history

---

##  Documentation

| Document | Description |
|----------|-------------|
| **NOTIFICATION_SYSTEM_SETUP_GUIDE.md** | Complete setup guide with testing steps |
| **PHASE_5_IMPLEMENTATION_COMPLETE.md** | Phase 5 implementation details |
| **PHASE_4_IMPLEMENTATION_COMPLETE.md** | Phase 4 service layer details |
| **PHASE_3_COMPLETE.md** | Phase 3 email templates |
| **PHASE_2_COMPLETE.md** | Phase 2 infrastructure setup |
| **docs/development/notifications/** | All phase specifications |

---

##  What's Included

###  Phase 1: Foundation Models
- Notification model
- NotificationTemplate model
- TechnicianNotificationPreference model
- CustomerNotificationPreference model
- NotificationDeliveryLog model

###  Phase 2: AWS Infrastructure
- Celery task queue
- Redis message broker
- AWS SES email configuration
- AWS SNS SMS configuration
- Management commands for testing

###  Phase 3: Email Templates
- EmailBrandingConfig model
- 8 professional email templates (HTML + text)
- Email preview system
- Admin interface for branding

###  Phase 4: Service Layer
- NotificationService (creates & routes notifications)
- EmailService (AWS SES integration)
- SMSService (AWS SNS integration)
- Celery tasks for async delivery
- Signal handlers for automatic triggers
- Retry logic with exponential backoff

###  Phase 5: User Preferences
- Notification preferences UI
- Notification history with filters
- Notification bell component
- Email/phone verification
- Quiet hours configuration
- Daily digest settings

---

##  Key Features

### For Technicians:
-  Control notification channels (email, SMS, in-app)
-  Choose which notification categories to receive
-  Set quiet hours (pause notifications during sleep)
-  Enable daily digest (one email per day)
-  Verify email and phone for notifications
-  View notification history with filters
-  Real-time notification bell with unread count

### Automatic Notifications:
-  Customer creates repair  Technician notified
-  Customer approves repair  Technician notified (URGENT)
-  Customer denies repair  Technician notified (URGENT)
-  Technician assigned to repair  Notified
-  Repair status changes  Customer/Technician notified
-  Batch repairs approved  Technician notified

### Admin Features:
-  Customize email branding (logo, colors, company info)
-  Manage notification templates
-  View delivery logs and retry history
-  Monitor notification preferences

---

##  URLs

### User Interface
- **Dashboard:** `/tech/`
- **Preferences:** `/tech/notifications/preferences/`
- **History:** `/tech/notifications/history/`

### AJAX Endpoints
- **Mark Read:** `/tech/notifications/<id>/mark-read/` (POST)
- **Mark All Read:** `/tech/notifications/mark-all-read/` (POST)
- **Unread Count:** `/tech/notifications/unread-count/` (GET)

### Verification
- **Send Email:** `/tech/verify-email/` (GET)
- **Confirm Email:** `/tech/verify-email/<uid>/<token>/` (GET)
- **Send SMS:** `/tech/verify-phone/` (GET)
- **Confirm SMS:** `/tech/verify-phone/confirm/` (POST)

### Admin
- **Templates:** `/admin/core/notificationtemplate/`
- **Branding:** `/admin/core/emailbrandingconfig/`
- **Delivery Logs:** `/admin/core/notificationdeliverylog/`

---

##  Testing Checklist

### Local Testing
- [ ] Redis running
- [ ] All services started
- [ ] Login successful
- [ ] Dashboard loads with notification bell
- [ ] Preferences page loads
- [ ] Create test repair triggers notification
- [ ] Notification appears in bell dropdown
- [ ] Mark as read works
- [ ] Notification history displays correctly
- [ ] Filters work (read/unread, category)
- [ ] Email verification sends email (check console)
- [ ] Phone verification generates code

### Production Deployment
- [ ] Environment variables configured
- [ ] AWS SES verified and out of sandbox
- [ ] AWS SNS configured
- [ ] AWS ElastiCache Redis running
- [ ] Database migrations applied
- [ ] Notification templates created
- [ ] Celery services running (systemd/supervisor)
- [ ] Test email sent successfully
- [ ] Test SMS sent successfully
- [ ] HTTPS enforced
- [ ] Email branding configured

---

##  Troubleshooting

### Redis Not Running
```bash
# macOS
brew services start redis

# Verify
redis-cli ping  # Should return: PONG
```

### Notifications Not Created
```bash
# Check signal handlers are registered
python manage.py shell -c "
from django.db.models.signals import post_save
from apps.technician_portal.models import Repair
print(f'Receivers: {len(post_save._live_receivers(Repair))}')
"
```

### Emails Not Sending
```bash
# Check Celery worker is running
# Terminal 2 should show task received messages

# Check delivery logs
python manage.py shell -c "
from core.models import NotificationDeliveryLog
failed = NotificationDeliveryLog.objects.filter(status='failed')
for log in failed:
    print(f'{log.channel}: {log.error_message}')
"
```

### Notification Bell Not Updating
- Check browser console for JavaScript errors
- Verify CSRF token in cookies
- Check AJAX endpoint returns JSON: `/tech/notifications/unread-count/`

---

##  Monitoring

### Celery Flower
Access at: http://localhost:5555

Features:
- View active tasks
- Monitor success/failure rates
- Inspect worker status
- View task history

### Django Admin
Access at: http://localhost:8000/admin/

Key Areas:
- **Notifications:** View all created notifications
- **Delivery Logs:** Track email/SMS delivery attempts
- **Templates:** Manage notification templates
- **Preferences:** View user notification settings

---

##  Security Notes

### Development Mode:
- Emails print to console (no real sending)
- SMS shows code in message (no real sending)
- DEBUG=True shows detailed errors

### Production Mode:
- Real emails sent via AWS SES
- Real SMS sent via AWS SNS
- CSRF protection on all endpoints
- HTTPS required
- Rate limiting on AWS services

---

##  Cost Estimates (Production)

Based on 100 technicians, 50 customers:

| Service | Monthly Cost |
|---------|--------------|
| AWS SES (email) | ~$2.70 |
| AWS SNS (SMS) | ~$87.00 |
| ElastiCache (Redis) | ~$13.00 |
| **Total** | **~$103/month** |

See `docs/development/notifications/AWS_SETUP_GUIDE.md` for optimization tips.

---

##  Learning Resources

### Django Signals
- How signal handlers automatically trigger notifications
- See: `apps/technician_portal/signals.py`

### Celery Tasks
- How async tasks process email/SMS delivery
- See: `core/tasks.py`

### Template Rendering
- How Django templates render notification content
- See: `core/services/notification_service.py`

### ContentType Framework
- How polymorphic relationships work (Notification  any recipient)
- See: `core/models/notification.py`

---

##  Support

For issues or questions:

1. Check **NOTIFICATION_SYSTEM_SETUP_GUIDE.md** for detailed troubleshooting
2. Review phase completion documents for implementation details
3. Check Django logs for errors
4. Monitor Celery worker output for task failures

---

##  Next Steps

### Immediate:
1. Run `bash setup_notifications.sh`
2. Start services with `bash start_notifications.sh`
3. Test all features
4. Create more test notifications

### Before Production:
1. Configure AWS credentials
2. Set up AWS SES and verify domain
3. Set up AWS SNS for SMS
4. Create Redis cluster on AWS ElastiCache
5. Run migrations on production database
6. Configure systemd/supervisor for Celery
7. Test email and SMS sending

### Optional Enhancements:
- Add customer portal notification UI
- Add notification search functionality
- Add notification export feature
- Add phone verification modal UI
- Add notification analytics

---

**You're all set!** 

Run the setup script, start the services, and begin testing. The notification system is fully functional and ready for use.
