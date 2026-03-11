# Subscription Lifecycle — Trial, Expiration & Data Retention

> Created: March 3, 2026 — Amelia
> Last updated: March 3, 2026
> Status: Partially implemented

---

## Current State (What Exists)

### ✅ Implemented (March 2026)
- **Trial enforcement middleware** (`apps/tenants/subscription_middleware.py`)
  - Blocks app access when trial expires or subscription is canceled/expired
  - Returns 402 JSON for API endpoints, redirects to `/pricing/` for HTML
  - Billing, auth, signup, and payment paths are exempt (user can still pay)
  - `past_due` status shows warning banner but doesn't block (grace period)
  - Runs after `TenantMiddleware` in the middleware stack

- **Trial tracking on Tenant model**
  - `trial_started_at` — when trial began
  - `subscription_status` — trialing, active, past_due, canceled, expired
  - `is_trial_expired` property — checks if 30 days (or plan-specific) have passed
  - `trial_days_remaining` property — days left in trial

### ❌ Not Yet Implemented
- Trial expiration email alerts (before and after expiry)
- Soft landing page for expired trials (currently hard redirect to /pricing/)
- Grace period for failed payments
- Data export option for departing users
- Re-activation flow from expired state

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

## Planned: Trial Expiration Email Alerts

### Email Schedule
| Trigger | Email | Subject |
|---------|-------|---------|
| 7 days before expiry | Friendly heads-up | "Your RS Systems trial ends in 7 days" |
| 3 days before expiry | Urgency nudge | "3 days left on your free trial" |
| 1 day before expiry | Last chance | "Your trial expires tomorrow — upgrade now" |
| Day of expiry | Expired notice | "Your free trial has ended" |
| 7 days after expiry | Win-back | "Your data is safe — upgrade to pick up where you left off" |
| 30 days after expiry | Final nudge | "We're keeping your data — here when you're ready" |

### Email Content Guidelines
- Always reassure that data is preserved
- Show usage stats (X repairs logged, X customers, X invoices)
- Clear CTA to upgrade
- No guilt/shame tactics — professional and helpful
- Unsubscribe link (CAN-SPAM compliance)

### Implementation Plan
1. **Celery beat task**: `check_trial_expirations` — runs daily at 9 AM UTC
2. Query all tenants where `plan='trial'` and `trial_started_at` matches alert windows
3. Use existing SendGrid integration via `notifications@rssystems.io`
4. Track sent alerts in a `TrialAlert` model (prevent duplicate sends):
   ```python
   class TrialAlert(models.Model):
       tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
       alert_type = models.CharField(max_length=20)  # '7_day', '3_day', '1_day', 'expired', etc.
       sent_at = models.DateTimeField(auto_now_add=True)
       class Meta:
           unique_together = ['tenant', 'alert_type']
   ```
5. Email templates in `templates/emails/trial/`

### Estimated effort: ~4-6 hours

---

## Planned: Soft Landing Page for Expired Trials

Instead of a hard redirect to `/pricing/`, show a dedicated page that:

1. **Acknowledges the situation** — "Your free trial has ended"
2. **Reassures about data** — "Your data is safe and waiting for you"
3. **Shows what they built** — "You have X customers, Y repairs, Z invoices"
4. **Clear upgrade path** — Plan comparison with CTA buttons
5. **Export option** — "Download your data" (CSV export of customers, repairs, invoices)
6. **Support contact** — In case they have questions

### URL: `/trial-expired/` (or render at `/pricing/` with trial-expired context)

### Estimated effort: ~2-3 hours

---

## Planned: Subscription Lifecycle Emails (Post-Trial)

Once Stripe subscription billing is live (Phase 7), add:

| Event | Email |
|-------|-------|
| Payment successful | Receipt + thank you |
| Payment failed | "We couldn't process your payment — update billing info" |
| 3 days before retry | "Payment retry coming up — please check your card" |
| Subscription canceled | "Sorry to see you go — your data is preserved for X days" |
| Plan upgraded | "Welcome to {plan} — here's what's new" |
| Plan downgraded | "Your plan has changed — here's what's different" |

---

## Related Docs
- [`BILLING_ROADMAP.md`](/BILLING_ROADMAP.md) — Phase 7: SaaS subscription billing
- [`ROADMAP.md`](ROADMAP.md) — Project roadmap and feature backlog
- `apps/tenants/subscription_middleware.py` — Current enforcement logic
- `apps/tenants/models.py` — Tenant.is_trial_expired, trial_days_remaining
