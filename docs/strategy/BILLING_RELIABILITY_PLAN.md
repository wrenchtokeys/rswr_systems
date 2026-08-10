# Billing Reliability Plan

> Written 2026-08-09 after the first real customer payment ($137.19,
> 2026-08-08) succeeded on Stripe but was never recorded in RS Systems.
> Goal: **a shop owner never has to guess whether a payment went through.**

## What happened

Production's unpinned `stripe>=8.0.0` silently upgraded to stripe-python
15.4.0, which removed dict inheritance from `StripeObject`. One
`event.get('account')` call made **every** delivery to
`/api/billing/stripe/webhook/` return HTTP 500 from Aug 5 onward (first
crash in prod logs: Aug 5, 23:36 CT). Payments succeeded on Stripe;
invoices stayed UNPAID; no receipts, no owner email, nothing in the
portal. The subscription endpoint had the same bug in silent form. Nobody
noticed for 4 days because Sentry is not wired up in production.

## Done

| # | Item | Where | Status |
|---|------|-------|--------|
| 1 | Webhook crash fix — handlers now parse the signature-verified payload into plain dicts (SDK-version-proof); `stripe<16` pinned; regression tests shaped like v15 events | PR #148 (`fix/stripe-webhook-sdk15-500`) | **MERGE + DEPLOY FIRST** |
| 2 | `StripeCheckoutAttempt` model — every checkout session is recorded per invoice (migration `billing/0031`) | PR: payment-reliability | built |
| 3 | Manual-payment guard — recording a cash/check payment first verifies open sessions with Stripe: already-paid → the Stripe payment is recorded instead; still-open → session expired so the customer can't double-pay; unverifiable → manual record **blocked** | `stripe_reconcile.guard_manual_payment`, wired into `owner_record_payment` + billing API `record_payment` | built |
| 4 | Reconciliation sweep — cron every 15 min re-checks open sessions and records paid ones the webhook missed (idempotent vs. webhook retries via payment_intent id) | `reconcile_stripe_payments` command + `.ebextensions/13_stripe_reconcile_cron.config` | built |
| 5 | Payment-complete page — now verifies the session with Stripe on landing and records the payment immediately (recovery path #2), shows the SHOP's name/contact and the invoice's real status instead of an unverified platform-branded claim | `rs_systems/views.payment_complete` | built |
| 6 | In-portal notification — managers get a bell notification for every online payment (fires from the shared recording path: webhook, sweep, or landing page) | `StripeService._record_stripe_payment` | built |
| 7 | Copy pay link — invoice detail page shows the tokened `/pay/` link with a copy button (no more emailing yourself an invoice to harvest the link) | owner invoice detail | built |
| 8 | Already-paid safeguard — a Stripe payment arriving for a fully-paid invoice is never recorded again and never emails the customer; the shop gets an in-portal + email alert to review a possible duplicate charge | `StripeService._record_stripe_payment` | built |

## Deploy order

1. Merge PR #148 (hotfix), then PR #149 (reliability, includes migration
   `billing/0031`), deploy once.
2. After deploy: `python manage.py reconcile_stripe_payments --dry-run`
   once to sanity-check, then let cron run it.
3. Do **not** resend old failed deliveries from the Stripe dashboard —
   Drake reconciled all outstanding invoices by hand on 2026-08-09.
   Stripe's own pending retries will land after deploy; the already-paid
   safeguard absorbs them: no double credit, no customer email, shop-only
   alert if anything looks like a genuine duplicate charge.

## Still to do (in order)

| # | Item | Why | Owner |
|---|------|-----|-------|
| 1 | Set `SENTRY_DSN` in EB env | 4 days of 500s went unseen; this is the alarm | **Drake** (account/DSN), then `eb setenv` |
| 2 | `set_stripe_prices --verify` after deploy | standard post-billing-deploy check | either |
| 3 | Weekly check of Stripe Dashboard webhook health until Sentry is live | belt and braces | Drake |
| 4 | Text-to-pay: send invoice/pay link by SMS | the incident night's biggest friction; SMS infra exists in the rswr project, not here | future PR |
| 5 | In-person card: Stripe Terminal / Tap to Pay, or at minimum a "charge card on file" flow | Drake had no sanctioned way to take a card in person | future PR (needs product decision) |
| 6 | Receipt/PDF texting UX (the "text a screenshot" hack) | follow-on of #4 | future PR |

## Invariants to keep (learned the hard way)

- Shop invoices are charged **only** on the shop's Connect account
  (tokened `/pay/` link). The webhook refuses charges from any other
  account. (PR #131 — verified still true everywhere, including
  auto-invoice.)
- Stripe payments dedup on `payment_intent` id via a DB partial unique
  index — every recovery path (webhook, sweep, landing page) reuses the
  same recording function, so they can never double-record each other.
- Never trust webhook delivery alone for money state; the sweep is the
  source of calm.
- Pin SDK majors; upgrade deliberately with the v15-shaped regression
  tests (`tests/test_stripe_webhook_sdk15.py`).
