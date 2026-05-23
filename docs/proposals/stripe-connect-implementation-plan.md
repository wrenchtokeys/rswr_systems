# Stripe Connect Implementation Plan

**Status:** ✅ SHIPPED — Phases 1-2 complete, Connect approved and live (March 2026)
**Date:** 2026-03-17
**Approved by:** Drake (via Telegram)

## Architecture Decisions

### Charge Type: Direct Charges
- Payment hits shop's connected account directly
- Stripe processing fees paid by **shop**, not platform
- Platform fee (application_fee_amount) routes to Drake's account
- At 0% fee: costs platform nothing

### Account Type: Express
- Stripe handles KYC/compliance
- Simplified onboarding for shop owners
- RS Systems maintains branding control

---

## Phase 1: Connected Account Onboarding

### Model Changes (apps/tenants/models.py)

```python
# New fields on Tenant
stripe_account_id = CharField(max_length=255, blank=True)
stripe_onboarding_status = CharField(
    choices=[
        ('not_started', 'Not Started'),
        ('pending', 'Onboarding Started'),
        ('in_review', 'In Review'),
        ('active', 'Active'),           # Can accept payments
        ('restricted', 'Restricted'),    # Stripe flagged issues
        ('disabled', 'Disabled'),        # Manually disabled by admin
    ],
    default='not_started'
)
stripe_payouts_enabled = BooleanField(default=False)
stripe_charges_enabled = BooleanField(default=False)
stripe_connected_at = DateTimeField(null=True, blank=True)
```

### Onboarding Flow
1. Owner clicks "Connect Stripe" in owner portal settings
2. We create Express account via API: `stripe.Account.create(type='express', ...)`
3. Generate onboarding link: `stripe.AccountLink.create(...)`
4. Redirect owner to Stripe's hosted onboarding
5. Stripe redirects back to our return URL
6. Webhook `account.updated` fires — we update status fields

### Webhook Handling
- `account.updated` → update stripe_onboarding_status, payouts_enabled, charges_enabled
- Must verify webhook signature (already have webhook secret infrastructure)
- Separate webhook endpoint for Connect events (or route in existing handler)

### Owner Portal UI
- Settings page: "Payment Processing" section
- Status indicator: Not Connected → Onboarding → In Review → Active
- "Connect Stripe" button (or "View Stripe Dashboard" if already connected)
- Clear messaging: "Complete Stripe verification to accept online payments through RS Systems"

---

## Phase 2: Payment Routing (Direct Charges)

### The Critical Rule: No KYC = No Online Payments

**If a shop hasn't completed Stripe Connect onboarding (status != 'active'), they can still:**
- ✅ Create repairs
- ✅ Generate invoices
- ✅ Send invoice PDFs to customers
- ✅ Record manual payments (cash, check)
- ✅ Use all other RS Systems features

**But they CANNOT:**
- ❌ Have Stripe payment links on their invoice PDFs
- ❌ Have "Pay Online" button in customer portal
- ❌ Create Stripe Checkout sessions for their invoices
- ❌ Receive online payments through RS Systems

### Implementation Points (where to check)

1. **Invoice PDF Generation** (`apps/billing/services/invoice_service.py`)
   - Check `invoice.tenant.stripe_onboarding_status == 'active'` AND `stripe_charges_enabled == True`
   - If not: omit Stripe payment URL from PDF entirely
   - Instead show: "Payment: Contact [shop name] directly" or show check/cash instructions

2. **Customer Portal Invoice View** (`apps/customer_portal/views.py`)
   - Check tenant's Connect status before showing "Pay Online" button
   - If not active: show only "Contact [shop name] for payment options"
   - Never expose a broken payment flow

3. **Stripe Checkout Session Creation** (`apps/billing/services/stripe_service.py`)
   - Hard block: if tenant has no active connected account, raise error
   - This is the last line of defense — even if UI somehow shows the button
   - Log this as a warning (should never happen if UI checks are correct)

4. **Owner Invoice Send** (`apps/saas/views.py`)
   - When owner clicks "Send Invoice", if no Connect:
     - Still send the invoice email
     - But invoice email template omits "Pay Online" link
     - Maybe add a note: "Online payments not yet available"

### Direct Charge Implementation

```python
# When creating checkout session for a customer invoice:
session = stripe.checkout.Session.create(
    payment_method_types=['card'],
    line_items=[...],
    mode='payment',
    success_url=...,
    cancel_url=...,
    stripe_account=tenant.stripe_account_id,  # Direct charge
    payment_intent_data={
        'application_fee_amount': calculate_platform_fee(amount, tenant),
    },
)
```

### Fee Calculation

```python
def calculate_platform_fee(amount_cents, tenant):
    """
    Calculate platform fee in cents.
    
    Priority:
    1. Tenant-specific override (tenant.platform_fee_percent)
    2. Global default (SaaS admin setting)
    3. Fallback: 0 (no fee)
    """
    # Get fee percentage
    fee_percent = tenant.platform_fee_percent  # Can be None
    if fee_percent is None:
        fee_percent = get_global_platform_fee()  # From admin config
    if fee_percent is None or fee_percent == 0:
        return 0
    
    fee = int(amount_cents * fee_percent / 100)
    return max(fee, 0)  # Never negative
```

### Fee Model Fields

```python
# On Tenant model
platform_fee_percent = DecimalField(
    max_digits=5, decimal_places=2,
    null=True, blank=True,
    help_text="Override global platform fee for this tenant. Null = use global default."
)

# New model or admin config
class PlatformConfig(models.Model):
    """Singleton — global platform settings."""
    default_fee_percent = DecimalField(max_digits=5, decimal_places=2, default=0)
    competition_pool_enabled = BooleanField(default=False)
    competition_pool_fee_percent = DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="% of subscription payments that go to competition pool"
    )
```

---

## Phase 3: Admin Fee Dashboard

### Admin Views
- **Connected Accounts list**: all tenants with Connect status, account ID, charges/payouts enabled
- **Fee Report**: monthly breakdown of platform fees collected per tenant
- **Bulk actions**: disable/enable Connect for a tenant (admin override)
- **Global settings**: default fee %, competition pool toggle

### Fee Tracking Model

```python
class PlatformFeeRecord(models.Model):
    """Tracks every platform fee collected for reporting and competition pool."""
    tenant = ForeignKey(Tenant)
    invoice = ForeignKey(Invoice)
    payment_intent_id = CharField(max_length=255)
    gross_amount = DecimalField(...)      # Total payment
    fee_amount = DecimalField(...)        # Platform fee collected
    fee_percent = DecimalField(...)       # Rate at time of charge
    stripe_account_id = CharField(...)    # Shop's connected account
    created_at = DateTimeField(auto_now_add=True)
```

---

## Edge Cases & Safety

### What if Connect status changes after invoice is generated?
- Invoice PDFs are generated at send time — they check status at generation
- If a shop's account gets restricted AFTER an invoice PDF was sent with a payment link:
  - Stripe will reject the charge and show an error to the customer
  - Our webhook handler catches `charge.failed` and updates invoice status
  - Customer sees "Payment failed" — not a silent failure

### What about refunds?
- Refunds on direct charges go through the connected account
- We use `reverse_transfer=True` to also reverse our platform fee
- Refund must come from the shop's connected account balance
- If insufficient balance: Stripe handles (debits shop's bank)

### What if a shop disconnects their Stripe account?
- `account.updated` webhook fires with `charges_enabled=False`
- We update tenant status to 'disabled'
- All future invoices: no payment link (same as never-connected)
- Existing payments already processed are unaffected

### What if our webhook is down?
- We also check account status before creating Checkout sessions (API call)
- Belt and suspenders: webhook keeps local state fresh, API call is the gate

### Platform fee edge cases
- Fee is calculated in CENTS (integers) to avoid floating-point issues
- Fee is calculated at charge time, not invoice time (fee % could change)
- Fee is recorded in PlatformFeeRecord for audit trail
- Minimum fee: 0 (never negative, even with rounding)
- Fee % stored on the record so historical data is accurate even if rate changes

### Race conditions
- Checkout session creation is idempotent (keyed by invoice)
- Platform fee is set at session creation, not after
- No window where fee could be modified mid-payment

---

## Phase 4: Competition Pool (FUTURE — Document Only)
See: docs/proposals/competition-pool.md

---

## Testing Requirements

### Phase 1 Tests
- Onboarding flow: create account, generate link, handle return
- Webhook: account.updated with various statuses
- Owner portal: correct status display, button states
- Cross-tenant: can't see another shop's Connect status

### Phase 2 Tests  
- **NO CONNECT = NO PAYMENT LINK** (most critical test)
  - Invoice PDF without Connect: no Stripe URL
  - Customer portal without Connect: no Pay button
  - Checkout session creation without Connect: hard error
- Direct charge with fee: correct amount routing
- Direct charge with 0% fee: no application_fee_amount
- Fee calculation: tenant override > global default > 0
- Refund with reverse_transfer

### Phase 3 Tests
- Admin fee report accuracy
- PlatformFeeRecord created on every charge
- Global settings CRUD
- Per-tenant fee override

---

## Migration Safety
- All new fields are nullable/have defaults — no destructive migrations
- Existing tenants start with stripe_onboarding_status='not_started'
- Existing invoice flow unchanged until shop completes Connect
- Zero risk to current billing for Rockstar Windshield Repair
