# RS Systems — Stability & UX Overhaul Plan

**Author:** Amelia  
**Date:** January 30, 2026  
**Status:** DRAFT — awaiting Drake's review

---

## The Problem

The system has grown organically across multiple build phases. Each phase added features (tech portal, customer portal, owner/SaaS portal, billing) but they were built with different access control assumptions. The result:

- Users get redirected to wrong portals or the landing page (feels like logout)
- Owners who aren't technicians can't access features they should
- Owners who ARE technicians don't always get recognized as techs
- Creating customers requires tech portal access that owners may not have
- Cross-portal navigation has gaps
- The overall flow is confusing from a user perspective

**This isn't a bug-by-bug problem. It's an architecture problem.**

---

## Root Causes

### 1. Dual Identity System
Users are identified two ways that can disagree:
- **Model records:** `Technician` model, `CustomerUser` model (existence = access)
- **TenantMembership role:** owner, manager, technician, viewer

Example conflict: An owner signs up → gets TenantMembership(role='owner') → adds self as tech in onboarding → gets Technician model + Technicians group. But the system checks different things in different places:
- Middleware checks TenantMembership
- `@technician_required` checks `is_staff`, then Group, then Technician model, then TenantMembership
- `@customer_required` checks CustomerUser model only
- `_get_owner_tenant()` checks TenantMembership role

**Fix:** One source of truth for "what can this user do?" — TenantMembership role, with model records as supplementary data.

### 2. `is_staff` Gate
The original codebase was single-tenant Django admin. Many checks use `request.user.is_staff` which SaaS owners don't have. We've been replacing these with `is_tenant_admin()` but some remain, and the `admin_required` decorator still checks `is_staff` only.

**Fix:** Audit and replace every `is_staff` check with tenant-aware role checks.

### 3. Onboarding Creates Incomplete State
Step 2 (add technician) has a critical bug: it redirects to step 3 even if the form is invalid. The Technician record, Group membership, etc. may never be created, but the user thinks it worked.

```python
# Current code — redirect is OUTSIDE the if block
elif step == '2':
    form = OnboardingTechnicianForm(request.POST)
    if form.is_valid():
        # ... create technician ...
    request.session['onboarding_step'] = '3'  # ← Always runs!
    return redirect('/onboarding/?step=3')     # ← Always runs!
```

**Fix:** Only advance steps on successful save. Show validation errors.

### 4. Three Competing Access Control Layers
1. **PortalAccessMiddleware** — checks TenantMembership + model records
2. **View decorators** (`@technician_required`, `@customer_required`, `@owner_or_manager_required`) — check their own criteria
3. **`_get_owner_tenant()`** — checks TenantMembership role

These can disagree: middleware allows a request, but the decorator blocks it (or vice versa). When they disagree, users get confusing redirects.

**Fix:** Consolidate into one access control layer. Decorators are the right place (per-view). Middleware should only handle obvious cross-portal violations as a safety net.

### 5. Redirect-to-Home = Perceived Logout
When access is denied, many paths redirect to `home` (the landing/marketing page). This page looks like the user is logged out because it's designed for anonymous visitors. Users think the system logged them out.

**Fix:** Never redirect authenticated users to the landing page. Denied users go to their correct portal with an error message, or to a "no access" page.

### 6. Customer Creation UX
Creating a customer requires navigating to the tech portal (`/tech/customers/create/`). But:
- Owners without tech access can't get there
- Even owners WITH tech access have to switch portals
- There's no customer creation from the owner dashboard

**Fix:** Customer creation should be accessible from the owner portal too.

---

## The Plan

### Phase 1: Fix Access Control Foundation (CRITICAL)
**Goal:** Every user type can access exactly the right portals. No dead ends, no false logouts.

#### 1.1 Unify the permission model
Create a single `get_user_role(user)` function that returns the user's effective role:
```python
def get_user_role(user, tenant=None):
    """Returns: 'superadmin', 'owner', 'manager', 'technician', 'customer', 'viewer', or None"""
```
All decorators and middleware use this one function.

#### 1.2 Fix onboarding step progression
- Only advance to next step on successful save
- Show form validation errors
- Verify Technician + Group are actually created when "add self" is checked
- Add a verification step: after onboarding, confirm the user's state is correct

#### 1.3 Fix decorators to use unified role check
- `@technician_required` → uses `get_user_role()`, owners/managers pass
- `@customer_required` → uses `get_user_role()`, owners/managers pass (oversight)
- `@owner_or_manager_required` → uses `get_user_role()`
- `admin_required` → replace `is_staff` with `get_user_role() in ('owner', 'manager', 'superadmin')`
- All denied redirects go to user's correct portal, never to `/` (home)

#### 1.4 Simplify middleware
Middleware becomes a pure safety net — just prevents cross-portal access for users who bypassed decorators (e.g., direct URL entry). All real access control lives in decorators.

#### 1.5 Fix redirect chains
Map every denied-access scenario and verify the redirect target is accessible:
| User Role | Tries to access | Redirect to |
|-----------|----------------|-------------|
| Owner (no tech) | /tech/ | /owner/ |
| Owner (with tech) | /tech/ | Allow |
| Technician | /owner/ | /tech/ |
| Technician | /app/ | /tech/ |
| Customer | /tech/ | /app/ |
| Customer | /owner/ | /app/ |
| Anonymous | Any portal | /login/ |

**Deliverables:** Updated decorators, middleware, redirect map. Every user type tested.

---

### Phase 2: Fix User Flows End-to-End (HIGH)
**Goal:** Complete every core workflow without errors or confusion.

#### 2.1 Owner signup → onboarding → dashboard
- [ ] Signup creates user + tenant + owner membership ✓
- [ ] Onboarding step 1 (business info) saves correctly
- [ ] Onboarding step 2 (add tech) — fix form validation, ensure tech is created
- [ ] Onboarding step 3 (add customer) — saves correctly
- [ ] Onboarding completes → owner dashboard loads with data
- [ ] Owner sees correct nav (dashboard, billing, settings, tech portal if applicable)

#### 2.2 Owner creates first customer
**Current path:** Owner → Tech Portal → Customers → Create ← too many steps, may not work

**Better path:** Owner dashboard should have a "Add Customer" action that works directly. Options:
1. Add customer creation to owner portal (duplicate the form)
2. Make the tech portal customer creation accessible to owners seamlessly
3. Add a "Quick Actions" section to owner dashboard with common tasks

**Recommendation:** Option 3 — Quick Actions on dashboard with links that work for the user's role.

#### 2.3 Owner creates first repair
Same issue — repair creation is in tech portal. Owner needs to get there smoothly.

#### 2.4 Tech invite → accept → login → work
- [ ] Owner invites tech from settings
- [ ] Tech receives invite link
- [ ] Tech sets password
- [ ] Tech logs in → routed to /tech/
- [ ] Tech can see customers, create repairs, update status

#### 2.5 Customer join → login → view repairs
- [ ] Customer uses join link (/join/<slug>/)
- [ ] Customer account created, auto-logged in
- [ ] Customer re-login routes to /app/ (not /owner/)
- [ ] Customer can view repairs, submit requests, edit company

**Deliverables:** Each flow tested manually. Screenshots or test script.

---

### Phase 3: UX Simplification (MEDIUM)
**Goal:** The system feels like one app, not three separate portals stitched together.

#### 3.1 Owner dashboard as command center
The owner dashboard should be the hub. Add:
- Quick stats (customers, repairs this week, revenue)
- Quick actions: Add Customer, Create Repair, Invite Technician
- Recent activity feed
- Link to tech portal if they're also a tech

#### 3.2 Navigation clarity
- Owner nav: Dashboard | Customers | Repairs | Billing | Settings
- Tech nav: Dashboard | Repairs | Customers | Notifications
- Customer nav: Dashboard | Repairs | Company

Remove confusing cross-portal links. Each portal should feel self-contained.

#### 3.3 Reduce portal-switching
For owner-technicians (most common case for small shops), minimize the need to switch between /owner/ and /tech/. Options:
- Merge the most-used tech features into the owner portal
- Or: seamless portal switch with clear visual indicator

#### 3.4 Error messages that help
Replace generic "You don't have access" with specific guidance:
- "You need to add yourself as a technician to access this. Go to Settings → Team."
- "This page is for shop owners. You're logged in as a technician."

**Deliverables:** Updated templates, navigation, dashboard.

---

### Phase 4: Billing & Invoice Fixes (MEDIUM)
**Goal:** Invoice creation works reliably end-to-end.

#### 4.1 Fix create_invoice error handling
- Wrap all external calls (PDF, S3, Stripe) in try/except ✓ (done)
- Return meaningful JSON errors ✓ (done)
- Add tenant parameter to all service calls ✓ (done)

#### 4.2 Test invoice flow end-to-end
- Create customer → create repair → complete repair → create invoice → verify PDF → verify S3 → verify email

#### 4.3 Owner-friendly invoicing
Currently billing is API-only. Add a UI for:
- Viewing uninvoiced repairs per customer
- One-click "Generate Invoice" from owner dashboard
- Invoice history with status

**Deliverables:** Working invoice flow, UI for common billing tasks.

---

### Phase 5: Testing & Deployment (HIGH)
**Goal:** Changes actually reach the server Drake is testing on.

#### 5.1 Deployment pipeline
- All fixes are on the `amelia` branch locally
- Need to push to remote and deploy to AWS
- Document the deployment process

#### 5.2 Automated smoke tests
Create a test script that validates all core flows:
```bash
# test_flows.sh
# 1. Sign up new owner
# 2. Complete onboarding
# 3. Verify owner can access dashboard, tech portal, create customer
# 4. Invite a technician
# 5. Accept invite, verify tech access
# 6. Create customer join link, join as customer
# 7. Verify customer routing
# 8. Create and complete a repair
# 9. Generate invoice
```

#### 5.3 Regression checklist
Before each deploy, verify:
- [ ] Owner signup → onboarding → dashboard
- [ ] Owner can create customer
- [ ] Owner can create repair  
- [ ] Tech invite → accept → login → /tech/
- [ ] Customer join → login → /app/
- [ ] Cross-portal access blocked correctly
- [ ] Invoice creation doesn't 500

**Deliverables:** Deploy script, smoke test, regression checklist.

---

## Execution Order

| Order | Phase | Est. Effort | Why This Order |
|-------|-------|-------------|----------------|
| 1 | 1.2 — Fix onboarding | 1 hour | Broken onboarding means broken users from the start |
| 2 | 1.1 + 1.3 — Unified permissions | 2 hours | Foundation for everything else |
| 3 | 1.4 + 1.5 — Middleware + redirects | 1 hour | Clean up the safety net |
| 4 | 2.1-2.5 — End-to-end flows | 2 hours | Verify everything works together |
| 5 | 5.1 — Deploy | 30 min | Get fixes to the real server |
| 6 | 3.1-3.4 — UX simplification | 3 hours | Polish after stability |
| 7 | 4.1-4.3 — Billing fixes | 2 hours | Lower priority, API works |
| 8 | 5.2-5.3 — Testing | 1 hour | Prevent regressions |

**Total estimated effort: ~12 hours of focused work**

---

## What's Already Done

Commits on `amelia` branch (not yet deployed):
- `d43b5de0` — Middleware overhaul, customer routing, invoice tenant fix
- `a3ae8f2f` — Invoice error handling hardened
- `57148ae5` — Onboarding redirect, rate limit, LOGIN_URL
- `50e846bc` — `@owner_or_manager_required` decorator, conditional tech portal nav

These address many symptoms but not the root causes listed above. The plan above goes deeper.

---

## Decision Points for Drake

1. **Owner portal scope:** Should owners be able to create customers and repairs directly from /owner/, or is switching to /tech/ acceptable?

2. **Portal merge:** For single-technician shops (owner IS the tech), should we merge the owner and tech portals into one view?

3. **Deployment process:** Can I push to `amelia` branch and you deploy? Or should I prepare PRs for `main`?

4. **Priority:** Is getting the current code deployed more urgent than the deeper refactor?
