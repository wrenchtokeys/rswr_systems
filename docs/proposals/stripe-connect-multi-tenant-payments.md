# Proposal: Stripe Connect Multi-Tenant Payments

**Status:** TODO
**Priority:** High (required before other shops process customer payments)
**Date:** 2026-03-15

## Problem

Currently, all Stripe payments (both SaaS subscriptions and customer invoice payments) flow to a single Stripe account — Drake's. This works for:
- Rockstar Windshield Repair's own customer invoices
- SaaS subscription fees from other shop owners

But when other shops onboard and their fleet customers pay invoices through RS Systems, those payments also land in Drake's Stripe account. There's no way to route customer invoice payments to the shop that performed the repair.

**Impact:** RS Systems cannot be used as a payment platform for other shops until this is resolved. Shop owners would need to collect payments outside the system, defeating the purpose of integrated billing.

## Solution: Stripe Connect

Integrate [Stripe Connect](https://stripe.com/connect) to enable multi-tenant payment routing.

### Architecture

1. **Platform Account** (Drake's Stripe account) — receives SaaS subscription payments
2. **Connected Accounts** (each shop owner) — receive their customer invoice payments

### Implementation Steps

#### Phase 1: Connected Account Onboarding
- Add `stripe_account_id` field to the Tenant model
- Build Stripe Connect onboarding flow (Standard or Express accounts)
- Shop owner clicks "Connect Stripe" → redirected to Stripe's hosted onboarding
- Store the connected account ID on return
- Handle `account.updated` webhook to track onboarding status (verified, restricted, etc.)

#### Phase 2: Payment Routing
- When creating a Checkout Session or Payment Intent for a customer invoice:
  ```python
  stripe.checkout.Session.create(
      ...,
      payment_intent_data={
          'application_fee_amount': calculate_platform_fee(amount),
          'transfer_data': {
              'destination': tenant.stripe_account_id,
          },
      },
  )
  ```
- Customer pays → funds go to the shop's connected account minus platform fee
- Platform fee goes to Drake's account (SaaS revenue on top of subscription)

#### Phase 3: Dashboard & Reporting
- Show shop owners their Stripe Connect status in owner portal
- Display payout history / balance (via Stripe API or embedded components)
- Admin dashboard: view all connected accounts, fees collected, payment volume

### Payment Flow Diagram

```
Customer Invoice Payment
    │
    ▼
Stripe Checkout (RS Systems platform)
    │
    ├── Platform Fee (e.g. 2.9% + $0.30) ──► Drake's Stripe Account
    │
    └── Remainder ──► Shop Owner's Connected Account
                          │
                          ▼
                    Shop Owner's Bank
```

```
SaaS Subscription Payment (unchanged)
    │
    ▼
Stripe Checkout → Drake's Stripe Account (direct, no Connect)
```

### Connect Account Types

| Type | Onboarding | Branding | Best For |
|------|-----------|----------|----------|
| **Standard** | Stripe-hosted, full | Shop's own | Shops that want their own Stripe dashboard |
| **Express** | Stripe-hosted, simplified | RS Systems | Simpler UX, shops don't need Stripe expertise |
| **Custom** | You build everything | Yours | Maximum control (not recommended initially) |

**Recommendation:** Start with **Express** accounts. Simplest for shop owners, Stripe handles KYC/compliance, and RS Systems maintains branding control.

### Fee Structure Options

| Model | Description | Example on $100 invoice |
|-------|-------------|------------------------|
| **Flat fee** | Fixed % per transaction | 2% → $2.00 to platform |
| **Flat + Stripe fees** | Platform % on top of Stripe's processing | 2% + Stripe 2.9%+$0.30 |
| **Subscription only** | No per-transaction fee, revenue from SaaS sub only | $0 platform fee |
| **Tiered** | Lower % at higher volume | 2% under $10k/mo, 1.5% over |

Decision needed from Drake on fee model.

## Scope

### What Changes
- `apps/tenants/models.py` — add `stripe_account_id`, `stripe_onboarding_status` fields
- `apps/saas/views.py` — new Connect onboarding views
- `apps/billing/services.py` — modify payment creation to use `transfer_data`
- `apps/billing/views.py` — webhook handler for `account.updated`
- Owner portal — "Connect Stripe" button, payout status
- Admin — connected accounts list, fee reporting

### What Doesn't Change
- SaaS subscription flow (stays direct to platform account)
- Invoice generation, PDF rendering, tax calculation
- Customer portal UX (they still click "Pay Invoice")

## Risk

| Risk | Mitigation |
|------|-----------|
| Stripe Connect adds complexity to payment flow | Start with Express (Stripe handles most of it) |
| KYC delays for shop owners | Clear onboarding status UI, email notifications |
| Refunds on connected accounts | Use `reverse_transfer` flag on refunds |
| Stripe fees on connected accounts | Clearly communicate fee structure during signup |
| Regulatory/compliance | Stripe handles this for Express/Standard accounts |
| Testing | Need test connected accounts in Stripe test mode before going live |

## Dependencies
- Stripe account must be approved for Connect (may need to apply)
- Terms of Service update (RS Systems becomes a payment platform)
- Privacy policy update

## Timeline Estimate
- Phase 1 (onboarding): ~2-3 days
- Phase 2 (payment routing): ~2-3 days
- Phase 3 (dashboard): ~2-3 days
- Testing & edge cases: ~2-3 days
- **Total: ~8-12 days**
