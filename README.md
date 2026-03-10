# RS Systems — Auto Glass Shop Management SaaS

A multi-tenant SaaS platform for auto glass shops. Manage repairs, replacements, customers, technicians, invoicing, and billing — all from one system.

## What It Does

A shop owner signs up, gets a 30-day free trial, and immediately has access to:

- **Repairs** — Track chip/crack repairs with configurable progressive pricing ($50→$40→$35→$30→$25 per unit, or flat rate)
- **Replacements** — Full glass swaps with parts + labor + ADAS calibration pricing
- **Auto-Assignment** — Smart repair assignment: primary tech, workload balancing, round-robin, or manual
- **Customers** — Fleet accounts (trucking companies), retail individuals, and walk-ins with primary contact management
- **Technicians** — Team management with role-based access and configurable auto-assignment strategies
- **Invoicing** — Auto-generated PDF invoices, email delivery, payment tracking
- **Billing** — Stripe subscriptions with 4 plan tiers, usage tracking, plan enforcement
- **Customer Portal** — Fleet managers track repairs, approve work, request service, earn reward points
- **Notifications** — 8 repair lifecycle email templates sent automatically as repairs move through the queue
- **Rewards & Referrals** — Points-based loyalty system with referral codes and reward redemption

Every shop gets fully isolated data. Tenant A never sees Tenant B's customers, repairs, or invoices.

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.12+
- PostgreSQL
- Git

### 1. Clone & set up

```bash
git clone git@github.com:wrenchtokeys/rswr_systems.git
cd rswr_systems
git checkout autonomous-work   # active development branch
```

### 2. Python environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Database

**PostgreSQL (recommended):**

```bash
# Linux
sudo -u postgres psql -c "CREATE DATABASE rs_systems_local;"
sudo -u postgres psql -c "CREATE USER rs_local WITH PASSWORD 'localpass123';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rs_systems_local TO rs_local;"
sudo -u postgres psql -c "ALTER USER rs_local CREATEDB;"

export LOCAL_DATABASE_URL="postgresql://rs_local:localpass123@localhost:5432/rs_systems_local"
```

**SQLite (quickest setup — no install needed):**

```bash
# Unset LOCAL_DATABASE_URL and Django falls back to SQLite automatically
unset LOCAL_DATABASE_URL
```

### 4. Initialize

```bash
python manage.py migrate
python manage.py seed_plans        # Creates the 4 subscription plan tiers
python manage.py setup_groups      # Creates Technicians group with permissions
python manage.py createsuperuser   # Admin account
```

### 5. Start

```bash
DJANGO_SETTINGS_MODULE=rs_systems.settings.development python manage.py runserver 0.0.0.0:8000
```

### 6. URLs

| URL | What it is |
|-----|-----------|
| http://localhost:8000/signup/ | **Start here** — create a shop account |
| http://localhost:8000/pricing/ | See the 4 plan tiers |
| http://localhost:8000/admin/ | Django admin (superuser) |

---

## Manual Testing Walkthrough

### The Full Flow (~10 minutes)

**1. Sign up as a shop owner:**
- Go to `/signup/`
- Enter: business name, your name, email, password
- Click "Start Your Free Trial"

**2. Complete onboarding:**
- Step 1: Add business info (phone, address) — or skip
- Step 2: Add a technician — or skip (you already have a tech profile as owner)
- Step 3: Add your first customer — or skip
- Step 4: Done → lands on owner dashboard

**3. Explore the owner dashboard:**
- `/owner/` — usage meters, quick actions, recent activity
- `/owner/billing/` — current plan, upgrade options, usage breakdown
- `/owner/settings/` — business info, team management, customer portal settings

**4. Invite a technician (team invite flow):**
- Owner Settings → Team → "Invite Member"
- Fill in name, email, role = Technician
- Click "Send Invite" → note the invite URL in the success message
- Open `/invite/<token>/` in incognito — set password → auto-routed to technician portal

**5. Use the technician portal:**
- `/tech/` — repair queue, customer list, dashboard
- Create a repair: pick customer, enter unit number, submit
- Repair moves through: REQUESTED → PENDING → APPROVED → IN\_PROGRESS → COMPLETED

**6. Invite a customer to the portal:**
- Owner Settings → Customer Portal card → "Send Invitation" or copy portal link
- Two paths:
  - **Direct invitation:** Enter fleet contact email → they get a personalized invite link with pre-filled info
  - **Self-signup link:** Share `/join/<slug>/` → customer creates their own account
- Invited contacts can be flagged as **primary contact** — they're the default recipient for repair notifications

**7. Use the customer portal:**
- `/app/` — customer dashboard with repair tracking
- View repair history, approve/deny pending repairs
- Request new repairs, view reward points and referral code

**8. Notifications (automatic):**
8 email templates fire automatically as repairs progress:
- `repair_pending_approval` — customer asked to approve a repair
- `repair_approved` / `repair_denied` — tech notified of customer decision
- `repair_assigned` — tech assigned to a repair
- `repair_reassigned_away` — tech notified when reassigned off
- `repair_in_progress` — customer notified when work starts
- `repair_completed` — customer notified on completion
- `batch_approved` — customer approved a multi-break batch

**9. Test billing (requires Stripe test keys):**
```bash
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_PUBLISHABLE_KEY="pk_test_..."
export STRIPE_WEBHOOK_SECRET="whsec_..."
```
- `/owner/billing/` → upgrade to a paid plan
- Stripe test card: `4242 4242 4242 4242`

### Testing Without Stripe

Everything works without Stripe except subscription creation. The trial plan is fully functional — create repairs, customers, replacements, invoices, etc.

---

## Running Tests

```bash
# Set test database
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development

# Full test suite (~331 tests, ~7 minutes)
python manage.py test tests/ -v 1

# Targeted fast tests
python manage.py test tests.test_primary_contact tests.test_e2e_today -v 2

# Specific test files
python manage.py test tests.test_step5_nav
python manage.py test tests.comprehensive.test_user_flow
```

---

## Architecture

```
                    RS Systems SaaS

  Signup  | Owner   | Technician | Customer  | REST API
  Onboard | Dashboard| Portal    | Portal    | (DRF + JSON)

            TenantMiddleware (request.tenant)
         SubscriptionEnforcementMiddleware

  tenants  | billing | tech_portal | customer  | rewards
  (Tenant, | (Invoice,| (Repair,   | (Portal,  | (Points,
  Members, | Payment, | Replace,   | Approve,  | Referrals,
  Plans)   | Stripe)  | Technician)| Invite)   | Redemption)

             core (Customer, Notifications, Vehicles)

              PostgreSQL + S3 (tenant-scoped data)
```

### Role Hierarchy

```
Owner — Full access: billing, settings, team management, all data
  └─ Manager — Manage repairs, invite technicians, update abilities
       └─ Technician — Create/manage repairs (scoped by abilities)
            └─ Viewer — Read-only dashboard access

Customer — Portal access: view repairs, approve work, request service
```

### Tenant Isolation

All data is scoped to the tenant. The middleware stack enforces this:

1. **TenantMiddleware** — resolves `request.tenant` from session/header/membership fallback
2. **SubscriptionEnforcementMiddleware** — blocks access if trial expired or subscription canceled; redirects anonymous authenticated users to login

Every model that belongs to a tenant has a `tenant` FK. Views query with `tenant=request.tenant`. A bug that leaks data across tenants is a serious security issue — see `tests/test_tenant_isolation*.py` for the isolation test suite.

### Invite & Signup Flows

**Team Invite (owner → technician/manager/viewer):**
1. Owner: Settings → Team → "Invite Member"
2. System creates User (no password), TenantMembership, Technician record, InviteToken
3. Email with `/invite/<token>/` link (7-day expiry)
4. Invitee clicks link → sets password → auto-routed to appropriate portal

**Customer Portal Invitation (owner → fleet contact):**
1. Owner: Settings → Customer Portal → "Send Invitation"
2. Enter contact name, email, optionally flag as primary contact
3. System emails personalized `/app/invite/<token>/` link with pre-filled info
4. Contact accepts → creates account → auto-logged into customer portal

**Customer Self-Signup (public join link):**
1. Owner copies shop join link: `/join/<slug>/`
2. Customer visits → shop-branded signup page
3. Creates account → auto-logged in → customer portal at `/app/`

### Primary Contact Management

Each `Customer` (fleet account) can have multiple `CustomerUser` accounts (different employees). One can be marked as **primary contact** (`is_primary_contact=True`). The primary contact is the default recipient for repair lifecycle notifications. Owners can set/change the primary contact from Settings → Customers.

### Notification System

8 repair lifecycle templates fire via `core.services.notification_service`. Templates are seeded in migration `0018_seed_repair_notification_templates`. Each template supports email (SendGrid) with per-user notification preferences. Customer notifications are company-scoped — all `CustomerUser` accounts for a company see the same notification feed.

Preference management: `/app/notifications/preferences/`
History: `/app/notifications/history/`

### Apps

| App | Purpose |
|-----|---------|
| `apps/tenants` | Multi-tenant models, middleware, subscription management |
| `apps/saas` | SaaS UI: signup, onboarding, owner dashboard, pricing |
| `apps/billing` | Invoicing, payments, PDF generation, Stripe integration, tax |
| `apps/technician_portal` | Repair/replacement management, technician workflows |
| `apps/customer_portal` | Customer-facing portal, approvals, repair requests, invitations |
| `apps/rewards_referrals` | Loyalty points, referral codes, reward redemption |
| `apps/security` | Login attempt tracking, rate limiting, audit |
| `apps/clawdbot` | Amelia's API namespace |
| `core` | Customer model, Vehicle model, notification system |

### Subscription Plans

| Plan | Monthly | Repairs/mo | Technicians | Customers |
|------|---------|------------|-------------|-----------|
| Trial | Free (30 days) | 50 | 2 | 10 |
| Starter | $49 | 200 | 5 | 50 |
| Pro | $99 | Unlimited | 15 | Unlimited |
| Enterprise | $249 | Unlimited | Unlimited | Unlimited |

### URL Structure

| URL | Access | Purpose |
|-----|--------|---------|
| `/signup/` | Public | Owner registration |
| `/login/` | Public | Unified login (routes by role) |
| `/pricing/` | Public | Plan comparison |
| `/invite/<token>/` | Public | Accept team invite, set password |
| `/join/<slug>/` | Public | Customer self-signup for a shop |
| `/app/invite/<token>/` | Public | Accept customer portal invitation |
| `/onboarding/` | Auth | Setup wizard (post-signup) |
| `/owner/` | Owner/Manager | Owner dashboard |
| `/owner/billing/` | Owner | Billing management |
| `/owner/settings/` | Owner/Manager | Business info, team, customers |
| `/tech/` | Technician | Repair management |
| `/tech/repairs/create-multi-break/` | Technician | Multi-break batch repair |
| `/app/` | Customer | Customer portal |
| `/app/notifications/` | Customer | Notification history and preferences |
| `/referrals/` | Customer | Rewards and referral system |
| `/api/billing/` | Auth | Billing API |
| `/api/tenants/` | Varies | Subscription API |
| `/admin/` | Superuser | Django admin |

---

## Shop Configuration

### Progressive Pricing

RS Systems supports **progressive pricing** — repair prices decrease with each subsequent repair on a unit:

| Repair # | Price |
|----------|-------|
| 1st | $50 |
| 2nd | $40 |
| 3rd | $35 |
| 4th | $30 |
| 5th+ | $25 |

Configurable at shop level (Settings → Billing) and per-customer (override for specific contract terms).

### Sales Tax

Configure state/county/city tax rates at Settings → Billing → Tax Rates. Tax is calculated automatically on every repair save and applied to invoices via `TaxService`.

### Other Shop Settings

| Setting | Location | Description |
|---------|----------|-------------|
| Auto Invoice | Settings → Billing | Auto-generate invoices on repair completion |
| Sales Tax Rates | Settings → Billing | Configure location-based tax rates |
| Assignment Strategy | Settings → General | How repairs are auto-assigned to techs |
| Customer Portal Link | Settings → Customer Portal | Public signup link for customers |

---

## Tech Stack

- **Backend:** Django 5.1, Django REST Framework, PostgreSQL
- **Frontend:** Tailwind CSS, Bootstrap, D3.js (data visualizations)
- **Payments:** Stripe (subscriptions + invoice payments)
- **Storage:** AWS S3 (photos, invoices)
- **Email:** SendGrid (notifications, invitations, invoices)
- **Deployment:** AWS EC2 + Elastic Beanstalk

---

## Environment Variables

```bash
# Required
SECRET_KEY=your-django-secret-key
LOCAL_DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Stripe (optional — needed for paid subscriptions)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# AWS S3 (optional — for photo/invoice storage)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=...
AWS_S3_REGION_NAME=us-east-1

# SendGrid (optional — for email delivery)
SENDGRID_API_KEY=SG....
```

---

## Development

```bash
# Create migrations after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Check for issues
python manage.py check

# Collect static files (production)
python manage.py collectstatic

# Security audit
python manage.py security_audit
```

### Branch Strategy
- `main` — production (AWS Elastic Beanstalk)
- `autonomous-work` — active development
- PRs required to merge into `main`

---

## Documentation

See the [`docs/`](docs/) directory for detailed guides:
- [Deployment Guide](docs/deployment/AWS_DEPLOYMENT.md)
- [Security Overview](docs/security/SECURITY_OVERVIEW.md)
- [Developer Guide](docs/DEVELOPER_GUIDE.md)
- [User Flows](docs/USER_FLOWS.md)
- [API Docs](docs/user-guides/ADMIN_GUIDE.md) — or visit `/api/schema/swagger-ui/`

---

*Built for glass shops, by glass shops. 🔧*
