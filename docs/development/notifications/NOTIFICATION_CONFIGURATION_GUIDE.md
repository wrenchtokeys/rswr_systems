# Notification System Configuration Guide

**Quick Reference**: How to configure branding, phone numbers, emails, and preferences

---

##  Table of Contents

1. [Email Branding Configuration](#email-branding-configuration)
2. [User Contact Information](#user-contact-information)
3. [Notification Preferences](#notification-preferences)
4. [Email Templates Preview](#email-templates-preview)
5. [AWS Configuration (Production)](#aws-configuration-production)
6. [System Settings](#system-settings)

---

##  Email Branding Configuration

### Access Email Branding Settings:

**URL**: http://localhost:8000/admin/core/emailbrandingconfig/

**Login Required**: Admin/Staff access

### What You Can Configure:

#### 1. **Logo**
- Upload your company logo
- Recommended size: 400px width max
- Formats: JPG, PNG
- Auto-optimized on upload

#### 2. **Color Scheme** (6 customizable colors)
- **Primary Color** (#2C5282) - Main brand color
- **Secondary Color** (#4299E1) - Accent color
- **Success Color** (#38A169) - Success messages (green)
- **Danger Color** (#E53E3E) - Error/denial messages (red)
- **Text Color** (#2D3748) - Body text
- **Background Color** (#F7FAFC) - Email background

**Tip**: Use the color picker widget to select colors visually!

#### 3. **Company Information**
- **Company Name**: RS Systems
- **Company Address**: Your physical address
- **Support Email**: contact@rssystems.io
- **Support Phone**: +1-800-555-1234
- **Website URL**: https://rssystems.io

#### 4. **Social Media Links** (Optional)
- Facebook URL
- Twitter URL
- LinkedIn URL

#### 5. **Typography**
- **Heading Font**: Arial, Helvetica, sans-serif
- **Body Font**: Arial, Helvetica, sans-serif
- **Button Border Radius**: 4px (default)

#### 6. **Footer Text**
- Custom footer text for all emails
- Default: "� 2025 RS Systems. All rights reserved."

### How to Update:

1. Go to http://localhost:8000/admin/core/emailbrandingconfig/
2. Click on the existing configuration (only 1 allowed - singleton)
3. Make your changes
4. Click "Save"
5. Preview emails to see changes: http://localhost:8000/admin/email-preview/repair_approved/

---

##  User Contact Information

### Customer Contact Info

**Access**: http://localhost:8000/admin/core/customer/

**Fields to Configure**:
- **Company Name**: Customer company name
- **Contact Name**: Primary contact person
- **Email**: customer@example.com
- **Phone Number**: +12025551234 (E.164 format: +[country code][number])
- **Email Verified**:  Check to enable email notifications
- **Phone Verified**:  Check to enable SMS notifications

**E.164 Phone Format Examples**:
- US: `+12025551234`
- UK: `+442071234567`
- Canada: `+14165551234`

### Technician Contact Info

**Access**: http://localhost:8000/admin/technician_portal/technician/

**Fields to Configure**:
- **User**: Link to Django user account
- **Phone Number**: +12025551234 (E.164 format)
- **Email Verified**:  Check to enable email notifications
- **Phone Verified**:  Check to enable SMS notifications
- **Is Manager**:  Check for manager permissions

**User Email**: Set in the linked User account (http://localhost:8000/admin/auth/user/)

---

##  Notification Preferences

### Technician Notification Preferences

**URL**: http://localhost:8000/tech/notifications/preferences/

**Login**: Use technician account credentials

**What Technicians Can Configure**:

#### 1. **Delivery Channels**
-  **Enable Email Notifications**
-  **Enable SMS Notifications**
-  **Enable In-App Notifications**

#### 2. **Category Preferences**
-  Repair Status Updates
-  New Assignments
-  Repair Approvals/Denials
-  Reassignments
-  Batch Operations
-  Reward Notifications

#### 3. **Quiet Hours**
-  Enable Quiet Hours
- **Start Time**: 22:00 (10:00 PM)
- **End Time**: 06:00 (6:00 AM)
- *Notifications during quiet hours are held until morning*

#### 4. **Digest Mode**
-  Enable Daily Digest
- *Batches non-urgent notifications into one daily email at 9 AM*

### Customer Notification Preferences

**Access**: Via customer portal (similar to technician preferences)

**Same configuration options** as technicians, tailored to customer-relevant categories.

---

##  Email Templates Preview

### Preview All Email Templates:

**Login Required**: Staff/Admin access

**Preview URLs**:
- **Repair Approved**: http://localhost:8000/admin/email-preview/repair_approved/
- **Repair Denied**: http://localhost:8000/admin/email-preview/repair_denied/
- **Repair Assigned**: http://localhost:8000/admin/email-preview/repair_assigned/
- **Repair Completed**: http://localhost:8000/admin/email-preview/repair_completed/
- **Batch Approved**: http://localhost:8000/admin/email-preview/batch_approved/

**What You'll See**:
- Full HTML email with your branding
- All colors, logo, and company info applied
- Sample repair data for testing
- Mobile-responsive layout preview

**Use This To**:
- Test branding changes
- Show stakeholders what emails look like
- Verify email template appearance before sending

---

##  AWS Configuration (Production)

### For Real Email/SMS Delivery

**When to Configure**: When ready to send actual emails/SMS (not just testing)

**Documentation**: `docs/development/notifications/setup/AWS_SETUP_GUIDE.md`

### Quick Overview:

#### AWS SES (Email)
1. **Verify Domain** in AWS Console
2. **Create IAM User** with SES permissions
3. **Get SMTP Credentials**
4. **Update .env**:
   ```bash
   AWS_SES_HOST=email-smtp.us-east-1.amazonaws.com
   AWS_SES_PORT=587
   AWS_SES_SMTP_USER=your-smtp-username
   AWS_SES_SMTP_PASSWORD=your-smtp-password
   AWS_SES_REGION=us-east-1
   ```
5. **Update settings.py**: Uncomment SES backend configuration

#### AWS SNS (SMS)
1. **Configure SNS** in AWS Console
2. **Set Spending Limits** (recommended: $50/month)
3. **Create IAM User** with SNS permissions
4. **Update .env**:
   ```bash
   AWS_SNS_REGION=us-east-1
   SMS_ENABLED=true
   ```

**Cost Estimates**:
- Email: ~$0.10 per 1,000 emails
- SMS: ~$0.00645 per SMS (US)

**Full Guide**: See `docs/development/notifications/setup/AWS_SETUP_GUIDE.md`

---

##  System Settings

### Environment Variables

**Key Settings**:

```bash
# Email (SendGrid)
SENDGRID_API_KEY=SG....
DEFAULT_FROM_EMAIL=notifications@rssystems.io

# AWS S3 (media/photos)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=rs-systems-media-20251029

# Django
DJANGO_SETTINGS_MODULE=rs_systems.settings.production  # or development
SECRET_KEY=...
LOCAL_DATABASE_URL=postgresql://...  # dev only
```

### Django Settings Files

**Development**: `rs_systems/settings/development.py`
- Console email backend (prints to terminal)
- SQLite fallback if no `LOCAL_DATABASE_URL`
- `DEBUG=True`

**Production**: `rs_systems/settings/production.py`
- SendGrid email backend
- PostgreSQL required
- `DEBUG=False`, S3 media, hardened security

**Base** (`rs_systems/settings/base.py`): Single source of truth for INSTALLED_APPS, MIDDLEWARE, etc.

---

##  Testing Your Configuration

### Test Email Branding

1. Update branding: http://localhost:8000/admin/core/emailbrandingconfig/
2. Preview template: http://localhost:8000/admin/email-preview/repair_approved/
3. Verify colors, logo, and company info appear correctly

### Test Contact Information

1. Update customer phone/email: http://localhost:8000/admin/core/customer/
2. Check "Email Verified" and "Phone Verified"
3. Create a test repair and approve it
4. Check Django terminal for email output
5. Check Celery worker terminal for delivery logs

### Test Notification Preferences

1. Login as technician: http://localhost:8000/tech/login/
2. Go to preferences: http://localhost:8000/tech/notifications/preferences/
3. Disable email notifications
4. Create/approve a repair assigned to that technician
5. Verify NO email is sent (check delivery logs in admin)
6. Re-enable email notifications
7. Create another repair
8. Verify email IS sent

### Test Quiet Hours

1. Set quiet hours: 22:00 - 06:00 (10 PM - 6 AM)
2. Create notification during quiet hours
3. Verify notification is held (check `next_retry_at` in delivery log)
4. Notification will send after 6 AM

---

##  Monitoring & Logs

### View All Notifications

**URL**: http://localhost:8000/admin/core/notification/

**What You'll See**:
- All notifications created
- Priority level (URGENT, HIGH, MEDIUM, LOW)
- Category (repair_status, assignment, approval, etc.)
- Read/unread status
- Created date

### View Delivery Logs

**URL**: http://localhost:8000/admin/core/notificationdeliverylog/

**What You'll See**:
- All email/SMS delivery attempts
- Status (sent, failed, pending_retry)
- Recipient email/phone
- Error messages (if failed)
- Attempt number
- Next retry time
- Cost (for SMS)

### View Notification History (User View)

**Technician View**: http://localhost:8000/tech/notifications/history/

**What Technicians See**:
- Their notifications
- Read/unread status
- Priority badges
- Filter by category
- Mark as read
- Notification details

---

##  Common Configuration Scenarios

### Scenario 1: Change Company Logo

1. Go to: http://localhost:8000/admin/core/emailbrandingconfig/
2. Upload new logo image
3. Save
4. Preview: http://localhost:8000/admin/email-preview/repair_approved/
5. Logo appears in all future emails

### Scenario 2: Update Company Colors

1. Go to: http://localhost:8000/admin/core/emailbrandingconfig/
2. Click color swatches to open color picker
3. Select new colors (or enter hex codes)
4. Save
5. Preview to see changes

### Scenario 3: Add New Customer

1. Go to: http://localhost:8000/admin/core/customer/
2. Click "Add Customer"
3. Fill in:
   - Company Name
   - Contact Name
   - Email
   - Phone (E.164 format: +12025551234)
   - Check "Email Verified" and "Phone Verified"
4. Save
5. Customer can now receive notifications

### Scenario 4: Disable Notifications for a Technician

**Option A - Admin Method**:
1. Go to: http://localhost:8000/admin/technician_portal/technician/
2. Find technician
3. Uncheck "Email Verified" and "Phone Verified"
4. Save

**Option B - User Method**:
1. Technician logs in: http://localhost:8000/tech/login/
2. Goes to preferences: http://localhost:8000/tech/notifications/preferences/
3. Unchecks "Enable Email Notifications"
4. Unchecks "Enable SMS Notifications"
5. Saves

### Scenario 5: Enable Production Email (AWS SES)

1. Follow AWS SES setup: `docs/development/notifications/setup/AWS_SETUP_GUIDE.md`
2. Get SMTP credentials from AWS
3. Update `.env` with SES credentials
4. Edit `rs_systems/settings.py`:
   - Comment out console backend
   - Uncomment SES SMTP backend
5. Restart Django server
6. Test: `python manage.py test_ses your@email.com`
7. Check your actual inbox for test email

---

##  Related Documentation

- **Main Documentation**: `docs/development/notifications/README.md`
- **Setup & Testing**: `docs/development/notifications/SETUP_AND_TESTING_GUIDE.md`
- **AWS Setup**: `docs/development/notifications/setup/AWS_SETUP_GUIDE.md`
- **Redis Setup**: `docs/development/notifications/setup/REDIS_LOCAL_SETUP.md`
- **Testing Checklist**: `docs/development/notifications/PHASE_6_TESTING_CHECKLIST.md`
- **Simple Testing**: `SIMPLE_TESTING_GUIDE.md`

---

##  Troubleshooting

### Issue: Emails not sending

**Check**:
1. `SENDGRID_API_KEY` set? Run `python manage.py test_ses your@email.com`
2. Email backend configured? (Console backend prints to terminal in dev)
3. Contact verified? (Email Verified checkbox)
4. Preferences enabled? (User notification preferences)
5. Delivery logs: http://localhost:8000/admin/core/notificationdeliverylog/

### Issue: Phone number format error

**Solution**: Use E.164 format
-  Correct: `+12025551234`
-  Wrong: `202-555-1234`
-  Wrong: `(202) 555-1234`
-  Wrong: `2025551234`

### Issue: Branding not updating

**Solution**:
1. Clear browser cache
2. Force refresh (Cmd+Shift+R on Mac, Ctrl+Shift+R on Windows)
3. Check preview URL: http://localhost:8000/admin/email-preview/repair_approved/
4. Verify save was successful in admin

### Issue: Notifications created but not delivered

**Check**:
1. Check delivery logs for errors: http://localhost:8000/admin/core/notificationdeliverylog/
2. Check Django server logs for exceptions
3. Check user preferences (may be disabled)
4. Check quiet hours settings

---

##  Configuration Checklist

Before going to production:

- [ ] Email branding configured with company logo and colors
- [ ] Company information updated (name, address, support contact)
- [ ] All customer emails/phones in E.164 format
- [ ] All technician emails/phones in E.164 format
- [ ] Email/phone verification enabled for all users
- [ ] SendGrid API key configured (`SENDGRID_API_KEY`)
- [ ] `DEFAULT_FROM_EMAIL=notifications@rssystems.io`
- [ ] Notification templates previewed and approved
- [ ] Test emails sent successfully (`python manage.py test_ses`)
- [ ] Quiet hours tested
- [ ] Notification preferences tested
- [ ] Delivery logs monitored for errors

---

**Last Updated**: November 30, 2025
**Version**: 1.0

For questions, see the documentation or check the admin interface!
