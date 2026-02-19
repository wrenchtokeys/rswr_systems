# Simple Testing Guide - Notification System

**Quick Reference**: How to test notifications while developing

---

##  Starting the App (Simple Method)

### Just run Django (no background services):

```bash
python manage.py runserver
```

Then open: **http://localhost:8000**

**That's it!** You can now:
- Create repairs
- Test the app normally
- Make changes and see them live

---

##  To Test Notifications (Full System)

Only when you want to test actual notification delivery, run these in **3 separate terminal windows**:

### Terminal 1 - Django (main app):
```bash
python manage.py runserver
```

### Terminal 2 - Celery Worker (sends notifications):
```bash
celery -A rs_systems worker --loglevel=info
```

### Terminal 3 - Celery Beat (scheduler):
```bash
celery -A rs_systems beat --loglevel=info
```

---

##  Stopping Services

### If services are in terminals:
- Press `Ctrl+C` in each terminal window

### If services are in background:
```bash
pkill -f "celery"
pkill -f "manage.py runserver"
```

---

##  Available Documentation

All docs are in: `docs/development/notifications/`

### Quick Access:
- **This Guide** (simple testing): `SIMPLE_TESTING_GUIDE.md` (this file)
- **Quick Setup**: `NOTIFICATION_README.md` (in root directory)
- **Full Setup & Testing**: `docs/development/notifications/SETUP_AND_TESTING_GUIDE.md`
- **Testing Checklist**: `docs/development/notifications/PHASE_6_TESTING_CHECKLIST.md`
- **Main Index**: `docs/development/notifications/README.md`

### Detailed Guides:
- **AWS Setup** (SES/SNS): `docs/development/notifications/setup/AWS_SETUP_GUIDE.md`
- **Redis Setup**: `docs/development/notifications/setup/REDIS_LOCAL_SETUP.md`

### Phase Documentation:
- **Implementation Specs**: `docs/development/notifications/implementation/PHASE_*.md`
- **Completion Summaries**: `docs/development/notifications/completion/PHASE_*_SUMMARY.md`

---

##  Testing Workflow

### Basic Testing (No Notifications):
1. Run: `python manage.py runserver`
2. Visit: http://localhost:8000/tech/
3. Login: `testtech` / `testpass123`
4. Create repairs, test features normally

### With Notifications:
1. Start all 3 services (Django + Celery Worker + Celery Beat)
2. Create a repair in PENDING status
3. Approve the repair
4. Check:
   - Terminal output (emails print to console)
   - Notification history: http://localhost:8000/tech/notifications/history/
   - Admin panel: http://localhost:8000/admin/core/notification/

---

##  Common Tasks

### View Notifications in Admin:
http://localhost:8000/admin/core/notification/

### View Notification Preferences:
http://localhost:8000/tech/notifications/preferences/

### View Notification History:
http://localhost:8000/tech/notifications/history/

### Preview Email Templates:
- http://localhost:8000/admin/email-preview/repair_approved/
- http://localhost:8000/admin/email-preview/repair_denied/
- http://localhost:8000/admin/email-preview/repair_assigned/
- http://localhost:8000/admin/email-preview/repair_completed/
- http://localhost:8000/admin/email-preview/batch_approved/

### Customize Email Branding:
http://localhost:8000/admin/core/emailbrandingconfig/

---

##  Checking Service Status

```bash
# Check if Django is running
curl -s http://localhost:8000/ > /dev/null && echo " Django running" || echo " Django not running"

# Check if Redis is running
redis-cli ping

# Check if Celery processes are running
ps aux | grep -E "(celery|manage.py runserver)" | grep -v grep
```

---

##  Pro Tips

1. **For most development**: Just run `python manage.py runserver`
   - You don't need Celery unless testing notifications

2. **Emails in development**: They print to the Django console (not sent to real email)

3. **To see emails**: Watch the Django terminal output when notifications trigger

4. **Stop everything quickly**:
   ```bash
   pkill -f "celery"
   pkill -f "manage.py runserver"
   ```

5. **Check logs**: All output goes to the terminal where you started each service

---

##  Quick Test Scenario

1. Start Django: `python manage.py runserver`
2. Login: http://localhost:8000/tech/ (`testtech` / `testpass123`)
3. Create a new repair (PENDING status)
4. Go to admin: http://localhost:8000/admin/core/notification/
5. You should see a notification was created (even without Celery running)
6. To actually send the notification, start Celery worker and it will process it

---

##  Need More Help?

- **Full Setup Guide**: `docs/development/notifications/SETUP_AND_TESTING_GUIDE.md`
- **Testing Checklist**: `docs/development/notifications/PHASE_6_TESTING_CHECKLIST.md`
- **All Documentation**: `docs/development/notifications/README.md`

---

**TL;DR**: Just run `python manage.py runserver` for normal development. Only start Celery when you want to test actual notification delivery.
