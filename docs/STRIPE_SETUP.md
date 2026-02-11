# Stripe Setup Guide

> Last updated: February 11, 2026

RS Systems uses Stripe for two separate billing flows:
1. **Customer invoices** — charging your customers for windshield repairs
2. **SaaS subscriptions** — charging glass shops for using RS Systems

---

## Quick Answers

**Webhook destination name:** `RS Systems Subscriptions` (or anything descriptive)

**Description:** Optional, but helpful: `Handles subscription lifecycle events for RS Systems SaaS billing`

---

## Test Mode Setup (Current)

### 1. Products & Prices

Create these products in Stripe Dashboard → Products:

| Product Name | Monthly Price | What you get |
|--------------|---------------|--------------|
| RS Systems Starter | $49/month | `price_xxxxx` |
| RS Systems Pro | $99/month | `price_xxxxx` |
| RS Systems Enterprise | $249/month | `price_xxxxx` |

**Where the price IDs go:** Django Admin → Subscription Plans → edit each plan → paste into "Stripe price id" field

### 2. Webhook Endpoint

**URL:** `https://rockstarwindshield.repair/api/tenants/webhooks/stripe/`

**Events to listen for:**
- `invoice.paid` — payment successful, activate/renew subscription
- `invoice.payment_failed` — payment failed, mark as past_due
- `customer.subscription.updated` — plan changed, period renewed
- `customer.subscription.deleted` — subscription fully canceled

**Signing secret:** Copy the `whsec_xxxxx` value and set as `STRIPE_WEBHOOK_SECRET` env var in AWS EB

### 3. Environment Variables (AWS Elastic Beanstalk)

```
STRIPE_SECRET_KEY=sk_test_xxxxx        # Already set
STRIPE_WEBHOOK_SECRET=whsec_xxxxx      # From webhook endpoint
```

---

## Going Live Checklist

When ready for production payments:

### 1. Switch Stripe to Live Mode
Toggle from "Test mode" to live in the Stripe Dashboard (top right)

### 2. Create Live Products & Prices
Recreate the same 3 products in live mode. You'll get NEW price IDs:

| Product | Test Price ID | Live Price ID |
|---------|---------------|---------------|
| Starter | `price_test_xxx` | `price_live_xxx` |
| Pro | `price_test_xxx` | `price_live_xxx` |
| Enterprise | `price_test_xxx` | `price_live_xxx` |

### 3. Update SubscriptionPlan Records
In Django Admin, update each plan's "Stripe price id" with the LIVE price IDs

### 4. Create Live Webhook Endpoint
Same URL, same events, but in live mode:
- URL: `https://rockstarwindshield.repair/api/tenants/webhooks/stripe/`
- Events: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, `customer.subscription.deleted`
- Copy the new `whsec_xxxxx` signing secret

### 5. Update Environment Variables
In AWS EB Configuration → Environment properties:

```
STRIPE_SECRET_KEY=sk_live_xxxxx        # Live secret key
STRIPE_WEBHOOK_SECRET=whsec_xxxxx      # Live webhook signing secret
```

### 6. Verify
1. Deploy the EB environment to pick up new env vars
2. Test a real subscription signup with a real card
3. Check Stripe Dashboard → Webhooks for successful deliveries

---

## Webhook Security

The webhook handler verifies signatures to prevent spoofed requests:
- **With secret:** Validates `Stripe-Signature` header — secure ✅
- **Without secret (DEBUG only):** Accepts unverified — INSECURE ⚠️
- **Without secret (production):** Returns error — won't process events

Location: `apps/tenants/webhooks.py`

---

## Troubleshooting

### Webhook returns 400/500
- Check `STRIPE_WEBHOOK_SECRET` is set correctly
- Check the signing secret matches the endpoint (test vs live)
- Check server logs: `eb logs` or CloudWatch

### Subscription not updating
- Verify webhook endpoint is receiving events (Stripe Dashboard → Webhooks → click endpoint → Recent events)
- Check the event type is in our handled list
- Check Django logs for errors

### "Plan has no Stripe Price ID"
- The SubscriptionPlan record is missing `stripe_price_id`
- Go to Django Admin → Subscription Plans → add the price ID

---

## Related Files

- Models: `apps/tenants/models.py` (SubscriptionPlan, Tenant)
- Service: `apps/tenants/services/subscription_service.py`
- Webhook: `apps/tenants/webhooks.py`
- Views: `apps/tenants/views.py`
- UI: `templates/saas/billing.html`
