# RS Systems — Auto Glass Shop Management SaaS

A multi-tenant SaaS platform for auto glass shops. Manage repairs, replacements, customers, technicians, invoicing, and billing — all from one system.

## What It Does

A shop owner signs up, gets a 30-day free trial, and immediately has access to:

- **Repairs** — Track chip/crack repairs with progressive pricing ($50→$40→$35→$30→$25 per unit)
- **Replacements** — Full glass swaps with parts + labor + ADAS calibration pricing
- **Auto-Assignment** — Smart repair assignment: primary tech, workload balancing, round-robin, or manual
- **Customers** — Fleet accounts (trucking companies), retail individuals, and walk-ins with optional primary technician
- **Technicians** — Team management with role-based access and configurable auto-assignment strategies
- **Invoicing** — Auto-generated PDF invoices, email delivery, payment tracking
- **Billing** — Stripe subscriptions with 4 plan tiers, usage tracking, plan enforcement

Every shop gets fully isolated data. Tenant A never sees Tenant B's customers, repairs, or invoices.

---

## Quick Start (Local Testing)

### Prerequisites
- Python 3.12+
- PostgreSQL
- Git

### 1. Clone & switch to the development branch

```bash
git clone git@github.com:wrenchtokeys/rswr_systems.git
cd rswr_systems
git checkout amelia
```

### 2. Set up Python environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Set up the database

**Option A: PostgreSQL (recommended for production-like testing)**

```bash
# Linux — Create a local PostgreSQL database
sudo -u postgres psql -c "CREATE DATABASE rs_systems_local;"
sudo -u postgres psql -c "CREATE USER rs_local WITH PASSWORD 'localpass123';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE rs_systems_local TO rs_local;"
sudo -u postgres psql -c "ALTER USER rs_local CREATEDB;"  # Needed for tests

# macOS (Homebrew) — use psql directly (no `sudo -u postgres` needed)
# brew install postgresql@16 && brew services start postgresql@16
psql postgres -c "CREATE DATABASE rs_systems_local;"
psql postgres -c "CREATE USER rs_local WITH PASSWORD 'localpass123';"
psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE rs_systems_local TO rs_local;"
psql postgres -c "ALTER USER rs_local CREATEDB;"

# Set environment variable
export LOCAL_DATABASE_URL="postgresql://rs_local:localpass123@localhost:5432/rs_systems_local"
```

**Option B: SQLite (quickest local setup — no install needed)**

```bash
# Skip the PostgreSQL setup entirely. Just set:
export LOCAL_DATABASE_URL="sqlite:///db.sqlite3"

# Or simply unset the variable — Django defaults to SQLite automatically:
unset LOCAL_DATABASE_URL
```

> **Note:** SQLite works for quick local testing but doesn't support all PostgreSQL features (e.g., `JSONField` lookups, concurrent writes). Use PostgreSQL for anything beyond basic dev work.

**Troubleshooting: PostgreSQL connection errors**

If you see `Connection refused` or `password authentication failed` when running `migrate`, PostgreSQL is either not running or not configured with the expected user. The fastest fix:

```bash
unset LOCAL_DATABASE_URL
python manage.py migrate
```

This bypasses PostgreSQL entirely and uses SQLite. To make it permanent, remove any `export LOCAL_DATABASE_URL=postgresql://...` line from your `~/.zshrc` or `~/.bashrc`, or replace it with:

```bash
export LOCAL_DATABASE_URL="sqlite:///db.sqlite3"
```

### 4. Run migrations & seed data

```bash
python manage.py migrate
python manage.py seed_plans          # Creates the 4 subscription plans
python manage.py createsuperuser     # Create your admin account
```

### 5. Start the server

```bash
python manage.py runserver 0.0.0.0:8000
```

### 6. Open your browser

| URL | What it is |
|-----|-----------|
| http://localhost:8000/signup/ | **Start here** — create a shop account |
| http://localhost:8000/pricing/ | See the 4 plan tiers |
| http://localhost:8000/admin/ | Django admin (superuser) |

---

## Manual Testing Walkthrough

### The Full Flow (10 minutes)

**1. Sign up as a shop owner:**
- Go to http://localhost:8000/signup/
- Enter: business name, your name, email, password
- Click "Start Your Free Trial"

**2. Complete onboarding:**
- Step 1: Add business info (phone, address) — or skip
- Step 2: Add yourself as a technician — or skip
- Step 3: Add your first customer — or skip
- Step 4: Done! → lands on owner dashboard

**3. Explore the owner dashboard:**
- http://localhost:8000/owner/ — usage meters, quick actions, recent activity
- http://localhost:8000/owner/billing/ — current plan, upgrade options, usage breakdown
- http://localhost:8000/owner/settings/ — business info, team management, invite members

**4. Invite a technician:**
- Go to http://localhost:8000/owner/settings/#team
- Click "Invite Member" → fill in name, email, role = Technician
- Check abilities (can repair, can replace)
- Click "Send Invite" — note the invite URL in the success message
- Open the invite URL in an incognito window: `/invite/<token>/`
- Set a password → auto-routed to technician dashboard

**5. Use the technician portal:**
- http://localhost:8000/tech/ — repair queue, customer list, dashboard
- Create a repair: pick a customer, enter unit number, submit
- Create a replacement: http://localhost:8000/tech/replacement/new/

**6. Invite a customer (portal link):**
- Go to http://localhost:8000/owner/settings/ → "Customer Portal" card
- Click "Copy Link" to copy the shop join URL: `/join/<slug>/`
- Open the link in an incognito window
- Sign up with name, email, (optional company name), password
- Auto-routed to the customer dashboard at `/app/`

**7. Use the customer portal:**
- http://localhost:8000/app/ — customer dashboard with repair tracking
- View repair history, approve/deny pending repairs
- Request new repairs, view rewards

**8. Manage team roles and abilities:**
- Go to http://localhost:8000/owner/settings/#team
- Click "Edit" on any team member → change role, toggle abilities
- "Deactivate" removes a member (soft delete)
- "Resend Invite" for members who haven't accepted yet

**9. Test billing (requires Stripe test keys):**
```bash
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_PUBLISHABLE_KEY="pk_test_..."
export STRIPE_WEBHOOK_SECRET="whsec_..."
```
- Go to http://localhost:8000/owner/billing/
- Click upgrade to subscribe to a paid plan
- Stripe test card: `4242 4242 4242 4242`

### Testing Without Stripe

Everything works without Stripe except subscription creation. The trial plan is fully functional — you can create repairs, customers, replacements, invoices, etc. Stripe is only needed for upgrading from the free trial.

---

## Running on the Amelia Branch (Without Merging to Main)

If you want to test the `amelia` branch on your existing EC2 or local setup:

```bash
# On your machine with the existing RS Systems repo
cd rswr_systems
git fetch origin
git checkout amelia

# Activate your venv
source venv/bin/activate
pip install -r requirements.txt

# Run migrations (safe — won't break existing data, adds new tables)
python manage.py migrate

# Seed subscription plans (idempotent — safe to run multiple times)
python manage.py seed_plans

# Start the server
python manage.py runserver 0.0.0.0:8000
```

**What happens to existing data:**
- All existing customers, repairs, and invoices get assigned to a default tenant ("Rockstar Windshield Repair")
- All existing users get a TenantMembership
- Nothing is deleted or modified — only new fields are added
- You can switch back to `main` at any time (migrations are backward-safe)

---

## Running Tests

```bash
# Set up test database
export LOCAL_DATABASE_URL="postgresql://rs_local:localpass123@localhost:5432/rs_systems_local"

# Run the full test suite (192 tests)
python manage.py test apps.tenants apps.saas apps.billing.tests --verbosity 2

# Run just tenant model tests (fast)
python manage.py test apps.tenants.tests.TenantModelTest

# Run just signup flow tests
python manage.py test apps.saas.tests.SignupFlowTest

# Run security tests
python manage.py test apps.billing.tests.test_api_security
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     RS Systems SaaS                         │
├──────────┬──────────┬───────────┬──────────┬───────────────┤
│  Signup  │  Owner   │ Technician│ Customer │   REST API    │
│  Onboard │ Dashboard│  Portal   │  Portal  │  (DRF + JSON) │
├──────────┴──────────┴───────────┴──────────┴───────────────┤
│              TenantMiddleware (request.tenant)              │
├────────────────────────────────────────────────────────────┤
│  tenants  │  billing │ tech_portal │ customer │  rewards   │
│  (Tenant, │ (Invoice,│  (Repair,   │ (Portal, │ (Points,   │
│  Members, │  Payment,│  Replace,   │  Approve,│  Referrals)│
│  Plans)   │  Stripe) │  Technician)│  Request)│            │
├────────────────────────────────────────────────────────────┤
│              core (Customer, Vehicle, Notifications)       │
├────────────────────────────────────────────────────────────┤
│                PostgreSQL + S3 (tenant-scoped)             │
└────────────────────────────────────────────────────────────┘
```

### Role Hierarchy

```
Owner ─────────── Full access: billing, settings, team management, all data
  │
  ├─ Manager ──── Manage repairs, invite technicians, update abilities
  │
  ├─ Technician ─ Create/manage repairs and replacements (scoped by abilities)
  │
  └─ Viewer ───── Read-only access to dashboard and reports
  
Customer ──────── Portal access: view repairs, approve work, request service
```

### TenantMembership Roles

| Role | Portal | Can Invite | Can Manage Team | Can Manage Billing | Can Do Repairs |
|------|--------|------------|-----------------|-------------------|----------------|
| Owner | Owner Dashboard | ✅ All roles | ✅ Full control | ✅ | Via tech abilities |
| Manager | Owner Dashboard | ✅ Tech/Viewer | ✅ Deactivate tech/viewer | ❌ | Via tech abilities |
| Technician | Tech Portal | ❌ | ❌ | ❌ | ✅ (per abilities) |
| Viewer | Owner Dashboard | ❌ | ❌ | ❌ | ❌ |
| Customer | Customer Portal | ❌ | ❌ | ❌ | Request only |

### Invite Flows

**Team Invite (owner/manager → technician/manager/viewer):**
1. Owner opens Settings → Team → "Invite Member"
2. Fills in name, email, role, abilities
3. System creates User (no password), TenantMembership, Technician record, InviteToken
4. Sends email with `/invite/<token>/` link (7-day expiry)
5. Invitee clicks link → sets password → auto-routed to appropriate portal

**Customer Self-Signup (public join link):**
1. Owner copies shop join link from Settings → Customer Portal card
2. Shares `/join/<slug>/` with customers
3. Customer visits link → sees shop-branded signup page
4. Creates account (name, email, optional company, password)
5. System creates User, Customer, CustomerUser, TenantMembership
6. Auto-logged in → redirected to customer portal at `/app/`

### Apps

| App | Purpose |
|-----|---------|
| `apps/tenants` | Multi-tenant models, middleware, subscription billing |
| `apps/saas` | SaaS UI: signup, onboarding, owner dashboard, pricing |
| `apps/billing` | Invoicing, payments, PDF generation, Stripe integration |
| `apps/technician_portal` | Repair/replacement management, technician workflows |
| `apps/customer_portal` | Customer-facing portal, approvals, repair requests |
| `apps/rewards_referrals` | Loyalty points, referral codes, reward redemption |
| `apps/clawdbot` | Amelia's API namespace (experimental) |
| `apps/security` | Login attempt tracking, rate limiting, audit |
| `core` | Customer model, Vehicle model, notification system |

### Subscription Plans

| Plan | Monthly | Repairs/mo | Technicians | Customers |
|------|---------|------------|-------------|-----------|
| Trial | Free (30 days) | 50 | 2 | 10 |
| Starter | $49 | 200 | 5 | 50 |
| Pro | $99 | Unlimited | 15 | Unlimited |
| Enterprise | $249 | Unlimited | Unlimited | Unlimited |

### Security

- All API endpoints require authentication
- All data queries scoped to current tenant
- CSRF enabled (exempt only Stripe webhooks)
- Rate limiting: 20/min anon, 60/min user, 5/hr signup
- Owner-only access on billing/subscription endpoints
- Stripe webhook signature verification
- Django password validators enforced

### URL Structure

| URL | Access | Purpose |
|-----|--------|---------|
| `/signup/` | Public | Owner registration |
| `/login/` | Public | Unified login (routes by role) |
| `/pricing/` | Public | Plan comparison |
| `/invite/<token>/` | Public | Accept team invite, set password |
| `/join/<slug>/` | Public | Customer self-signup for a shop |
| `/onboarding/` | Auth | Setup wizard (post-signup) |
| `/owner/` | Owner/Manager | Owner dashboard |
| `/owner/billing/` | Owner | Billing management |
| `/owner/settings/` | Owner/Manager | Business info, team, customers |
| `/owner/team/<id>/update/` | Owner | Update member role/abilities |
| `/owner/team/<id>/deactivate/` | Owner/Manager | Deactivate team member |
| `/owner/team/<id>/resend-invite/` | Owner/Manager | Resend invite email |
| `/tech/` | Technician | Repair management |
| `/tech/replacement/new/` | Technician | New replacement |
| `/app/` | Customer | Customer portal |
| `/api/billing/` | Auth | Billing API |
| `/api/tenants/` | Varies | Subscription API |
| `/admin/` | Superuser | Django admin |

---

## Tech Stack

- **Backend:** Django 5.1, Django REST Framework, PostgreSQL
- **Frontend:** Tailwind CSS, Bootstrap, D3.js (visualizations)
- **Payments:** Stripe (subscriptions + invoice payments)
- **Storage:** AWS S3 (photos, invoices)
- **Email:** SendGrid (invoice delivery, notifications)
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
- `main` — production-ready code
- `amelia` — active development (Amelia's branch)
- PRs required to merge into `main`

---

## Documentation

See the [`docs/`](docs/) directory for detailed guides:
- [User Flows](docs/USER_FLOWS.md) — Complete user journeys for every role
- [Developer Guide](docs/DEVELOPER_GUIDE.md)
- [Deployment Guide](docs/deployment/AWS_DEPLOYMENT.md)
- [API Documentation](docs/user-guides/ADMIN_GUIDE.md) — or visit `/api/schema/swagger-ui/`
- [Amelia's Development Log](AMELIA_README.md)

---

*Built for glass shops, by glass shops. 🔧*
