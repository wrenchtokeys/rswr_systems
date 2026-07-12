# Security Incident Response Guide

Emergency procedures and quick reference for security incidents in RS Systems.

## 🚨 Emergency Response - Quick Actions

### Suspected Security Breach
```bash
# 1. IMMEDIATE: Enable maintenance mode
eb setenv MAINTENANCE_MODE=true

# 2. Capture current state
eb logs --all > incident_logs_$(date +%Y%m%d_%H%M%S).txt

# 3. Create emergency backup
eb ssh
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > emergency_backup.sql
aws s3 cp emergency_backup.sql s3://rs-systems-backups-20250823/emergency/

# 4. Contact emergency personnel
# See Emergency Contacts section below
```

---

## Incident Types & Responses

### 1. Suspicious User Detected

**Symptoms:**
- Bot-like username (e.g., `ygzwnplsgv`, `xkqwmplgz`)
- Multiple failed login attempts
- Unusual registration patterns

**Immediate Actions:**
```bash
# Check the user
python manage.py security_audit --check-user suspicious_username

# If confirmed malicious, investigate
python manage.py shell
from django.contrib.auth.models import User
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair

user = User.objects.filter(username='suspicious_username').first()
if user:
    print(f"Joined: {user.date_joined}")
    print(f"Last login: {user.last_login}")
    print(f"Email: {user.email}")

    # Check for related data
    try:
        customer_user = user.customeruser
        print(f"Customer: {customer_user.customer.name}")
        repairs = Repair.objects.filter(customer=customer_user.customer)
        print(f"Repairs created: {repairs.count()}")
    except:
        print("No customer profile")
```

**If No Legitimate Activity:**
```python
# Delete suspicious user
from django.contrib.auth.models import User

# Backup user data first (if any)
user = User.objects.get(username='suspicious_username')
print(f"Deleting user: {user.username}, Email: {user.email}")

# Delete
user.delete()
print("User deleted successfully")
```

**Documentation:**
```markdown
## Incident Report

**Date**: [YYYY-MM-DD HH:MM UTC]
**Incident Type**: Suspicious User
**Username**: suspicious_username
**IP Address**: [from LoginAttempt logs]
**Actions Taken**:
1. User investigated
2. No legitimate activity found
3. User deleted
4. [Any other actions]

**Impact**: None / Minimal / [Description]
**Resolution**: User removed, monitoring continued
```

---

### 2. Rate Limit Attack (Brute Force)

**Symptoms:**
- Many failed login attempts from same IP
- Rate limit errors in logs
- High server load

**Immediate Actions:**
```bash
# 1. Check recent failed logins
python manage.py shell
from apps.security.models import LoginAttempt
from django.utils import timezone
from datetime import timedelta

recent = timezone.now() - timedelta(hours=1)
failed = LoginAttempt.objects.filter(
    timestamp__gte=recent,
    success=False
).values('ip_address').annotate(count=Count('id')).order_by('-count')

for attempt in failed[:10]:
    print(f"IP: {attempt['ip_address']} - Failed attempts: {attempt['count']}")
```

**Block Attacking IP (Temporary):**
```python
# In Django shell
from django.core.cache import cache

# Block IP for 24 hours
attacker_ip = '1.2.3.4'
cache.set(f'blocked_ip_{attacker_ip}', True, 86400)
```

**Permanent IP Block:**
```python
# rs_systems/settings/production.py or environment variable
# Add to configuration
BLOCKED_IPS = [
    '1.2.3.4',
    '5.6.7.8',
]

# In middleware, check:
if get_client_ip(request) in settings.BLOCKED_IPS:
    return HttpResponseForbidden("Access denied")
```

**AWS WAF Rule (If Configured):**
```bash
# Create IP set for blocking
aws wafv2 create-ip-set \
  --name BlockedIPs \
  --scope REGIONAL \
  --ip-address-version IPV4 \
  --addresses 1.2.3.4/32

# Associate with Web ACL (if WAF configured)
```

---

### 3. Mass Bot Registration

**Symptoms:**
- Multiple new users with suspicious usernames
- High registration rate
- All from similar IPs or user agents

**Immediate Actions:**
```bash
# 1. Identify suspicious registrations
python manage.py security_audit --verbose

# 2. Temporarily disable registration
# Add to customer_portal/views.py customer_register function:
# return HttpResponse("Registration temporarily disabled for maintenance", status=503)
```

**Clean Up Bot Accounts:**
```bash
# Use security audit command
python manage.py security_audit --delete-suspicious

# Or manual cleanup
python manage.py shell
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

# Find users registered in last hour with no email
recent = timezone.now() - timedelta(hours=1)
suspicious = User.objects.filter(
    date_joined__gte=recent,
    email=''
).exclude(username__startswith='tech')

print(f"Found {suspicious.count()} suspicious users")
for user in suspicious:
    print(f"- {user.username} (joined {user.date_joined})")

# Delete if confirmed
# suspicious.delete()
```

**Re-Enable Registration:**
```python
# Remove temporary disable from views.py
# Ensure bot protection is active:
# - Rate limiting enabled
# - Honeypot fields in place
# - Username validation active
```

---

### 4. Database Compromise Suspected

**Symptoms:**
- Unauthorized data access logs
- Unexpected database queries
- Data modification without user action

**IMMEDIATE ACTIONS:**
```bash
# 1. STOP EVERYTHING
eb setenv MAINTENANCE_MODE=true

# 2. Emergency backup
eb ssh
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > critical_backup_$(date +%Y%m%d_%H%M%S).sql
aws s3 cp critical_backup_*.sql s3://rs-systems-backups-20250823/emergency/

# 3. Rotate database credentials
aws rds modify-db-instance \
  --db-instance-identifier rswr-db-1 \
  --master-user-password NEW_SECURE_PASSWORD

# 4. Update application
eb setenv DB_PASSWORD=NEW_SECURE_PASSWORD

# 5. Restart application
eb restart
```

**Investigation:**
```bash
# Check database logs
aws rds download-db-log-file-portion \
  --db-instance-identifier rswr-db-1 \
  --log-file-name error/postgresql.log

# Check for suspicious queries
# Review connection logs
# Identify unauthorized access
```

**Containment:**
```bash
# Restrict database access
# Update RDS security group
# Only allow EB environment security group
# No public access

# Force logout all users
python manage.py shell
from django.contrib.sessions.models import Session
Session.objects.all().delete()
```

---

### 5. XSS Attack Detected

**Symptoms:**
- Malicious JavaScript in user-submitted content
- Reports of unexpected browser behavior
- Content serving unauthorized scripts

**Immediate Actions:**
```bash
# 1. Identify the attack vector
# Check recent form submissions
python manage.py shell
from apps.technician_portal.models import Repair

# Look for script tags in notes fields
suspicious = Repair.objects.filter(
    Q(technician_notes__icontains='<script') |
    Q(customer_notes__icontains='<script')
)

for repair in suspicious:
    print(f"Repair {repair.id}: {repair.technician_notes[:100]}")
```

**Sanitize Data:**
```python
from django.utils.html import escape

# Clean up malicious content
for repair in suspicious:
    if '<script' in repair.technician_notes:
        repair.technician_notes = escape(repair.technician_notes)
    if '<script' in repair.customer_notes:
        repair.customer_notes = escape(repair.customer_notes)
    repair.save()
```

**Verify CSP Headers:**
```bash
# Test CSP is active
curl -I https://rssystems.io | grep Content-Security-Policy

# Should see:
# Content-Security-Policy: default-src 'self'; ...
```

**Fix Template Escaping:**
```django
{# Ensure auto-escaping is on (default) #}
{{ user_input }}  <!-- Automatically escaped -->

{# Audit all uses of |safe filter #}
{# Remove |safe unless absolutely necessary #}
{{ potentially_unsafe_html|safe }}  <!-- AUDIT THIS -->
```

---

### 6. DDoS Attack

**Symptoms:**
- High traffic volume
- Server unresponsive
- Legitimate users cannot access site

**Immediate Actions:**
```bash
# 1. Check CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/ElasticBeanstalk \
  --metric-name RequestCount \
  --dimensions Name=EnvironmentName,Value=rs-systems-prod \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum

# 2. Scale up immediately
eb scale 3  # Increase instance count

# 3. Enable AWS Shield (if not already)
# Free tier automatically active
```

**Cloudflare Protection (If Configured):**
```bash
# Enable "I'm Under Attack" mode
# Via Cloudflare dashboard:
# 1. Go to Security → Settings
# 2. Set Security Level to "I'm Under Attack"
# 3. Visitor gets challenge before accessing site
```

**Application-Level Protection:**
```python
# Temporarily increase rate limits
# In rs_systems/settings/production.py
RATELIMIT_ENABLE = False  # Temporarily disable for legitimate traffic

# Or increase limits
# @ratelimit(key='ip', rate='100/h')  # Increase from 10/h
```

---

## Investigation Tools

### Log Analysis

**Application Logs:**
```bash
# View recent errors
eb logs | grep ERROR

# Search for specific IP
eb logs | grep "1.2.3.4"

# Find security events
eb logs | grep "SECURITY"

# Download all logs
eb logs --all > full_logs.txt
```

**Database Logs:**
```bash
# Download PostgreSQL logs
aws rds download-db-log-file-portion \
  --db-instance-identifier rswr-db-1 \
  --log-file-name error/postgresql.log \
  --output text > db_logs.txt
```

**Access Logs (If ALB configured):**
```bash
# Download access logs from S3
aws s3 sync s3://alb-logs-bucket/prefix/ ./alb_logs/

# Analyze with awk
awk '{print $3}' alb_logs/*.log | sort | uniq -c | sort -rn | head -20
```

### User Investigation

**Full User Audit:**
```python
from django.contrib.auth.models import User
from apps.security.models import LoginAttempt
from apps.customer_portal.models import CustomerUser

username = 'suspicious_user'
user = User.objects.filter(username=username).first()

if user:
    print(f"Username: {user.username}")
    print(f"Email: {user.email}")
    print(f"Joined: {user.date_joined}")
    print(f"Last login: {user.last_login}")
    print(f"Is staff: {user.is_staff}")
    print(f"Is active: {user.is_active}")

    # Login history
    attempts = LoginAttempt.objects.filter(username=username).order_by('-timestamp')[:10]
    for attempt in attempts:
        print(f"  {attempt.timestamp}: {attempt.ip_address} - {'Success' if attempt.success else 'Failed'}")

    # Related data
    try:
        customer_user = user.customeruser
        print(f"Customer: {customer_user.customer.name}")
    except:
        print("No customer profile")
```

### Network Analysis

**IP Geolocation (Free API):**
```python
import requests

ip = '1.2.3.4'
response = requests.get(f'https://ipapi.co/{ip}/json/')
data = response.json()

print(f"Country: {data.get('country_name')}")
print(f"City: {data.get('city')}")
print(f"ISP: {data.get('org')}")
```

**Suspicious IP Patterns:**
```python
from collections import Counter
from apps.security.models import LoginAttempt

# Find IPs with most failed attempts
failed_attempts = LoginAttempt.objects.filter(success=False)
ip_counts = Counter([attempt.ip_address for attempt in failed_attempts])

print("Top 10 IPs with failed logins:")
for ip, count in ip_counts.most_common(10):
    print(f"{ip}: {count} failures")
```

---

## Communication Plan

### Internal Communication

**Immediate Notification (Critical):**
```
TO: Development Team, Management
SUBJECT: URGENT - Security Incident Detected

A security incident has been detected and response is in progress.

Incident Type: [Type]
Detected At: [Time]
Current Status: [Investigating/Contained/Resolved]
Impact: [Description]
Actions Taken: [List]

Updates will be provided every 30 minutes or as situation changes.

Do not make any system changes without coordination.
```

**Status Update (Every 30 min during active incident):**
```
TO: Stakeholders
SUBJECT: Security Incident Update #[N]

Update Time: [Time]
Status: [Status]
Progress: [Description]
Next Steps: [List]
Estimated Resolution: [Time or "Unknown"]
```

**Resolution Notification:**
```
TO: All Stakeholders
SUBJECT: Security Incident Resolved

The security incident detected at [Time] has been resolved.

Incident Summary:
- Type: [Type]
- Duration: [Duration]
- Impact: [Description]
- Root Cause: [Summary]

Actions Taken:
- [Action 1]
- [Action 2]
- [Action 3]

Preventive Measures:
- [Measure 1]
- [Measure 2]

Full incident report will be available within 48 hours.

Normal operations have resumed.
```

### User Communication (If Needed)

**Data Breach Notification:**
```
TO: Affected Users
SUBJECT: Important Security Notice

We are writing to inform you of a security incident that may have affected your account.

What Happened: [Description]
What Information: [Type of data]
When: [Date/Time range]

What We've Done:
- [Action 1]
- [Action 2]

What You Should Do:
- Change your password immediately
- Review recent account activity
- [Other actions]

We take security seriously and have implemented additional measures to prevent similar incidents.

For questions, contact: [Email/Phone]
```

---

## Recovery Procedures

### After Security Incident

**1. System Restoration:**
```bash
# If system was compromised
# 1. Deploy from clean source
git checkout [last-known-good-commit]
eb deploy

# 2. Restore database from pre-incident backup
# See PRODUCTION_CHECKLIST.md for restore procedure

# 3. Verify integrity
python manage.py check --deploy
python manage.py test

# 4. Monitor closely
eb logs --stream
```

**2. Credential Rotation:**
```bash
# Rotate all credentials
# - Django SECRET_KEY
# - Database passwords
# - AWS access keys
# - API keys

# Update environment variables
eb setenv SECRET_KEY=new_key DB_PASSWORD=new_password

# Restart application
eb restart
```

**3. Security Hardening:**
```python
# Review and tighten security settings
# - Update dependencies
# - Review user permissions
# - Audit code for vulnerabilities
# - Enable additional security features
```

**4. Monitoring Enhancement:**
```bash
# Increase monitoring
# - More frequent log reviews
# - Lower alert thresholds
# - Additional security checks
# - Enhanced rate limiting
```

---

## Post-Incident Report Template

```markdown
# Security Incident Report

**Incident ID**: [YYYY-MM-DD]-[NN]
**Date**: [Date]
**Severity**: Critical / High / Medium / Low

## Executive Summary
[Brief 2-3 sentence overview]

## Incident Details

**Detection Time**: [Time]
**Response Start**: [Time]
**Containment**: [Time]
**Resolution**: [Time]
**Total Duration**: [Duration]

**Type**: [Type of incident]
**Attack Vector**: [How it occurred]
**Affected Systems**: [List]

## Timeline

- **[Time]**: Initial detection
- **[Time]**: Investigation begun
- **[Time]**: Incident confirmed
- **[Time]**: Containment actions started
- **[Time]**: Threat contained
- **[Time]**: Recovery begun
- **[Time]**: System restored
- **[Time]**: Incident closed

## Impact Assessment

**Users Affected**: [Number or "None"]
**Data Exposed**: [Description or "None"]
**Downtime**: [Duration or "None"]
**Financial Impact**: [Estimate]

## Root Cause Analysis

**Primary Cause**: [Description]
**Contributing Factors**: [List]
**How It Happened**: [Detailed explanation]

## Response Actions

### Immediate Actions
1. [Action with timestamp]
2. [Action with timestamp]

### Containment Actions
1. [Action with timestamp]
2. [Action with timestamp]

### Recovery Actions
1. [Action with timestamp]
2. [Action with timestamp]

## Lessons Learned

**What Went Well**:
- [Item 1]
- [Item 2]

**What Could Be Improved**:
- [Item 1]
- [Item 2]

## Preventive Measures

**Short-term (Immediate)**:
- [ ] [Action 1]
- [ ] [Action 2]

**Medium-term (This Quarter)**:
- [ ] [Action 1]
- [ ] [Action 2]

**Long-term (Strategic)**:
- [ ] [Action 1]
- [ ] [Action 2]

## Recommendations

1. [Recommendation 1]
2. [Recommendation 2]
3. [Recommendation 3]

---

**Report Prepared By**: [Name]
**Report Approved By**: [Name]
**Distribution**: [List]
```

---

## Emergency Contacts

### Internal Team
- **Development Lead**: [Name] - [Email] - [Phone]
- **DevOps**: [Name] - [Email] - [Phone]
- **Management**: [Name] - [Email] - [Phone]

### External Support
- **AWS Support**: Via AWS Console (Priority based on support plan)
- **Cloudflare Support**: [If configured]
- **Security Consultant**: [If contracted]

### Escalation Path
1. Development team (responds within 15 min)
2. Management (if issue not resolved in 1 hour)
3. External support (if needed)

---

## Quick Reference Commands

```bash
# Enable maintenance mode
eb setenv MAINTENANCE_MODE=true

# Emergency backup
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > emergency_backup.sql

# Download logs
eb logs --all > incident_logs.txt

# Check security audit
python manage.py security_audit

# Block IP (temporary)
# In Django shell:
from django.core.cache import cache
cache.set('blocked_ip_1.2.3.4', True, 86400)

# Force logout all users
from django.contrib.sessions.models import Session
Session.objects.all().delete()

# Rotate credentials
eb setenv SECRET_KEY=new_key DB_PASSWORD=new_password

# Restart application
eb restart

# Disable maintenance mode
eb setenv MAINTENANCE_MODE=false
```

---

**Document Version**: 1.0
**Last Updated**: October 21, 2025
**Next Review**: January 2026
**Emergency Hotline**: [To be configured]

---

**Remember**: Stay calm, document everything, communicate clearly, and follow the procedures.
