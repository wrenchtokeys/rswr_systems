# Deployment Configuration Files

This directory contains legacy Celery service files (no longer used) and is kept for reference only.

> **Note**: Celery and Redis have been removed from RS Systems. Notifications are now delivered
> synchronously, and billing tasks run as Django management commands scheduled via EB cron.

## Current Production Architecture

RS Systems deploys to **AWS Elastic Beanstalk** at **https://rssystems.io**.

- **Platform**: Python 3.13 on EB
- **Database**: RDS PostgreSQL
- **Storage**: S3 (`rs-systems-media-20251029`)
- **Email**: SendGrid (`notifications@rssystems.io`)
- **Settings**: `rs_systems.settings.production`

## Deploying

```bash
# From main branch
eb deploy

# Verify
curl -I https://rssystems.io/health/
```

## Scheduled Billing Tasks (EB Cron)

Billing tasks run as management commands scheduled via `.ebextensions/11_billing_cron.config`:

| Command | Schedule | Purpose |
|---------|----------|---------|
| `process_batch_invoices` | 6 AM UTC daily | Auto-generate batch invoices |
| `process_overdue_invoices` | 8 AM UTC daily | Mark overdue, send reminders |
| `generate_aging_report` | 9 AM UTC daily | Update aging data |

## Environment Variables

Set via `eb setenv` or `.ebextensions/04_env_vars.config`:

```bash
DJANGO_SETTINGS_MODULE=rs_systems.settings.production
SECRET_KEY=...
DB_NAME=...
DB_USER=...
DB_HOST=...
DB_PORT=5432
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=rs-systems-media-20251029
SENDGRID_API_KEY=SG....
DEFAULT_FROM_EMAIL=notifications@rssystems.io
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## Post-Deploy Steps

```bash
# SSH into instance
eb ssh

cd /var/app/current
source /var/app/venv/*/bin/activate

# Run migrations
python manage.py migrate

# Seed plans (first deploy only)
python manage.py seed_plans
python manage.py setup_groups
python manage.py setup_notification_templates
```

## Monitoring

```bash
# Health check
eb health

# Stream logs
eb logs --stream

# View env vars
eb printenv
```

## Legacy Files (Archived)

- `celery-worker.service` — Celery worker systemd unit (no longer used)
- `celery-beat.service` — Celery beat scheduler systemd unit (no longer used)

These files are kept for historical reference. Do not reinstall them.
