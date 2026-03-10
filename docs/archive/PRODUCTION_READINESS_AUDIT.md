# RS Systems — Production Readiness Audit & Replacement Improvement Recommendations

**Date:** February 17, 2026
**Scope:** Customer signup flow readiness for marketing to glass shops + replacement functionality gaps

---

## Executive Summary

The signup and onboarding flow is **close to production-ready** with strong fundamentals (rate limiting, CSRF, honeypot protection, multi-tenant architecture, Stripe billing). However, there are **5 critical/high-priority gaps** that should be resolved before marketing begins, and the replacement functionality has **significant holes** that limit it as a sellable feature.

**Signup Verdict:** Fix 5 issues, then it's ready for marketing.
**Replacement Verdict:** Needs substantial work — customer portal has zero replacement support, and the owner/tech side is missing edit, list, and tax features.

---

## PART 1: SIGNUP FLOW FINDINGS

### What's Working Well

| Feature | Status | Notes |
|---------|--------|-------|
| Shop owner signup (`/signup/`) | Solid | Creates Tenant + User, starts 30-day trial, redirects to onboarding |
| 4-step onboarding wizard (`/onboarding/`) | Solid | Business info → technician → customer → done. All steps skippable |
| Customer self-signup via shop link (`/join/<slug>/`) | Solid | Cleanest customer path. Shows shop branding, creates CustomerUser |
| Unified login (`/login/`) | Solid | Email OR username, role-based routing to correct portal |
| Rate limiting | Solid | 30/hr on login, 5/hr on registration |
| Security | Solid | CSRF on all forms, honeypot bot trap, login attempt logging, open redirect prevention |
| Stripe billing integration | Solid | Trial tracking, plan limits, checkout flow |

---

### CRITICAL — P0: No Password Reset Flow

**Impact:** Users who forget their password are permanently locked out. Requires manual admin intervention. This is a **hard blocker** for any SaaS product being marketed to external customers.

**Current state:** Zero references to Django's `PasswordResetView` anywhere in the codebase. No "Forgot Password?" link on the login page. No password reset URLs configured.

**What exists that helps:** Django's built-in password reset views handle everything (token generation, email sending, confirmation). SendGrid email is already configured in `base.py`. The `DEFAULT_FROM_EMAIL` is set.

**Recommended fix:**

1. Add 4 URL patterns to `rs_systems/urls.py` using Django's built-in auth views:
   - `/password-reset/` — email entry form
   - `/password-reset/done/` — "check your inbox" page
   - `/password-reset/confirm/<uidb64>/<token>/` — new password form
   - `/password-reset/complete/` — success page

2. Create 6 templates in `templates/registration/` extending `saas/base_public.html`:
   - `password_reset_form.html` — email input form
   - `password_reset_email.html` — email body (plain text)
   - `password_reset_subject.txt` — email subject line
   - `password_reset_done.html` — confirmation page
   - `password_reset_confirm.html` — new password + confirm form
   - `password_reset_complete.html` — success with login link

3. Add "Forgot your password?" link to `templates/saas/login.html` between the password field (line 109) and the submit button (line 111)

**Files to modify:** `rs_systems/urls.py`, `templates/saas/login.html`
**Files to create:** 6 templates in `templates/registration/`
**No migration needed** — uses Django's built-in token generation

---

### HIGH — P1: No Email Verification on Signup

**Impact:** Users can sign up with typo'd or fake emails. Notification emails bounce silently. Email deliverability reputation degrades over time with SendGrid.

**Current state:** The `Customer` model has `email_verified` and `email_verified_at` fields. Verification views exist at `/app/verify-email/` and `/app/verify-email/<uidb64>/<token>/`. But verification is **entirely opt-in** — only accessible from the notification preferences page, never triggered during signup. A user can complete full registration and use the portal indefinitely without verifying.

**Recommended fix:**

1. In `apps/saas/views.py` — `signup_view()`: After `login(request, auth_user)`, send a verification email using the existing token infrastructure. Use `fail_silently=True` so email failures never block signup.

2. In `apps/saas/views.py` — `shop_join_view()`: Same pattern after successful customer creation.

3. **Do NOT gate access on verification** — this kills conversion. Instead, show a persistent dismissible banner on the dashboard: "Please verify your email address. [Resend verification email]"

**Files to modify:** `apps/saas/views.py` (2 locations: `signup_view` and `shop_join_view`)

---

### HIGH — P1: Missing Terms of Service & Privacy Policy Pages

**Impact:** The signup form at `/signup/` already says "By signing up, you agree to our Terms of Service and Privacy Policy" — but these are dead text with no links. This is a legal/compliance gap for a production SaaS product.

**Recommended fix:**

1. Add two views to `apps/saas/views.py`:
   ```python
   def terms_of_service(request):
       return render(request, 'saas/terms_of_service.html')

   def privacy_policy(request):
       return render(request, 'saas/privacy_policy.html')
   ```

2. Add URL patterns to `apps/saas/urls.py`:
   - `/terms/` → `terms_of_service`
   - `/privacy/` → `privacy_policy`

3. Create two templates extending `saas/base_public.html` with standard SaaS legal content covering:
   - **ToS:** Account terms, acceptable use, service availability, termination, liability limits, governing law
   - **Privacy:** Data collected (email, vehicle/repair data, photos), usage purposes, third parties (AWS, SendGrid, Stripe), data retention, user rights, contact info

4. Update `templates/saas/signup.html` line 155 to make the text actual links using `{% url %}` tags

5. Add footer links to `templates/landing.html` and `templates/saas/base_public.html`

**Files to modify:** `apps/saas/views.py`, `apps/saas/urls.py`, `templates/saas/signup.html`
**Files to create:** `templates/saas/terms_of_service.html`, `templates/saas/privacy_policy.html`

---

### MEDIUM — P2: Registration Form Clears on Validation Error

**Impact:** When a validation error occurs on `/app/register/` (e.g., "username taken"), the entire form clears and the user must re-enter all fields. This causes abandonment.

**Current state:** All `messages.error()` branches in `customer_register` (views.py line 854-878) return `render(request, 'customer_portal/register.html')` without passing `request.POST` back. The template has no logic to repopulate fields.

**Recommended fix:**

1. In `apps/customer_portal/views.py` — every error `render()` call in `customer_register`:
   ```python
   return render(request, 'customer_portal/register.html', {
       'form_data': request.POST,
   })
   ```

2. In `templates/customer_portal/register.html` — add `value="{{ form_data.FIELD|default:'' }}"` to each input:
   - `first_name`, `last_name`, `username`, `email`, `referral_code`
   - Do NOT repopulate password fields (security standard)

**Files to modify:** `apps/customer_portal/views.py`, `templates/customer_portal/register.html`

---

### MEDIUM — P2: Stale Branding Across Templates

**Impact:** Prospects seeing "RSWR Systems" or "Rockstar Windshield Repair" on any page will question product quality and professionalism.

**Instances found:**

| File | Line(s) | Current Text | Should Be |
|------|---------|-------------|-----------|
| `templates/customer_portal/register.html` | 3, 10-11, 20-21 | "RSWR Systems" | "RS Systems" |
| `templates/customer_login.html` | 3, 37 | "Rockstar Windshield Repair" | "RS Systems" |
| `templates/login_router.html` | 3, 10 | "Rockstar Windshield Repair" | "RS Systems" |
| `templates/technician_login.html` | 3, 37 | "Rockstar Windshield Repair" | "RS Systems" |
| `templates/registration/register_technician.html` | 3, 37 | "Rockstar Windshield Repair" | "RS Systems" |
| `templates/billing/payment_complete.html` | 7, 44 | "Rockstar Windshield Repair" | "RS Systems" |
| `templates/billing/payment_cancelled.html` | 7, 47 | "Rockstar Windshield Repair" | "RS Systems" |
| `templates/landing.html` | 462 | "&copy; 2025" | "&copy; {% now \"Y\" %}" |

**Files to modify:** 8 template files (find-and-replace, ~15 minutes total)

---

### LOW — P3: Additional Signup Hardening

These are not blockers but worth noting for a future pass:

1. **Profile creation has no rate limiting:** `customer_register` has `@ratelimit(key='ip', rate='5/h', method='POST')` but `profile_creation` has only `@login_required`. A logged-in user could spam company creation.
   - **Fix:** Add `@ratelimit(key='user', rate='10/h', method='POST')` to `profile_creation`

2. **No server-side validation on new company fields:** When `is_new_company == 'yes'`, `company_name` from POST is passed directly to `Customer.objects.create()` without checking it's non-empty. HTML `required` attributes are set by JavaScript and can be bypassed.
   - **Fix:** Add explicit `if not company_name:` check before `Customer.objects.create()`

3. **Password strength is advisory only:** The hint says "mix of letters, numbers, and symbols" but the view only checks `len(password) < 8`. Django's `AUTH_PASSWORD_VALIDATORS` (CommonPasswordValidator, etc.) are never invoked.
   - **Fix:** Call `django.contrib.auth.password_validation.validate_password()` in the view

4. **Landing page loads Tailwind from CDN:** `templates/landing.html` uses `<script src="https://cdn.tailwindcss.com">` which loads the full ~3MB unminified library. For a marketing page, this impacts Core Web Vitals and SEO.
   - **Fix:** Replace with compiled static CSS via `{% static 'css/output.css' %}`

5. **Hardcoded trust bar stats:** Landing page shows "500+ Jobs Tracked" and "$50K+ Invoiced" as static text, not database-driven.
   - **Fix:** Query actual aggregate stats in the landing view and pass to template, or update manually as milestones are hit

---

## PART 2: REPLACEMENT FUNCTIONALITY FINDINGS

### Current Architecture

The `Replacement` model (`apps/technician_portal/models.py:930-1086`) is a **separate model** that shares the `GlassService` abstract base class with `Repair`. It was split from `Repair` in migration `0021` (January 2026). It has glass-specific fields:

| Field | Type | Purpose |
|-------|------|---------|
| `glass_position` | CharField | WINDSHIELD, FRONT_LEFT, REAR, QUARTER_LEFT, SUNROOF, etc. (10 choices) |
| `glass_type` | CharField | OEM or AFTERMARKET |
| `nags_number` | CharField | Industry standard glass part number |
| `parts_cost` | DecimalField | Cost of glass/materials |
| `labor_cost` | DecimalField | Labor cost |
| `requires_adas_calibration` | BooleanField | Does it need ADAS recalibration? |
| `adas_calibration_cost` | DecimalField | ADAS cost if applicable |

**Pricing:** `cost = parts_cost + labor_cost + adas_calibration_cost` (auto-calculated on save)

**Technician capability:** `Technician.can_replace` boolean (default `False`) gates who can be assigned replacements

---

### What's Working

| Feature | Location | Notes |
|---------|----------|-------|
| Create replacement | `/tech/replacement/new/` via `apps/saas/views.py:537` | Full form with glass position, NAGS, pricing, insurance, photos |
| View replacement detail | `/tech/replacement/<pk>/` via `apps/saas/views.py:581` | Read-only detail, tenant-scoped |
| Owner dashboard integration | `apps/saas/views.py:390` | Shows replacement revenue + recent activity |
| Unit details page | `apps/technician_portal/views/customers.py:161` | Shows replacements per unit |
| Batch invoicing | `apps/billing/tasks.py:240-306` | Includes replacements as line items |
| Auto-assignment | `apps/tenants/services/assignment_service.py` | Assigns to `can_replace=True` technicians |
| REST API | `/api/replacements/` | Admin-only CRUD via `ReplacementViewSet` |
| Quick mark-as-replaced | `/tech/customers/<id>/units/<unit>/replace/` | Creates minimal completion record |

---

### GAP 1 — CRITICAL: No Customer Portal Support

**Impact:** Customers have **zero visibility** into their replacement jobs. The customer portal (`apps/customer_portal/`) has no replacement-related code whatsoever. Fleet managers can see their repairs but not their replacements — yet replacements are often the higher-value service.

**What's missing:**
- No replacement list view for customers
- No replacement detail view for customers
- No replacement approval/deny flow (user confirmed they want full approval flow)
- No replacement stats on customer dashboard
- No "Replacements" link in customer portal navigation
- No notifications for replacement status changes

**Recommended fix — Full customer portal replacement support:**

1. **Customer replacement list view** — `apps/customer_portal/views.py`
   - New `customer_replacements` view at `/app/replacements/`
   - Filter by status, paginated (25 per page)
   - Template: `templates/customer_portal/replacements.html` (follow pattern of `repairs.html`)

2. **Customer replacement detail view** — `apps/customer_portal/views.py`
   - New `customer_replacement_detail` view at `/app/replacements/<id>/`
   - Shows glass specs, pricing breakdown (parts + labor + ADAS), photos, status timeline
   - Template: `templates/customer_portal/replacement_detail.html`

3. **Approval flow** — `apps/customer_portal/views.py`
   - New `customer_replacement_approve` and `customer_replacement_deny` views
   - PENDING replacements show approve/deny buttons (same UX as repair approvals)
   - POST-only, CSRF-protected, with confirmation
   - Dashboard "Awaiting Approval" section includes replacements alongside repairs

4. **Navigation update** — `templates/customer_portal/base_customer.html`
   - Add "Replacements" link between "My Repairs" and "Request Repair"

5. **Dashboard stats** — `apps/customer_portal/views.py` (`customer_dashboard`)
   - Add `active_replacements`, `completed_replacements` counts
   - Add replacement-specific "Awaiting Approval" section
   - Template: update `templates/customer_portal/dashboard.html`

6. **URL patterns** — `apps/customer_portal/urls.py`
   ```
   /app/replacements/                → customer_replacements
   /app/replacements/<id>/           → customer_replacement_detail
   /app/replacements/<id>/approve/   → customer_replacement_approve
   /app/replacements/<id>/deny/      → customer_replacement_deny
   ```

**Access control:** All views must filter by `customer=customer_user.customer` to enforce tenant isolation. Use `get_object_or_404(Replacement, id=id, customer=customer)` pattern.

---

### GAP 2 — HIGH: No Replacement Edit or Status Update

**Impact:** After a replacement is created, there is no way to update its status or edit any fields through the UI. Replacements are stuck at their initial status forever (usually PENDING). The only workaround is the Django admin or REST API.

**Current state:** Only two views exist — `replacement_create` and `replacement_detail` (read-only). No `replacement_update` or `replacement_edit` view.

**Recommended fix:**

1. **Status update view** — `apps/saas/views.py`
   - New `replacement_update` POST-only view
   - Accepts `queue_status` parameter, validates against allowed choices
   - Tenant-scoped, owner/manager only
   - URL: `/tech/replacement/<pk>/update/`

2. **Full edit view** (optional but recommended) — `apps/saas/views.py`
   - New `replacement_edit` view using the existing `ReplacementForm`
   - Pre-populates form with current data
   - URL: `/tech/replacement/<pk>/edit/`

3. **Update replacement_detail template** — `templates/saas/replacement_detail.html`
   - Add status transition buttons (e.g., "Move to In Progress", "Mark Complete")
   - Add "Edit" link to the edit view

**Files to modify:** `apps/saas/views.py`, `apps/saas/urls.py`, `templates/saas/replacement_detail.html`
**Files to create:** `templates/saas/replacement_edit.html` (if full edit view)

---

### GAP 3 — HIGH: No Replacement List View

**Impact:** There is no page listing all replacements. The owner dashboard shows only "recent activity" (which is broken — see Gap 6). Owners and managers cannot browse, filter, or search their replacement history.

**Recommended fix:**

1. **List view** — `apps/saas/views.py`
   - New `replacement_list` view at `/tech/replacements/`
   - Tenant-scoped, paginated (25 per page)
   - Filter by status (tabs or dropdown)
   - Columns: Date, Customer, Unit/Vehicle, Glass Position, Status, Cost
   - Each row links to `replacement_detail`
   - "New Replacement" action button

2. **Navigation** — Add "Replacements" link to owner/tech sidebar/nav

**Files to modify:** `apps/saas/views.py`, `apps/saas/urls.py`, owner navigation template
**Files to create:** `templates/saas/replacement_list.html`

---

### GAP 4 — HIGH: No Tax on Replacements

**Impact:** The `Repair` model has full `TaxService` integration (`tax_rate`, `tax_amount`, `total_with_tax`). The `Replacement` model has **none of these fields**. When replacements appear on invoices, they show $0 tax. This means invoices with both repairs and replacements have inconsistent tax treatment.

**Current state:**
- `Repair.save()` calls `TaxService` to calculate `tax_rate` and `tax_amount` on every save
- `Replacement.save()` only calculates `cost = parts + labor + adas` — no tax
- `billing/tasks.py` adds replacement line items at face value with no tax
- `Replacement` model literally does not have `tax_rate` or `tax_amount` fields

**Recommended fix:**

1. **Add fields to Replacement model** — `apps/technician_portal/models.py`
   ```python
   tax_rate = models.DecimalField(max_digits=5, decimal_places=3, default=0)
   tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
   ```
   Add `total_with_tax` property matching Repair's implementation

2. **Add tax calculation to Replacement.save()** — after cost calculation:
   ```python
   from apps.billing.services.tax_service import TaxService
   tax_result = TaxService().calculate_tax(subtotal=self.cost, customer=self.customer)
   self.tax_rate = tax_result['rate']
   self.tax_amount = tax_result['amount']
   ```

3. **Update billing tasks** — `apps/billing/tasks.py` replacement line items should use `total_with_tax`

4. **Update detail template** — show tax row in pricing section

5. **Create migration** — `python manage.py makemigrations technician_portal`

**Architectural note:** Long-term, consider moving `tax_rate`, `tax_amount`, and `total_with_tax` up into the `GlassService` abstract base class so any future service types inherit tax automatically. For now, adding directly to `Replacement` is lower risk.

**Files to modify:** `apps/technician_portal/models.py`, `apps/billing/tasks.py`, `templates/saas/replacement_detail.html`
**New migration required**

---

### GAP 5 — MEDIUM: Rewards Don't Apply to Replacements

**Impact:** The reward/loyalty system only applies to repairs. `Replacement.get_discounted_cost()` is hardcoded to return zero discount. Customers earning points from referrals cannot use them toward replacements.

**Current state:** `Repair.apply_available_rewards()` handles the full discount flow (checks `RewardRedemption`, calculates percentage/fixed/free discount). `Replacement` has a stub that always returns `{'discount': 0, 'final_cost': self.cost, ...}`.

**Recommended fix (confirm business need first):**

Replacements are often insurance-billed where discounts may not apply. Before building this:
- **If rewards should apply to replacements:** Extract the reward application logic from `Repair` into a shared utility function (or mixin on `GlassService`), then call it from both models
- **If rewards should NOT apply:** Document this as intentional in a code comment and leave the stub

**Files to modify (if implementing):** `apps/technician_portal/models.py` (both Repair and Replacement), potentially extract to a service

---

### GAP 6 — MEDIUM: Owner Dashboard Template Bugs

**Impact:** The "Recent Activity" section on the owner dashboard renders broken/empty data for both Repair and Replacement items.

**Root cause:** The template references properties that don't exist on the model objects:

| Template Reference | Actual Model Property | Result |
|---|---|---|
| `item.type` | Does not exist | Renders empty |
| `item.status` | `item.queue_status` | Renders empty |
| `item.status_display` | `item.get_queue_status_display` | Renders empty |
| `item.unit` | `item.unit_number` | Renders empty |
| `item.date` | `item.service_date` | Renders empty |

**Recommended fix:**

1. In `apps/saas/views.py` — `owner_dashboard` view, annotate items after building the merged list:
   ```python
   for item in recent_activity:
       item.item_type = 'Replacement' if isinstance(item, Replacement) else 'Repair'
   ```

2. In `templates/saas/owner_dashboard.html`, fix all 5 property references:
   - `item.type` → `item.item_type`
   - `item.status` → `item.queue_status`
   - `item.status_display` → `item.get_queue_status_display`
   - `item.unit` → `item.unit_number`
   - `item.date` → `item.service_date`

**Files to modify:** `apps/saas/views.py`, `templates/saas/owner_dashboard.html`

---

### GAP 7 — LOW: `mark_unit_replaced` Creates Incomplete Records

**Impact:** The quick "Mark as Replaced" action (`/tech/customers/<id>/units/<unit>/replace/`) creates a `Replacement` record with `cost=0`, `glass_position='WINDSHIELD'`, and no other details. This pollutes the replacement data with incomplete records.

**Current state** (`apps/technician_portal/views/customers.py:217`):
```python
Replacement.objects.create(
    customer=customer, unit_number=unit_number,
    cost=Decimal('0.00'), glass_position='WINDSHIELD',
    queue_status='COMPLETED', ...
)
```

**Recommended fix:** Instead of creating the record inline, redirect to the full replacement form (`replacement_create`) with pre-filled query parameters:
```
/tech/replacement/new/?customer_id=X&unit_number=Y&glass_position=WINDSHIELD
```
This ensures proper pricing, glass details, and NAGS numbers are captured.

**Files to modify:** `apps/technician_portal/views/customers.py`, `apps/saas/views.py` (to accept query params in `replacement_create`)

---

### GAP 8 — LOW: ReplacementForm Missing Vehicle Fields

**Impact:** The `ReplacementForm` in `apps/saas/forms.py:219-316` does not include `vehicle_year`, `vehicle_make`, `vehicle_model`, `technician_notes`, `customer_notes`, or `authorization_number`. These fields exist on the model (inherited from `GlassService`) but aren't exposed in the form.

**Vehicle info is important for replacements** because glass parts are vehicle-specific (the NAGS number depends on year/make/model). Without these fields on the form, technicians must rely on the description field for vehicle details.

**Recommended fix:** Add `vehicle_year`, `vehicle_make`, `vehicle_model` to the form's `Meta.fields` list and add corresponding form UI.

**Files to modify:** `apps/saas/forms.py`, `templates/saas/replacement_form.html`

---

## PART 3: RECOMMENDED PRIORITY ORDER

### Before Marketing Launch (Do These First)

| # | Item | Type | Effort |
|---|------|------|--------|
| 1 | Password reset flow | Signup P0 | 2-3 hrs |
| 2 | Terms of Service + Privacy Policy pages | Signup P1 | 2-3 hrs |
| 3 | Stale branding cleanup (8 templates) | Signup P2 | 15 min |
| 4 | Registration form state preservation | Signup P2 | 30 min |
| 5 | Owner dashboard template bugs | Replacement Gap 6 | 1 hr |

### Near-Term (Before Customers Use Replacements)

| # | Item | Type | Effort |
|---|------|------|--------|
| 6 | Replacement edit/status update view | Replacement Gap 2 | 1-2 hrs |
| 7 | Replacement list view | Replacement Gap 3 | 2 hrs |
| 8 | Tax on replacements | Replacement Gap 4 | 2 hrs |
| 9 | Customer portal replacement views + approval | Replacement Gap 1 | 4-5 hrs |
| 10 | Post-signup email verification | Signup P1 | 1 hr |

### Future Polish

| # | Item | Type | Effort |
|---|------|------|--------|
| 11 | Fix mark_unit_replaced | Replacement Gap 7 | 30 min |
| 12 | Add vehicle fields to replacement form | Replacement Gap 8 | 30 min |
| 13 | Reward integration for replacements | Replacement Gap 5 | 2 hrs |
| 14 | Landing page CDN Tailwind | Signup P3 | 1 hr |
| 15 | Registration hardening (rate limit, password validators) | Signup P3 | 1 hr |

---

## PART 4: KEY FILE REFERENCE

| Area | File | Purpose |
|------|------|---------|
| Central URLs | `rs_systems/urls.py` | Add password reset routes |
| SaaS views | `apps/saas/views.py` | Replacement CRUD, signup, dashboard, ToS/Privacy |
| SaaS URLs | `apps/saas/urls.py` | Replacement + legal page routes |
| SaaS forms | `apps/saas/forms.py:219-316` | `ReplacementForm` |
| Customer views | `apps/customer_portal/views.py` | Registration fix, new replacement views |
| Customer URLs | `apps/customer_portal/urls.py` | New replacement routes |
| Replacement model | `apps/technician_portal/models.py:930-1086` | Tax fields, reward integration |
| Billing tasks | `apps/billing/tasks.py:240-306` | Replacement invoice line items |
| Tax service | `apps/billing/services/tax_service.py` | Tax calculation to reuse |
| Login template | `templates/saas/login.html` | "Forgot password?" link |
| Signup template | `templates/saas/signup.html` | ToS/Privacy links |
| Owner dashboard | `templates/saas/owner_dashboard.html` | Fix broken property references |
| Replacement detail | `templates/saas/replacement_detail.html` | Status buttons, tax row, edit link |
| Customer nav | `templates/customer_portal/base_customer.html` | Add "Replacements" link |
| Customer dashboard | `templates/customer_portal/dashboard.html` | Replacement stats |
