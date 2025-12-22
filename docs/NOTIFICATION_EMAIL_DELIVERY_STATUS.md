# Email Notification Delivery - Status Report

**Date:** December 22, 2025
**Environment:** Production (rs-systems-production)
**Status:** 🔴 CRITICAL - Notifications created but emails not delivered

---

## Executive Summary

**What Works:**
- ✅ Email verification system (users can verify their emails)
- ✅ Notification creation (notifications stored in database with incrementing IDs)
- ✅ SendGrid configuration (API key configured, ready to send)
- ✅ Redis task queue (connected and storing tasks)
- ✅ Application health (web app responding normally)

**What's Broken:**
- ❌ Email delivery (Celery workers not running)
- ❌ EC2 deployment commands (instance stuck/unresponsive)
- ❌ Environment health (Red status due to failed deployments)

**Impact:**
- Users can request repairs, approve repairs, and use the system normally
- Email notifications ARE being created and queued in Redis
- **But emails are NOT being sent** because Celery workers aren't processing the queue
- 2+ email tasks currently stuck in Redis queue waiting to be processed

---

## Problem Timeline

### Initial Issue Reported
User reported: "Email verification works (receives verification emails) but repair event notifications are NOT being sent to customers or technicians."

### Root Causes Identified

#### 1. ✅ FIXED: JSON Serialization Error
**Problem:** Notification creation was failing with `"Object of type Repair is not JSON serializable"`

**Location:** `core/views/test_notification.py` (lines 66-77)

**Cause:** Test endpoint was passing Django model objects directly into `template_context` JSONField:
```python
# WRONG - caused error:
context = {
    'repair': repair,  # Django model object - not JSON serializable
}

# CORRECT - fixed version:
context = {
    'repair_id': repair.pk,  # Primitive values only
    'unit_number': repair.unit_number,
    'customer_name': repair.customer.name,
}
```

**Fix Applied:** Updated `core/views/test_notification.py` to use only JSON-serializable primitives

**Verification:** User tested `/test-notification/` and received:
```json
{
  "success": true,
  "notification_id": 57,  // ✅ ID incrementing (was 55 → 57)
  "notification_created": true
}
```

**Status:** ✅ FIXED - Notifications are now being created successfully

#### 2. ❌ CRITICAL: Celery Workers Not Running
**Problem:** Email tasks queued in Redis but never processed

**Diagnostic Evidence:**
User accessed `/celery-status/` endpoint:
```json
{
  "redis": {
    "connected": true,
    "tasks_in_queue": 2  // ✅ Tasks are queued
  },
  "celery": {
    "workers_online": false,  // ❌ No workers to process them
    "worker_count": 0,
    "error": "No workers responding to ping"
  },
  "diagnosis": {
    "issue": "CELERY_WORKERS_NOT_RUNNING",
    "severity": "CRITICAL"
  }
}
```

**Root Cause:** `.ebextensions/celery.config` configures systemd services to start Celery workers, but these services are not starting on the EC2 instance.

**Status:** ❌ UNFIXED - This is the core issue blocking email delivery

#### 3. ❌ NEW ISSUE: EC2 Instance Unresponsive to Deployments
**Problem:** All deployment attempts timing out after 14+ minutes (should take 2-3 minutes)

**Cause:** Multiple failed attempts to deploy Celery worker configurations left the EC2 instance in a bad state with stuck processes or locks.

**Error Pattern:**
```
WARN: The following instances have not responded in the allowed command timeout time
ERROR: Unsuccessful command execution on instance id(s) 'i-0035c8884bfe7a2e9'
```

**Impact:** Cannot deploy fixes or updates to production

**Status:** ❌ CRITICAL - Environment needs rebuild

---

## What We Attempted (and why it failed)

### Attempt 1: systemd Services (`.ebextensions/celery.config`)
**Approach:** Configure systemd services for celery-worker and celery-beat

**Configuration:**
- Created `/etc/systemd/system/celery-worker.service`
- Created `/etc/systemd/system/celery-beat.service`
- Used `container_commands` to enable and start services

**Result:** ❌ Services configured but not starting (checked via `/celery-status/`)

**Likely Cause:**
- Virtual environment path issues
- Environment variable loading problems
- Service start timing conflicts with EB deployment lifecycle

### Attempt 2: Supervisor Process Manager
**Approach:** Use Supervisor to manage Celery worker process

**Configuration:**
- Installed `supervisor` via yum packages
- Created `/etc/supervisord.d/celery.ini`
- Dynamic venv detection script

**Result:** ❌ Deployment failed immediately

**Error:** Package installation error (Supervisor not available on Amazon Linux 2023)

**Action Taken:** Reverted commit `ba05f45b`

### Attempt 3: Background Daemon with Auto-Restart Loop
**Approach:** Simple bash daemon script with infinite restart loop

**Configuration:**
- `/usr/local/bin/celery_daemon.sh` - Main worker process
- `/usr/local/bin/start_celery_daemon.sh` - Daemon starter
- Cron monitoring every 5 minutes
- Used `nohup` to detach from deployment

**Result:** ❌ Deployment hung for 14+ minutes, then timed out

**Likely Cause:** Script was blocking the deployment process despite `nohup`

**Impact:** EC2 instance became unresponsive to ALL subsequent deployments

**Action Taken:**
- Aborted deployment
- Reverted commits `8035c95d` and `86e9ef54`
- Disabled all Celery `.ebextensions` configs

---

## Current System State

### Deployed Version
```
app-11ba-251221_211000751770
```

**This version includes:**
- ✅ JSON serialization fix for notifications
- ✅ `/test-notification/` diagnostic endpoint
- ✅ `/check-notification-prefs/` diagnostic endpoint
- ✅ `/celery-status/` diagnostic endpoint
- ❌ NO Celery workers running

### Environment Health
```
Status: Ready
Health: Red
CNAME: rs-systems-production.us-east-1.elasticbeanstalk.com
```

**Health Check Response:**
```bash
curl https://rs-systems-production.us-east-1.elasticbeanstalk.com/health/
# Returns: {"status": "healthy", "service": "rs_systems", "database": "connected"}
```

**Observation:** App is responding correctly, but EB monitoring shows Red health (likely due to failed deployment attempts)

### Database State
- **Notifications Created:** ID incrementing (55 → 57 confirmed)
- **Email Verified Users:** At least 2 (customer and technician test accounts)
- **Preferences Status:** All correct (`email_verified: true`, `can_send_email: true`)

### Redis Queue
- **Connection:** ✅ Working
- **Tasks Queued:** 2 email tasks waiting
- **Workers Online:** 0

### SendGrid Configuration
```bash
# Environment variables (confirmed via `eb printenv`):
SENDGRID_API_KEY=SG.cNd5NraUTGS...  ✅ Set
DEFAULT_FROM_EMAIL=notifications@rockstarwindshield.repair  ✅ Set
EMAIL_HOST=smtp.sendgrid.net  ✅ Configured
EMAIL_PORT=587  ✅ Configured
```

**Direct Email Test:** Not attempted (need to run `python manage.py test_direct_email` on production)

### EC2 Instance State
- **Instance ID:** `i-0035c8884bfe7a2e9`
- **Deployment Response:** Timing out (14+ minutes)
- **SSH Access:** Not configured (`eb ssh --setup` needed)
- **Likely Issue:** Stuck processes or locks from failed Celery deployments

---

## Diagnostic Tools Available

### 1. `/celery-status/` (Web-based)
**URL:** `https://rswr.systems/celery-status/`

**Returns:**
```json
{
  "redis": {
    "connected": true/false,
    "broker_url": "redis://...",
    "tasks_in_queue": <number>
  },
  "celery": {
    "workers_online": true/false,
    "worker_count": <number>,
    "workers": ["celery@hostname"],
    "active_tasks": <number>
  },
  "diagnosis": {
    "issue": "CELERY_WORKERS_NOT_RUNNING",
    "severity": "CRITICAL",
    "message": "...",
    "solution": "..."
  }
}
```

### 2. `/test-notification/` (Web-based)
**URL:** `https://rswr.systems/test-notification/`

**Purpose:** Creates a test notification and queues email delivery

**Returns:**
```json
{
  "success": true,
  "notification_id": <id>,
  "notification_created": true/false,
  "recipient_email": "...",
  "email_verified": true/false,
  "can_send_email": true/false,
  "message": "..."
}
```

### 3. `/check-notification-prefs/` (Web-based)
**URL:** `https://rswr.systems/check-notification-prefs/`

**Purpose:** Shows all notification preference settings for logged-in user

**Returns:** All preference fields including verification status

### 4. Management Commands
```bash
# Test direct email (bypasses Celery)
python manage.py test_direct_email <email>

# Check Celery queue status
python manage.py check_celery_queue

# Sync email verification status (backfill)
python manage.py sync_email_verification

# Check notifications created
python manage.py shell
>>> from core.models import Notification
>>> Notification.objects.all().count()
>>> Notification.objects.latest('created_at')
```

---

## Recommended Next Steps

### IMMEDIATE: Restore Environment Health

#### Option 1: Rebuild Environment (RECOMMENDED)
```bash
eb rebuild
```

**What this does:**
- Terminates current EC2 instance
- Launches fresh instance
- Deploys last successful application version
- Clears any stuck processes/locks

**Timeline:** 5-10 minutes (includes brief downtime)

**Outcome:**
- Environment health returns to Green
- Deployments will work again
- App will be responsive
- Still NO email delivery (need to implement workers separately)

**Risk:**
- 5-10 minute downtime
- Users cannot access app during rebuild

#### Option 2: Restart Application Only
```bash
# Requires SSH access (not currently configured)
eb ssh --setup  # One-time setup
eb ssh
sudo systemctl restart web
```

**Timeline:** 2-3 minutes (no downtime)

**Outcome:** May restore health without rebuild

**Risk:** May not fix stuck processes; rebuild might still be needed

### NEXT: Implement Celery Workers (Choose ONE approach)

#### Approach A: Post-Deployment Hook (RECOMMENDED)
**Why:** Starts workers AFTER deployment completes, avoiding timeout issues

**Implementation:**
1. Create `.platform/hooks/postdeploy/01_start_celery.sh`:
```bash
#!/bin/bash
# Runs AFTER deployment completes successfully

VENV_BIN=$(find /var/app/venv -name activate | head -1 | xargs dirname)
cd /var/app/current

# Load environment variables
set -a
source /opt/elasticbeanstalk/deployment/env
set +a

# Kill old Celery processes
pkill -f 'celery.*worker' || true
sleep 2

# Start Celery worker in background
nohup $VENV_BIN/celery -A rs_systems worker \
  --loglevel=info \
  --concurrency=2 \
  --logfile=/var/log/celery-worker.log \
  --pidfile=/var/run/celery-worker.pid \
  >/dev/null 2>&1 &

echo "Celery worker started (PID: $!)"
```

2. Make executable and deploy:
```bash
chmod +x .platform/hooks/postdeploy/01_start_celery.sh
git add .platform/
git commit -m "Add post-deployment Celery worker startup"
git push && eb deploy
```

**Pros:**
- Runs AFTER deployment completes (no timeout risk)
- Simple, minimal configuration
- Easy to debug (separate log file)
- Standard EB pattern

**Cons:**
- Workers restart on every deployment
- No automatic recovery if worker crashes

#### Approach B: Separate Worker Tier Environment
**Why:** Dedicated environment just for background workers

**Implementation:**
1. Create new EB environment:
```bash
eb create rs-systems-workers \
  --tier worker \
  --instance_type t2.small \
  --single
```

2. Configure worker environment:
- Uses same codebase
- Runs Celery worker instead of web server
- Connects to same Redis and PostgreSQL
- Auto-scales independently

**Pros:**
- ✅ Completely isolated from web tier
- ✅ Can scale workers independently
- ✅ Automatic restart on failure
- ✅ No deployment interference
- ✅ Production-grade solution

**Cons:**
- Additional AWS costs (~$15/month for t2.small)
- More complex setup
- Two environments to manage

#### Approach C: AWS ECS/Fargate Container
**Why:** Modern containerized approach

**Implementation:**
1. Create ECS task definition for Celery worker
2. Run as Fargate service (serverless containers)
3. Configure to connect to existing Redis/RDS

**Pros:**
- ✅ Most scalable solution
- ✅ Auto-restart and health checks
- ✅ Can scale to 0 when idle (cost savings)
- ✅ Modern best practice

**Cons:**
- Most complex to set up
- Requires learning ECS/Fargate
- Different deployment process than EB

#### Approach D: Cron-Based Daemon Monitor (SIMPLEST)
**Why:** Extremely simple, works everywhere

**Implementation:**
1. Create startup script in `.platform/hooks/postdeploy/`
2. Add cron job to check every 5 minutes:
```bash
# /etc/cron.d/celery_monitor
*/5 * * * * root /usr/local/bin/ensure_celery_running.sh
```

3. Monitor script checks if worker running, starts if not

**Pros:**
- ✅ Very simple
- ✅ Automatic recovery
- ✅ No external dependencies
- ✅ Works with existing infrastructure

**Cons:**
- May miss crashes between cron runs
- Less elegant than proper process manager

---

## Technical Reference

### Key Files Modified This Session

#### 1. `core/views/test_notification.py` (FIXED)
**Lines 66-87:** Changed context from model objects to primitives

**Commit:** `ff79e34c` - "Fix: Resolve JSON serialization error in test notification endpoint"

#### 2. `core/views/celery_status.py` (NEW)
**Purpose:** Web-based Celery worker status diagnostic

**Commit:** `11ba1ffa` - "Add simple Celery status diagnostic endpoint"

**URL Route:** `/celery-status/`

#### 3. `core/management/commands/test_direct_email.py` (NEW)
**Purpose:** Test email sending directly via SendGrid (bypasses Celery)

**Usage:** `python manage.py test_direct_email <email>`

**Status:** Deployed but not tested on production

#### 4. `core/management/commands/check_celery_queue.py` (NEW)
**Purpose:** Check Redis queue status and worker availability

**Usage:** `python manage.py check_celery_queue`

**Status:** Deployed but CLI access needed

#### 5. `.ebextensions/celery.config.DISABLED` (DISABLED)
**Original Purpose:** systemd services for Celery workers

**Status:** Disabled to prevent deployment interference

**Location:** Renamed from `celery.config` to `celery.config.DISABLED`

### Configuration Files

#### SendGrid Email Settings (`rs_systems/settings_aws.py`)
```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'apikey'
EMAIL_HOST_PASSWORD = os.environ.get('SENDGRID_API_KEY')
DEFAULT_FROM_EMAIL = 'notifications@rockstarwindshield.repair'
```

#### Celery Configuration (`rs_systems/celery.py`)
```python
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL')
# Currently: redis://rs-systems-redis.jdkvdt.0001.use1.cache.amazonaws.com:6379/0

CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND')
# Same as broker

CELERY_CONCURRENCY = 4  # But using 2 in worker startup for t2.small
```

### Redis/ElastiCache
```
Endpoint: rs-systems-redis.jdkvdt.0001.use1.cache.amazonaws.com:6379
Status: ✅ Connected and working
Queue Name: 'celery' (default)
Current Tasks: 2 pending
```

### Email Notification Flow (Current)

```
1. User triggers repair event (create, approve, complete)
   ↓
2. Signal handler fires (apps/technician_portal/signals.py)
   ↓
3. NotificationService.create_notification() called
   ↓
4. Notification record created in PostgreSQL ✅
   ↓
5. NotificationService._queue_delivery() called
   ↓
6. send_notification_email.delay() queues task in Redis ✅
   ↓
7. Celery worker picks up task ❌ (NO WORKERS RUNNING)
   ↓
8. EmailService.send_notification_email() sends via SendGrid ❌
   ↓
9. Email delivered to user ❌
```

**Where it's stuck:** Step 7 - Tasks are in Redis queue but no workers to process them

---

## Success Criteria

When email notifications are fully working, you should see:

### 1. Celery Status Check
```bash
curl https://rswr.systems/celery-status/
```
Returns:
```json
{
  "celery": {
    "workers_online": true,  // ✅ MUST be true
    "worker_count": 1,       // ✅ At least 1
    "active_tasks": 0        // ✅ 0 when idle
  }
}
```

### 2. Test Notification
```bash
curl https://rswr.systems/test-notification/
```
Then check email inbox within 1-2 minutes. Should receive email with subject "Test notification created..."

### 3. Real Repair Flow
1. Create repair request (customer portal)
2. Technician should receive "New Repair Request" email
3. Technician approves repair
4. Customer should receive "Repair Approved" email
5. Technician marks complete
6. Customer should receive "Repair Completed" email

### 4. Redis Queue Empty
```bash
python manage.py check_celery_queue
```
Returns:
```
celery: 0 tasks  // ✅ Workers processing queue
```

---

## Lessons Learned

### What Worked
1. **Web-based diagnostics** (`/celery-status/`) - Much easier than SSH/logs
2. **JSON serialization fix** - Straightforward, immediate impact
3. **Management commands** - Good for testing but require CLI access

### What Didn't Work
1. **systemd services in .ebextensions** - Too fragile for EB environment
2. **Supervisor** - Not available on Amazon Linux 2023
3. **Background daemon in container_commands** - Blocks deployment process

### Key Insights
1. **.ebextensions are executed DURING deployment** - Anything that takes >1 minute or doesn't properly detach will cause timeouts
2. **Post-deployment hooks are better for long-running processes** - They run AFTER deployment completes
3. **Separate worker tier is production best practice** - Keeps web and workers isolated
4. **Always test with direct email first** - Eliminates Celery as variable when debugging

---

## Questions to Answer

### For Understanding Current State
1. Can you access the production EC2 instance via AWS Systems Manager or SSH?
2. Are there any logs showing why systemd services didn't start? (`journalctl -u celery-worker`)
3. What does `ps aux | grep celery` show on the EC2 instance?

### For Choosing Next Approach
1. What's your preference: minimal complexity vs. production best practice?
2. Is 5-10 minutes of downtime acceptable for `eb rebuild`?
3. Budget for separate worker environment ($15-20/month)?

### For Verification
1. Has the direct email test command been run on production?
   ```bash
   python manage.py test_direct_email wdrakeduncan@gmail.com
   ```
2. What happens when you manually start Celery on the instance?
   ```bash
   source /var/app/venv/*/bin/activate
   celery -A rs_systems worker --loglevel=info
   ```

---

## Recommended Action Plan

### Phase 1: Restore Stability (15 minutes)
```bash
# 1. Rebuild environment to get fresh EC2 instance
eb rebuild

# 2. Wait for completion and verify
eb status  # Should show Health: Green

# 3. Verify app is working
curl https://rswr.systems/health/
# Should return: {"status": "healthy"}

# 4. Verify diagnostics still available
curl https://rswr.systems/celery-status/
```

### Phase 2: Implement Workers (30 minutes)
**Recommended: Post-Deployment Hook Approach**

```bash
# 1. Create hook directory
mkdir -p .platform/hooks/postdeploy

# 2. Create startup script
# (See "Approach A: Post-Deployment Hook" above for script content)

# 3. Make executable
chmod +x .platform/hooks/postdeploy/01_start_celery.sh

# 4. Deploy
git add .platform/
git commit -m "Add Celery worker post-deployment startup"
git push origin main
eb deploy

# 5. Verify workers started
curl https://rswr.systems/celery-status/
# Should show: "workers_online": true
```

### Phase 3: Test & Verify (10 minutes)
```bash
# 1. Test notification creation
curl https://rswr.systems/test-notification/

# 2. Check email inbox (should arrive in 1-2 minutes)

# 3. Test real repair flow
# - Create repair
# - Approve repair
# - Complete repair
# - Verify emails received at each step

# 4. Check Redis queue
curl https://rswr.systems/celery-status/
# Should show: "tasks_in_queue": 0
```

### Phase 4: Monitor (Ongoing)
```bash
# Set up cron monitoring (optional but recommended)
# Add to .platform/hooks/postdeploy/02_monitor_celery.sh
# Check every 5 minutes, restart if crashed
```

---

## Additional Resources

### Elastic Beanstalk Documentation
- Platform Hooks: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/platforms-linux-extend.html
- Worker Tier: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/using-features-managing-env-tiers.html

### Celery Documentation
- Daemonization: https://docs.celeryq.dev/en/stable/userguide/daemonizing.html
- Monitoring: https://docs.celeryq.dev/en/stable/userguide/monitoring.html

### Project Documentation
- Notification System: `docs/development/notifications/README.md`
- Deployment Guide: `docs/deployment/AWS_DEPLOYMENT.md`
- Operations Guide: `docs/operations/NOTIFICATION_OPERATIONS.md`

---

## Contact & Next Steps

**Current Status:** Awaiting decision on environment rebuild

**Blocked On:** EC2 instance unresponsive to deployments

**Ready to Deploy:** Post-deployment hook Celery worker solution

**Estimated Time to Fix:** 1 hour (including rebuild + implementation + testing)

**Last Tested:** December 22, 2025

**Test Results:**
- ✅ Notifications created: ID 57 (confirmed incrementing)
- ✅ User preferences: All correct
- ✅ SendGrid config: API key set
- ✅ Redis: Connected with 2 tasks queued
- ❌ Workers: 0 online
- ❌ Email delivery: Not working

---

## Appendix: Failed Deployment Logs

### Celery Daemon Deployment Timeout
```
2025-12-22 17:44:28    WARN    The following instances have not responded in the allowed command timeout time (they might still finish eventually on their own): [i-0035c8884bfe7a2e9].
2025-12-22 17:44:28    INFO    Command execution completed on all instances. Summary: [Successful: 0, TimedOut: 1].
2025-12-22 17:44:28    ERROR   Unsuccessful command execution on instance id(s) 'i-0035c8884bfe7a2e9'. Aborting the operation.
```

**Context:** Attempting to deploy `.ebextensions/celery_daemon.config` with background daemon script

**Duration:** 14+ minutes (normal is 2-3 minutes)

**Result:** Deployment aborted, instance became unresponsive to all subsequent deployments

---

**END OF REPORT**
