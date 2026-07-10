# AWS Production Deployment Guide

Complete guide for deploying RS Systems to AWS Elastic Beanstalk with PostgreSQL, SSL/TLS, and production-grade security.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Database Configuration](#database-configuration)
- [SSL & Domain Setup](#ssl--domain-setup)
- [Security Configuration](#security-configuration)
- [Deployment Process](#deployment-process)
- [Backup & Recovery](#backup--recovery)
- [Monitoring & Maintenance](#monitoring--maintenance)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools
- **AWS CLI**: `pip install awscli` + `aws configure`
- **EB CLI**: `pip install awsebcli`
- **Git**: Version control
- **Python 3.8+**: Application runtime

### AWS Resources Required
- AWS Account with appropriate permissions
- RDS PostgreSQL database
- S3 bucket for backups
- (Optional) Route 53 for DNS management
- (Optional) ACM certificate for SSL

---

## Initial Setup

### 1. Initialize Elastic Beanstalk

```bash
cd /path/to/rs_systems_branch2
eb init

# Configuration:
# - Region: us-east-1 (N. Virginia)
# - Application name: rs_systems_branch2
# - Platform: Python 3.13
```

### 2. Set Environment Variables

```bash
# Database credentials (never commit to repo)
export DB_PASSWORD='your_secure_password'
export SECRET_KEY='your-django-secret-key'
export ADMIN_PASSWORD='secure-admin-password'
```

### 3. Create Environment

```bash
eb create rs-systems-prod \
    --database.engine postgres \
    --database.username rswradmin \
    --database.password $DB_PASSWORD \
    --database.name rswr_db \
    --envvars SECRET_KEY=$SECRET_KEY,ADMIN_PASSWORD=$ADMIN_PASSWORD,DB_PASSWORD=$DB_PASSWORD
```

---

## Database Configuration

### RDS PostgreSQL Setup

**Production Database Configuration:**
- **Endpoint**: `your-database-instance.region.rds.amazonaws.com` (set via environment variable)
- **Port**: `5432`
- **Username**: `your_db_username` (set via environment variable)
- **Database Name**: `your_db_name`
- **Encryption**: Enabled (AWS KMS)
- **Backups**: 30-day automated retention (RDS)

### Environment Variables

Set in `.ebextensions/04_env_vars.config`:
```yaml
option_settings:
  aws:elasticbeanstalk:application:environment:
    DB_NAME: your_db_name
    DB_USER: your_db_username
    DB_HOST: your-database-instance.region.rds.amazonaws.com
    DB_PORT: 5432
    USE_HTTPS: true
    ENVIRONMENT: production
```

### Security Groups

Ensure RDS security group allows:
- Inbound PostgreSQL (port 5432) from EB environment security group
- No public access (security best practice)

---

## SSL & Domain Setup

### 1. Request SSL Certificate (ACM)

```bash
# Certificate for multiple domains
aws acm request-certificate \
  --domain-name yourdomain.com \
  --subject-alternative-names www.yourdomain.com app.yourdomain.com \
  --validation-method DNS \
  --region us-east-1
```

**Certificate ARN Format:**
```
arn:aws:acm:REGION:YOUR_AWS_ACCOUNT_ID:certificate/YOUR_CERTIFICATE_ID
```
Note: Store your actual certificate ARN in environment variables.

### 2. DNS Validation Records

Add to your DNS provider (provided by AWS after certificate request):

**Main domain validation:**
- **Name**: `_VALIDATION_STRING.yourdomain.com.`
- **Type**: CNAME
- **Value**: `_VALIDATION_TARGET.acm-validations.aws.`

**www subdomain validation:**
- **Name**: `_VALIDATION_STRING.www.yourdomain.com.`
- **Type**: CNAME
- **Value**: `_VALIDATION_TARGET.acm-validations.aws.`

**app subdomain validation:**
- **Name**: `_VALIDATION_STRING.app.yourdomain.com.`
- **Type**: CNAME
- **Value**: `_VALIDATION_TARGET.acm-validations.aws.`

Note: AWS provides these values after you request the certificate. Check ACM console for exact values.

### 3. Point Domain to Application

**Elastic Beanstalk CNAME:**
```
your-app-name.region.elasticbeanstalk.com
```
(Found in EB console or via `eb status`)

**DNS Records to Add:**

| Name | Type | Value |
|------|------|-------|
| `@` (root) | CNAME | `your-app-name.region.elasticbeanstalk.com` |
| `www` | CNAME | `your-app-name.region.elasticbeanstalk.com` |
| `app` | CNAME | `your-app-name.region.elasticbeanstalk.com` |

### 4. Enable HTTPS Configuration

Once certificate status is "ISSUED":

1. Edit `.ebextensions/08_https_redirect.config`
2. Uncomment HTTPS listener configuration
3. Set environment variables:
   ```bash
   eb setenv HTTPS_AVAILABLE=true FORCE_HTTPS=true
   ```
4. Rename `09_https_redirect.config.disabled` to `09_https_redirect.config`
5. Deploy: `eb deploy`

### 5. Verify SSL Setup

```bash
# Check certificate status
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:REGION:YOUR_AWS_ACCOUNT_ID:certificate/YOUR_CERTIFICATE_ID \
  --region us-east-1

# Test HTTPS endpoints
curl -I https://yourdomain.com
curl -I https://www.yourdomain.com
curl -I https://app.yourdomain.com
```

---

## Security Configuration

### Production Security Headers

**Implemented in `apps/security/middleware.py`:**
-  **Content Security Policy (CSP)** - XSS prevention
-  **HTTP Strict Transport Security (HSTS)** - Force HTTPS
-  **X-Frame-Options** - Clickjacking prevention
-  **X-Content-Type-Options** - MIME-type sniffing prevention
-  **Referrer-Policy** - Referrer information control
-  **Permissions-Policy** - Browser feature restrictions
-  **Cross-Origin Policies** - Cross-origin attack protection

### Session Security

```python
# settings_aws.py
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
```

### Rate Limiting

- **Login attempts**: 10/hour per IP
- **Registration**: 5/hour per IP
- **Bot protection**: Username validation, honeypot fields

### Gradual Security Enablement

If issues occur, disable security temporarily:

```python
# settings_aws.py
# Temporarily disable for troubleshooting
SECURE_SSL_REDIRECT = False  # Re-enable when HTTPS works
SESSION_COOKIE_SECURE = False  # Re-enable with HTTPS
CSRF_COOKIE_SECURE = False    # Re-enable with HTTPS
```

Then re-enable gradually after fixing issues.

---

## Deployment Process

### Initial Deployment

```bash
# 1. Ensure all environment variables are set
eb setenv KEY=value

# 2. Deploy application
eb deploy

# 3. Run database migrations
eb ssh
cd /var/app/current
source /var/app/venv/*/bin/activate
python manage.py migrate
exit

# 4. Create superuser
python manage.py createsu
```

### Subsequent Deployments

```bash
# 1. Commit changes
git add .
git commit -m "Description of changes"

# 2. Deploy
eb deploy

# 3. Check logs
eb logs

# 4. Open application
eb open
```

### Environment Management

```bash
# List environments
eb list

# Check environment health
eb health

# View configuration
eb config

# SSH into instance
eb ssh

# Tail logs in real-time
eb logs --stream
```

---

## Backup & Recovery

### Automated Backup System

**Last Updated**: October 30, 2025 (Migrated to AWS-managed backups)

RS Systems uses AWS-managed backup solutions for data protection:

#### 1. RDS Automated Backups (Database)

**Configuration:**
- **Database**: `rs-systems-production-db` (PostgreSQL 15.14)
- **Backup Window**: Daily at 3:29-3:59 AM UTC
- **Retention**: 30 days (configurable)
- **Storage**: Automated in AWS-managed storage
- **Recovery**: Point-in-time restore to any second within retention period

**Backup Status:**
```bash
# Check current backup configuration
aws rds describe-db-instances \
  --db-instance-identifier rs-systems-production-db \
  --query 'DBInstances[0].[BackupRetentionPeriod,PreferredBackupWindow,LatestRestorableTime]' \
  --output table

# List available snapshots
aws rds describe-db-snapshots \
  --db-instance-identifier rs-systems-production-db
```

#### 2. S3 Versioning (Media Files)

**Configuration:**
- **Bucket**: `rs-systems-media-20251029`
- **Versioning**: Enabled (protects against accidental deletion)
- **Lifecycle Policy**:
  - Previous versions retained for 30 days
  - Automatic cleanup after 30 days
  - Expired delete markers removed automatically
- **Cost Control**: Old versions auto-deleted to prevent storage bloat

**Photo Protection:**
- Current photos stored indefinitely
- Deleted/replaced photos recoverable for 30 days
- Application delete operations work normally
- Hidden version history for recovery

**Check Versioning Status:**
```bash
# Verify versioning is enabled
aws s3api get-bucket-versioning --bucket rs-systems-media-20251029

# View lifecycle policies
aws s3api get-bucket-lifecycle-configuration --bucket rs-systems-media-20251029

# List all versions of a file
aws s3api list-object-versions \
  --bucket rs-systems-media-20251029 \
  --prefix media/repair_photos/
```

### Recovery Procedures

#### Database Recovery

**Point-in-Time Restore (Recommended):**

Restore database to any point within the last 30 days:

```bash
# Restore to specific timestamp
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier rs-systems-production-db \
  --target-db-instance-identifier rs-systems-recovery-db \
  --restore-time 2025-10-25T14:30:00Z

# Or restore to latest restorable time
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier rs-systems-production-db \
  --target-db-instance-identifier rs-systems-recovery-db \
  --use-latest-restorable-time
```

**Snapshot Restore:**

```bash
# List available snapshots
aws rds describe-db-snapshots \
  --db-instance-identifier rs-systems-production-db

# Restore from specific snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier rs-systems-recovery-db \
  --db-snapshot-identifier rds:rs-systems-production-db-2025-10-29-03-38
```

**After Database Restore:**

1. Update application to use recovery database
2. Test functionality thoroughly
3. If successful, promote recovery DB to production
4. Update DNS/environment variables

#### Media File Recovery

**Recover Deleted Photo:**

```bash
# 1. List all versions to find the deleted file
aws s3api list-object-versions \
  --bucket rs-systems-media-20251029 \
  --prefix media/repair_photos/before/IMG_0433.jpeg

# 2. Copy specific version back (making it current)
aws s3api copy-object \
  --copy-source "rs-systems-media-20251029/media/repair_photos/before/IMG_0433.jpeg?versionId=VERSION_ID" \
  --bucket rs-systems-media-20251029 \
  --key media/repair_photos/before/IMG_0433.jpeg
```

**Recover Multiple Files:**

```bash
# Script to restore all files in a folder to a previous date
# This requires custom scripting based on version timestamps
aws s3api list-object-versions \
  --bucket rs-systems-media-20251029 \
  --prefix media/repair_photos/ \
  --query "Versions[?LastModified<'2025-10-25']"
```

### Manual Backup (Additional Protection)

For extra protection before major changes:

```bash
# Create manual RDS snapshot (retained indefinitely)
aws rds create-db-snapshot \
  --db-instance-identifier rs-systems-production-db \
  --db-snapshot-identifier manual-backup-$(date +%Y%m%d)

# Sync media files to separate backup location
aws s3 sync s3://rs-systems-media-20251029/media/ \
  s3://your-additional-backup-bucket/media-backup-$(date +%Y%m%d)/ \
  --storage-class GLACIER_IR  # Lower cost for archival
```

### Backup Validation

**Monthly Recovery Test (Recommended):**

```bash
# 1. Create test database from latest snapshot
aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier rs-systems-test \
  --db-snapshot-identifier rds:rs-systems-production-db-2025-10-30-03-38

# 2. Verify data integrity
psql -h rs-systems-test.xxx.rds.amazonaws.com -U rswradmin -d rswr_db -c "SELECT COUNT(*) FROM technician_portal_repair;"

# 3. Clean up test database
aws rds delete-db-instance \
  --db-instance-identifier rs-systems-test \
  --skip-final-snapshot
```

**Monitoring:**

```bash
# Check latest restorable time (should be within 5 minutes of current time)
aws rds describe-db-instances \
  --db-instance-identifier rs-systems-production-db \
  --query 'DBInstances[0].LatestRestorableTime'

# Verify S3 versioning is still enabled
aws s3api get-bucket-versioning --bucket rs-systems-media-20251029
```

### Cost Optimization

**Current Estimated Costs:**
- RDS backups (30-day retention): ~$10/month
- S3 versioning (30-day old versions): ~$0.50-5/month (grows with photo uploads)
- **Total**: ~$10-15/month

**Cost Controls in Place:**
- Lifecycle policies auto-delete old versions after 30 days
- Incomplete multipart uploads cleaned up after 7 days
- Expired delete markers removed automatically

**To Reduce Costs:**

```bash
# Reduce RDS retention to 7 days (saves ~$7/month)
aws rds modify-db-instance \
  --db-instance-identifier rs-systems-production-db \
  --backup-retention-period 7 \
  --apply-immediately

# Reduce S3 version retention to 7 days (minimal savings)
# Edit lifecycle policy to set NoncurrentDays: 7
```

### Backup Strategy Migration Notes

**Previous System (Deprecated):**
- Custom backup scripts to `rs-systems-backups-20250823` bucket
-  Failed silently for 67+ days (designed for SQLite, but using PostgreSQL)
-  Bucket was empty despite daily cron jobs
-  Removed on October 30, 2025

**Current System (Active):**
-  AWS RDS automated backups (30-day retention)
-  S3 versioning with lifecycle policies (30-day version retention)
-  No maintenance required
-  Integrated with AWS infrastructure

---

## Monitoring & Maintenance

### Health Checks

```bash
# Check environment health
eb health

# View detailed health info
aws elasticbeanstalk describe-environment-health \
  --environment-name rs-systems-prod \
  --attribute-names All

# Check database performance
aws rds describe-db-instances \
  --db-instance-identifier rswr-db-1
```

### Log Monitoring

```bash
# View recent logs
eb logs

# Stream logs in real-time
eb logs --stream

# Download all logs
eb logs --all > production_logs.txt

# Check specific log file
eb logs --log-group /aws/elasticbeanstalk/rs-systems-prod/var/log/web.stdout.log
```

### Performance Monitoring

**CloudWatch Metrics:**
- CPU utilization
- Memory usage
- Request count
- Response time
- Error rate
- Database connections

**Database Monitoring:**
- Query performance (Performance Insights enabled)
- Connection count
- Storage usage
- Replication lag (if applicable)

### Maintenance Tasks

**Weekly:**
- Review application logs
- Check error rates
- Verify backup completion

**Monthly:**
- Review security settings
- Test backup recovery
- Update dependencies
- Review database performance
- Audit S3 storage for orphaned files (`python manage.py audit_repair_photos`)

**Quarterly:**
- Security audit
- Cost optimization review
- SSL certificate renewal check
- Disaster recovery test
- Clean up orphaned repair photos (`python manage.py audit_repair_photos --delete`)

---

## Troubleshooting

### Deployment Issues

**502 Bad Gateway:**
```bash
# Check application logs
eb logs

# Common causes:
# 1. Django settings error
# 2. Gunicorn not starting
# 3. Health check endpoint failing

# Fix: Check /health endpoint
curl http://your-app-name.elasticbeanstalk.com/health
```

**Database Connection Errors:**
```bash
# Verify security group allows EB  RDS
# Check environment variables
eb printenv

# Test database connection
eb ssh
python manage.py dbshell
```

**Static Files Not Loading:**
```bash
# Verify collectstatic ran
eb logs | grep collectstatic

# Manually run collectstatic
eb ssh
cd /var/app/current
python manage.py collectstatic --noinput
```

### SSL/HTTPS Issues

**Certificate Not Validating:**
```bash
# Check certificate status
aws acm describe-certificate --certificate-arn ARN

# Verify DNS records are correct
nslookup _validation.yourdomain.com

# Wait up to 30 minutes for validation
```

**HTTPS Redirect Loop:**
```bash
# Check load balancer configuration
# Ensure X-Forwarded-Proto header is set
# Verify SECURE_PROXY_SSL_HEADER in settings

# Temporarily disable redirect
eb setenv FORCE_HTTPS=false
```

### Performance Issues

**High CPU Usage:**
```bash
# Check running processes
eb ssh
top

# Scale up instance type
eb scale 1 --instance-type t3.medium

# Or scale horizontally
eb scale 2
```

**Database Performance:**
```bash
# Check slow queries
# Enable Performance Insights in RDS console
# Add database indexes for frequently queried fields
```

### Common Error Patterns

| Error | Cause | Solution |
|-------|-------|----------|
| `DisallowedHost` | ALLOWED_HOSTS not configured | Add domain to ALLOWED_HOSTS |
| `CSRF verification failed` | CSRF_TRUSTED_ORIGINS missing | Add https://domain to setting |
| `OperationalError: connection refused` | Database not accessible | Check security group + DB endpoint |
| `ModuleNotFoundError` | Dependency missing | Add to requirements.txt + deploy |
| `Permission denied` | File permissions | `chown webapp:webapp` on EB instance |

---

## Production Checklist

### Pre-Deployment
- [ ] All tests passing locally
- [ ] Environment variables configured
- [ ] Database migrations created
- [ ] Static files collected
- [ ] Secret key rotated for production
- [ ] DEBUG = False
- [ ] ALLOWED_HOSTS configured
- [ ] Database backup created

### Deployment
- [ ] Code deployed successfully
- [ ] Database migrations applied
- [ ] Static files loading
- [ ] Health check passing
- [ ] All endpoints responding
- [ ] SSL certificate active
- [ ] HTTPS redirect working

### Post-Deployment
- [ ] Application functional end-to-end
- [ ] Login/authentication working
- [ ] Customer portal accessible
- [ ] Technician portal accessible
- [ ] Admin interface working
- [ ] Photo uploads functional
- [ ] Email notifications working (if configured)
- [ ] Backup system running
- [ ] Monitoring alerts configured
- [ ] DNS propagated fully

---

## Quick Reference

### Essential Commands

```bash
# Deploy
eb deploy

# View logs
eb logs

# SSH into instance
eb ssh

# Check health
eb health

# Set environment variable
eb setenv KEY=value

# Open in browser
eb open

# Restart application
eb restart

# Terminate environment
eb terminate ENVIRONMENT_NAME
```

### Important URLs

- **Production App**: https://rssystems.io
- **Admin Interface**: https://rssystems.io/admin/
- **API Docs**: https://rssystems.io/api/schema/swagger-ui/
- **Health Check**: https://rssystems.io/health/

### Support Resources

- **AWS Documentation**: https://docs.aws.amazon.com/elasticbeanstalk/
- **Django Deployment**: https://docs.djangoproject.com/en/stable/howto/deployment/
- **Internal Docs**: `/docs/` directory in repository

---

**Last Updated**: March 2026
**Environment**: rs-systems-prod
**Domain**: rssystems.io
**Region**: us-east-1
**Status**: Production Ready

## Architecture Notes (Current)

- **No Celery / No Redis**: Notifications are synchronous. Billing tasks run as management commands via EB cron (`.ebextensions/11_billing_cron.config`).
- **Email**: Amazon SES over SMTP (`notifications@rssystems.io`), `us-east-1`. Domain `rssystems.io` is verified and DKIM-signed; the account has production access (50,000 msg/day, 14 msg/sec).
- **Settings**: `rs_systems.settings.production` (three-file layout: base/development/production).
