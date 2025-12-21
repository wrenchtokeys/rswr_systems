# Security Policy

## Overview

This repository contains production-ready code for a Django-based fleet management system. All sensitive credentials and secrets have been removed or sanitized for public distribution.

## Security Model

### Environment-Based Security

This project uses **environment variables** for all sensitive configuration:

- **Database credentials**: `DB_PASSWORD`, `DB_HOST`, `DB_USER`
- **API keys**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `SENDGRID_API_KEY`
- **Secret keys**: `SECRET_KEY`, `ADMIN_PASSWORD`
- **SSL certificates**: `SSL_CERTIFICATE_ARN`

**IMPORTANT**: Never commit `.env` files or any files containing real credentials to version control.

### What's Been Sanitized

The following information has been replaced with placeholders in this repository:

✅ AWS Account IDs → `YOUR_AWS_ACCOUNT_ID`
✅ RDS Database Endpoints → `your-database-instance.region.rds.amazonaws.com`
✅ SSL Certificate ARNs → `arn:aws:acm:REGION:YOUR_AWS_ACCOUNT_ID:certificate/YOUR_CERTIFICATE_ID`
✅ Production Domain Names → `yourdomain.com`
✅ Elastic Beanstalk URLs → `your-app-name.region.elasticbeanstalk.com`
✅ Hardcoded Passwords → Environment variable references

### What's Safe in This Repository

The following are **intentionally public** and pose no security risk:

- Application code structure and logic
- Database schema and migrations
- Frontend templates and JavaScript
- Test files with dummy credentials (e.g., `password='testpass'`)
- Configuration file templates (`.env.example`)
- Documentation and guides
- AWS service configurations (without account-specific details)

## Reporting a Security Vulnerability

If you discover a security vulnerability in this codebase, please report it responsibly:

**Please DO NOT:**
- Open a public GitHub issue for security vulnerabilities
- Disclose the vulnerability publicly before it's been addressed

**Please DO:**
- Email security concerns to: [your-security-email@example.com]
- Provide detailed information about the vulnerability
- Allow reasonable time for the issue to be addressed

### What Constitutes a Security Issue

**Valid Security Reports:**
- Authentication bypass vulnerabilities
- SQL injection, XSS, or CSRF vulnerabilities not already mitigated
- Exposure of sensitive data or credentials
- Remote code execution vulnerabilities
- Authorization flaws allowing privilege escalation

**Not Security Issues:**
- Missing security headers (already implemented in `apps/security/middleware.py`)
- Generic dependency updates without active exploits
- Theoretical issues without proof of concept
- Issues requiring physical access or social engineering

## Security Features

### Implemented Protections

This application includes enterprise-grade security features:

- ✅ **Content Security Policy (CSP)** - XSS prevention
- ✅ **HTTP Strict Transport Security (HSTS)** - Force HTTPS
- ✅ **CSRF Protection** - Cross-site request forgery prevention
- ✅ **SQL Injection Prevention** - Django ORM parameterized queries
- ✅ **Session Security** - HTTPOnly and Secure cookies
- ✅ **Rate Limiting** - Login attempt throttling (10/hour per IP)
- ✅ **Bot Protection** - Honeypot fields and validation
- ✅ **Password Security** - Django's PBKDF2 hashing
- ✅ **Input Validation** - Server-side form validation
- ✅ **Portal Isolation** - Middleware-enforced access control

### Security Middleware

See `apps/security/middleware.py` for implementation details of security headers.

### Authentication & Authorization

- **Django's built-in authentication system** with secure password hashing
- **Group-based permissions** for technician and customer roles
- **Portal-specific access control** via `PortalAccessMiddleware`
- **Session management** with secure cookie settings in production

## Deployment Security Checklist

Before deploying to production, ensure:

- [ ] All environment variables are set securely (never committed to repo)
- [ ] `DEBUG = False` in production settings
- [ ] `SECRET_KEY` is unique and randomly generated
- [ ] Database uses strong passwords and encryption at rest
- [ ] SSL/TLS certificates are valid and properly configured
- [ ] Security groups restrict database access to application servers only
- [ ] AWS IAM roles follow principle of least privilege
- [ ] Backup systems are tested and functional
- [ ] CloudWatch alarms are configured for monitoring
- [ ] All dependencies are up to date
- [ ] Security headers are enabled in production

## AWS Security Best Practices

### Database Security (RDS)

- ✅ Encryption at rest enabled (AWS KMS)
- ✅ No public access (security group restricts to EB instances only)
- ✅ Automated backups with 30-day retention
- ✅ Strong password requirements
- ⚠️ Ensure security groups are properly configured in your deployment

### S3 Storage Security

- ✅ Bucket versioning enabled for data recovery
- ✅ Lifecycle policies to manage old versions
- ✅ IAM roles for application access (no hardcoded keys)
- ⚠️ Review bucket policies to prevent public access to sensitive files

### Elastic Beanstalk Security

- ✅ HTTPS enforced for all production traffic
- ✅ Security headers configured via middleware
- ✅ Environment variables for secrets management
- ⚠️ Regularly update platform versions

## Dependency Management

### Keeping Dependencies Secure

```bash
# Check for security vulnerabilities
pip install safety
safety check

# Update dependencies
pip list --outdated
pip install -U package-name

# Update requirements.txt
pip freeze > requirements.txt
```

### Known Dependencies

See `requirements.txt` for full dependency list. Key security-relevant packages:

- **Django**: Web framework with built-in security features
- **psycopg2**: PostgreSQL adapter (production database)
- **gunicorn**: Production WSGI server
- **boto3**: AWS SDK for S3/RDS integration
- **Pillow**: Image processing (ensure latest version for security patches)

## License and Disclaimer

This software is provided "as is" without warranty of any kind. Users are responsible for:

- Securing their own deployments
- Managing their own credentials and secrets
- Implementing additional security measures as needed for their use case
- Compliance with applicable laws and regulations

## Security Updates

This section will be updated with security-related changes:

### 2025-12-21
- Initial public release
- All sensitive credentials sanitized
- Security documentation added
- Environment variable-based configuration implemented

---

**Last Updated**: December 21, 2025
**Security Contact**: [your-security-email@example.com]
