# Production Deployment Checklist

Comprehensive pre-deployment, deployment, and post-deployment verification checklist for RS Systems.

---

## Pre-Deployment Phase

### Code Quality & Testing
- [ ] All unit tests passing (`python manage.py test`)
- [ ] Integration tests completed
- [ ] Manual testing performed on staging environment
- [ ] No critical bugs or security vulnerabilities
- [ ] Code reviewed and approved
- [ ] All Sprint acceptance criteria met

### Database Preparation
- [ ] All migrations created (`python manage.py makemigrations`)
- [ ] Migrations tested on development database
- [ ] **CRITICAL**: Production database backed up
- [ ] Backup download verified and tested
- [ ] Migration rollback plan documented
- [ ] No destructive migrations (data loss risk)

### Configuration Review
- [ ] `DEBUG = False` in production settings
- [ ] `SECRET_KEY` is unique and secure (not the development key)
- [ ] `ALLOWED_HOSTS` configured with production domains
- [ ] `CSRF_TRUSTED_ORIGINS` includes all production URLs
- [ ] Database credentials secured (environment variables only)
- [ ] AWS credentials not in codebase
- [ ] `.gitignore` updated (no secrets in repo)

### Environment Variables
- [ ] `SECRET_KEY` set
- [ ] `DB_PASSWORD` set
- [ ] `ADMIN_PASSWORD` set
- [ ] `ENVIRONMENT=production` set
- [ ] `USE_HTTPS=true` set
- [ ] `ALLOWED_HOSTS` set
- [ ] All custom app variables configured

### Static & Media Files
- [ ] `collectstatic` runs without errors
- [ ] Static files configuration verified
- [ ] Media upload path configured
- [ ] S3 bucket configured (if using S3)
- [ ] File permissions correct

### Security Checklist
- [ ] SSL certificate validated and active
- [ ] HTTPS redirect configured
- [ ] Security headers enabled (CSP, HSTS, etc.)
- [ ] Session cookies secure (`SESSION_COOKIE_SECURE = True`)
- [ ] CSRF cookies secure (`CSRF_COOKIE_SECURE = True`)
- [ ] Rate limiting enabled
- [ ] Bot protection active
- [ ] SQL injection protection verified (ORM usage)
- [ ] XSS protection enabled

### Documentation
- [ ] Deployment notes updated
- [ ] Changelog updated with current version
- [ ] Known issues documented
- [ ] Rollback procedure documented
- [ ] Stakeholder communication prepared

---

## Deployment Phase

### Pre-Deployment Backup
- [ ] **CRITICAL**: Create immediate database backup
  ```bash
  eb ssh
  pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > pre_deployment_backup.sql
  aws s3 cp pre_deployment_backup.sql s3://rs-systems-backups-20250823/emergency/
  ```
- [ ] **CRITICAL**: Backup current media files
  ```bash
  aws s3 sync /var/app/current/media/ s3://rs-systems-backups-20250823/emergency/media/
  ```
- [ ] Download backups to local machine (extra safety)
- [ ] Verify backup integrity

### Deployment Steps
- [ ] Create deployment git tag
  ```bash
  git tag -a v1.X.X -m "Production deployment - Sprint X"
  git push origin v1.X.X
  ```
- [ ] Deploy application
  ```bash
  eb deploy rs-systems-prod
  ```
- [ ] Monitor deployment logs
  ```bash
  eb logs --stream
  ```
- [ ] Wait for deployment completion (no errors)

### Database Migration
- [ ] SSH into production
  ```bash
  eb ssh rs-systems-prod
  ```
- [ ] Activate virtual environment
  ```bash
  cd /var/app/current
  source /var/app/venv/*/bin/activate
  ```
- [ ] **CRITICAL**: Create pre-migration backup
  ```bash
  python manage.py dumpdata > pre_migration_data.json
  ```
- [ ] Run migrations
  ```bash
  python manage.py migrate
  ```
- [ ] Verify migration success (no errors)
- [ ] Check migration status
  ```bash
  python manage.py showmigrations
  ```

### Application Restart
- [ ] Restart application servers
  ```bash
  eb restart rs-systems-prod
  ```
- [ ] Wait for health check to pass
- [ ] Verify application status
  ```bash
  eb health
  ```

---

## Post-Deployment Verification

### Health & Status Checks
- [ ] Application health check passing
  ```bash
  curl https://rssystems.io/health
  ```
- [ ] Expected response: `{"status": "healthy"}`
- [ ] Environment health: **Green**
- [ ] No error logs in CloudWatch
- [ ] Database connections stable

### Core Functionality Tests

#### Customer Portal
- [ ] Landing page loads (`https://rssystems.io`)
- [ ] Customer login works (`https://rssystems.io/app/login/`)
- [ ] Customer registration works
- [ ] Dashboard displays correctly
- [ ] Repair request submission works
- [ ] Photo upload functional
- [ ] Repair approval/denial works
- [ ] Analytics charts render

#### Technician Portal
- [ ] Technician login works (`https://rssystems.io/tech/login/`)
- [ ] Dashboard displays correctly
- [ ] Repair list loads
- [ ] Repair detail page works
- [ ] Repair creation works
- [ ] Repair status updates work
- [ ] Photo viewing works
- [ ] Notifications display

#### Admin Interface
- [ ] Admin login works (`https://rssystems.io/admin/`)
- [ ] All models accessible
- [ ] Customer pricing configuration works
- [ ] Technician management works
- [ ] Customer repair preferences work
- [ ] No permission errors

### October 2025 Critical Features
- [ ] **Manager Assignment**: Managers can assign REQUESTED repairs
- [ ] **Customer Approval**: PENDING repairs show on customer dashboard
- [ ] **Approval System**: Customers can approve/deny from dashboard
- [ ] **Security Fix**: Technicians cannot bypass approval by setting COMPLETED status
- [ ] **Preferences**: Customer repair preferences enforced server-side
- [ ] **Visibility**: Non-managers cannot see REQUESTED repairs
- [ ] **Visibility**: All technicians cannot see PENDING repairs
- [ ] **Notifications**: Assignment notifications include repair links

### Data Integrity Checks
- [ ] No data loss from migration
- [ ] Existing repairs display correctly
- [ ] Customer data intact
- [ ] Technician data intact
- [ ] Photo URLs resolve correctly
- [ ] Repair history accurate

### Security Verification
- [ ] HTTPS enforced (HTTP redirects to HTTPS)
- [ ] SSL certificate valid
- [ ] Security headers present
  ```bash
  curl -I https://rssystems.io | grep -E "(Strict-Transport|Content-Security|X-Frame)"
  ```
- [ ] CSRF protection working
- [ ] Rate limiting functional
- [ ] Session cookies secure (check browser dev tools)

### Performance Checks
- [ ] Page load times acceptable (<3 seconds)
- [ ] API response times normal
- [ ] Database query performance acceptable
- [ ] No memory leaks
- [ ] CPU usage normal
- [ ] No N+1 query issues

### Monitoring Setup
- [ ] CloudWatch alarms active
- [ ] Error rate monitoring configured
- [ ] Database performance monitoring enabled
- [ ] Backup system running
- [ ] Log aggregation working

---

## Rollback Procedure

### When to Rollback
Rollback if any of these occur:
- Critical functionality broken
- Data corruption detected
- Security vulnerability introduced
- Performance degradation >50%
- Database migration failure
- Unable to login (any portal)

### Rollback Steps

#### 1. Immediate Actions
```bash
# Stop accepting new requests (if applicable)
eb setenv MAINTENANCE_MODE=true
```

#### 2. Code Rollback
```bash
# Redeploy previous version
git checkout <previous-commit-or-tag>
eb deploy

# Or restore from previous EB version
eb deploy --version <previous-version-label>
```

#### 3. Database Rollback
```bash
# SSH into production
eb ssh

# Restore pre-deployment backup
aws s3 cp s3://rs-systems-backups-20250823/emergency/pre_deployment_backup.sql ./
psql -h $DB_HOST -U $DB_USER -d $DB_NAME < pre_deployment_backup.sql

# Or rollback migrations
python manage.py migrate <app_name> <previous_migration_number>
```

#### 4. Media Files Rollback
```bash
# Restore media files if needed
aws s3 sync s3://rs-systems-backups-20250823/emergency/media/ /var/app/current/media/
```

#### 5. Verification
```bash
# Restart application
eb restart

# Verify health
eb health

# Test critical functionality
curl https://rssystems.io/health
```

#### 6. Communication
- [ ] Notify stakeholders of rollback
- [ ] Document reason for rollback
- [ ] Create incident report
- [ ] Plan fix and re-deployment

---

## Post-Rollback Analysis

If rollback was necessary:
- [ ] Root cause identified
- [ ] Fix implemented and tested
- [ ] Additional tests added to prevent recurrence
- [ ] Deployment procedure updated
- [ ] Incident report completed
- [ ] Team debriefing scheduled

---

## Communication Plan

### Pre-Deployment Communication
**Send to stakeholders 24 hours before deployment:**
```
Subject: Scheduled Production Deployment - [Date/Time]

Team,

We will be deploying Sprint X updates to production on [Date] at [Time].

Expected downtime: [X minutes]
New features: [List key features]
Known issues: [List if any]

Please avoid making changes during this window.

Contact [Name] with questions.
```

### During Deployment
- [ ] Post status update: "Deployment in progress"
- [ ] Update if issues encountered
- [ ] Provide ETA for completion

### Post-Deployment Communication
**Send to stakeholders after successful deployment:**
```
Subject: Production Deployment Complete - [Date/Time]

Team,

Sprint X deployment completed successfully at [Time].

 All systems operational
 New features live
 No data loss

New features available:
- [Feature 1]
- [Feature 2]
- [Feature 3]

Please report any issues to [Contact].

Documentation: [Link to docs]
```

### Rollback Communication
**If rollback occurs:**
```
Subject: URGENT - Production Rollback Completed

Team,

We experienced issues with today's deployment and have rolled back to the previous version.

Current status: All systems restored to pre-deployment state
Issue: [Brief description]
Next steps: [Plan to address and re-deploy]

All data has been preserved. No action required from users.

We will provide updates as we work on the fix.
```

---

## Emergency Contacts

### Escalation Path
1. **Primary**: Development Team Lead
2. **Backup**: DevOps Engineer
3. **Emergency**: AWS Support (if infrastructure issue)

### Critical Contact Information
- **AWS Support**: Available via AWS Console
- **Database Administrator**: [Contact]
- **Security Team**: [Contact]

---

## Deployment Log Template

After each deployment, record:

```markdown
## Deployment [Date]

**Version**: v1.X.X
**Sprint**: Sprint X
**Deployed By**: [Name]
**Deployment Time**: [Start] - [End]
**Downtime**: [X minutes]

### Changes Deployed
- [Feature/Fix 1]
- [Feature/Fix 2]
- [Bug fix 1]

### Migrations Run
- [App name]: [Migration number]

### Issues Encountered
- [None / List issues]

### Rollback Required
- [Yes/No]
- [Reason if yes]

### Post-Deployment Status
- Health Check:  Pass
- Core Functionality:  Pass
- Performance:  Normal
- Monitoring:  Active

### Notes
[Any additional notes or observations]
```

---

## Success Criteria

Deployment is considered successful when:
-  All health checks passing
-  All core functionality verified
-  No critical errors in logs
-  Performance within acceptable range
-  Security measures active
-  Monitoring and backups operational
-  Stakeholders notified
-  Documentation updated

---

**Document Version**: 1.0
**Last Updated**: October 21, 2025
**Next Review**: After each major deployment

---

## Quick Reference - Essential Commands

```bash
# Create backup
pg_dump -h $DB_HOST -U $DB_USER -d $DB_NAME > backup.sql

# Deploy
eb deploy

# Check health
eb health

# View logs
eb logs --stream

# SSH to production
eb ssh

# Run migrations
python manage.py migrate

# Rollback migration
python manage.py migrate app_name migration_number

# Restart app
eb restart

# Emergency maintenance mode
eb setenv MAINTENANCE_MODE=true
```

---

 **This checklist should be completed for every production deployment**
