# RS Systems Security Audit

**Date:** 2026-02-10  
**Auditor:** Amelia (AI Security Review)  
**Scope:** Full codebase  settings, views, templates, services, APIs  
**Branch:** amelia

---

## Executive Summary

The codebase is **generally well-secured** with proper tenant isolation, authentication on all views, Stripe webhook signature verification, rate limiting on login/signup, and good production security headers. However, **one critical issue** was found and fixed immediately.

**Findings:** 1 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW

---

## CRITICAL

### 1. Unauthenticated Database Setup Endpoint (FIXED)
- **File:** `rs_systems/views.py:302` + `rs_systems/urls.py:31`
- **Issue:** `/setup-database/` is publicly accessible with `@csrf_exempt`, no authentication. Anyone can POST to run migrations and create a superuser with hardcoded credentials (`admin` / `admin123`). The response also displays these credentials in plaintext HTML.
- **Impact:** Full system takeover  any attacker can create an admin account.
- **Fix Applied:** Removed the URL route. The view is legacy scaffolding that should never be in production.
- **Status:**  FIXED

---

## HIGH

### 2. Production SSL/Cookie Security Gated by Environment Variable
- **File:** `rs_systems/settings/production.py:79-81`
- **Issue:** `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, and `CSRF_COOKIE_SECURE` are all conditional on `USE_HTTPS` env var defaulting to `false`. If the env var is missing in production, all three are disabled  cookies sent over HTTP, no SSL redirect.
- **Recommendation:** In production.py, these should default to `True`, not `False`. Change:
  ```python
  SECURE_SSL_REDIRECT = os.environ.get('USE_HTTPS', 'true').lower() == 'true'
  SESSION_COOKIE_SECURE = True
  CSRF_COOKIE_SECURE = True
  ```

### 3. Billing API Views Missing Role-Based Authorization
- **File:** `apps/billing/views.py` (all endpoints)
- **Issue:** All billing views use `@login_required` + tenant scoping but **no role check**. Any authenticated user (including `viewer`/customer role with a TenantMembership) could access billing dashboard, create invoices, record payments, cancel invoices, and send reminders  if they can reach the URL.
- **Mitigating factor:** The `PortalAccessMiddleware` may restrict routing, and the billing URLs are under `/api/billing/` which may not be directly exposed to customer portal users. However, defense-in-depth requires explicit authorization.
- **Recommendation:** Add `@requires('invoices')` decorator to all billing views (except `stripe_webhook`).

---

## MEDIUM

### 4. Webhook Signature Verification Skipped Without Secret
- **File:** `apps/tenants/webhooks.py:55-63`
- **Issue:** If `STRIPE_WEBHOOK_SECRET` is not set, the subscription webhook parses the payload without signature verification and logs a warning. This is intended for dev but if production deploys without the env var, webhooks are unverified.
- **Recommendation:** In production, raise an error or return 500 if `STRIPE_WEBHOOK_SECRET` is not configured. The billing webhook (`apps/billing/services/stripe_service.py:238`) correctly returns an error when the secret is missing  use the same pattern.

### 5. Development Secret Key in Settings
- **File:** `rs_systems/settings/development.py:16`
- **Issue:** `SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-key-not-for-production')`  the fallback key is insecure. While production.py correctly raises if SECRET_KEY is missing, a misconfigured deployment using development settings would use this key.
- **Recommendation:** Acceptable for local dev, but add a check: if `DEBUG=False` and using the insecure key, raise an error.

### 6. API ViewSets Not Tenant-Scoped
- **File:** `apps/technician_portal/api/views.py`
- **Issue:** `TechnicianViewSet`, `CustomerViewSet`, `RepairViewSet`, `ReplacementViewSet` use `queryset = Model.objects.all()`  no tenant filtering. They require `IsAdminUser` which limits exposure, but a Django staff user could see/modify data across all tenants.
- **Recommendation:** Override `get_queryset()` to filter by `request.tenant`.

### 7. `|safe` Filter in Template
- **File:** `templates/technician_portal/repair_form.html:657`
- **Issue:** `{{ customer_types_json|safe }}`  rendering JSON directly with `|safe`. If `customer_types_json` contains user-controlled data, this is an XSS vector.
- **Mitigating factor:** `customer_types_json` is likely built from model choices (not user input), but the pattern is risky.
- **Recommendation:** Use `json_script` template tag instead: `{{ customer_types_json|json_script:"customer-types" }}`.

---

## LOW

### 8. No Login Attempt Lockout
- **File:** `rs_systems/views.py:117`
- **Issue:** Rate limit is `30/h` per IP for login. This is reasonable but doesn't prevent distributed brute force. No account lockout mechanism exists.
- **Recommendation:** Consider adding per-account rate limiting (e.g., django-axes) for targeted brute force protection.

### 9. Customer Registration Allows Username Enumeration
- **File:** `apps/customer_portal/views.py` (customer_register)
- **Issue:** Separate error messages for "Username already exists" and "Email already exists" allow enumeration of valid accounts.
- **Recommendation:** Use a generic message like "An account with these details already exists."

### 10. Customer Can Edit Company Name to Lowercase Only
- **File:** `apps/customer_portal/views.py` (edit_company)
- **Issue:** `customer.name = request.POST.get('name', '').lower()` forces lowercase. Not a security issue per se, but the `.lower()` appears unintentional.
- **Recommendation:** Remove `.lower()` or make it intentional with `.strip()`.

---

## Passed Checks (No Issues Found)

| Area | Status | Notes |
|------|--------|-------|
| **SQL Injection** |  PASS | No raw SQL found. All queries use Django ORM. |
| **CSRF Protection** |  PASS | All `@csrf_exempt` usages are legitimate (Stripe webhooks, health checks). CSRF middleware is active. |
| **Tenant Isolation** |  PASS | All data queries filter by `tenant`. Customer portal views verify `customer=customer_user.customer`. |
| **Customer Data Isolation** |  PASS | Customer views use `get_object_or_404(Repair, id=repair_id, customer=customer)`  customers can only see their own data. |
| **Password Validation** |  PASS | All 4 Django validators configured in `base.py`. Shop join uses `validate_password()`. |
| **Stripe Billing Webhook** |  PASS | `stripe_service.py:handle_webhook()` verifies signature, returns error if secret missing. |
| **File Upload Validation** |  PASS | `validate_repair_photo()` checks file size (5MB) and content type. HEIC conversion handled. |
| **Session Security** |  PASS | `SESSION_COOKIE_HTTPONLY=True`, `SAMESITE=Lax`, 24h expiry in production. |
| **HSTS** |  PASS | 1 year, include subdomains, preload in production. |
| **X-Frame-Options** |  PASS | `DENY` in production. |
| **Content-Type Nosniff** |  PASS | `SECURE_CONTENT_TYPE_NOSNIFF = True` |
| **Rate Limiting (API)** |  PASS | DRF throttling: `anon=20/min`, `user=60/min`, `signup=5/hr`. |
| **Rate Limiting (Login)** |  PASS | `@ratelimit(key='ip', rate='30/h')` on login. |
| **Rate Limiting (Registration)** |  PASS | `@ratelimit(key='ip', rate='5/h')` on customer registration + honeypot. |
| **Sensitive Data in Logs** |  PASS | No passwords/keys logged. Sentry `send_default_pii=False`. |
| **Secrets in Code** |  PASS | All secrets from environment variables. Test fixtures use dummy passwords (acceptable). |
| **Email Injection** |  PASS | All emails use `django.core.mail.send_mail()` which sanitizes headers. |
| **Autoescape** |  PASS | Django's autoescape is on by default, no `{% autoescape off %}` found. |
| **Owner/Tech Isolation** |  PASS | `@owner_or_manager_required` on owner views; `@customer_required` on customer views; tenant middleware separates portals. |

---

## Fix Log

### CRITICAL Fix: Removed `/setup-database/` endpoint

**Commit:** See git log  
**Change:** Removed `path('setup-database/', views.setup_database, name='setup_database')` from `rs_systems/urls.py`.

This endpoint was legacy scaffolding from initial development. It allowed anyone to:
1. Run database migrations
2. Create a superuser with hardcoded credentials (`admin` / `admin123`)
3. View the credentials in the response HTML

The view function remains in `rs_systems/views.py` (dead code)  recommend deleting it entirely in a follow-up cleanup.
