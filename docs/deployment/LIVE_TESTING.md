# Live Testing Checklist — July 2026 Release Wave

Covers everything deployed in PRs #125–#133 (deployed 2026-07-29, version
`app-238e`). Work through this top to bottom — the Stripe sections are
ordered so each test sets up the next.

**Why this matters:** live-account review found that **no shop has ever
successfully subscribed in production** (migration `tenants/0013` seeded
price IDs from an abandoned Stripe account). Migration `tenants/0021`
fixed the IDs, but the full subscription path has still never been
exercised live. That is the single most important test in this document.

---

## 0. Pre-flight (5 minutes, do first)

- [ ] Health: `curl -I https://rssystems.io/health/` → HTTP 200
- [ ] Price IDs match Stripe (run on the instance):
  ```bash
  eb ssh
  cd /var/app/current && source /var/app/venv/*/bin/activate
  python manage.py set_stripe_prices --verify
  ```
  Every plan must resolve against the live platform account
  (`acct_1SuOa20zbBWahwkN`). Any "No such price" means a wrong-account ID
  (suffix `1JK8PzBpGP`) crept back in — stop and fix before testing
  subscriptions.
- [ ] Crons installed (same SSH session):
  ```bash
  cat /etc/cron.d/rs-systems-reviews   # */20 * * * * send_review_requests
  cat /etc/cron.d/billing_tasks        # batch/overdue/aging/loyalty/alerts
  ```
- [ ] Migrations applied: `python manage.py showmigrations tenants technician_portal | grep -E '0021|0047'` — both checked.
- [ ] Webhook endpoints in the Stripe dashboard (platform account →
  Developers → Webhooks) are enabled and show recent successful
  deliveries, not failures:
  | URL | Type |
  |-----|------|
  | `/api/tenants/webhooks/stripe/` | Platform (subscriptions) |
  | `/api/billing/stripe/webhook/` | Connect (shop invoice payments) |
  | `/api/billing/stripe/webhook/` | Platform legacy catch-all (duplicate deliveries are expected and harmless) |

---

## 1. Subscription checkout — THE critical test

**What broke before:** checkout always failed with "No such price".
**What to prove:** a shop can subscribe, the webhook lands, and the app
flips the tenant to active.

⚠️ **This is live mode — real cards are charged real money.** Options,
best first:
1. Create a **100%-off coupon** in the Stripe dashboard and apply it at
   checkout (tests the full flow for $0).
2. Subscribe on Starter monthly ($49) with a real card, then refund the
   charge and cancel the subscription from the dashboard afterward.

Steps:
- [ ] Use a test tenant (sign up a fresh shop at `/signup/` or use an
      existing trial tenant — **not** the Rockstar production tenant).
- [ ] Owner Settings → subscription/pricing page → choose **Starter
      monthly** → complete Stripe Checkout.
- [ ] Checkout page loads without error (this alone proves the 0021 fix).
- [ ] After payment: app shows the plan as active; tenant
      `subscription_status` is `active` (check Django admin → Tenants).
- [ ] Stripe dashboard → Subscriptions: subscription exists on the
      platform account with the right price.
- [ ] Stripe dashboard → Webhooks → `/api/tenants/webhooks/stripe/`:
      `checkout.session.completed` and `invoice.paid` delivered with 2xx.
- [ ] Repeat once for an **annual** price if possible (annual IDs were
      also wrong before 0021).

Also verify enforcement still behaves:
- [ ] Cancel the test subscription in Stripe → within the webhook
      (`customer.subscription.deleted`) the tenant should lose access
      (SubscriptionEnforcementMiddleware → blocked/upgrade page), not
      before.

---

## 2. Stripe Connect onboarding (shop payment account)

**What to prove:** a new shop can connect a bank account and become
payable.

- [ ] On the test tenant: Owner Settings → **Payments** → start
      onboarding. Completes Stripe's hosted Express flow (real SSN/bank
      details required in live mode — use your own info for the test
      shop).
- [ ] Back in Owner Settings → Payments: status shows charges enabled
      (`tenant.can_accept_payments` true — Pay buttons appear on
      invoices).
- [ ] **"View payouts"** link opens the Stripe Express dashboard
      (tests `create_login_link`).
- [ ] Stripe dashboard → Connect → Accounts: the new Express account
      shows `charges_enabled` and `details_submitted` true.

---

## 3. Customer invoice payment (the money-routing fix, PR #131)

**What broke before:** payments could route to the platform account.
**What to prove:** a customer's payment lands on the **shop's** Connect
account, with the platform fee split out.

- [ ] Check the test tenant's `platform_fee_percent` in Django admin
      first. **Gotcha:** tenants created before migration `tenants/0012`
      have `0.00` (an explicit 0% override) — set a real value (e.g. 2%)
      so you can verify the fee shows up.
- [ ] Create a job + invoice for an **individual (RETAIL)** customer with
      a real email you control.
- [ ] Send the invoice (see §5 for what the send flow itself should look
      like). Open the email; the pay link must be the tokened
      `/pay/<invoice_id>/<token>/` URL.
- [ ] Pay it with a real card (small invoice — you're refunding this).
- [ ] Invoice flips to PAID in the app (webhook
      `checkout.session.completed` on the **Connect** endpoint).
- [ ] **Stripe dashboard → the shop's Connect account**: the charge is
      there. **Platform account balance: nothing.** If the charge landed
      on the platform account, stop — that's the exact bug #131 fixed,
      and the webhook should have refused to mark it paid.
- [ ] Platform account → Connect → **Application fees**: the platform
      fee appears (percent of charge, whole cents).
- [ ] Django admin: a `PlatformFeeRecord` row was written.
- [ ] Refund from the shop account when done; confirm the app handles
      the refund sanely (invoice status, no crash).

Failure path:
- [ ] Attempt a payment with a declining card — invoice stays unpaid, no
      error email storms, page shows a sane failure.

---

## 4. Review request system (PR #133 — the reason for this deploy)

**What to prove:** the cron actually sends, and fleet gating holds.

Setup: Settings → **Reviews** tab → set the shop's Google review URL,
leave **Include Fleet Accounts OFF** (the default).

- [ ] Complete a repair for a **RETAIL or WALK_IN** customer with your
      email. Within ~20 minutes (cron is `*/20`), the branded review
      email arrives.
- [ ] The email's review button hits the Google URL; the click is
      tracked (check the ReviewRequest record in admin).
- [ ] Complete a repair for a **FLEET** customer → no email; admin shows
      the request skipped with `skip_reason='fleet_disabled'`.
      **Remember `Customer.customer_type` defaults to `FLEET`** — a
      customer you created without picking a type will (correctly) be
      skipped.
- [ ] Flip **Include Fleet Accounts ON**, complete another fleet repair →
      email arrives.
- [ ] Opt-out link in the email works and future requests are suppressed.
- [ ] On the instance: `tail /var/log/review-requests.log` shows runs
      every 20 minutes with no tracebacks.

---

## 5. Invoice sending polish (PRs #125, #126, #129)

- [ ] Sending an invoice shows the **confirm-before-send** step (no
      one-click accidental sends).
- [ ] Email wording: **"View invoice" vs "Pay invoice"** matches whether
      the shop can accept payments.
- [ ] Send a copy to yourself; delivery + **viewed** tracking appears on
      the invoice after you open it.
- [ ] Send to a bad address (e.g. `bounce@simulator.amazonses.com`) →
      bounce alert reaches the shop.
- [ ] Invoice PDF prints the **shop's own warranty wording** (PR #129),
      and the shop's brand color/logo — not Rockstar's — for a second
      tenant.

## 6. Tax overhaul (PR #127)

- [ ] A tenant with **no tax setup** gets **0 tax** on new tickets — the
      silent 6.5% default is gone.
- [ ] After configuring a tax rate, new tickets calculate it; the
      **per-ticket toggle** can exclude an individual ticket.

## 7. Fleet / individual separation (PR #128)

- [ ] Job creation clearly separates fleet accounts from individual
      customers; an individual walk-in can be created and invoiced
      without touching a fleet account.

## 8. Soft delete + restore (PR #130)

- [ ] Delete an invoice, a job, a customer, and a portal user → each
      disappears from normal views but is restorable for 30 days.
- [ ] Restore one of each; relationships (invoice ↔ job ↔ customer)
      survive intact.
- [ ] `python manage.py purge_deleted_records --days 30` (dry run —
      **without** `--apply`) reports sane counts.

## 9. Admin (PR #132)

- [ ] As superuser, deleting a test tenant cascade-deletes without the
      BillingConfig permission error.

---

## Wrap-up

- [ ] Refund/cancel every live charge and subscription created above.
- [ ] `eb logs` / CloudWatch: no new recurring tracebacks.
- [ ] Log results + anything broken in `docs/development/CHANGELOG.md`
      or a GitHub issue per bug.

**Rollback if something is badly broken:**
`eb deploy --version app-7274da-260728_134529807100` (the pre-#133
version) — see `PRODUCTION_CHECKLIST.md` for full rollback including DB.
