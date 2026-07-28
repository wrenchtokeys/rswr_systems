# Stripe Architecture

> How money moves through RS Systems: the platform account, shop Connect
> accounts, subscriptions, and platform fees.
> Last verified against the live Stripe account: July 28, 2026.

---

## The two money flows

RS Systems touches Stripe in two completely separate ways:

1. **Shops paying the platform** (subscriptions): a shop owner subscribes to
   a plan (Starter/Pro/Enterprise). Charged on the **platform account**.
2. **Shop customers paying shops** (invoices): a fleet or individual pays a
   shop's invoice online. Charged **directly on the shop's own Stripe
   Connect account** — this money never enters the platform's balance.

**Rule: a shop customer's invoice payment must never be charged on the
platform account.** There is no automated way to move that money to the
shop afterward. All customer-facing pay links are the tokened
`/pay/<invoice_id>/<token>/` URL, which creates a direct charge on the
shop's Connect account at click time. The webhook refuses to mark an
invoice paid if the charge landed on any other account
(`event['account']` mismatch check in
`apps/billing/services/stripe_service.py`).

---

## Platform account

- Live account: `acct_1SuOa20zbBWahwkN` ("RS Systems").
- **Careful**: an older/abandoned Stripe account (IDs containing
  `1JK8PzBpGP`) appears in historic migrations. Migration
  `tenants/0013` wrote that account's price IDs into the database, which
  broke subscription checkout until migration `tenants/0021` corrected
  them. If you ever see "No such price" on checkout, an ID from the wrong
  account has crept back in — run `python manage.py set_stripe_prices
  --verify`, which retrieves every plan's price from Stripe and asserts
  the amount matches the DB.

### Subscription plans (live price IDs)

| Plan | Monthly | Annual |
|------|---------|--------|
| Starter | $49 — `price_1TBOVk0zbBWahwkNapnUrfVx` | $470 — `price_1TDYDM0zbBWahwkNjiUGHCrv` |
| Pro | $99 — `price_1TBOVn0zbBWahwkNgDKWvEe4` | $950 — `price_1TDYDN0zbBWahwkNqbohtNbs` |
| Enterprise | $249 — `price_1TBOVq0zbBWahwkN1uZvyhin` | $2390 — `price_1TDYDN0zbBWahwkN9JM3oE05` |

To change a price: create the new Price in the Stripe dashboard, then
`python manage.py set_stripe_prices --plan <slug> --price <id>` (and/or
`--annual-price <id>`), then `--verify`. Never hardcode price IDs in code
or new migrations.

---

## Shop accounts: Stripe Connect **Express**

Shops onboard through Owner Settings → Payments, which creates a Stripe
**Express** account (`ConnectService.create_connect_account`) and sends
the owner through Stripe's hosted onboarding.

What Express means for a shop — the answer to "can a shop ever lose
access to their Stripe?":

- **The money is the shop's.** Charges settle in the shop's own Connect
  account and Stripe pays out to the **shop's own bank account** on
  Stripe's normal payout schedule. Funds never sit in the platform's
  balance.
- **Their balance survives platform problems.** If the platform's Stripe
  account were restricted or closed, Stripe still holds and pays out the
  connected accounts' balances to the shops' banks.
- **The account is platform-managed.** Shops do not get a standalone
  Stripe login; they see their payouts/balance through the Stripe Express
  dashboard, reached from Owner Settings → Payments → "View payouts"
  (a `create_login_link` deep link). This is the standard SaaS setup.
- **Shops cannot self-migrate away.** An Express account is bound to the
  platform. If a shop leaves RS Systems and wants its own Stripe account,
  it opens a fresh Stripe account — history/saved cards do not transfer
  automatically (Stripe support can migrate data on request).
- **KYC is the shop's responsibility.** Stripe may ask a shop for more
  identity/bank information; until provided, `charges_enabled` /
  `payouts_enabled` go false and the app hides the shop's Pay buttons
  (`tenant.can_accept_payments`).

### Charge type and platform fee

Invoice payments are **direct charges** (`stripe_account=<shop acct>` on
the Checkout Session). The shop pays Stripe's processing fees. The
platform takes `application_fee_amount`, computed as
`tenant.platform_fee_percent`, falling back to
`PlatformConfig.default_fee_percent` when the tenant field is NULL
(percent-only, truncated to whole cents). Collected fees appear in the
platform dashboard under **Connect → Application fees** and are recorded
locally as `PlatformFeeRecord` rows (written by the
`payment_intent.succeeded` webhook from PaymentIntent metadata).

**Gotcha:** tenants created before migration `tenants/0012` have
`platform_fee_percent = 0.00` (not NULL), which reads as an explicit 0%
override — they pay no platform fee until the field is cleared or set in
Django admin.

---

## Webhook endpoints (live)

| URL | Type | Purpose |
|-----|------|---------|
| `/api/billing/stripe/webhook/` | **Connect** (listens to connected accounts) | Shop invoice payments: `checkout.session.completed`, `payment_intent.succeeded`. Should also have `account.updated` (keeps `can_accept_payments` in sync when Stripe restricts a shop). |
| `/api/tenants/webhooks/stripe/` | Platform | Subscriptions: `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated/deleted`. |
| `/api/billing/stripe/webhook/` | Platform | Legacy catch-all (subscription + billing events). Redundant with the two above; harmless but causes duplicate deliveries. |

Signing secrets: `STRIPE_CONNECT_WEBHOOK_SECRET`,
`STRIPE_SUBSCRIPTION_WEBHOOK_SECRET`, `STRIPE_WEBHOOK_SECRET` (EB env
vars). The billing endpoint tries the platform secret first, then the
Connect secret.

---

## Operational checklist

- After any deploy touching billing: `python manage.py set_stripe_prices --verify`.
- New shop can't take payments? Check Owner Settings → Payments status,
  then the account in **Stripe dashboard → Connect → Accounts** —
  `charges_enabled`/`details_submitted` tell you whether onboarding is
  incomplete or Stripe wants more KYC info.
- Never run one-off scripts that write Stripe IDs without confirming the
  account suffix matches `0zbBWahwkN`.
