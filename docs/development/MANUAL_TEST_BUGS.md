# Manual Test Bugs — Found March 3, 2026

Drake manually tested steps 1–11 of the test plan (up to One-Click Approval/Deny Links).
Below are all issues found, categorized by severity.

**Status:** 🔴 = Not started | 🟡 = In progress | 🟢 = Fixed

---

## 🚨 CRITICAL — Security / Data Integrity

### BUG-001: Cross-tenant customer data leak on repair form
- **Severity:** CRITICAL
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Repair form dropdown shows OTHER glass shops' customers to a new owner
- **Impact:** Full cross-tenant data leakage — can see and select another shop's customers
- **Expected:** Repair form customer dropdown should ONLY show current tenant's customers
- **Root cause:** `RepairForm.customer` used `Customer.objects.all()` (line 229 of forms.py). Technician queryset also unfiltered.
- **Also:** Can add repairs under other shops' customers (data integrity violation)
- **Fix:** RepairForm now accepts `tenant` kwarg, filters both customer and technician querysets. All 4 view callsites updated. Tests in `test_bug_fixes_march.py`.

### BUG-002: No enforcement of trial expiration / subscription cancellation
- **Severity:** CRITICAL
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** App allows continuous use after trial expires and after subscription cancellation
- **Impact:** No revenue enforcement — users can use the platform indefinitely without paying
- **Expected:** After trial expiry or failed payment/cancellation, restrict access to read-only or lock out with upgrade prompt
- **Fix:** New `SubscriptionEnforcementMiddleware` in `apps/tenants/subscription_middleware.py`. Blocks expired trials, canceled, and expired subscriptions. Returns 402 for API, redirects to /pricing/ for HTML. Billing/auth paths exempt. Added to MIDDLEWARE after TenantMiddleware. Tests in `test_bug_fixes_march.py`.

### BUG-003: Tax auto-applied from other shop's settings
- **Severity:** CRITICAL
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** New shop had tax auto-set to Drake's local tax rates instead of zero/unconfigured
- **Impact:** Wrong tax charged to customers of other businesses; cross-tenant config leak
- **Expected:** New tenants should default to `tax_enabled=False` with zero rates. BillingConfig is a singleton — this is likely the root cause (shared across tenants)
- **Root cause:** BillingConfig is a global singleton, NOT tenant-scoped. TaxService read rates from it.
- **Fix:** TaxService rewritten to be tenant-aware. Now accepts `tenant` param and reads from tenant-scoped `TaxRate` model. If tenant has no TaxRate entries → tax disabled (zero). All callers updated (models, invoice_service, invoice_tracking_service). BillingConfig singleton remains for legacy/company-info but tax rates are now per-tenant. Tests in `test_bug_fixes_march.py`.

---

## 🔴 HIGH — Broken Functionality

### BUG-004: Signup crash — `make_random_password` AttributeError
- **Severity:** HIGH
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** "Could not add technician" error during signup when adding self as tech
- **Error:** `no attribute 'make_random_password'`
- **Root cause:** Django 5.x removed `User.objects.make_random_password()`.
- **Where:** `apps/saas/views.py` line 270
- **Fix:** Replaced with `secrets.token_urlsafe(16)`. Grep test in `test_bug_fixes_march.py` ensures it doesn't come back.

### BUG-005: Signup — adding self as tech still requires name fields
- **Severity:** HIGH
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** When owner checks "add myself as technician" during signup, form still requires filling in technician name fields
- **Expected:** Should auto-populate from the owner's name fields already entered, or skip the technician name section entirely
- **Fix:** Made name fields optional in `OnboardingTechnicianForm`. When `add_self` is checked, view creates Technician using the owner's existing user (no new user/name needed). When unchecked, adds a separate technician as before.

### BUG-006: Signup — "Skip for now" button on add-first-customer step doesn't work
- **Severity:** HIGH
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Cannot proceed past the "add first customer" step without entering a customer name
- **Expected:** "Skip for now" should bypass this step and go to dashboard
- **Root cause:** Browser HTML5 validation blocked submit because `customer_name` was required. Skip button is `type="submit"` so browser validated all required fields first.
- **Fix:** Added `formnovalidate` attribute to all 3 skip buttons in `templates/saas/onboarding.html`.

### BUG-007: Change primary tech to owner returns 403 Forbidden
- **Severity:** HIGH
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** On owner dashboard at `/tech/customers`, tried to change a customer's primary technician to the owner — got 403 error page
- **Expected:** Owner should be able to assign any team member (including themselves) as primary tech
- **Root cause:** Missing `{% csrf_token %}` in the primary tech form in `customer_details.html`. Django's CSRF middleware rejects the POST → 403.
- **Fix:** Added `{% csrf_token %}` to the form. Also added tenant filter on Technician lookup to prevent cross-tenant assignment.

### BUG-008: Password reset shows success for non-existent emails
- **Severity:** HIGH (security concern — user enumeration protection vs. UX confusion)
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Entering a bogus email on forgot-password page shows "email is on its way" message
- **Note:** This is actually Django's default behavior BY DESIGN to prevent user enumeration attacks. However, it's confusing UX.
- **Fix:** Changed message to "If an account exists with that email, we've sent a password reset link." This is the standard compromise — prevents user enumeration while not being misleading.

---

## 🟠 MEDIUM — UX / Logic Issues

### BUG-009: Progressive pricing assumed for all shops
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Default pricing tiers ($50/$40/$35/$30/$25) applied automatically — not all shops use progressive pricing
- **Expected:** New shops should either:
  - Be prompted to set their pricing during onboarding, OR
  - Have a clear "set pricing" step before creating repairs, OR
  - Allow entering price directly on the repair form if no pricing is configured
- **Related:** No option to disable progressive pricing per-customer in the UI (model has `use_progressive_pricing` but no UI toggle)
- **Fix:** Added pricing warning banner on repair form when shop is using default pricing (detects if all 5 prices match hardcoded defaults). Links to settings. Also covered by setup checklist (BUG-010).

### BUG-010: New user onboarding lacks setup guidance
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** No tutorial, alerts, or guided setup for new users to configure critical settings (tax, pricing, company info)
- **Expected:** After signup, show a setup checklist or wizard:
  1. Company info & address
  2. Pricing tiers
  3. Tax settings (default to DISABLED with prompt)
  4. First customer
  5. First technician
- **Impact:** Users start using the system with wrong defaults and don't know what to configure
- **Fix:** Added dynamic setup checklist to owner dashboard. Shows incomplete steps: business info, pricing, tax, first customer, first technician. Each step links directly to the relevant settings page. Disappears once all steps are complete.

### BUG-011: Viscosity rank badges (1, 2) confusing
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Little award logos with numbers 1, 2 on viscosity rankings make no sense to users
- **Expected:** Better visual indicator or remove the badge styling entirely. Explain what the rank means.
- **Fix:** Replaced 🥇🥈🥉 medal emojis with simple `#1`, `#2`, `#3` numbering. Added title tooltip explaining "rules are checked top to bottom, first match wins."

### BUG-012: Viscosity settings page confusing
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Settings don't explain themselves. New users have no idea what viscosity recommendations are or why they matter.
- **Expected:** Add helper text, tooltips, or an intro paragraph explaining the feature
- **Fix:** Added explanation box at top of viscosity rules page: "When a technician enters the windshield temperature on a repair form, the system automatically suggests which resin viscosity to use." With example of how rule matching works.

### BUG-013: Viscosity recommendation not showing on main repair form
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Viscosity recommendation shows on EDIT repair form but NOT on the main CREATE repair form
- **Expected:** Should appear on create form too (or not at all — be consistent)
- **Root cause:** Actually reversed — the create wizard had the JS, the edit form (`repair_form.html`) was missing it entirely. The `viscositySuggestion` div existed but no JS to populate it.
- **Fix:** Added viscosity suggestion fetch JS to `repair_form.html`. Now both create and edit forms auto-suggest viscosity when temperature is entered. Only auto-fills if viscosity field is empty (won't overwrite existing values on edit).

### BUG-014: Customer company names shown as example placeholders
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Real customer names (e.g., "EOS Trucking") used as placeholder/example text in form fields
- **Expected:** Use generic examples like "Acme Trucking" or "Your Company Name"
- **Fix:** Changed placeholders in `saas/forms.py` and `customer_form.html` from "EOS Trucking, Penske" to "Acme Trucking, ABC Logistics".

### BUG-015: All settings pages confusing / no self-documentation
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Settings pages across the app don't explain what each option does
- **Expected:** Add help text, tooltips, or inline descriptions for every setting
- **Fix:** Added description text to Business Information section, expanded Progressive Pricing description to explain what it does and when to disable it. Viscosity rules page already fixed in BUG-012.

---

## 🔵 LOW — Minor UX / Nice-to-have

### BUG-016: No alert to assigner when assignee completes a job
- **Severity:** LOW
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** When a tech completes an assigned repair, the person who assigned it gets no notification
- **Expected:** Send notification (in-app + optional email) to assigner when repair is completed
- **Fix:** `_notify_owner_repair_completed` already existed but only notified the owner. Now also notifies all active managers in the tenant (who may have assigned the repair). Skips the tech who completed it and the owner (already notified separately).

### BUG-017: Repair form includes unnecessary tech fields for assignment
- **Severity:** LOW
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** When assigning a repair, form asks for drill bit, temperature, location, etc. — these are tech-specific fields the assigner wouldn't know
- **Expected:** Assignment should only need: customer, unit, break count, notes. Tech fills in their own fields when they start work.
- **Fix:** Added info banner for admins on step 3 of repair wizard: "These fields are optional when assigning a repair. The assigned technician can fill them in later." Fields were already optional at the model level.

### BUG-018: Repair form slide architecture is bad
- **Severity:** LOW (but Drake hates it)
- **Status:** 🟡 DEFERRED — needs design discussion with Drake
- **Found:** Main repair form uses a multi-slide/wizard pattern that's frustrating
- **Expected:** Consider a single-page form with sections, or a simpler 2-step flow
- **Note:** Drake specifically said "main repair form sucks and i hate the architecture of slides"
- **Options to discuss:**
  1. **Single-page form** with collapsible sections (most common pattern for trade apps)
  2. **Two-step flow**: Step 1 = Customer + Unit + Damage Type (required), Step 2 = Everything else (optional, expandable)
  3. **Smart form**: Only show fields relevant to the user's role (admin sees assignment fields, tech sees repair fields)
  4. **Keep wizard but reduce to 3 steps** instead of 6: (1) Who/What, (2) Details, (3) Photos

### BUG-019: Email login for invited tech goes to owner dashboard
- **Severity:** LOW (works as designed but confusing)
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Invited a tech using the shop owner's email. Login via that email goes to owner dashboard.
- **Fix:** Added check in `invite_member` — if the email matches the logged-in owner's email, shows a warning message and suggests using "Add myself" option instead. Prevents the confusing scenario entirely.

---

## Testing Coverage Gap

Manual testing completed through step 11 (One-Click Approval/Deny Links).
Steps 12+ still need testing:
- 12. Invoice Generation & Viewing
- 13. Payment Recording
- 14. Stripe Integration
- 15. Tax Calculation
- 16. Owner Portal & Reports
- 17. Notification System
- 18. Team Management
- 19. Multi-tenant Isolation
- 20. Performance & Edge Cases

---

## Fix Priority Order

1. **BUG-001** — Cross-tenant customer leak (SHIP BLOCKER)
2. **BUG-003** — Cross-tenant tax config leak (SHIP BLOCKER)
3. **BUG-002** — Trial/subscription enforcement (SHIP BLOCKER)
4. **BUG-004** — `make_random_password` crash (BLOCKS SIGNUP)
5. **BUG-006** — Skip button broken (BLOCKS ONBOARDING)
6. **BUG-005** — Tech name fields redundant (BAD ONBOARDING UX)
7. **BUG-007** — Primary tech 403 (BROKEN FEATURE)
8. **BUG-009** — Pricing defaults (WRONG CHARGES)
9. **BUG-010** — Onboarding guidance (USER CONFUSION)
10. Everything else

---

## Round 2 — Code Audit Bugs (March 4, 2026)

Automated code audit of billing services, focusing on multi-tenant isolation,
Stripe integration, and service-layer defense-in-depth.

### BUG-020 — InvoiceTrackingService.get_outstanding_invoices() missing tenant filter
- **Severity:** 🔴 Critical (SHIP BLOCKER)
- **Location:** `apps/billing/services/invoice_tracking_service.py`
- **Issue:** `Invoice.objects.filter(status__in=...)` returned ALL tenants' outstanding invoices
- **Fix:** Use `Invoice.objects.for_tenant(self.tenant)` when tenant is set
- **Status:** ✅ Fixed

### BUG-021 — InvoiceTrackingService.update_overdue_statuses() missing tenant filter
- **Severity:** 🔴 Critical (SHIP BLOCKER)
- **Location:** `apps/billing/services/invoice_tracking_service.py`
- **Issue:** Bulk update of overdue statuses affected ALL tenants' invoices
- **Fix:** Scope queryset to tenant before updating
- **Status:** ✅ Fixed

### BUG-022 — InvoiceTrackingService.get_uninvoiced_repairs() missing tenant filter
- **Severity:** 🟡 Medium
- **Location:** `apps/billing/services/invoice_tracking_service.py`
- **Issue:** `Repair.objects.filter(customer=customer)` didn't also filter by tenant (defense-in-depth)
- **Fix:** Added `repairs = repairs.filter(tenant=self.tenant)` when tenant is set
- **Status:** ✅ Fixed

### BUG-023 — DashboardService.get_alerts() leaks cross-tenant data
- **Severity:** 🔴 Critical (SHIP BLOCKER)
- **Location:** `apps/billing/services/dashboard_service.py`
- **Issue:** Two problems: (1) `CustomerRepairPreference.objects.filter(invoice_preference='batch')` had no tenant filter — returned all tenants' batch customers. (2) `InvoiceTrackingService()` was instantiated without tenant.
- **Fix:** Filter CustomerRepairPreference by `customer__tenant=self.tenant`; pass `tenant=self.tenant` to InvoiceTrackingService
- **Status:** ✅ Fixed

### BUG-024 — StripeService._record_stripe_payment() missing tenant propagation
- **Severity:** 🟡 Medium
- **Location:** `apps/billing/services/stripe_service.py`
- **Issue:** `InvoiceTrackingService()` instantiated without tenant after Stripe webhook payment
- **Fix:** Pass `tenant=invoice.tenant` to InvoiceTrackingService
- **Status:** ✅ Fixed

### BUG-025 — ReminderService uses BillingConfig.objects.first() instead of get_instance()
- **Severity:** 🟢 Low
- **Location:** `apps/billing/services/reminder_service.py`
- **Issue:** `.first()` returns None if no config exists; `get_instance()` creates default
- **Fix:** Changed to `BillingConfig.get_instance()`
- **Status:** ✅ Fixed

### BUG-026 — InvoiceService missing tenant parameter
- **Severity:** 🟡 Medium
- **Location:** `apps/billing/services/invoice_service.py`
- **Issue:** `InvoiceService.__init__()` didn't accept a tenant parameter; `get_completed_repairs()` queried Repair without tenant filter
- **Fix:** Added `tenant=None` parameter; filter repairs by tenant when set
- **Status:** ✅ Fixed

### BUG-027 — send_invoice_email and send_invoice_email_batch views: NameError on Invoice
- **Severity:** 🔴 Critical (CRASH)
- **Location:** `apps/billing/views.py`, `send_invoice_email()` and `send_invoice_email_batch()`
- **Issue:** `Invoice` model was used without importing it — would crash with `NameError` when any user tried to send/resend an invoice email
- **Fix:** Added `from apps.billing.models import Invoice` inside each function
- **Status:** ✅ Fixed

### BUG-028 — InvoiceEmailService missing tenant isolation
- **Severity:** 🟡 Medium
- **Location:** `apps/billing/services/invoice_email_service.py`
- **Issue:** InvoiceEmailService didn't accept tenant parameter; InvoiceLineItem and Invoice queries inside it had no tenant filter
- **Fix:** Added `tenant=None` parameter; propagated to InvoiceService; added tenant filter to InvoiceLineItem and Invoice queries
- **Status:** ✅ Fixed

---

## Round 2 — Code Audit Bugs (March 4, 2026)

Audited by Amelia: billing services, invoice tracking, email, dashboard, Stripe webhook,
multi-tenant isolation in all query paths.

### BUG-020: NameError in send_invoice_email / send_invoice_email_batch views
- **Severity:** HIGH — Runtime crash
- **Location:** `apps/billing/views.py` — `send_invoice_email()` and `send_invoice_email_batch()`
- **Problem:** `Invoice` model used without importing it first. Other functions in the same file import it locally, but these two were missed.
- **Fix:** Added `from apps.billing.models import Invoice` inside both functions.
- **Status:** ✅ FIXED

### BUG-021: Cross-tenant leak in InvoiceTrackingService.get_outstanding_invoices()
- **Severity:** HIGH — Multi-tenant data leak
- **Location:** `apps/billing/services/invoice_tracking_service.py`
- **Problem:** When `self.tenant` is None and no customer is passed, the query returned ALL tenants' invoices.
- **Fix:** Falls back to `customer.tenant` when available, otherwise returns `Invoice.objects.none()`.
- **Status:** ✅ FIXED

### BUG-022: Cross-tenant mutation in InvoiceTrackingService.update_overdue_statuses()
- **Severity:** CRITICAL — Updates ALL tenants' invoices
- **Location:** `apps/billing/services/invoice_tracking_service.py`
- **Problem:** Without tenant, `update_overdue_statuses()` fell back to `Invoice.objects.all()`, marking invoices across ALL tenants as overdue.
- **Fix:** Returns 0 with warning log when called without tenant.
- **Status:** ✅ FIXED

### BUG-023: Cross-tenant collision in InvoiceTrackingService.get_uninvoiced_repairs()
- **Severity:** MEDIUM — Multi-tenant isolation gap
- **Location:** `apps/billing/services/invoice_tracking_service.py`
- **Problem:** `InvoiceLineItem.objects.filter()` query for already-invoiced repairs had no tenant filter, potentially matching invoice line items from other tenants.
- **Fix:** Added `invoice__tenant=tenant` filter.
- **Status:** ✅ FIXED

### BUG-024: No tenant context in Stripe webhook payment recording
- **Severity:** LOW — Documented, not a data leak
- **Location:** `apps/billing/services/stripe_service.py` — `_record_stripe_payment()`
- **Problem:** `Invoice.objects.get(id=invoice_id)` uses no tenant filter. This is acceptable because invoice_id comes from our own Stripe metadata (not user input), but it should be documented.
- **Fix:** Added audit logging of tenant_id when processing Stripe payments.
- **Status:** ✅ DOCUMENTED

### BUG-025: No tenant filter in InvoiceService.build_invoice_data()
- **Severity:** HIGH — Multi-tenant data leak
- **Location:** `apps/billing/services/invoice_service.py`
- **Problem:** `Customer.objects.get(id=customer_id)` had no tenant filter, allowing a service with tenant A context to generate invoices for tenant B's customers.
- **Fix:** Added tenant-scoped query when `self.tenant` is set.
- **Status:** ✅ FIXED

### BUG-026: Dashboard alerts query all tenants' batch customers
- **Severity:** MEDIUM — Multi-tenant isolation gap
- **Location:** `apps/billing/services/dashboard_service.py`
- **Problem:** `CustomerRepairPreference.objects.filter(invoice_preference='batch')` queried all tenants, then filtered after. Without tenant, leaked all results.
- **Fix:** Filter by tenant in initial query; return empty when no tenant.
- **Status:** ✅ FIXED

### BUG-027: InvoiceEmailService lacks tenant awareness
- **Severity:** MEDIUM — Multi-tenant isolation gap
- **Location:** `apps/billing/services/invoice_email_service.py`
- **Problem:** Payment link lookups via `InvoiceLineItem.objects.filter()` and `Invoice.objects.filter()` had no tenant scoping. The service didn't accept a tenant parameter at all.
- **Fix:** Added `tenant` parameter to constructor; scoped all queries. Updated all callers in views.py, saas/views.py, and auto_invoice_service.py.
- **Status:** ✅ FIXED

---

## Round 3 — Systematic Tenant Isolation Sweep (March 4, 2026)

Comprehensive audit of every `.objects.` query across all Python files.

### BUG-029: REST API ViewSets completely unscoped
- **Severity:** CRITICAL — Full cross-tenant data leak via API
- **Location:** `apps/technician_portal/api/views.py`
- **Problem:** All 4 ViewSets (TechnicianViewSet, CustomerViewSet, RepairViewSet, ReplacementViewSet) used hardcoded `queryset = Model.objects.all()` with no tenant filtering. Any authenticated admin user could read/write ALL tenants' data via the REST API.
- **Fix:** Added `TenantScopedViewSetMixin` that overrides `get_queryset()` to filter by `request.tenant`. Applied to all 4 ViewSets.
- **Status:** ✅ FIXED

### BUG-030: Dashboard admin_data shows cross-tenant Technician and RewardRedemption counts
- **Severity:** MEDIUM — Cross-tenant data leak in dashboard stats
- **Location:** `apps/technician_portal/views/dashboard.py`
- **Problem:** `Technician.objects.count()` and `RewardRedemption.objects.filter(status='PENDING').count()` in admin_data block had no tenant filter, showing counts from all tenants.
- **Fix:** Added tenant scoping to both queries using `.filter(tenant=tenant)` and `.filter(reward__customer_user__customer__tenant=tenant)`.
- **Status:** ✅ FIXED

### BUG-031: Dashboard pending RewardRedemption list unscoped for admin users
- **Severity:** MEDIUM — Cross-tenant data leak
- **Location:** `apps/technician_portal/views/dashboard.py`
- **Problem:** `all_pending_redemptions` for non-technician admin users and technician users showed pending redemptions from all tenants.
- **Fix:** Added tenant scoping via `reward__customer_user__customer__tenant` for both code paths.
- **Status:** ✅ FIXED

### BUG-032: RewardFulfillmentService assigns technicians from any tenant
- **Severity:** HIGH — Cross-tenant technician assignment
- **Location:** `apps/rewards_referrals/services.py` — `RewardFulfillmentService.assign_technician()`
- **Problem:** `Technician.objects.all()` selected from all tenants when assigning a technician to fulfill a reward redemption. A tenant B technician could be assigned to fulfill a tenant A customer's reward.
- **Fix:** Extracted tenant from `redemption.reward.customer_user.customer.tenant` and scoped technician query.
- **Status:** ✅ FIXED

### BUG-033: get_pending_redemptions() returns all tenants' redemptions
- **Severity:** LOW — Service method, not directly exposed
- **Location:** `apps/rewards_referrals/services.py` — `RewardFulfillmentService.get_pending_redemptions()`
- **Problem:** No tenant parameter or filtering, returned all tenants' pending redemptions.
- **Fix:** Added optional `tenant` parameter with tenant scoping via `reward__customer_user__customer__tenant`.
- **Status:** ✅ FIXED

### BUG-034: Referral leaderboard shows all tenants' referrers
- **Severity:** MEDIUM — Cross-tenant data leak in leaderboard
- **Location:** `apps/rewards_referrals/views.py` — `referral_leaderboard()`
- **Problem:** `ReferralCode.objects.all()` iterated over all tenants' referral codes, showing a global leaderboard.
- **Fix:** Added `request.tenant` scoping via `customer_user__customer__tenant`.
- **Status:** ✅ FIXED

### BUG-035: Customer portal profile creation falls back to all customers without tenant
- **Severity:** MEDIUM — Cross-tenant data leak in dropdown
- **Location:** `apps/customer_portal/views.py` — profile creation GET handler
- **Problem:** When no tenant context, `Customer.objects.all()` returned all customers across all tenants in the dropdown.
- **Fix:** Changed fallback from `.all()` to `.none()` — no tenant means no customers shown.
- **Status:** ✅ FIXED

### BUG-036: Multiple Customer.objects.all() fallbacks in profile creation POST
- **Severity:** MEDIUM — Cross-tenant data leak in error paths
- **Location:** `apps/customer_portal/views.py` — profile creation POST error handling
- **Problem:** Three separate error-handling paths fell back to `Customer.objects.all()` when no tenant context.
- **Fix:** Changed all three fallbacks from `.all()` to `.none()`.
- **Status:** ✅ FIXED
