# Critical Audit — January 29, 2026

## 🔴 CRITICAL Security Issues

### 1. Billing API has ZERO authentication
**Location:** `apps/billing/views.py` — ALL 15+ endpoints
**Problem:** Every billing endpoint (`/api/billing/*`) has `@csrf_exempt` and no `@login_required` or `IsAuthenticated`. Anyone on the internet can:
- View the billing dashboard
- Create invoices for any customer
- Record payments
- Cancel invoices
- Send payment reminders
- Access Stripe checkout sessions
**Fix:** Add `@login_required` + tenant scoping to all endpoints. Keep `@csrf_exempt` only on the Stripe webhook.

### 2. Clawdbot API has ZERO authentication
**Location:** `apps/clawdbot/views.py`
**Problem:** All clawdbot endpoints are public. Anyone can list customers, repairs, generate PDFs.
**Fix:** Add authentication. These were originally meant for internal use but are now exposed.

### 3. Billing & Clawdbot APIs are NOT tenant-scoped
**Location:** Both `apps/billing/views.py` and `apps/clawdbot/views.py`
**Problem:** Even with auth added, queries are unscoped: `Customer.objects.all()`, `Repair.objects.all()`. A user from Tenant A could see Tenant B's data.
**Fix:** Filter all queries by `request.tenant`.

### 4. Technician portal is NOT tenant-scoped
**Location:** `apps/technician_portal/views/*.py`
**Problem:** Queries like `Repair.objects.all()`, `Customer.objects.all()` in dashboard, repair list, customer list — no tenant filtering.
**Fix:** Add `.filter(tenant=request.tenant)` to all queries.

### 5. Customer portal is NOT tenant-scoped
**Location:** `apps/customer_portal/views.py`
**Problem:** Same as technician portal — `Customer.objects.all()`, `Repair.objects.filter(customer=customer)` without tenant checks.
**Fix:** Filter by tenant.

### 6. `@csrf_exempt` on non-webhook billing endpoints
**Location:** `apps/billing/views.py` lines 109, 288, 350, 470, 529, 594, 623, 651
**Problem:** `create_invoice`, `record_payment`, `cancel_invoice`, `update_invoice_preferences`, `create_checkout_session`, `create_payment_link`, `send_reminder`, `process_all_reminders` all have `@csrf_exempt`. This is a CSRF vulnerability.
**Fix:** Remove `@csrf_exempt` from all non-webhook endpoints. Use DRF token auth or session auth instead.

### 7. Replacement detail has weak tenant check
**Location:** `apps/saas/views.py` `replacement_detail()`
**Problem:** `if tenant and replacement.tenant_id and replacement.tenant_id != tenant.id` — if either is None, the check passes. A user without tenant context can view any replacement.
**Fix:** Strict check — deny if tenant is None or doesn't match.

## 🟡 Architecture Issues

### 8. Duplicated signup logic
**Problem:** `POST /api/tenants/signup/` (API in `apps/tenants/views.py`) and `/signup/` (UI form in `apps/saas/views.py`) both create tenants with completely separate code paths.
**Fix:** Extract shared signup service, call from both.

### 9. No login routing for owners
**Problem:** After signup, owners get redirected to onboarding. But returning owners who log in via `/tech/login/` or `/app/login/` end up in the wrong portal.
**Fix:** Add login routing that detects owner role and redirects to `/owner/`.

### 10. Version number stale
**Problem:** Status endpoint shows version 0.6.0 but we're at 0.8+ now.
**Fix:** Update.

## 🟢 Testing Gaps

### 11. Zero automated tests for new code
**Problem:** No tests for: saas app, tenants app, billing security, tenant scoping, signup flow, onboarding, owner dashboard, replacement form, subscription management.
**Fix:** Comprehensive test suite.

## 📝 Documentation

### 12. AMELIA_README.md needs full overhaul
**Problem:** Partially updated but doesn't reflect current architecture, all phases complete, or the UI that was built.
