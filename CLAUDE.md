# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Essential Commands

### Development Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Initialize
python manage.py migrate
python manage.py seed_plans               # 4 subscription plan tiers
python manage.py setup_groups             # Technicians group + permissions
python manage.py setup_notification_templates  # 8 repair lifecycle templates
python manage.py createsuperuser
```

### Core Development Commands
```bash
# Run with correct settings
DJANGO_SETTINGS_MODULE=rs_systems.settings.development python manage.py runserver 0.0.0.0:8000

# Database
python manage.py makemigrations
python manage.py migrate

# Static files (production)
python manage.py collectstatic

# Frontend CSS build — run after ANY template or static/js class change
./scripts/build_css.sh   # compiles static/css/app.css (COMMIT this file)
```

### Frontend CSS Rules
- Tailwind is compiled via the standalone CLI (`scripts/build_css.sh` downloads `bin/tailwindcss`, gitignored). No node/npm anywhere.
- `tailwind.config.js` is the single source of truth for the brand palette; `static/css/src/input.css` holds design tokens + `@layer components` (`.btn-*`, `.card*`, `.badge-*`, `.modal-*` — see `docs/development/UI_DESIGN_GUIDE.md`).
- `static/css/app.css` is a build artifact but IS committed (EB deploys unchanged; manifest storage handles cache busting).
- **Never reintroduce `cdn.tailwindcss.com`** or inline `tailwind.config` blocks in templates.
- Classes composed dynamically (JS string concat, Django template vars like `grid-cols-{{ n }}`) must be safelisted in `tailwind.config.js` or the purge will drop them.

### Running Tests
```bash
# Test database credentials
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development

# Full suite (~331 tests, ~7 min)
python manage.py test tests/ -v 1

# Fast smoke tests (use these during dev)
python manage.py test tests.test_primary_contact tests.test_e2e_today -v 2

# Specific test file
python manage.py test tests.test_step5_nav
python manage.py test tests.comprehensive.test_user_flow
python manage.py test tests.comprehensive.test_rewards

# Run a single test
python manage.py test tests.test_e2e_today.SubscriptionEnforcementTests.test_trial_user_can_access_dashboard
```

Test files live in `tests/` (top-level), not `apps/*/tests.py`. Some app-level test files exist but the canonical suite is under `tests/`.

### Maintenance Commands
```bash
python manage.py audit_repair_photos         # Dry run — show orphaned S3 photos
python manage.py audit_repair_photos --delete # Delete orphaned photos
python manage.py security_audit              # Security checks
python manage.py setup_simplified_rewards    # Seed 4 default reward options
python manage.py audit_remediation_data      # Read-only data-drift audit (A1/A2/A3/C2)
python manage.py sync_job_prices_from_invoices                    # Dry run — job vs invoiced price drift
python manage.py sync_job_prices_from_invoices --customer x --apply  # Back-fill job cost from invoice
```

### Notification & Billing Commands
```bash
python manage.py test_ses email@example.com   # Test Amazon SES delivery

# Billing (also scheduled via EB cron)
python manage.py process_batch_invoices       # Generate batch invoices
python manage.py process_overdue_invoices     # Mark overdue, send reminders
python manage.py generate_aging_report        # Refresh aging data

# Subscription alerts (scheduled via EB cron)
python manage.py check_subscription_alerts    # Send expiry warning emails

# Review requests (scheduled via EB cron, every 20 min — 12_reviews_cron.config)
python manage.py send_review_requests           # Send due review request emails
python manage.py send_review_requests --dry-run # Count without sending
```

---

## Architecture

### Apps

| App | Purpose |
|-----|---------|
| `apps/tenants` | Multi-tenant models, middleware, subscription enforcement |
| `apps/saas` | SaaS UI: signup, onboarding, owner dashboard, pricing |
| `apps/billing` | Invoicing, payments, PDF, Stripe, tax service |
| `apps/technician_portal` | Repair/replacement management, technician workflows |
| `apps/customer_portal` | Customer portal, approvals, requests, invitations |
| `apps/rewards_referrals` | Points, referral codes, redemption |
| `apps/security` | Login throttling, audit logging |
| `apps/clawdbot` | Amelia's API namespace |
| `core` | Customer, Vehicle, notification system |

### Middleware Stack (order matters)

In `rs_systems/settings/base.py`:
1. `apps.tenants.middleware.TenantMiddleware` — resolves `request.tenant`
2. `apps.tenants.subscription_middleware.SubscriptionEnforcementMiddleware` — blocks expired/canceled tenants

TenantMiddleware resolves tenant in order: X-Tenant-Slug header → session `tenant_id` → first active TenantMembership → CustomerUser lookup.

### Settings Package

`rs_systems/settings/` — three-file layout:
- `base.py` — **Single source of truth**: INSTALLED_APPS, MIDDLEWARE, TEMPLATES, REST_FRAMEWORK, email config
- `development.py` — `from .base import *` + DEBUG=True, SQLite fallback, dev overrides
- `production.py` — `from .base import *` + DEBUG=False, PostgreSQL required, S3, hardened security

**Rule**: New apps/middleware always go in `base.py`. Never in `development.py` or `production.py` individually.

Old `settings.py` and `settings_aws.py` are deleted — do not recreate.

### Key Business Logic

**Repair Workflow**: `Repair` model with queue-based status progression:
`REQUESTED → PENDING → APPROVED → IN_PROGRESS → COMPLETED`

Shop-created repairs/replacements auto-approve on create via `resolve_initial_shop_status` (`apps/technician_portal/models.py`), called from both `save()` hooks. `CustomerRepairPreference.field_repair_approval_mode` defaults to `AUTO_APPROVE`; setting it to `REQUIRE_APPROVAL`/`UNIT_THRESHOLD` explicitly brings back the PENDING → Approve/Deny flow — this is the future customer-portal "customer approves work in the portal" setting. Customer-portal requests enter as `REQUESTED` and are unaffected.

**Replacement Invoicing**: `InvoiceLineItem` has both `repair` and `replacement` FKs. `InvoiceTrackingService.create_invoice_from_services` accepts a mixed list (`create_invoice_from_repairs` is a back-compat delegator). Uninvoiced queries: `get_uninvoiced_repairs` + `get_uninvoiced_replacements` (both honor `skip_invoicing`). Auto-invoice (`AutoInvoiceService.generate_and_save`) is record-first: Invoice row created before PDF/S3/email, and PDFs render from the record (`generate_invoice_from_record`) — never from the repairs-only live-query path.

Tax is calculated automatically on every `Repair.save()` via `TaxService(tenant=self.tenant).calculate_tax()`. If no `TaxRate` exists for the tenant, tax is 0. Tests that check tax behavior must create a `TaxRate` in setUp.

**Multi-Break Batch Repairs**: Multiple repairs for same unit in one session. Each break is a separate `Repair` linked via `repair_batch_id` (UUID). Progressive pricing: Break N priced as repair #(existing_count + N). Created atomically. URL: `/tech/repairs/create-multi-break/`.

**Progressive Pricing**: Repair cost decreases per unit: $50→$40→$35→$30→$25. Tracked via `UnitRepairCount`. Configurable at shop level and per-customer. With progressive off, the shop sets a single flat "Price per repair" (`repair_price_1`); `calculate_batch_pricing` honors the toggle too. Custom prices are per-job (and per-break in multi-break) — authorization is `is_manager` (`can_override_pricing` is deprecated: nothing ever set it).

**Job ↔ Invoice Price Sync** (`apps/billing/services/invoice_sync.py`): the two directions can't drift. Invoice→job: the owner line-item editor writes edited prices back to the Repair/Replacement (cost + pre-discount `cost_override`). Job→invoice: `Repair.save()`/`Replacement.save()` update the job's line on any live invoice and recalc totals via `recalculate_invoice_totals`. PAID/CANCELLED/trashed invoices are never touched; jobs on a PAID invoice get their price fields removed in RepairForm (lock note names the invoice). Historical drift: audit with `sync_job_prices_from_invoices` (dry-run default).

**Invoice Numbers**: per-tenant `{prefix}-{counter}` sequence (default INV-1001, …), configured in Settings → Billing. Always allocate via `BillingConfig.allocate_invoice_number()` (row-locked, skips taken numbers incl. soft-deleted); never hand-format invoice numbers in record-creating paths.

**Tenant Isolation**: All data queries must be scoped to `request.tenant`. Views that don't do this are bugs. The subscription middleware redirects authenticated users with no tenant context to `/login/` — tests that use `client.login()` need to verify the login actually succeeds (use `force_login()` when the username is auto-generated from first name, not email).

**Customer Portal Invitations**: `CustomerInvitation` model + `invitation_service.py`. Owners invite fleet contacts by email → personalized token link → `/app/invite/<token>/`. Primary contacts (`is_primary_contact=True`) receive repair lifecycle notifications by default.

**Notification System**: 8 repair lifecycle templates seeded in migration `0018_seed_repair_notification_templates`:
`repair_pending_approval`, `repair_approved`, `repair_denied`, `repair_assigned`, `repair_reassigned_away`, `repair_in_progress`, `repair_completed`, `batch_approved`

All fire via `core.services.notification_service`. Per-user and per-customer preferences. Customer notifications are company-scoped (all `CustomerUser` accounts for a company share the feed). There are no `replacement_*` lifecycle templates yet — replacement requests notify the shop via `TechnicianNotification` + `send_branded_email` only (see `_notify_shop_replacement_requested` in `apps/customer_portal/views.py`).

**Tenant Email Branding**: `templates/emails/base.html` renders `{{ branding.company_name }}` in the header/footer/title. Always build that context with `EmailBrandingConfig.get_tenant_context(tenant)` (`core/models/email_branding.py`) — it keeps the platform singleton's visual identity but overrides identity fields with the tenant's name/contact/logo. Using the raw singleton (`get_instance().to_template_context()`) in tenant-scoped email is a bug: the singleton is platform-wide and its `company_name` is the platform-owner tenant. `NotificationService.create_notification` auto-injects `branding` (derived repair → customer → recipient) when the context doesn't include one.

**Shop Branding (`Tenant.brand_color` + `Tenant.logo`)**: Owners configure branding in Owner Settings → General (Business Information card = logo/contact, Branding card = one brand color, `form_type='branding'`). `brand_color` overrides `primary_color`/`secondary_color` in `get_tenant_context`, drives `send_branded_email` header/buttons, and colors the invoice PDF — `InvoiceService._load_branding_config` reads colors + logo from the **tenant only**, never the `EmailBrandingConfig` singleton (the singleton leaked the platform owner's logo/colors onto every shop's invoices; migration `tenants/0020` copied them onto the platform-owner tenant). The customer portal's Tailwind `brand-*` palette reads `--brand-N` CSS variables (defaults in `static/css/src/input.css`, per-shop shades from `apps/tenants/branding.brand_shades` injected via `{% tenant_brand_css %}` in `base_customer.html`). Outgoing shop email uses `core.email_utils.shop_sender`: From = `"<Shop> via RS Systems" <notifications@rssystems.io>` (never the shop's own domain — SPF/DKIM alignment; the "via" pattern defuses display-name-spoof heuristics), Reply-To = `tenant.business_email`. No emoji, no bracketed subjects, no tracking pixel, no photo attachments in email (photos render on the public invoice page) — see `docs/operations/SES_OPERATIONS.md` before changing email content.

**Customer Replacement Requests**: `/app/replacements/request/` (`request_replacement` in `apps/customer_portal/views.py`). Creates a `Replacement` with `queue_status='REQUESTED'` and no parts/labor pricing (cost stays 0, tax skipped) — the shop prices it, then the customer approves. `get_available_technician(tenant, service_type='replacement')` prefers `can_replace=True` techs but falls back to any active tech (new shops' auto-created owner tech has `can_replace=False`). The customer dashboard merges repairs + replacements into `recent_services` and `pending_approval_replacements`; the legacy repair-only context keys are preserved and asserted by `tests/bug_fixes/test_code141/149/159/168/262`.

**Reward Integration**: Points-based loyalty with referral codes. **Customer-anchored** (Aug 2026): `Reward`/`PointTransaction` key on `core.Customer` — one shared balance per company; customers with no portal accounts earn too. `LoyaltyService.award_points(customer, ...)` takes a Customer (`acting_customer_user=` is optional attribution); returns None if the program is off or `customer.tenant` is None. Awards fire from `loyalty_hook` on job COMPLETED. Shops can redeem on the customer's behalf (customer page / Apply Reward page — creating a redemption is manager/owner-gated). Referrals are recorded PENDING at signup (`/join/<slug>/?ref=CODE`) and pay out on the referred customer's first completed job via `referral_payout_hook`. Invoice/review emails show a balance line gated by `LoyaltyConfig.show_balance_in_emails` + `is_active` (`LoyaltyService.get_email_balance_line`). `RewardOption` objects are tenant-scoped (have a `tenant` FK). `get_reward_options(tenant=...)` filters by tenant. Tests must pass `tenant=` when creating RewardOptions.

**Configure Your Shop** (`/owner/setup/`): Onboarding page where new owners fill in shop info. Includes viscosity auto-populate — selecting windshield type auto-fills viscosity value.

**BillingConfig (per-tenant, fixed CODE-002)**: BillingConfig is now per-tenant via `OneToOneField(Tenant)`. Use `BillingConfig.get_for_tenant(tenant)` — creates with defaults if missing. `get_instance()` raises `RuntimeError`. Migrations: `0013_billingconfig_tenant_fk`, `0014_alter_billingconfig_options`.

**Review Request System**: After a repair completes, `review_request_hook` (`apps/technician_portal/hooks.py`) calls `ReviewRequestService.schedule_review_request`, which queues a Google-review email (per-tenant `ReviewConfig`, Settings → Reviews tab). The `send_review_requests` command (EB cron `12_reviews_cron.config`, every 20 min) sends due requests — concurrency-safe via `select_for_update(skip_locked=True)` (CODE-230). **Fleet accounts are excluded by default** (`ReviewConfig.send_to_fleet=False`, skip_reason `fleet_disabled`) — only RETAIL/WALK_IN customers get requests unless the shop enables the "Include Fleet Accounts" toggle. Note `Customer.customer_type` defaults to `'FLEET'`. Tests that exercise sending must set `send_to_fleet=True` or use a RETAIL customer. See `docs/proposals/review-request-system.md`.

**v2.3 — Subscription Expiry UX**: Grace period, blocked/upgrade page, subscription enforcement middleware, email alerts via `check_subscription_alerts` management command.

**v2.4 — Admin Console Overhaul**: Dashboard widget, tenant filtering, CSV exports, global search, audit log. Tests: `tests/test_admin.py` (41 tests).

### Technician Auto-Assignment

When a new owner signs up (`create_tenant_with_owner`), the service:
1. Creates `User` with username from first_name (not email)
2. Creates `Tenant` with `plan='trial'`, `subscription_status='trialing'`
3. Creates `TenantMembership` (role='owner', is_active=True)
4. Creates `Technician` (is_manager=True, is_active=True)
5. Adds user to 'Technicians' group

**Important**: Username is generated from first_name. Always use `client.force_login(user)` in tests, not `client.login(username=email)`.

---

## Testing Patterns

### Test Setup for Authenticated Views

```python
# WRONG — login(username=email) fails because username = first_name
self.client.login(username='owner@test.com', password='pass123!')

# RIGHT — use force_login
self.client.force_login(self.user)

# Also set tenant in session for subscription middleware
session = self.client.session
session['tenant_id'] = self.tenant.id
session.save()
```

### Creating Test Tenants

Follow `tests/test_e2e_today.py` make_tenant() pattern for consistency:
```python
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants.models import SubscriptionPlan

SubscriptionPlan.objects.get_or_create(
    slug='trial', defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True}
)
result = create_tenant_with_owner(
    business_name='Test Shop', email='owner@test.com',
    password='testpass123!', first_name='Test', last_name='Owner',
)
self.user = result['user']
self.tenant = result['tenant']
self.client.force_login(self.user)
session = self.client.session
session['tenant_id'] = self.tenant.id
session.save()
```

### Testing Tax Behavior

Any test that checks `repair.tax_rate` must create a TaxRate for the tenant:
```python
from apps.billing.models import TaxRate
TaxRate.objects.create(
    tenant=self.tenant, city='Little Rock', state='AR',
    state_rate=Decimal('6.500'), is_active=True,
)
```
Otherwise TaxService finds no rate and sets tax_rate=0.

### Testing Reward Options API

`RewardOption` objects must have `tenant=self.tenant` for the API view (which filters by `request.tenant`) to return them.

---

## Branch Strategy

- `main` — production (AWS Elastic Beanstalk, rssystems.io)
- `autonomous-work` — active development (Amelia's work branch)
- PRs from `autonomous-work` → `main` for production deploys

**When developing autonomously:**
1. Verify `git branch` shows `autonomous-work`
2. Run targeted tests for the changed area
3. Commit with clear message
4. Push to `origin/autonomous-work`
5. Create PR if change is substantial

---

## Deployment to AWS Elastic Beanstalk

```bash
eb deploy        # from repo root on main branch
eb events | head -20
curl -I https://rssystems.io/health/
```

**Deploy workflow:**
1. Commit and push feature branch
2. Merge into `main` via GitHub PR
3. `git checkout main && git pull origin main`
4. `eb deploy`
5. Verify with `curl -I https://rssystems.io/health/`

Required EB environment variable: `DJANGO_SETTINGS_MODULE=rs_systems.settings.production`

Check with `eb printenv`. Fix with `eb setenv DJANGO_SETTINGS_MODULE=rs_systems.settings.production`.

**Common deploy failures:**
- Missing EB env var → `eb setenv` to fix
- New app/middleware not in `base.py` → causes ImportError in production
- Missing package in `requirements.txt`

---

## Environment Variables

```bash
# Required for local dev
SECRET_KEY=...
LOCAL_DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Stripe (paid subscriptions)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# AWS S3 (photos, invoices)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=...
AWS_S3_REGION_NAME=us-east-1

# Amazon SES (email) — SMTP credentials, NOT an AWS access key pair.
# Generate at: SES Console > SMTP settings > Create SMTP credentials
EMAIL_HOST=email-smtp.us-east-1.amazonaws.com
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=notifications@rssystems.io
```

---

## Documentation

- `docs/deployment/AWS_DEPLOYMENT.md` — AWS/EB deployment guide
- `docs/deployment/STRIPE_ARCHITECTURE.md` — platform vs shop (Connect Express) money flows, live price IDs, webhooks, platform fees
- `docs/deployment/PRODUCTION_CHECKLIST.md` — pre/post deploy verification
- `docs/operations/SES_OPERATIONS.md` — email deliverability: auth setup, content rules, verification log
- `docs/security/SECURITY_OVERVIEW.md` — security features
- `docs/security/INCIDENT_RESPONSE.md` — emergency procedures
- `docs/development/TESTING.md` — testing procedures
- `docs/development/CHANGELOG.md` — version history
- `docs/user-guides/` — admin, technician, customer guides
