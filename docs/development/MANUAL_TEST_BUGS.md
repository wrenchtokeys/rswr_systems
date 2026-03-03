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
- **Status:** 🔴
- **Found:** Little award logos with numbers 1, 2 on viscosity rankings make no sense to users
- **Expected:** Better visual indicator or remove the badge styling entirely. Explain what the rank means.

### BUG-012: Viscosity settings page confusing
- **Severity:** MEDIUM
- **Status:** 🔴
- **Found:** Settings don't explain themselves. New users have no idea what viscosity recommendations are or why they matter.
- **Expected:** Add helper text, tooltips, or an intro paragraph explaining the feature

### BUG-013: Viscosity recommendation not showing on main repair form
- **Severity:** MEDIUM
- **Status:** 🔴
- **Found:** Viscosity recommendation shows on EDIT repair form but NOT on the main CREATE repair form
- **Expected:** Should appear on create form too (or not at all — be consistent)

### BUG-014: Customer company names shown as example placeholders
- **Severity:** MEDIUM
- **Status:** 🟢 FIXED (2026-03-03)
- **Found:** Real customer names (e.g., "EOS Trucking") used as placeholder/example text in form fields
- **Expected:** Use generic examples like "Acme Trucking" or "Your Company Name"
- **Fix:** Changed placeholders in `saas/forms.py` and `customer_form.html` from "EOS Trucking, Penske" to "Acme Trucking, ABC Logistics".

### BUG-015: All settings pages confusing / no self-documentation
- **Severity:** MEDIUM
- **Status:** 🔴
- **Found:** Settings pages across the app don't explain what each option does
- **Expected:** Add help text, tooltips, or inline descriptions for every setting

---

## 🔵 LOW — Minor UX / Nice-to-have

### BUG-016: No alert to assigner when assignee completes a job
- **Severity:** LOW
- **Status:** 🔴
- **Found:** When a tech completes an assigned repair, the person who assigned it gets no notification
- **Expected:** Send notification (in-app + optional email) to assigner when repair is completed

### BUG-017: Repair form includes unnecessary tech fields for assignment
- **Severity:** LOW
- **Status:** 🔴
- **Found:** When assigning a repair, form asks for drill bit, temperature, location, etc. — these are tech-specific fields the assigner wouldn't know
- **Expected:** Assignment should only need: customer, unit, break count, notes. Tech fills in their own fields when they start work.

### BUG-018: Repair form slide architecture is bad
- **Severity:** LOW (but Drake hates it)
- **Status:** 🔴
- **Found:** Main repair form uses a multi-slide/wizard pattern that's frustrating
- **Expected:** Consider a single-page form with sections, or a simpler 2-step flow
- **Note:** Drake specifically said "main repair form sucks and i hate the architecture of slides"

### BUG-019: Email login for invited tech goes to owner dashboard
- **Severity:** LOW (works as designed but confusing)
- **Status:** 🔴
- **Found:** Invited a tech using the shop owner's email. Login via that email goes to owner dashboard.
- **Note:** This is correct behavior (email maps to owner account), but the invite flow should probably prevent inviting an email that's already the owner's.

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
