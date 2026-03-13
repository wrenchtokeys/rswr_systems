# Subscription Lifecycle — Trial, Expiration & Data Retention

> Created: March 3, 2026 — Amelia
> Last updated: March 12, 2026
> Status: Implemented

---

## Current State (What Exists)

### ✅ Implemented (March 2026)

#### Trial Enforcement Middleware
(`apps/tenants/subscription_middleware.py`)
- Blocks app access when trial expires or subscription is canceled/expired
- Returns 402 JSON for API endpoints, redirects to `/subscription-blocked/` for HTML
- Billing, auth, signup, and payment paths are exempt (user can still pay)
- `past_due` status shows warning banner but doesn't block (grace period)
- Runs after `TenantMiddleware` in the middleware stack

#### Trial Tracking on Tenant Model
- `trial_started_at` — when trial began
- `subscription_status` — trialing, active, past_due, canceled, expired
- `is_trial_expired` property — checks if 30 days (or plan-specific) have passed
- `trial_days_remaining` property — days left in trial
- `grace_period_end` — date when read-only grace period ends

#### Grace Period (30-day Read-Only)
- After trial/subscription expires, tenants enter a 30-day grace period
- GET requests allowed — users can still view all their data
- Write operations blocked — no new repairs, customers, or invoices during grace
- Grace period warnings shown in banners for all authenticated users
- After grace ends, full access suspension

#### Soft Landing Page — `/subscription-blocked/`
Role-aware content instead of a hard redirect to `/pricing/`:
- **Owner** → upgrade CTA with plan comparison
- **Technician** → contact your account owner messaging
- **Customer** → shop contact info and current status

#### Subscription Banners
- **Trial countdown** — amber banner for all authenticated users when ≤ 7 days remain
- **Grace period warnings** — banner shown when in read-only grace window
- **Expired notice** — clear messaging when grace period has ended
- Smart messaging distinguishes trial-ended vs subscription-ended scenarios

#### Email Alerts — 6 Lifecycle Stages
Management command: `python manage.py check_subscription_alerts` (run daily via cron)

Sent alerts tracked via `subscription_alerts_sent` JSONField on `Tenant` (not a separate model).

| Stage | Timing | Subject |
|-------|--------|---------|
| Pre-expiry warning | 7 days before expiry | "Your RS Systems trial ends in 7 days" |
| Last chance | 1 day before expiry | "Your trial expires tomorrow — upgrade now" |
| Expiry notice | Day of expiry | "Your free trial has ended" |
| Grace mid-point | 15 days into grace | "Your data is safe — upgrade to pick up where you left off" |
| Grace urgent | 5 days before grace ends | "Final reminder — your access ends in 5 days" |
| Grace ended | Day grace period ends | "Your RS Systems access has been suspended" |

Email sent from: `notifications@rssystems.io` (SendGrid, domain-authenticated for rssystems.io)

**Implementation notes:**
- Uses `subscription_alerts_sent` JSONField on `Tenant` to track which alerts have fired (prevents duplicate sends)
- Management command (cron) instead of Celery beat — simpler, no broker dependency
- No separate `TrialAlert` model needed

---

## Data Retention Policy

**Decision (March 3, 2026): Keep all data indefinitely.**

When a trial expires or subscription is canceled:
- All tenant data is **preserved** (customers, repairs, invoices, photos, settings)
- User accounts remain active but access is gated by the subscription middleware
- No automated cleanup or deletion
- If user upgrades/reactivates, everything is right where they left it

**Rationale:** Storage is cheap. A user returning months later and finding their data intact is a strong conversion signal. The goodwill and trust is worth more than the storage cost.

**Future consideration:** If storage costs become a concern (unlikely in near-term), options include:
1. Archive photos to cold storage (S3 Glacier) after 6 months of inactivity
2. Compress/downsample images for inactive tenants
3. Set a retention window (e.g., 1 year) with advance notice emails before deletion
4. Offer a data export before any cleanup

**Important:** Any future data cleanup must include:
- 30-day advance email warning
- Easy data export (CSV/PDF zip)
- Clear communication of what will be removed and when
- Option to reactivate and prevent cleanup

---

## Planned: Subscription Lifecycle Emails (Post-Trial)

Once Stripe subscription billing is fully live (Phase 6+), add:

| Event | Email |
|-------|-------|
| Payment successful | Receipt + thank you |
| Payment failed | "We couldn't process your payment — update billing info" |
| 3 days before retry | "Payment retry coming up — please check your card" |
| Subscription canceled | "Sorry to see you go — your data is preserved" |
| Plan upgraded | "Welcome to {plan} — here's what's new" |
| Plan downgraded | "Your plan has changed — here's what's different" |

---

## Planned: Self-Serve Re-activation & Data Export

From the `/subscription-blocked/` page:
- **Re-activation flow** — owner can upgrade/reactivate without contacting support
- **Data export** — CSV/PDF zip of customers, repairs, invoices (CAN-SPAM / goodwill)

---

## Related Docs
- [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) — Phase 7: SaaS subscription billing
- [`ROADMAP.md`](ROADMAP.md) — Project roadmap and feature backlog
- `apps/tenants/subscription_middleware.py` — Current enforcement logic
- `apps/tenants/models.py` — Tenant.is_trial_expired, trial_days_remaining, grace_period_end
- `apps/tenants/management/commands/check_subscription_alerts.py` — Email alert command
