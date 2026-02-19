# AWS SES + SNS Setup Plan for RS Systems Notifications

**Domain:** rockstarwindshield.repair
**Route 53 Hosted Zone ID:** Z00152269ZHHL7BWWEO5
**Primary Contact:** poorboychips@gmail.com
**Target Sender Addresses:** notifications@rockstarwindshield.repair, info@rockstarwindshield.repair

---

## Overview

This document guides you through setting up AWS Simple Email Service (SES) and Simple Notification Service (SNS) for the RS Systems notification system. By the end, you'll be able to send professional emails and SMS from your application.

### What You're Setting Up:
-  **AWS SES** - Send emails FROM notifications@rockstarwindshield.repair
-  **Domain Verification** - Prove you own rockstarwindshield.repair
-  **DKIM/SPF** - Prevent emails going to spam (80-90% deliverability improvement)
-  **IAM Credentials** - Secure access keys for sending
-  **Local Testing** - Test before deploying to production
-  **Production Access** - Exit sandbox mode to send to all customers
-  **AWS SNS** - (Optional) SMS notifications

### Prerequisites:
- AWS account with billing enabled
- Access to AWS Console
- Route 53 hosted zone for rockstarwindshield.repair ( You have this!)
- Local development environment with notification system installed

---

## DNS Records Explained (Simple Terms)

When you verify a domain in SES, AWS requires 4 types of DNS records:

### 1. Domain Verification TXT Record
**Purpose:** Proves to AWS you control the domain
**Analogy:** Like showing your driver's license to prove identity
**Format:**
```
Type: TXT
Name: _amazonses.rockstarwindshield.repair
Value: "SomeRandomStringFromAWS123456"
```

### 2. DKIM CNAME Records (3 records)
**Purpose:** Cryptographic signature proving emails are authentic
**Analogy:** Like a wax seal on a letter - proves it wasn't tampered with
**Impact:** Without DKIM, emails often go to spam. With DKIM, deliverability increases 80-90%
**Format:**
```
Type: CNAME
Name: abc123._domainkey.rockstarwindshield.repair
Value: abc123.dkim.amazonses.com
(Plus 2 more similar records with different prefixes)
```

### 3. SPF TXT Record
**Purpose:** Tells email servers "Amazon SES is allowed to send email for my domain"
**Analogy:** Like giving SES a hall pass to send mail on your behalf
**Format:**
```
Type: TXT
Name: rockstarwindshield.repair
Value: "v=spf1 include:amazonses.com ~all"
```

### 4. MX Record (For Inbound Email - Optional)
**Purpose:** Routes incoming emails to SES (for forwarding to Gmail)
**We'll set this up later if you want inbound email**

---

## Phase 1: Verify Route 53 Access & Create SES Domain Identity (15 mins)

### Step 1.1: Verify Route 53 Access

1. Log into AWS Console: https://console.aws.amazon.com/
2. Search for "Route 53" in the top search bar
3. Click "Hosted zones" in the left sidebar
4. Find: **rockstarwindshield.repair**
5. Verify Hosted Zone ID matches: **Z00152269ZHHL7BWWEO5** 
6. Click on the domain name to view existing DNS records

**What you should see:**
- NS (Name Server) records
- SOA (Start of Authority) record
- Possibly A records pointing to your website

### Step 1.2: Access AWS SES Console

1. In AWS Console, search for "Simple Email Service" or "SES"
2. **CRITICAL:** Select region **us-east-1** (N. Virginia) in the top-right dropdown
   - Why: Your Elastic Beanstalk app is in us-east-1, keep everything in same region
3. You should see the SES dashboard

### Step 1.3: Create Domain Identity

1. In SES Console, click **"Verified identities"** in left sidebar
2. Click **"Create identity"** button (orange)
3. Configure identity:
   - **Identity type:**  Domain (not email address)
   - **Domain:** `rockstarwindshield.repair` (no https://, just domain)
   - **Assign a default configuration set:** Leave unchecked for now
   - **Use a custom MAIL FROM domain:** Leave unchecked for simplicity
   - **Advanced DKIM settings:**
     -  **Enable DKIM signing** (CRITICAL - check this!)
     - DKIM signing key length: 2048-bit RSA (default)
     - DKIM identity: Use domain (default)
   - **Publish DNS records to Route 53:**  **Check this!** (Auto-creates DNS records)
4. Click **"Create identity"** button

### Step 1.4: Automatic DNS Record Creation

AWS will now:
1. Detect your Route 53 hosted zone (Z00152269ZHHL7BWWEO5)
2. Automatically add DNS records:
   - 1 domain verification TXT record
   - 3 DKIM CNAME records
3. Show confirmation: "DNS records published to Route 53"

**Verification Status:**
- Initial status: **"Pending"** (orange)
- DNS propagation time: 15-60 minutes typically
- Final status: **"Verified"** (green checkmark)

**You can continue to next steps while waiting for verification!**

---

## Phase 2: Add SPF Record Manually (5 mins)

AWS doesn't auto-create SPF records, so we'll add it manually.

### Step 2.1: Check for Existing SPF Record

1. Go back to Route 53  Hosted zones  rockstarwindshield.repair
2. Look for a TXT record with name "rockstarwindshield.repair" (or blank/@ symbol)
3. Check if value contains "v=spf1"

**If SPF record exists:**
- Current value might be: `"v=spf1 include:_spf.google.com ~all"`
- Modify to: `"v=spf1 include:amazonses.com include:_spf.google.com ~all"`
- (Adds SES authorization while keeping existing authorizations)

**If NO SPF record exists (most likely):**
- Continue to Step 2.2

### Step 2.2: Create SPF Record

1. In Route 53 hosted zone view, click **"Create record"**
2. Configure record:
   - **Record name:** Leave blank (or enter `@` if required)
   - **Record type:** TXT
   - **Value:** `"v=spf1 include:amazonses.com ~all"`
   - **TTL:** 300 (5 minutes)
   - **Routing policy:** Simple routing
3. Click **"Create records"**

**What this does:**
- Authorizes Amazon SES to send email on behalf of rockstarwindshield.repair
- Tells recipient email servers to trust emails from SES
- Reduces spam folder placement by ~30-40%

---

## Phase 3: Create IAM User & SMTP Credentials (15 mins)

**Security Best Practice:** Create a dedicated IAM user with minimal permissions (not root account).

### Step 3.1: Create IAM Policy

1. AWS Console  Search "IAM"  Click "IAM"
2. Left sidebar  **"Policies"**  Click **"Create policy"**
3. Click **"JSON"** tab (not Visual editor)
4. Delete the placeholder JSON and paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail",
        "ses:SendTemplatedEmail"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ses:GetSendStatistics",
        "ses:GetSendQuota"
      ],
      "Resource": "*"
    }
  ]
}
```

5. Click **"Next: Tags"**  Skip tags  Click **"Next: Review"**
6. Policy details:
   - **Name:** `RS-Systems-SES-Send-Policy`
   - **Description:** `Allows RS Systems notification system to send emails via SES`
7. Click **"Create policy"**

### Step 3.2: Create IAM User

1. IAM Console  **"Users"**  Click **"Add users"**
2. User details:
   - **User name:** `rs-systems-ses-user`
   - **Access type:**  **Access key - Programmatic access** (NOT console access)
3. Click **"Next: Permissions"**
4. Set permissions:
   - Select **"Attach existing policies directly"**
   - Search for: `RS-Systems-SES-Send-Policy`
   -  Check the box next to your policy
5. Click **"Next: Tags"**  Skip  **"Next: Review"**  **"Create user"**

### Step 3.3: Download Access Keys

** CRITICAL:** These credentials are shown ONLY ONCE!

1. After user creation, you'll see:
   - **Access key ID:** AKIA... (20 characters)
   - **Secret access key:** wJalrXUtnFEMI... (40 characters)
2. Click **"Download .csv"** button
3. Save file securely (DO NOT commit to git!)

**Copy these values - you'll need them in Phase 4:**
```
Access Key ID: AKIA...
Secret Access Key: wJalrXUtnFEMI...
```

### Step 3.4: Generate SMTP Credentials (Alternative Method)

SES supports both API credentials (above) and SMTP credentials. Let's create SMTP credentials for Django:

1. Go back to SES Console
2. Left sidebar  **"SMTP Settings"**
3. Click **"Create SMTP Credentials"** button
4. IAM User Name: `rs-systems-smtp-user` (pre-filled, keep it)
5. Click **"Create"**
6. **Download SMTP credentials** (only shown once!)

**You'll get:**
- **SMTP Username:** AKIA... (looks like access key)
- **SMTP Password:** BPej4qU... (different from secret key - auto-generated)
- **SMTP Endpoint:** email-smtp.us-east-1.amazonaws.com
- **Port:** 587 (TLS) or 465 (SSL)

**Save these - you'll use them in .env file!**

---

## Phase 4: Configure Local Environment (10 mins)

### Step 4.1: Update .env File

Open your `.env` file and add/update the following:

```bash
# ================================================================
# AWS SES Configuration (Email Notifications)
# ================================================================
AWS_SES_HOST=email-smtp.us-east-1.amazonaws.com
AWS_SES_PORT=587
AWS_SES_SMTP_USER=AKIA... # From Step 3.4 - SMTP Username
AWS_SES_SMTP_PASSWORD=BPej4... # From Step 3.4 - SMTP Password
AWS_SES_REGION=us-east-1

# Email sender configuration
DEFAULT_FROM_EMAIL=notifications@rockstarwindshield.repair
DEFAULT_FROM_NAME=RS Systems Notifications

# Email rate limiting (SES default: 14/sec in production, 1/sec in sandbox)
EMAIL_RATE_LIMIT=14

# ================================================================
# SMS Configuration (Disabled for now - we'll set up later)
# ================================================================
SMS_ENABLED=false
AWS_SNS_REGION=us-east-1

# ================================================================
# AWS Credentials (if not already set)
# ================================================================
AWS_ACCESS_KEY_ID=AKIA... # From Step 3.3 or use SMTP user
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI... # From Step 3.3
AWS_REGION=us-east-1
```

**Important Notes:**
- Use SMTP credentials from Step 3.4 (not the IAM access keys from 3.3)
- Keep `SMS_ENABLED=false` until we set up SNS
- DO NOT commit .env file to git (should be in .gitignore)

### Step 4.2: Verify .env.example

Your `.env.example` should have placeholders (no real values):

```bash
AWS_SES_HOST=email-smtp.us-east-1.amazonaws.com
AWS_SES_PORT=587
AWS_SES_SMTP_USER=your_smtp_username_here
AWS_SES_SMTP_PASSWORD=your_smtp_password_here
DEFAULT_FROM_EMAIL=notifications@yourdomain.com
```

### Step 4.3: Restart Django Development Server

If you have Django running:
```bash
# Kill existing server (Ctrl+C if running in foreground)
# Or find and kill the process
ps aux | grep "manage.py runserver"
kill <PID>

# Start fresh
python manage.py runserver
```

---

## Phase 5: Test Email Sending Locally (15 mins)

### Step 5.1: Verify poorboychips@gmail.com (Required in Sandbox Mode)

**Why:** In sandbox mode, you can only send TO verified email addresses.

1. SES Console  **"Verified identities"**  **"Create identity"**
2. **Identity type:**  Email address
3. **Email address:** `poorboychips@gmail.com`
4. Click **"Create identity"**
5. Check your Gmail inbox for verification email from AWS
6. Click the verification link (expires in 24 hours)
7. Return to SES console - status should be **"Verified"**

**Repeat for any other email addresses you want to test with.**

### Step 5.2: Run SES Test Command

```bash
cd /Users/drakeduncan/projects/rs_systems_branch2
source venv/bin/activate  # If using virtual environment

python manage.py test_ses poorboychips@gmail.com
```

**Expected Output (Success):**
```
======================================================================
AWS SES Email Test
======================================================================
Recipient: poorboychips@gmail.com
From: notifications@rockstarwindshield.repair
Email Backend: django.core.mail.backends.smtp.EmailBackend
SMTP Host: email-smtp.us-east-1.amazonaws.com:587
======================================================================

Sending test email...

======================================================================
 Email sent successfully!

Message ID: <some-aws-message-id>
Check the recipient inbox for the test email.
======================================================================
```

**Expected Output (Error - if domain not verified yet):**
```
 Failed to send email

Error: Email address is not verified. The following identities failed the check
in region US-EAST-1: notifications@rockstarwindshield.repair

Solution: Wait for domain verification to complete (check SES console)
```

**If you see errors:**
- Check domain verification status in SES console
- Verify SMTP credentials are correct in .env
- Check recipient email is verified (poorboychips@gmail.com)
- Review error message for specific issue

### Step 5.3: Check Gmail Inbox

1. Open Gmail (poorboychips@gmail.com)
2. Look for email FROM: notifications@rockstarwindshield.repair
3. Subject: "AWS SES Test Email - RS Systems"

**Check email headers (important for deliverability):**
- Gmail: Click "..." menu  "Show original"
- Look for:
  - `DKIM: PASS` 
  - `SPF: PASS` 
  - `DMARC: PASS`  (if configured)

### Step 5.4: Test with Actual Notification

Let's create a real notification using your system:

```bash
python manage.py shell
```

In the Django shell:

```python
from core.services.notification_service import NotificationService
from django.contrib.auth import get_user_model
from apps.technician_portal.models import Technician

# Get or create a test user
User = get_user_model()
test_user, created = User.objects.get_or_create(
    username='test_tech',
    defaults={
        'email': 'poorboychips@gmail.com',
        'first_name': 'Test',
        'last_name': 'Technician'
    }
)

# Get or create technician profile
technician, created = Technician.objects.get_or_create(
    user=test_user,
    defaults={
        'email': 'poorboychips@gmail.com',
        'phone_number': '+12025551234',
        'employee_id': 'TEST001',
        'name': 'Test Technician'
    }
)

# Create a test notification
notification = NotificationService.create_notification(
    recipient=technician,
    template_name='repair_assigned',
    context={
        'repair_id': 'TEST-001',
        'unit_number': '1234',
        'customer_name': 'Test Customer',
        'address': '123 Test St, City, ST 12345'
    }
)

print(f"Notification created: {notification.id}")
print(f"Email queued: {notification.email_sent}")
print(f"Check Celery worker logs for email delivery status")
```

**Expected result:**
- Notification created in database
- Celery task queued for email delivery
- Email sent within 30 seconds
- Check Gmail for "New Repair Assigned" email

### Step 5.5: Check Celery Logs

If Celery worker is running:

```bash
# Check worker logs
tail -f celery_worker.log

# Or if running in terminal, check output for:
[INFO] Sending email for notification <ID> to poorboychips@gmail.com (attempt 1)
[INFO] Email sent successfully (notification <ID>)
```

**If you see errors:**
- Check .env configuration
- Verify domain is verified in SES
- Check recipient email is verified (sandbox mode requirement)

---

## Phase 6: Request Production Access (5 mins to submit)

**Current Status: Sandbox Mode**
-  Can send to verified email addresses only
-  Limited to 200 emails/day
-  1 email per second max

**Production Mode (After Approval):**
-  Send to ANY email address
-  50,000+ emails/day
-  14 emails/second

### Step 6.1: Submit Production Access Request

1. SES Console  Left sidebar  **"Account dashboard"**
2. Look for banner: "Your account has sandbox access"
3. Click **"Request production access"** button
4. Fill out the form:

**Mail type:**
-  Transactional

**Website URL:**
- `https://rockstarwindshield.repair`

**Use case description:** (Be specific and professional)
```
Windshield repair notification system for fleet managers and repair technicians.

Our system sends transactional email notifications for:
- Repair status updates (pending approval, approved, in progress, completed)
- Technician assignment notifications
- Customer approval requests
- Daily digest summaries

All recipients have opted in by creating accounts on our platform. Users can
manage notification preferences and opt-out at any time via account settings.

We have implemented bounce and complaint handling, and maintain a strict
privacy policy.

Privacy Policy: https://rockstarwindshield.repair/privacy
Terms of Service: https://rockstarwindshield.repair/terms

Expected daily volume: 1,000 emails
Expected peak volume: 2,000 emails/day
```

**How do you plan to handle bounces and complaints:**
```
Our notification system includes:

1. Automated bounce handling via SES feedback
2. NotificationDeliveryLog model tracks all delivery attempts
3. Failed deliveries automatically marked and retried with exponential backoff
4. Persistent failures trigger user contact verification requests
5. Users can manage notification preferences in account settings
6. One-click unsubscribe links in all emails
7. Regular monitoring of bounce/complaint rates via CloudWatch

Technical implementation:
- Django-based email service with retry logic
- Celery task queue for asynchronous delivery
- AWS SES configuration sets for tracking
- Sentry error monitoring
```

**Compliance acknowledgments:**
-  I will only send to recipients who have requested my emails
-  I have a process to handle bounces and complaints
-  I have a privacy policy

**Planned daily sending volume:**
- `1000` (start conservative)

**Maximum send rate:**
- `10` emails/second (start conservative)

5. Click **"Submit request"**

### Step 6.2: What Happens Next

**Timeline:**
- AWS typically reviews within 24-48 hours
- Sometimes approved in 2-4 hours
- Rarely takes longer (if so, they'll ask for clarification)

**You'll receive email notification when:**
-  Approved: "Your SES sending limit increase request has been granted"
-  More info needed: "We need additional information..."
-  Denied: Very rare for legitimate transactional use cases

**While waiting:**
- Continue testing with verified emails
- Set up SMS (Phase 7)
- Configure Elastic Beanstalk environment variables
- Document your setup

---

## Phase 7: Set Up SMS with AWS SNS (Optional - 30 mins)

**Cost:** ~$0.00645 per SMS in US (~$32/month for 500 SMS)

### Step 7.1: Enable SMS in SNS

1. AWS Console  Search "SNS"  Simple Notification Service
2. **Region:** us-east-1 (same as SES)
3. Left sidebar  **"Text messaging (SMS)"**

### Step 7.2: Configure SMS Settings

1. Click **"Text messaging preferences"**
2. Configure:
   - **Default message type:**  Transactional (higher priority, better delivery)
   - **Account spend limit:** `50.00` USD/month (adjust based on needs)
   - **Default sender ID:** `RS Systems` (Note: Not supported in US, works in other countries)
3. Click **"Save changes"**

### Step 7.3: Create IAM User for SNS

1. IAM Console  Policies  Create Policy  JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sns:Publish",
        "sns:PublishBatch"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "sns:GetSMSAttributes",
        "sns:SetSMSAttributes"
      ],
      "Resource": "*"
    }
  ]
}
```

2. Name: `RS-Systems-SNS-SMS-Policy`
3. Create IAM user: `rs-systems-sns-user`
4. Attach policy
5. Create access keys
6. Download credentials

### Step 7.4: Update .env File

```bash
# AWS SNS Configuration (SMS)
SMS_ENABLED=true
AWS_SNS_REGION=us-east-1
SMS_SENDER_ID=RS Systems
SMS_MAX_PRICE_USD=0.50

# Use the SNS IAM user credentials (or same as SES if combined)
AWS_ACCESS_KEY_ID=AKIA... # SNS user
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI... # SNS user
```

### Step 7.5: Test SMS

```bash
python manage.py test_sns +12025551234  # Replace with your phone
```

**Expected Output:**
```
======================================================================
AWS SNS SMS Test
======================================================================
Recipient: +12025551234
AWS Region: us-east-1
SMS Enabled: True
======================================================================

Initializing AWS SNS client...
Sending test SMS...

======================================================================
 SMS sent successfully!

Message ID: 12345678-1234-1234-1234-123456789012
Cost: ~$0.00645 USD
Region: us-east-1
======================================================================
```

Check your phone for SMS!

---

## Phase 8: Deploy to Elastic Beanstalk (After SES Approval)

### Step 8.1: Add Environment Variables to EB

**Option A: Via EB CLI**
```bash
eb setenv \
  AWS_SES_HOST=email-smtp.us-east-1.amazonaws.com \
  AWS_SES_PORT=587 \
  AWS_SES_SMTP_USER=AKIA... \
  AWS_SES_SMTP_PASSWORD=BPej4... \
  AWS_SES_REGION=us-east-1 \
  DEFAULT_FROM_EMAIL=notifications@rockstarwindshield.repair \
  DEFAULT_FROM_NAME="RS Systems Notifications" \
  EMAIL_RATE_LIMIT=14 \
  SMS_ENABLED=true \
  AWS_SNS_REGION=us-east-1 \
  SMS_MAX_PRICE_USD=0.50
```

**Option B: Via AWS Console**
1. Elastic Beanstalk  Your environment
2. Configuration  Software  Edit
3. Environment properties  Add each variable
4. Save and apply

### Step 8.2: Configure Celery Workers

Create `.ebextensions/celery.config`:

```yaml
files:
  "/opt/elasticbeanstalk/tasks/bundlelogs.d/celery.conf":
    mode: "000755"
    owner: root
    group: root
    content: |
      /var/log/celery-worker.log
      /var/log/celery-beat.log

commands:
  01_celery_tasks:
    command: "mkdir -p /var/log"

container_commands:
  01_start_celery_worker:
    command: "celery -A rs_systems worker --detach --loglevel=info --logfile=/var/log/celery-worker.log --concurrency=4"
    leader_only: true

  02_start_celery_beat:
    command: "celery -A rs_systems beat --detach --loglevel=info --logfile=/var/log/celery-beat.log"
    leader_only: true
```

### Step 8.3: Deploy

```bash
git add .
git commit -m "Configure AWS SES and SNS for notification system"
eb deploy
```

### Step 8.4: Run Production Migrations

```bash
eb ssh
source /var/app/venv/*/bin/activate
cd /var/app/current

python manage.py migrate core
python manage.py setup_notification_templates

# Verify templates created
python manage.py shell
>>> from core.models import NotificationTemplate
>>> NotificationTemplate.objects.count()
12  # Should see 8-12 templates

>>> exit()
```

### Step 8.5: Test Production Notification

```bash
# Still SSH'd into EB instance
python manage.py test_ses poorboychips@gmail.com
python manage.py test_sns +12025551234  # If SMS enabled
```

---

## Phase 9: Set Up CloudWatch Monitoring (30 mins)

### Step 9.1: Create SNS Topic for Alarms

1. AWS Console  SNS  Topics  Create topic
2. Type: Standard
3. Name: `RS-Systems-Notification-Alarms`
4. Create topic
5. Create subscription:
   - Protocol: Email
   - Endpoint: poorboychips@gmail.com
   - Confirm subscription via email

### Step 9.2: Create CloudWatch Alarms

**Alarm 1: Email Delivery Failure Rate**
```
Metric: SES  Bounce Rate
Threshold: > 5%
Period: 5 minutes
Actions: Send to RS-Systems-Notification-Alarms
```

**Alarm 2: SMS Monthly Spending**
```
Metric: Custom  SMSCost (from your metrics service)
Threshold: > $50
Period: 1 day
Actions: Send alert
```

**Alarm 3: Celery Queue Depth**
```
Metric: Custom  QueueDepth
Threshold: > 100
Period: 5 minutes
Actions: Send alert
```

### Step 9.3: Enable CloudWatch in .env

```bash
AWS_CLOUDWATCH_ENABLED=true
AWS_REGION=us-east-1
```

Redeploy to EB.

---

## Troubleshooting

### Domain Not Verifying
- Wait 24-72 hours for DNS propagation
- Check DNS records in Route 53 (should see 4 new records)
- Use `dig` to verify: `dig TXT _amazonses.rockstarwindshield.repair`

### Emails Going to Spam
- Verify DKIM is enabled and verified (3 green checkmarks in SES)
- Add SPF record (Phase 2)
- Check email content (avoid spammy words)
- Warm up your domain (start with low volume)

### SMTP Authentication Failed
- Double-check SMTP username/password in .env
- Verify IAM user has SES permissions
- Check region matches (us-east-1)

### Sandbox Mode Restrictions
- Can only send to verified email addresses
- Verify recipient emails in SES console
- Request production access (Phase 6)

### SMS Not Delivering
- Verify phone number is in E.164 format (+12025551234)
- Check spending limit not exceeded
- Verify IAM user has SNS permissions
- Check CloudWatch logs for delivery status

---

## Cost Summary

**Monthly Estimates:**

| Service | Usage | Rate | Monthly Cost |
|---------|-------|------|--------------|
| **Route 53** | 1 hosted zone | $0.50/zone | $0.50 |
| **SES Emails** | 30,000 emails | $0.10/1000 | $3.00 |
| **SNS SMS** | 500 SMS | $0.00645 each | $32.25 |
| **CloudWatch** | Basic metrics | ~$3-5/month | $4.00 |
| **Data Transfer** | Minimal | Included | $0.00 |
| **Total** | | | **~$40/month** |

**Cost Optimization Tips:**
- Use email for non-urgent notifications (much cheaper than SMS)
- Implement daily digest mode (batch multiple notifications)
- Allow SMS opt-out for non-critical categories
- Monitor spending weekly via CloudWatch

---

## Next Steps After Completion

1.  Monitor SES dashboard for bounce/complaint rates
2.  Set up inbound email forwarding (if needed)
3.  Configure notification preferences UI for users
4.  Add custom email templates with branding
5.  Implement daily digest emails
6.  Set up CloudWatch dashboards
7.  Document troubleshooting procedures for team

---

## Quick Reference Commands

```bash
# Test email
python manage.py test_ses poorboychips@gmail.com

# Test SMS
python manage.py test_sns +12025551234

# Create notification templates
python manage.py setup_notification_templates

# Check Celery workers
celery -A rs_systems inspect active

# Check SES quota
aws ses get-send-quota --region us-east-1

# Check SNS spending
aws sns get-sms-attributes --region us-east-1

# View Route 53 records
aws route53 list-resource-record-sets --hosted-zone-id Z00152269ZHHL7BWWEO5
```

---

## Support Resources

- **AWS SES Documentation:** https://docs.aws.amazon.com/ses/
- **AWS SNS Documentation:** https://docs.aws.amazon.com/sns/
- **Notification System Docs:** See `docs/development/notifications/`
- **Deployment Guide:** See `docs/deployment/NOTIFICATION_DEPLOYMENT.md`
- **CloudWatch Setup:** See `docs/deployment/CLOUDWATCH_SETUP.md`

---

**Document Created:** December 1, 2025
**Last Updated:** December 1, 2025
**Version:** 1.0
**Status:** Ready for implementation
