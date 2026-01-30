# RS Systems — Stability & UX Plan

**Author:** Amelia  
**Date:** January 30, 2026  
**Status:** DRAFT — awaiting Drake's review

---

## Who Uses This System?

### The Shop Owner (Drake's #1 customer)
A windshield repair shop owner. Probably runs a small operation — 1 to 5 people. They're often the primary technician too. They signed up because they're tired of paper and texts.

**What they want to do:**
1. Add a customer (a trucking company, a dealership)
2. Log a repair they did
3. See what repairs are pending, completed, owed
4. Send an invoice
5. Eventually: invite a tech to help them

**What they DON'T want to think about:**
- "Portals" — they don't care what URL they're on
- "Access control" — they own the shop, they can do everything
- "Switching contexts" — one interface, everything accessible

**What actually happens today:**
1. They sign up → onboarding wizard → lands on owner dashboard ✓
2. Dashboard has "New Customer" button — great! They click it.
3. **They get bounced to the home page. Looks like they're logged out.** ✗
4. They try "New Repair" — same thing. ✗
5. They try "Tech Portal" in the nav — same thing. ✗
6. They can't do the basic thing they signed up to do.

**Why it fails:** The "New Customer" button links to `/tech/customers/create/` which requires technician access. The owner doesn't have it because the onboarding silently failed to create their technician profile. Even if it DID work, the page shows the wrong navigation (customer portal nav instead of owner nav).

---

### The Technician (employee)
Gets an invite from the shop owner. Sets password, logs in. Needs a focused work interface.

**What they want:**
1. See their assigned repairs
2. Update repair status (completed, in progress)
3. Create new repairs in the field
4. Look up customer info

**What they DON'T need:**
- Billing settings, pricing, team management
- Business analytics, revenue numbers
- Anything about running the shop

**Current experience:** Works OK if the invite flow succeeds. Login routes to `/tech/`. But the invite flow can fail silently too (invite token issues).

---

### The Customer (fleet manager)
Manages a fleet of trucks. Gets their windshields repaired by Drake's shop.

**What they want:**
1. See their repair history
2. Know what's pending, what's done
3. Approve/deny repair requests
4. View and pay invoices

**Current experience:** Join link works. Portal works. But re-login routes them to the owner dashboard instead of their customer portal. (Fixed in local code, not deployed.)

---

## What's Actually Wrong

### Problem 1: Owner Can't Do Anything After Signup
The owner dashboard looks great — revenue cards, usage meters, quick action buttons. But every quick action button leads to a dead end.

**Root cause chain:**
1. Owner signs up → `create_tenant_with_owner()` creates user + tenant + owner membership. **No Technician profile. Not in Technicians group. Not is_staff.** Just a regular user with an owner TenantMembership.
2. Onboarding step 2 says "Add yourself as a technician" with `add_self` checked by default.
3. Owner fills out the form and submits.
4. **BUG:** Even if the form has a validation error, the code advances to step 3. The Technician profile may never be created. The owner doesn't know.
5. Onboarding completes. Owner thinks they're set up.
6. Owner clicks "New Customer" → hits `@technician_required` → decorator checks:
   - `is_staff`? No. 
   - In Technicians group? No (onboarding failed silently).
   - Has Technician profile? No (same).
   - Owner/manager TenantMembership? Yes — but only in my unreleased local code.
7. Decorator rejects them → redirects to `home` (the marketing landing page) → owner thinks they're logged out.

**Even if onboarding succeeds:** The tech portal pages use `base.html` which shows the wrong navigation. It checks `is_superuser or 'Technicians' in groups` to decide which nav to show. SaaS owners who aren't superusers and whose Technicians group membership was silently skipped see the CUSTOMER navigation on tech portal pages. Total confusion.

### Problem 2: Three Portals Is One Too Many (for owners)
The system has:
- `/owner/` — Owner dashboard (billing, settings, analytics)
- `/tech/` — Technician portal (repairs, customers, work)
- `/app/` — Customer portal (their repairs, invoices)

For a technician or customer, this makes sense — they each have a focused view. But for the **owner**, having to switch between `/owner/` (to see revenue) and `/tech/` (to add a customer) is confusing. The owner OWNS everything — they should see it all in one place.

### Problem 3: Access Control Is Checking 5 Different Things
The system has too many ways to identify "what can this user do":

| Check | Where it's used | What it means |
|-------|----------------|---------------|
| `user.is_staff` | `admin_required`, `base.html` nav, various views | Django admin user — SaaS owners DON'T have this |
| `user.is_superuser` | `base.html` nav, logo URL | Django superuser — only the site admin |
| `user.groups (Technicians)` | `base.html` nav, `has_technician_access()` | Added during onboarding/invite — can fail silently |
| `Technician` model exists | `has_technician_access()`, `technician_required` | Created during onboarding — can fail silently |
| `TenantMembership.role` | Middleware, `_get_owner_tenant()`, `owner_or_manager_required` | The actual role system — most reliable |
| `CustomerUser` model exists | `customer_required`, middleware | Links Django user to a Customer record |

These checks disagree constantly. The middleware says "allowed", the decorator says "denied". The nav shows tech links, but the pages reject the user.

### Problem 4: "Redirect to Home" = Perceived Logout
When any access check fails, the user gets sent to `/` — the marketing landing page. This page is designed for anonymous visitors. An authenticated user landing here thinks the system logged them out. It's the worst possible error UX.

---

## The Plan

### Phase 1: Make the Owner's Day-One Work (TOP PRIORITY)
**Goal:** Owner signs up, adds a customer, creates a repair. No errors. No confusion. 30 minutes or less.

This is the critical path. Nothing else matters if the owner can't do basic work.

#### 1.1 Fix onboarding so the owner IS a technician
After signup, the owner needs to be able to do tech work. Period. Don't make them opt in — just do it.

**Changes:**
- In `create_tenant_with_owner()`: automatically create a Technician profile and add to Technicians group. Every owner is also their shop's first technician.
- Remove the confusing "Add yourself as a technician" checkbox from onboarding step 2. Instead, step 2 becomes "Add another technician" (optional — skip if they're solo).
- Fix the step progression bug: only advance to next step on successful save.

**Why:** In the real world, every small shop owner IS their first technician. Making this automatic eliminates the silent failure and the confused state.

#### 1.2 Fix tech portal pages to show correct nav for owners
When an owner visits a `/tech/` page (via Quick Actions buttons on their dashboard), they should see their owner navigation — not the old tech/customer nav from `base.html`.

**Changes:**
- Tech portal templates that owners will commonly use (customer_form, repair_form, repair_list, customer_list) should detect the owner and show owner nav.
- Simplest approach: these templates extend `base.html` → create a new template tag or context variable that picks the right base template based on user role.
- Or: move the most-used forms (create customer, create repair) into the owner portal namespace so they use `base_owner.html` natively.

#### 1.3 Never redirect to home
No authenticated user should ever land on the marketing page as a result of an access denied.

**Changes:**
- `technician_required`: redirect to `owner_dashboard` for owners, `customer_dashboard` for customers
- `customer_required`: redirect to `owner_dashboard` for owners, `technician_dashboard` for techs
- `owner_or_manager_required`: redirect to `technician_dashboard` for techs, `customer_dashboard` for customers
- Middleware: same pattern
- Remove `return redirect('home')` from every decorator for authenticated users

#### 1.4 Owner nav that makes sense
Current owner nav: `Dashboard | Billing | Settings | [Tech Portal]`

Better owner nav: `Dashboard | Customers | Repairs | Billing | Settings`

"Customers" links to the customer list (currently at `/tech/customers/`).
"Repairs" links to the repair list (currently at `/tech/repairs/`).
These pages already exist — we're just putting them in the nav where the owner expects them.

Remove the "Tech Portal" link entirely. The owner doesn't need a separate portal — they have everything.

**Deliverables:** Owner signs up → completes onboarding → clicks "New Customer" → form loads → saves → back to dashboard. No errors, no wrong nav, no dead ends.

---

### Phase 2: Fix Every User's Login Experience
**Goal:** Every user type logs in and lands in the right place. Every time.

#### 2.1 Login routing (already fixed locally, needs deploy)
- Customers → `/app/`
- Technicians → `/tech/`
- Owners/managers → `/owner/`
- Customer with viewer TenantMembership → check CustomerUser first → `/app/`

#### 2.2 Cross-portal access control
Simple rules, enforced consistently:
- **Owners/managers** can access: `/owner/`, `/tech/`, `/app/` (full oversight)
- **Technicians** can access: `/tech/` only
- **Customers** can access: `/app/` only
- **Anonymous** → `/login/`
- **Denied** → redirect to user's correct portal (never to `/`)

#### 2.3 Kill `is_staff` and `is_superuser` as permission checks
Replace every instance of:
- `is_staff` → `is_tenant_admin(user)` (owner/manager OR Django staff)
- `is_superuser or 'Technicians' in groups` → `has_technician_access(user)` or the context processor

This is a search-and-replace across templates AND views. No more dual identity system.

**Deliverables:** Test matrix — every user type logs in, accesses their portal, gets blocked from other portals correctly.

---

### Phase 3: Make It Feel Like One App
**Goal:** The system feels coherent. No "two different apps" feeling.

#### 3.1 Owner sees tech data in their portal
Add to owner dashboard or as separate owner pages:
- **Customers page** (`/owner/customers/`) — list of customers, with "Add Customer" button. Uses `base_owner.html`.
- **Repairs page** (`/owner/repairs/`) — list of all repairs across technicians. Uses `base_owner.html`.
- **Customer detail** (`/owner/customers/<id>/`) — view customer repairs, create invoice.

These can be thin wrappers around existing tech portal views/querysets, just with the owner template.

#### 3.2 Simplify onboarding
Current: 4 steps (Business Info → Add Technician → Add Customer → Done).
Better: 3 steps (Business Info → Add First Customer → You're Ready).

Why remove "Add Technician" step: The owner IS a technician (auto-created in Phase 1). They can invite additional techs later from Settings. For day-one, they just need a customer to bill.

#### 3.3 Smart nav across portals
When an owner navigates to a `/tech/` page (for any feature we haven't moved to `/owner/` yet), the page should:
1. Show the owner nav (Dashboard | Customers | Repairs | Billing | Settings)
2. Have a breadcrumb showing where they are
3. Not feel like they "left" their dashboard

Implementation: context processor checks user role → templates use `{% if is_owner_or_manager %}` to extend `base_owner.html` instead of `base.html`.

#### 3.4 Consistent visual language
All three portals should feel like the same app with different views:
- Same font, colors, spacing
- Same header style
- Tech portal currently uses older `base.html` styling vs owner portal's modern Tailwind

This is a bigger effort — may be a future phase.

**Deliverables:** Owner has Customers and Repairs pages in their own portal. No portal-switching needed for daily work.

---

### Phase 4: Billing That Works
**Goal:** Owner can generate and send invoices from the UI.

#### 4.1 Fix invoice creation (already done locally)
- Error handling hardened ✓
- Tenant parameter fixed ✓
- PDF/S3/Stripe failures don't crash the endpoint ✓

#### 4.2 Invoice UI for owners
- Owner's customer detail page shows "X uninvoiced repairs — Generate Invoice" button
- Invoice history list with statuses
- One-click "Send to customer" (email)

#### 4.3 Payment recording
- Owner can mark invoice as paid (cash, check, Stripe)
- Dashboard shows outstanding balance across all customers

**Deliverables:** End-to-end flow: repairs done → click "Generate Invoice" → PDF created → email sent → payment recorded.

---

### Phase 5: Polish & Testing
**Goal:** Confidence that it works. Prevention of regressions.

#### 5.1 Smoke test script
Automated script that tests every core flow:
1. Sign up → onboarding → dashboard
2. Create customer
3. Create repair
4. Complete repair
5. Generate invoice
6. Invite technician → accept → login
7. Customer join → login → view repairs

#### 5.2 Error handling audit
Every view should:
- Never 500 — always catch exceptions and show meaningful errors
- Never redirect to an inaccessible page
- Show a flash message explaining what happened

#### 5.3 Deployment
Push `amelia` branch → PR → deploy to AWS.

---

## Execution Order

| Step | What | Why First | Time |
|------|------|-----------|------|
| **1** | Fix `create_tenant_with_owner()` to auto-create Technician | Owner's day-one is broken without this | 30 min |
| **2** | Fix onboarding step 2 progression + make "add tech" optional | Prevents incomplete state | 30 min |
| **3** | Fix all decorator redirects (never → home) | Stops the "logged out" feeling | 1 hr |
| **4** | Add Customers + Repairs to owner nav | Owner can find things | 30 min |
| **5** | Deploy to AWS | Get fixes to the real server | 30 min |
| **6** | Fix login routing + cross-portal rules | All users land correctly | 1 hr |
| **7** | Replace is_staff/is_superuser checks | Kill the dual identity system | 2 hrs |
| **8** | Owner customer/repair pages (/owner/customers/, /owner/repairs/) | One-portal experience | 3 hrs |
| **9** | Invoice UI | End-to-end billing | 3 hrs |
| **10** | Smoke tests + error audit | Prevent regressions | 2 hrs |

**Steps 1-5 fix the critical path: ~3 hours.**  
**Steps 6-10 build the complete experience: ~11 hours.**  
**Total: ~14 hours.**

---

## What's Already Done (local, not deployed)
- `d43b5de0` — Middleware overhaul, customer routing fix
- `a3ae8f2f` — Invoice error handling hardened
- `57148ae5` — Onboarding step 4 redirect, rate limit, LOGIN_URL
- `50e846bc` — `@owner_or_manager_required`, conditional tech nav, owners recognized as techs in decorators

---

## Decision Points for Drake

1. **Auto-technician on signup?** I think every owner should automatically be a technician. It's the common case and eliminates the biggest bug. But if you see owners who DON'T do repairs (pure management), we could make it a clear choice during onboarding instead.

2. **Keep or kill the "Tech Portal" link for owners?** My recommendation: kill it. Replace with Customers + Repairs links that go to the same data but feel like part of the owner dashboard. The separate tech portal is for employees only.

3. **Priority — deploy now or build more first?** Steps 1-5 could be done and deployed today. Steps 6-10 are the bigger polish. Your call on which approach.
