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
- [ ] EB cron jobs verified (billing commands running at scheduled times)

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

---

## Billing Automation (EB Cron)

Billing tasks are scheduled via `.ebextensions/11_billing_cron.config`. No Celery or Redis required.

Verify cron is active after deploy:
```bash
eb ssh
cat /etc/cron.d/billing_tasks
```

Expected entries:
- `0 6 * * *` — `process_batch_invoices`
- `0 8 * * *` — `process_overdue_invoices`
- `0 9 * * *` — `generate_aging_report`

---

## Management Command Registry

All scheduled and operational management commands for RS Systems. Update this table whenever a new command is added.

### Scheduled (EB Cron — `.ebextensions/11_billing_cron.config`)

| Command | Schedule (UTC) | Log File | Purpose |
|---------|---------------|----------|---------|
| `process_batch_invoices` | Daily 6:00 AM | `/var/log/billing-batch.log` | Auto-generate batch invoices for fleet customers on their billing cycle |
| `process_overdue_invoices` | Daily 8:00 AM | `/var/log/billing-overdue.log` | Mark invoices past due date as OVERDUE, send configurable reminder emails |
| `generate_aging_report` | Daily 9:00 AM | `/var/log/billing-aging.log` | Refresh AR aging report cache (30/60/90/90+ day buckets) |
| `check_subscription_alerts` | Daily 9:00 AM | (stdout) | Send subscription expiry warning emails at 7d/1d/0d/15d-past/5d-past/end milestones |

> **Note:** New loyalty commands (`expire_loyalty_points`, `reconcile_loyalty_balances`) and the review request command (`send_review_requests`) should be added to the cron config before the next production deployment. See "Add to Cron" section below.

### Loyalty & Review Commands — Add to Cron Before Next Deploy

These commands are implemented but not yet in `.ebextensions/11_billing_cron.config`. Add them:

```cron
# Run daily at midnight UTC — expire points past their expiry date
0 0 * * * webapp /bin/bash -c 'source /var/app/venv/*/bin/activate && cd /var/app/current && python manage.py expire_loyalty_points --json >> /var/log/loyalty-expire.log 2>&1'

# Run daily at 3 AM UTC — reconcile Reward.points cache vs PointTransaction ledger
0 3 * * * webapp /bin/bash -c 'source /var/app/venv/*/bin/activate && cd /var/app/current && python manage.py reconcile_loyalty_balances --json >> /var/log/loyalty-reconcile.log 2>&1'

# Run every 15 minutes — send pending review request emails whose scheduled_at has arrived
*/15 * * * * webapp /bin/bash -c 'source /var/app/venv/*/bin/activate && cd /var/app/current && python manage.py send_review_requests >> /var/log/review-requests.log 2>&1'
```

### On-Demand Commands (Run Manually)

| Command | App | Purpose | Flags |
|---------|-----|---------|-------|
| `expire_loyalty_points` | `rewards_referrals` | Expire points past their `expires_at` date, deduct from `Reward.points` balance | `--dry-run`, `--tenant-id <id>`, `--json` |
| `reconcile_loyalty_balances` | `rewards_referrals` | Compare `Reward.points` cache vs `PointTransaction` ledger sum; alert on drift | `--fix` (auto-correct), `--tenant-id <id>`, `--json` |
| `send_review_requests` | `technician_portal` | Send pending review request emails whose scheduled time has arrived | `--dry-run` |
| `purge_deleted_records` | `technician_portal` | Hard-delete soft-deleted Repairs/Invoices older than N days | `--days <n>` (default 30), `--apply` (required to execute) |
| `generate_aging_report` | `billing` | Refresh aging report cache; useful after bulk data imports | `--tenant-id <id>`, `--json` |
| `fix_billing_config_names` | `billing` | One-time fix: correct `BillingConfig.company_name` defaulted to "Rockstar" | `--apply` |
| `setup_viscosity_rules` | `technician_portal` | Seed default viscosity rules for a tenant | `--tenant-id <id>` |
| `setup_simplified_rewards` | `rewards_referrals` | Seed default reward options for a tenant | `--tenant-id <id>` |
| `security_audit` | `security` | Run security checks and log findings to `SecurityAuditLog` | (none) |
| `seed_plans` | `tenants` | Seed subscription plan records (Starter/Pro/Enterprise) | (none) |
| `set_stripe_prices` | `tenants` | Sync Stripe price IDs onto `SubscriptionPlan` records | (none) |

### Maintenance-Only Commands (One-Time Use)

| Command | Purpose |
|---------|---------|
| `reset_connect` | Full reset of Stripe Connect for a tenant (use with extreme care) |
| `load_tax_rates` | Bulk-load tax rates from CSV (deprecated — owners now manage via UI) |
| `tax_debug` | Debug tax calculation for a specific tenant |

### Adding a New Command Checklist

When adding a new management command:
1. Create in `apps/<app>/management/commands/<name>.py`
2. Add `help` attribute with a clear one-line description
3. Add to this registry table (correct section)
4. If scheduled: add to `.ebextensions/11_billing_cron.config` + add log file to `bundlelogs.d`
5. Document `--dry-run` flag if the command mutates data
6. Add regression tests in `tests/test_<name>.py` or the relevant test file

---

**Document Version**: 1.2
**Last Updated**: March 2026 (Sprint 7 — Management Command Registry)
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
