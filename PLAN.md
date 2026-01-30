# RS Systems — Complete Redesign Plan

**Author:** Amelia  
**Date:** January 30, 2026  
**Status:** PLAN — for Drake's review before execution

---

## Vision

RS Systems should be the Shopify of windshield repair. A shop owner signs up, adds their first customer in under 5 minutes, and never has to read a manual. Every screen should be obvious. Every action should be one or two clicks away.

**Design principles:**
1. **5-minute time to value** — signup to first logged repair in under 5 minutes
2. **One interface per role** — no portal switching, no confusion
3. **Progressive disclosure** — simple by default, powerful when you dig in
4. **Mobile-first for field work** — techs are in parking lots, not at desks
5. **Zero dead ends** — every click leads somewhere useful or explains why not

---

## The Three Users

### 1. Shop Owner / Manager
*"I run the shop. I need to see everything and do everything."*

This is Drake's primary customer. Usually a small operation (1-5 people). The owner is almost always the first technician too. They signed up to replace paper and texts.

**Their day:**
- Morning: Check what repairs are scheduled, any new customer requests
- During the day: Log repairs as they do them, take photos, note damage types
- End of day: Review completed work, send invoices, check payments
- Weekly: Look at revenue, manage team, follow up on unpaid invoices

**What they need on screen:**
```
┌─────────────────────────────────────────────────────┐
│  RS Systems          Customers  Repairs  Invoices   │
│  [Shop Name]                          Settings  [U] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Good morning, Drake!                               │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ 12       │ │ 3        │ │ $4,250   │            │
│  │ Repairs  │ │ Pending  │ │ Owed     │            │
│  │ this mo  │ │ approval │ │ to you   │            │
│  └──────────┘ └──────────┘ └──────────┘            │
│                                                     │
│  [+ New Repair]  [+ New Customer]  [+ Invoice]      │
│                                                     │
│  Today's Repairs                                    │
│  ┌─────────────────────────────────────────────┐    │
│  │ EOS Trucking  │ Unit 847  │ Star chip │ ✓   │    │
│  │ EOS Trucking  │ Unit 302  │ Bullseye  │ ...  │    │
│  │ Penske        │ Unit 1205 │ Crack     │ ○   │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  Outstanding Invoices                               │
│  ┌─────────────────────────────────────────────┐    │
│  │ INV-001  │ EOS Trucking  │ $1,250 │ 15 days │    │
│  │ INV-003  │ West Tree     │ $375   │ OVERDUE │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Navigation:** `Dashboard | Customers | Repairs | Invoices | Settings`

That's it. Five items. Everything they need.

- **Dashboard** = overview + quick actions + today's work + alerts
- **Customers** = list of all customers, click to see their repairs & invoices, add new
- **Repairs** = all repairs, filter by status/customer/tech/date, add new
- **Invoices** = all invoices, create new, track payments, send reminders
- **Settings** = business info, team management (invite techs), pricing rules, notifications, billing/plan

No "Tech Portal". No "Owner Dashboard" vs "Repair Management". It's all one thing.

### 2. Technician (Employee)
*"I fix windshields. Show me what I need to do today."*

Gets invited by the shop owner. Works in the field. Needs a focused, mobile-friendly interface.

**Their day:**
- Morning: Check assigned repairs for today
- At the job: Pull up customer info, log repair, take photos, mark complete
- Between jobs: Check for new assignments, customer requests to review

**What they need on screen:**
```
┌─────────────────────────────────────────────────────┐
│  RS Systems                              [🔔] [U]   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  My Repairs Today  (3)                              │
│  ┌─────────────────────────────────────────────┐    │
│  │ EOS Trucking  │ Unit 847  │ [Start]         │    │
│  │ Penske        │ Unit 1205 │ [Start]         │    │
│  │ West Tree     │ Unit 009  │ [Start]         │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  [+ Log New Repair]                                 │
│                                                     │
│  Recent Completed                                   │
│  ┌─────────────────────────────────────────────┐    │
│  │ EOS Trucking  │ Unit 302  │ Done today      │    │
│  │ AP&T          │ Unit 155  │ Done yesterday  │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

**Navigation:** `My Repairs | Customers | Notifications`

Three items. That's all a tech needs. Managers get a fourth: `Team`.

### 3. Customer (Fleet Manager)
*"Show me what's been repaired on my trucks and what I owe."*

Gets a link from the shop. Checks in occasionally to see repair status and pay invoices.

**What they need on screen:**
```
┌─────────────────────────────────────────────────────┐
│  RS Systems                              [🔔] [U]   │
│  Rockstar Windshield Repair                         │
├─────────────────────────────────────────────────────┤
│                                                     │
│  EOS Trucking                                       │
│                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ 47       │ │ 2        │ │ $625     │            │
│  │ Repairs  │ │ Pending  │ │ Balance  │            │
│  │ total    │ │ approval │ │ due      │            │
│  └──────────┘ └──────────┘ └──────────┘            │
│                                                     │
│  Needs Your Attention                               │
│  ┌─────────────────────────────────────────────┐    │
│  │ Unit 847  │ Star chip  │ [Approve] [Deny]   │    │
│  │ Unit 302  │ Bullseye   │ [Approve] [Deny]   │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  Recent Repairs                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │ Unit 1205 │ Completed Jan 28 │ $45          │    │
│  │ Unit 009  │ In Progress      │ $45          │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

**Navigation:** `Dashboard | Repairs | Invoices | Company`

Four items. Clean, read-mostly interface.

---

## What's Wrong Today (Structural)

### 1. Three Portals Instead of Three Roles
The system was built as three separate mini-apps:
- `/owner/` — SaaS management (9 views, `base_owner.html` template)
- `/tech/` — Repair work (25+ views, `base.html` template)
- `/app/` — Customer view (20+ views, `base_customer.html` template)

Each has its own base template, its own styling, its own nav, its own access control logic. They don't share anything.

**The problem:** The owner needs features from BOTH `/owner/` and `/tech/`. But switching between them changes the entire UI — different nav, different styling, different feel. And the access control doesn't reliably let them cross.

**The fix:** The owner should have ONE interface that includes everything they need. Customers and Repairs should be part of the owner's nav, not buried in a separate portal.

### 2. Five Identity Systems
The codebase checks "who is this user" in five different, conflicting ways:

| System | Source of truth | Problem |
|--------|----------------|---------|
| `user.is_staff` | Django admin flag | SaaS owners don't have it |
| `user.is_superuser` | Django superuser flag | Only site admin, but used in template nav |
| `user.groups` | Django groups ("Technicians") | Set during onboarding — can fail silently |
| Model records | `Technician`, `CustomerUser` exist? | Created during onboarding — can fail silently |
| `TenantMembership.role` | Tenant role system | The actual intended authority — but not always checked |

**The fix:** `TenantMembership.role` is the single source of truth. Everything else is supplementary data. One function: `get_user_permissions(user, tenant)` → returns what they can do.

### 3. Onboarding That Creates Broken Users
The 4-step wizard has a critical bug: form validation failures silently advance to the next step. The owner thinks they completed setup, but their Technician profile was never created. Then nothing works.

Beyond the bug, the wizard asks the wrong questions at the wrong time:
- Step 2 asks "Add a technician" — confusing. Am I the technician? Do I add someone else? What if I just want to try the app first?
- Step 3 asks "Add a customer" — better, but what if I don't have customer details handy?

**The fix:** Minimal onboarding. Get the owner to their dashboard fast. Let them discover features naturally.

### 4. Templates Are Three Different Apps
- `base.html` — old styling, `<header>` with `<ul>` nav, loads Tailwind via CDN in individual templates
- `base_owner.html` — modern Tailwind, sticky nav, dropdown menus, consistent styling
- `base_customer.html` — modern Tailwind, similar to owner but different color scheme

The tech portal templates extend `base.html` but then load Tailwind via `<script>` tag in `extra_css` blocks. This means every tech page has different Tailwind config. The nav in `base.html` checks `is_superuser` and group membership to decide what to show — wrong for SaaS users.

**The fix:** One unified base template system. Role determines which nav to show, not which base template to extend.

### 5. Dead-End Redirects
When access is denied, users land on the marketing homepage (`/`). For an authenticated user, this page has no navigation to get back to their dashboard. It looks and feels like a logout. Devastating UX.

**The fix:** Authenticated users should NEVER see the marketing page as a result of navigation. Access denied = redirect to their portal with an error message.

---

## The Architecture

### URL Structure

```
# Public (no auth)
/                           → Marketing landing page
/signup/                    → Sign up
/login/                     → Log in
/pricing/                   → Pricing page
/join/<slug>/               → Customer self-signup for a shop

# Owner / Manager (auth + owner/manager role)
/dashboard/                 → Owner dashboard (overview, stats, quick actions)
/customers/                 → Customer list + search
/customers/new/             → Create customer
/customers/<id>/            → Customer detail (repairs, invoices, balance)
/repairs/                   → All repairs (filterable by status, customer, tech, date)
/repairs/new/               → Create repair
/repairs/<id>/              → Repair detail (status, photos, history)
/invoices/                  → Invoice list
/invoices/new/<customer>/   → Create invoice for customer
/invoices/<id>/             → Invoice detail
/team/                      → Team management (invite, roles, abilities)
/team/invite/               → Invite a technician
/settings/                  → Business settings (info, pricing rules, notifications)
/settings/billing/          → Subscription billing (plan, payment method)
/setup/                     → Post-signup setup wizard (minimal)

# Technician (auth + technician role)
/tech/                      → Tech dashboard (my repairs today)
/tech/repairs/              → My repair list
/tech/repairs/new/          → Log a repair
/tech/repairs/<id>/         → Repair detail
/tech/customers/            → Customer list (read-only for regular techs)
/tech/notifications/        → Notifications
/tech/profile/              → My profile

# Customer (auth + customer role)
/my/                        → Customer dashboard (their shop's repairs)
/my/repairs/                → Their repair list
/my/repairs/<id>/           → Repair detail + approve/deny
/my/invoices/               → Their invoices
/my/company/                → Company info edit
/my/notifications/          → Notifications

# API (unchanged)
/api/                       → REST API
/api/billing/               → Billing API
/admin/                     → Django admin (superusers only)
```

**Key changes:**
- Owner pages move from `/owner/` to root-level (`/dashboard/`, `/customers/`, `/repairs/`, etc.) — these are the primary experience
- Customer portal moves from `/app/` to `/my/` — clearer meaning ("my stuff")
- Tech portal stays at `/tech/` — it's the employee interface
- Owner can access `/tech/` pages for oversight, but shouldn't need to for daily work

### Template Architecture

```
templates/
  base_app.html              → Shared foundation (head, fonts, Tailwind, body wrapper)
  
  layouts/
    nav_owner.html           → Owner nav: Dashboard | Customers | Repairs | Invoices | Settings
    nav_tech.html            → Tech nav: My Repairs | Customers | Notifications
    nav_customer.html        → Customer nav: Dashboard | Repairs | Invoices | Company
    shell.html               → Full page shell (uses nav_*.html based on user role)
  
  owner/                     → Owner-specific page content
    dashboard.html
    customer_list.html
    customer_detail.html
    customer_form.html
    repair_list.html
    repair_detail.html
    repair_form.html
    invoice_list.html
    invoice_detail.html
    invoice_create.html
    team.html
    settings.html
    settings_billing.html
    setup.html               → Post-signup setup (replaces onboarding)
  
  tech/                      → Technician-specific page content
    dashboard.html
    repair_list.html
    repair_detail.html
    repair_form.html
    customer_list.html
    notifications.html
    profile.html
  
  customer/                  → Customer-specific page content
    dashboard.html
    repair_list.html
    repair_detail.html
    invoice_list.html
    company.html
    notifications.html
  
  public/                    → Unauthenticated pages
    landing.html
    signup.html
    login.html
    pricing.html
    join.html                → Customer self-signup
    invite_accept.html
```

**One base template** (`base_app.html`) with **one shell** (`shell.html`) that includes the right nav based on user role. No more three different styling systems.

### Permission Model

**Single source of truth:** `TenantMembership.role`

```python
# One function to rule them all
def get_user_role(user, tenant=None):
    """
    Returns the user's effective role for the given tenant.
    
    Priority: owner > manager > technician > customer > viewer > None
    """
    if not user.is_authenticated:
        return None
    
    if user.is_superuser:
        return 'superadmin'
    
    # Get membership
    membership = TenantMembership.objects.filter(
        user=user, tenant=tenant, is_active=True
    ).first() if tenant else TenantMembership.objects.filter(
        user=user, is_active=True
    ).order_by('role').first()
    
    if not membership:
        # Check for CustomerUser without membership (legacy)
        if CustomerUser.objects.filter(user=user).exists():
            return 'customer'
        return None
    
    return membership.role  # 'owner', 'manager', 'technician', 'viewer'

# Three decorators. That's it.
@shop_required          # Must have ANY active TenantMembership (owner/manager/tech)
@owner_required         # Must be owner or manager
@customer_required      # Must be customer (CustomerUser or viewer membership)
```

**Kill:**
- `is_staff` checks (replace with role checks)
- `is_superuser` in templates (replace with role context variable)
- `Technicians` group checks (replace with role checks)
- `has_technician_access()` complex logic (replace with simple role check)
- `admin_required` decorator (replace with `@owner_required`)
- `technician_required` decorator (replace with `@shop_required`)

**Keep:**
- `TenantMembership` model (it's correct)
- `Technician` model (stores tech-specific data like abilities, phone)
- `CustomerUser` model (links Django user to Customer record)
- Middleware for tenant resolution (it works fine)

### Signup & Setup Flow

**Current (broken):**
```
Signup → 4-step wizard → Owner dashboard (can't do anything)
```

**New:**
```
Signup → Dashboard with setup checklist → Productive immediately
```

**Signup form:** Business name, your name, email, password. That's it. 30 seconds.

**What happens on signup:**
1. Create User (not is_staff, not is_superuser)
2. Create Tenant
3. Create TenantMembership(role='owner')
4. Create Technician profile for the user (auto — every owner is their first tech)
5. Log them in, redirect to `/dashboard/`

**Dashboard shows a setup checklist** (dismissible, comes back until complete):
```
Getting Started:
☑ Create your account                    ← done
☐ Add your first customer                ← link to /customers/new/
☐ Log your first repair                  ← link to /repairs/new/
☐ Set your pricing                       ← link to /settings/#pricing
☐ Invite a technician (optional)         ← link to /team/invite/
```

Each item links directly to the relevant page. No wizard. No multi-step form that can fail silently. Just direct links to real pages they'll use every day. The checklist teaches them the interface by using it.

**Why this is better:**
- Owner is productive immediately (the dashboard IS the app)
- No silent failures (each page works independently)
- They learn the nav naturally by completing checklist items
- Optional items (like inviting a tech) don't block required ones
- If they skip the checklist and just start adding repairs, that's fine too

### Data Model

The current data model is actually solid. No changes needed to core models:
- `Tenant` → the shop
- `TenantMembership` → who can access the shop and their role
- `Customer` → fleet account / retail / walk-in
- `Technician` → employee with repair abilities
- `Repair` (extends `GlassService`) → the core work unit
- `Invoice` → billing document linking to repairs
- `CustomerUser` → links a Django user to a Customer (for portal access)

**Small additions:**
- Add `setup_completed` boolean to `Tenant` (hides/shows setup checklist)
- Add `setup_checklist` JSON field to `Tenant` (tracks which steps are done)

### Middleware & Access Control

**TenantMiddleware** (keep as-is): Resolves `request.tenant` from session/header/membership.

**PortalAccessMiddleware** (simplify):
```python
class PortalAccessMiddleware:
    """
    Simple cross-portal guard. The real access control is in decorators.
    This just prevents obvious URL mistakes.
    """
    def process_request(self, request):
        if not request.user.is_authenticated:
            return None
        
        role = get_user_role(request.user, request.tenant)
        path = request.path
        
        # Customers can only access /my/ and public pages
        if role == 'customer' and self._is_shop_page(path):
            return redirect('/my/')
        
        # Techs can only access /tech/ and public pages
        if role == 'technician' and self._is_owner_page(path):
            return redirect('/tech/')
        
        return None
    
    def _is_shop_page(self, path):
        return any(path.startswith(p) for p in 
            ['/dashboard/', '/customers/', '/repairs/', '/invoices/', '/team/', '/settings/', '/tech/'])
    
    def _is_owner_page(self, path):
        return any(path.startswith(p) for p in
            ['/dashboard/', '/invoices/', '/team/', '/settings/'])
```

---

## Execution Plan

### Phase 0: Foundation (Before Any UI Work)
**Goal:** Permission system works. No dead ends. No phantom logouts.

| # | Task | Details | Time |
|---|------|---------|------|
| 0.1 | Create `get_user_role()` function | Single source of truth in `common/auth.py` | 30 min |
| 0.2 | Create `@shop_required`, `@owner_required` decorators | Replace all existing decorators | 1 hr |
| 0.3 | Fix signup to auto-create Technician | In `create_tenant_with_owner()` | 15 min |
| 0.4 | Fix onboarding step progression bug | Only advance on valid form | 15 min |
| 0.5 | Fix ALL redirect-to-home paths | Authenticated users → their portal, never `/` | 1 hr |
| 0.6 | Fix login routing | Customer viewer → `/my/`, owner → `/dashboard/`, tech → `/tech/` | 30 min |
| 0.7 | Replace `is_staff`/`is_superuser` checks | Across all views and templates | 2 hrs |

**Deliverable:** Every user type can log in, reach their portal, and never hit a dead end. ~5.5 hrs.

### Phase 1: Unified Base Template
**Goal:** One visual system. All portals look like the same app.

| # | Task | Details | Time |
|---|------|---------|------|
| 1.1 | Create `base_app.html` | Foundation: head, Tailwind config, Inter font, body wrapper | 1 hr |
| 1.2 | Create `layouts/shell.html` | Page shell with sticky nav, messages, content area | 1 hr |
| 1.3 | Create role-based nav templates | `nav_owner.html`, `nav_tech.html`, `nav_customer.html` | 1 hr |
| 1.4 | Migrate owner templates to new base | `owner_dashboard` → extends `shell.html` | 2 hrs |
| 1.5 | Migrate tech templates to new base | All tech pages → extends `shell.html` | 3 hrs |
| 1.6 | Migrate customer templates to new base | All customer pages → extends `shell.html` | 2 hrs |

**Deliverable:** All pages share one visual system. Nav adapts to role. ~10 hrs.

### Phase 2: Owner Experience
**Goal:** Owner has everything they need at their fingertips. No portal switching.

| # | Task | Details | Time |
|---|------|---------|------|
| 2.1 | New URL structure for owner | `/dashboard/`, `/customers/`, `/repairs/`, `/invoices/`, `/settings/` | 1 hr |
| 2.2 | Owner dashboard redesign | Stats + quick actions + today's work + outstanding invoices + setup checklist | 3 hrs |
| 2.3 | Owner customer list page | All customers with search, repair counts, balance due | 2 hrs |
| 2.4 | Owner customer detail page | Customer info + repairs + invoices + "Create Invoice" button | 2 hrs |
| 2.5 | Owner repair list page | All repairs, filterable by status/customer/tech/date | 2 hrs |
| 2.6 | Owner repair form | Create repair: pick customer, unit, damage, photos. Save and done. | 2 hrs |
| 2.7 | Owner invoice list page | All invoices with status, filters, totals | 2 hrs |
| 2.8 | Owner invoice creation | Select customer → see uninvoiced repairs → generate invoice | 2 hrs |
| 2.9 | Setup checklist (replaces wizard) | Dashboard shows getting-started items, tracks completion | 1 hr |
| 2.10 | Settings consolidation | Business info + team + pricing + subscription in one place | 2 hrs |

**Deliverable:** Complete owner experience. They never need `/tech/`. ~19 hrs.

### Phase 3: Technician Experience
**Goal:** Clean, focused, mobile-friendly tech interface.

| # | Task | Details | Time |
|---|------|---------|------|
| 3.1 | Tech dashboard redesign | Today's repairs + quick actions + recent completed | 2 hrs |
| 3.2 | Tech repair list | My assigned repairs, filterable | 1 hr |
| 3.3 | Tech repair form | Streamlined for field use: customer, unit, damage, photo, save | 2 hrs |
| 3.4 | Tech repair detail | Status update, photos, notes, cost | 1 hr |
| 3.5 | Mobile optimization | Touch targets, swipe actions, camera integration | 3 hrs |
| 3.6 | Manager features | Team view, assign repairs, approve customer requests | 2 hrs |

**Deliverable:** Tech interface is clean and mobile-friendly. ~11 hrs.

### Phase 4: Customer Experience
**Goal:** Customer sees their stuff clearly. Can approve/deny and pay.

| # | Task | Details | Time |
|---|------|---------|------|
| 4.1 | Move customer portal to `/my/` | Update URLs, redirects, nav | 1 hr |
| 4.2 | Customer dashboard redesign | Pending approvals + recent repairs + balance due | 2 hrs |
| 4.3 | Customer repair list | Their repairs with status, photos, history | 1 hr |
| 4.4 | Customer invoice list | Their invoices with pay button (Stripe) | 2 hrs |
| 4.5 | Join flow polish | Clean signup, auto-login, straight to dashboard | 1 hr |

**Deliverable:** Customer portal is clean and useful. ~7 hrs.

### Phase 5: Billing & Invoicing
**Goal:** End-to-end invoicing from the owner interface.

| # | Task | Details | Time |
|---|------|---------|------|
| 5.1 | Invoice creation UI | Owner clicks customer → sees uninvoiced repairs → one-click invoice | 3 hrs |
| 5.2 | Invoice PDF generation | Clean PDF with shop logo, line items, payment instructions | 2 hrs |
| 5.3 | Email delivery | Send invoice via email with PDF attached | 1 hr |
| 5.4 | Payment recording | Mark paid (cash/check/Stripe), partial payments | 1 hr |
| 5.5 | Payment reminders | Automated overdue reminders via email | 1 hr |
| 5.6 | Stripe integration | Customer pays via Stripe checkout link | 2 hrs |

**Deliverable:** Full invoice lifecycle from creation to payment. ~10 hrs.

### Phase 6: Testing & Deployment
**Goal:** Confidence. No regressions.

| # | Task | Details | Time |
|---|------|---------|------|
| 6.1 | Automated smoke tests | Script that validates all core flows | 3 hrs |
| 6.2 | Error handling audit | Every view: no 500s, meaningful errors, helpful messages | 2 hrs |
| 6.3 | Redirect audit | Every access-denied path → user lands somewhere helpful | 1 hr |
| 6.4 | Migration script | Old URLs → new URLs (301 redirects for bookmarks) | 1 hr |
| 6.5 | Deploy to AWS | Push, migrate, verify | 1 hr |

**Deliverable:** Production deployment with confidence. ~8 hrs.

---

## Timeline

| Phase | Description | Effort | Priority |
|-------|-------------|--------|----------|
| **0** | Foundation (permissions, signup, redirects) | ~5.5 hrs | **CRITICAL** — nothing works without this |
| **1** | Unified base template | ~10 hrs | **HIGH** — stops the "three different apps" feel |
| **2** | Owner experience | ~19 hrs | **HIGH** — this IS the product |
| **3** | Technician experience | ~11 hrs | **MEDIUM** — works today, needs polish |
| **4** | Customer experience | ~7 hrs | **MEDIUM** — works today, needs restructure |
| **5** | Billing & invoicing | ~10 hrs | **MEDIUM** — important but not day-one blocker |
| **6** | Testing & deployment | ~8 hrs | **HIGH** — nothing matters if it's not deployed |

**Total: ~70 hours of focused work.**

**Recommended order:** Phase 0 → Phase 1 → Phase 2 → Phase 6 → Phase 3 → Phase 4 → Phase 5

Phase 0 + 1 + 2 gives us a working owner experience (~35 hrs). Deploy that. Then iterate.

---

## What We Keep vs. Replace

### Keep (working and well-built)
- Data models (Customer, Repair, Invoice, Technician, Tenant, etc.)
- Tenant middleware (resolves request.tenant)
- Billing services (InvoiceTrackingService, DashboardService, etc.)
- Email services and templates
- API endpoints (/api/)
- Signup service (create_tenant_with_owner — just add auto-technician)
- Rewards/referrals system
- Pricing engine (viscosity rules, damage type pricing)

### Rebuild (structurally broken)
- Permission decorators (5 overlapping systems → 3 clean ones)
- Base templates (3 different styling systems → 1 unified)
- Owner views (separate portal → integrated experience)
- Onboarding wizard (4-step form → setup checklist)
- Portal middleware (complex redirect logic → simple role guard)
- Template nav logic (checks is_staff/is_superuser → checks role)

### Retire (no longer needed after rebuild)
- `base.html` (replaced by `base_app.html` + `shell.html`)
- `base_owner.html` (merged into unified shell)
- `admin_required` decorator (replaced by `@owner_required`)
- `technician_required` decorator (replaced by `@shop_required`)
- Old onboarding wizard templates and views
- `/owner/` URL prefix (replaced by root-level URLs)
- `/app/` URL prefix (replaced by `/my/`)

---

## Non-Negotiables

1. **Every signed-in click leads somewhere useful.** No dead ends. No phantom logouts. No "access denied" with no explanation.

2. **Owners never NEED the tech portal.** Everything is in their interface. Tech portal exists for employees only.

3. **One visual language.** Every page looks like the same app regardless of who's viewing it.

4. **5-minute time to value.** Signup → add customer → log repair in under 5 minutes. No mandatory wizard.

5. **Mobile works.** Techs are in parking lots. Touch targets, readable text, camera access.

---

*This plan replaces all previous planning documents. Ready for Drake's review before execution.*
