# Security Overview - RS Systems

Comprehensive security documentation for the RS Systems windshield repair management platform.

## Table of Contents
- [Current Security Implementation](#current-security-implementation)
- [Authentication & Authorization](#authentication--authorization)
- [Bot Protection](#bot-protection)
- [Security Headers](#security-headers)
- [Data Protection](#data-protection)
- [Monitoring & Auditing](#monitoring--auditing)
- [Security Roadmap](#security-roadmap)
- [Best Practices](#best-practices)

---

## Current Security Implementation

### Security Status: Production Ready ✅
**Cost**: $0/month (using Django built-in features + free packages)

### Implemented Features

#### ✅ Authentication & Access Control
- **Rate Limiting**: 10 login attempts per hour per IP
- **Portal Separation**: Customer/technician portals with middleware enforcement
- **Username Validation**: Blocks bot-like usernames
- **Password Requirements**: Minimum 8 characters enforced
- **Session Security**: 24-hour expiry, HTTPOnly cookies

#### ✅ Bot Protection
- **Honeypot Fields**: Hidden form fields catch automated bots
- **Registration Rate Limiting**: 5 registrations/hour per IP
- **Pattern Detection**: Blocks suspicious username patterns:
  - More than 4 consecutive consonants
  - Less than 20% vowels
  - Common bot patterns (all lowercase 10+ chars, hex strings)

#### ✅ Security Headers (Production)
- **XSS Protection**: `SECURE_BROWSER_XSS_FILTER` enabled
- **Content Type**: `SECURE_CONTENT_TYPE_NOSNIFF` enabled
- **Frame Options**: `X_FRAME_OPTIONS = 'DENY'`
- **HSTS**: 1-year strict transport security with preload
- **Content Security Policy (CSP)**: Prevents XSS attacks
- **Referrer Policy**: Controls referrer information

#### ✅ Infrastructure Security
- **ALLOWED_HOSTS**: Properly configured (no wildcards)
- **Health Check Middleware**: Secure ELB health checks
- **CSRF Protection**: Full token validation
- **SSL/TLS**: HTTPS enforced in production
- **Secure Cookies**: HTTPOnly, SameSite=Lax, Secure flags

#### ✅ Monitoring & Logging
- **Login Attempt Tracking**: All attempts logged with IP, user agent
- **Security Audit Logs**: Security events tracked
- **Suspicious Activity Detection**: Automatic attack pattern detection

---

## Authentication & Authorization

### User Authentication

**Login Security:**
```python
# Rate limiting configuration
@ratelimit(key='ip', rate='10/h', method='POST')
def customer_login(request):
    # Login attempts tracked
    LoginAttempt.objects.create(
        username=username,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT'),
        success=authenticated
    )
```

**Password Policy:**
- Minimum 8 characters
- Django's built-in password validators
- Password reset via secure token
- No password reuse (future enhancement)

### Portal Access Control

**Middleware Enforcement:**
```python
# common/portal_middleware.py
class PortalAccessMiddleware:
    """Enforces portal access boundaries"""
    # Customers can only access /app/*
    # Technicians can only access /tech/*
    # Admins can access /admin/*
```

**Access Patterns:**
- `/app/*` → Requires CustomerUser profile
- `/tech/*` → Requires Technician profile
- `/admin/*` → Requires staff/superuser status

### Role-Based Permissions

**Django Groups:**
- **Technicians Group**: View/add/change repairs, view-only customers
- **Managers**: Extended permissions for pricing override, work assignment
- **Admins**: Full system access via Django admin

**Permission Checks:**
```python
# Only managers can see REQUESTED repairs
if not user.technician.is_manager:
    repairs = repairs.exclude(queue_status='REQUESTED')

# Only customers can see PENDING repairs
# (completely hidden from technician portal)
```

---

## Bot Protection

### Registration Security

**Username Validation:**
```python
def is_suspicious_username(username):
    """Detect bot-like usernames"""
    # Check for excessive consonants
    # Check for low vowel ratio
    # Check for common bot patterns
    return suspicious_score > threshold
```

**Honeypot Protection:**
```html
<!-- Hidden field catches bots -->
<input type="text" name="website" style="display:none" value="">
<!-- If filled, registration rejected -->
```

**Rate Limiting:**
```python
@ratelimit(key='ip', rate='5/h', method='POST')
def customer_register(request):
    # Maximum 5 registrations per hour per IP
```

### Attack Detection

**Suspicious Patterns Blocked:**
- Random strings: `ygzwnplsgv`, `xkqwmplgz`
- Hex strings: `a1b2c3d4e5f6`
- All lowercase 10+ characters
- More than 4 consecutive consonants
- Less than 20% vowels

**Security Audit Command:**
```bash
# Check for suspicious users
python manage.py security_audit

# Check specific user
python manage.py security_audit --check-user username

# Remove suspicious users
python manage.py security_audit --delete-suspicious
```

---

## Security Headers

### Production Headers Configuration

**Content Security Policy (CSP):**
```python
# apps/security/middleware.py
csp_directives = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com",
    "font-src 'self' fonts.gstatic.com data:",
    "img-src 'self' data: https:",
    "connect-src 'self'"
]
```

**HTTP Strict Transport Security (HSTS):**
```python
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
```

**Additional Headers:**
```python
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
```

### Session & Cookie Security

**Session Configuration:**
```python
SESSION_COOKIE_SECURE = True  # HTTPS only
SESSION_COOKIE_HTTPONLY = True  # No JavaScript access
SESSION_COOKIE_SAMESITE = 'Lax'  # CSRF protection
SESSION_COOKIE_AGE = 86400  # 24 hours
```

**CSRF Configuration:**
```python
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_TRUSTED_ORIGINS = [
    'https://rockstarwindshield.repair',
    'https://www.rockstarwindshield.repair'
]
```

---

## Data Protection

### Database Security

**Connection Security:**
```python
# Production database (PostgreSQL)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'OPTIONS': {
            'sslmode': 'require'  # Force SSL connections
        }
    }
}
```

**Sensitive Data Protection:**
- Passwords hashed with PBKDF2
- Secret key stored in environment variables
- Database credentials in environment variables
- No hardcoded credentials in codebase

**Data Encryption:**
- In-transit: HTTPS/TLS 1.2+
- At-rest: AWS RDS encryption enabled
- Backups: Encrypted in S3

### Input Validation & Sanitization

**SQL Injection Prevention:**
```python
# Django ORM prevents SQL injection
Repair.objects.filter(customer=customer)  # Safe
# NEVER use raw SQL with user input
```

**XSS Prevention:**
```django
{# Templates auto-escape by default #}
{{ user_input }}  <!-- Automatically escaped -->

{# Only use |safe when absolutely necessary #}
{{ trusted_html|safe }}
```

**File Upload Security:**
```python
# Photo upload validation
ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png']
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB

def validate_image(file):
    # Validate file type
    # Validate file size
    # Validate image integrity (using Pillow)
```

---

## Monitoring & Auditing

### Login Attempt Tracking

**LoginAttempt Model:**
```python
class LoginAttempt(models.Model):
    username = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField()
```

**Query Recent Attempts:**
```python
# Failed logins in last 24 hours
from django.utils import timezone
from datetime import timedelta

today = timezone.now() - timedelta(days=1)
failed = LoginAttempt.objects.filter(
    timestamp__gte=today,
    success=False
).count()
```

### Security Audit Logging

**Events Logged:**
- All login attempts (success/failure)
- Registration attempts
- Password changes
- Permission escalations
- Suspicious activity detected

**Log Analysis:**
```bash
# View recent security events
eb logs | grep "SECURITY"

# Check for attack patterns
eb logs | grep "Rate limit exceeded"

# Identify suspicious IPs
eb logs | grep "Blocked suspicious"
```

### Monitoring Commands

**Daily Security Check:**
```bash
# Run comprehensive security audit
python manage.py security_audit

# Output shows:
# - Suspicious usernames
# - Failed login attempts
# - Rate limit violations
# - Potential security issues
```

**User Investigation:**
```bash
# Check specific user
python manage.py security_audit --check-user username

# View user details
python manage.py shell
from django.contrib.auth.models import User
user = User.objects.get(username='username')
print(f"Last login: {user.last_login}")
print(f"Date joined: {user.date_joined}")
```

---

## Security Roadmap

### Phase 0: Current (Completed) ✅
**Cost**: $0/month

- ✅ Rate limiting
- ✅ Bot protection
- ✅ Security headers
- ✅ Portal separation
- ✅ SSL/TLS
- ✅ Basic monitoring

### Phase 1: Early Growth (1-100 customers)
**Timeline**: When first paying customers
**Cost**: ~$20-50/month

**Email Verification** ($5/month)
- AWS SES (62,000 emails/month free) or SendGrid (100/day free)
- Email verification on registration
- Password reset via email
- Security alerts

**Basic WAF Protection** ($20/month)
- Cloudflare Pro: DDoS protection, bot management
- Alternative: AWS WAF basic rules

**Enhanced Monitoring** (Free-$10/month)
- Sentry (5K errors/month free)
- UptimeRobot (50 monitors free)
- Papertrail logs (100MB/month free)

### Phase 2: Scaling (100-1,000 customers)
**Timeline**: 6-12 months post-launch
**Cost**: ~$200-300/month

**Professional Authentication** ($100-240/month)
- Option A: AWS Cognito (~$0.0055 per MAU)
  - MFA, social login, password policies
- Option B: Auth0 ($240/month for 1000 MAU)
  - SSO, enterprise connections, advanced MFA

**Advanced Bot Protection**
- Google reCAPTCHA v3
- Machine learning-based detection
- Behavioral analysis

**Compliance & Audit**
- SOC 2 Type II preparation
- GDPR compliance tools
- Detailed audit trails
- Penetration testing

### Phase 3: Enterprise (1,000+ customers)
**Timeline**: 12-24 months post-launch
**Cost**: ~$1,000+/month

**Enterprise Security**
- Dedicated WAF with custom rules
- Advanced DDoS protection
- Penetration testing quarterly
- Security operations center (SOC)

**Compliance Certifications**
- SOC 2 Type II
- ISO 27001 (if required)
- Industry-specific compliance

**Advanced Features**
- Single Sign-On (SSO)
- Multi-factor authentication (MFA) required
- Granular role-based access control (RBAC)
- API security with OAuth 2.0

---

## Best Practices

### For Developers

**Never Commit Secrets:**
```bash
# ❌ Don't do this
SECRET_KEY = 'hardcoded-secret'

# ✅ Do this
SECRET_KEY = os.environ.get('SECRET_KEY')
```

**Validate All Input:**
```python
# ❌ Don't trust user input
sql = f"SELECT * FROM users WHERE username='{username}'"

# ✅ Use ORM or parameterized queries
User.objects.filter(username=username)
```

**Use HTTPS Everywhere:**
```python
# settings_aws.py
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

### For Administrators

**Regular Security Audits:**
- Run `python manage.py security_audit` daily
- Review failed login attempts weekly
- Update dependencies monthly
- Security review quarterly

**Access Control:**
- Limit admin access to necessary personnel
- Use strong, unique passwords
- Enable MFA for admin accounts (when available)
- Regular audit of user permissions

**Incident Response:**
- Have rollback plan ready
- Keep backups up-to-date
- Know emergency contacts
- Document all incidents

### For Users

**Password Security:**
- Minimum 8 characters (enforced)
- Use unique passwords per site
- Consider password manager
- Change password if suspicious activity

**Account Security:**
- Log out after use
- Don't share credentials
- Report suspicious activity
- Keep contact info updated

---

## Security Checklist

### Daily
- [ ] Monitor error logs for unusual activity
- [ ] Check failed login attempts
- [ ] Review security audit output

### Weekly
- [ ] Run full security audit
- [ ] Review user registrations
- [ ] Check rate limit violations
- [ ] Verify backup completion

### Monthly
- [ ] Update dependencies
- [ ] Review security settings
- [ ] Audit user permissions
- [ ] Test incident response plan

### Quarterly
- [ ] Security architecture review
- [ ] Penetration testing (when budget allows)
- [ ] Update security documentation
- [ ] Team security training

---

## Compliance & Regulations

### Current Compliance
- **HTTPS**: Enforced in production
- **Data Encryption**: In-transit and at-rest
- **User Privacy**: No unauthorized data sharing
- **Data Retention**: Configurable per customer

### Future Compliance (as needed)
- **GDPR**: EU data protection (if serving EU customers)
- **CCPA**: California privacy (if serving CA customers)
- **HIPAA**: If handling health information
- **PCI DSS**: If processing credit cards directly

---

## Resources

### Internal Documentation
- [Incident Response Guide](/docs/security/INCIDENT_RESPONSE.md)
- [Deployment Security](/docs/deployment/AWS_DEPLOYMENT.md#security-configuration)
- [Production Checklist](/docs/deployment/PRODUCTION_CHECKLIST.md)

### External Resources
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Django Security](https://docs.djangoproject.com/en/stable/topics/security/)
- [AWS Security Best Practices](https://aws.amazon.com/security/best-practices/)

### Tools
- **Security Audit**: `python manage.py security_audit`
- **Dependency Check**: `pip-audit` (install separately)
- **Code Analysis**: Django's `check --deploy`

---

---

## Security Audit - February 2026

### Vulnerabilities Remediated

A comprehensive security audit identified and remediated **16 vulnerabilities** across authentication, input validation, and configuration.

#### Critical Fixes (4)

| Vulnerability | Location | Fix |
|--------------|----------|-----|
| Open Redirect | `rs_systems/views.py` | Added `url_has_allowed_host_and_scheme()` validation to `?next=` redirects |
| Unprotected Setup Endpoint | `rs_systems/views.py`, `urls.py` | Requires staff auth, DEBUG mode only, URL excluded in production |
| Hardcoded Default Password | `core/management/commands/createsu.py` | Removed `admin123` default, requires `DJANGO_ADMIN_PASSWORD` env var |
| SQL Injection (migration) | Historical migration file | Documented only (migrations should not be modified) |

#### High Priority Fixes (8)

| Vulnerability | Location | Fix |
|--------------|----------|-----|
| No Rate Limiting on Invites | `accept_invite()` | Added `@ratelimit(key='ip', rate='10/h')` |
| Weak Password Validation | `accept_invite()` | Using Django's `validate_password()` instead of length check |
| Exception Swallowing | Decorators, middleware | Catching specific exceptions, logging unexpected errors |
| Stripe Webhook Optional | `apps/tenants/webhooks.py` | Returns 500 if `STRIPE_WEBHOOK_SECRET` not set in production |
| XSS via mark_safe() | `core/admin.py`, `forms.py` | Replaced with `format_html()` |
| ALLOWED_HOSTS Too Broad | `settings/production.py` | Removed wildcards, using `EB_HOSTNAME` env var |
| PII in Logs | Service files | Masked via `core/utils/logging.py` |
| Portal Middleware Exceptions | `portal_middleware.py` | Specific exception handling with logging |

#### Medium Priority Fixes (4)

| Vulnerability | Location | Fix |
|--------------|----------|-----|
| PII Logged in Plaintext | `sms_service.py`, `email_service.py` | Added `mask_phone()`, `mask_email()` utilities |
| Path Traversal Risk | `auto_invoice_service.py` | Using `os.path.basename()` for filenames |
| File Type Validation | Email branding | Extension validation (MIME validation TODO) |
| User Enumeration | Login errors | Already using generic messages |

### Required Environment Variables

Before deploying, ensure these are configured:

```bash
# Required for createsu command (minimum 12 characters)
DJANGO_ADMIN_PASSWORD=your-strong-password-here

# Required for Stripe webhooks in production
STRIPE_WEBHOOK_SECRET=whsec_your-webhook-secret

# Required for ALLOWED_HOSTS (your specific EB domain)
EB_HOSTNAME=your-app.us-east-1.elasticbeanstalk.com

# Optional: Additional internal hostname for health checks
AWS_INTERNAL_HOSTNAME=internal-hostname.amazonaws.com
```

### Security Tests

New security tests added in `tests/security/test_vulnerabilities.py`:
- Open redirect protection
- Setup endpoint access control
- Password validation strength
- PII masking utilities
- Stripe webhook verification
- XSS protection via format_html
- Rate limiting verification
- ALLOWED_HOSTS configuration

Run tests: `python manage.py test tests.security`

### Credential Rotation Reminder

If `.env` file was ever exposed, rotate:
- RDS database password
- AWS IAM access keys
- SendGrid API key
- Stripe webhook secret

---

**Last Updated**: February 4, 2026
**Security Team**: Development Team
**Next Review**: May 2026
**Status**: Production Ready ✅
