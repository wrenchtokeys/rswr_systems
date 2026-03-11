# Tenants App  Multi-Tenant SaaS Architecture

*RS Systems Multi-Tenant Subscription Platform*

---

## Overview

The `apps/tenants` app provides full multi-tenant data isolation and SaaS subscription management for RS Systems. Every glass shop that signs up gets its own **Tenant**  a walled-off business context with its own customers, repairs, invoices, technicians, and billing.

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Tenant** | A single glass shop business. All data is scoped to a tenant. |
| **TenantMembership** | Links a User to a Tenant with a role (owner/manager/tech/viewer). |
| **SubscriptionPlan** | Defines a pricing tier with limits and features. |
| **Tenant Middleware** | Automatically resolves `request.tenant` on every request. |
| **Plan Enforcement** | Mixins/services that check usage against plan limits. |

---

## How Tenant Resolution Works

The `TenantMiddleware` sets `request.tenant` on every authenticated request using this priority:

1. **`X-Tenant-Slug` header**  API clients send `X-Tenant-Slug: quick-fix-auto-glass`
2. **Session `tenant_id`**  Stored from a previous request in the same browser session
3. **First active membership**  Fallback: picks the user's first tenant

If no tenant can be resolved, `request.tenant = None`. Views that require a tenant check for this and return 403.

```
Request  AuthMiddleware  TenantMiddleware  View
                              
                    request.tenant = <Tenant>
                              
              All queries filtered by tenant FK
```

---

## API Endpoint Reference

All endpoints are under `/api/tenants/`.

### POST `/api/tenants/signup/`  Register a new shop
**Auth:** None (public)  
**Throttle:** 5 requests/hour per IP

```json
// Request
{
    "business_name": "Quick Fix Auto Glass",
    "email": "owner@quickfix.com",
    "password": "securepass123",
    "first_name": "John",
    "last_name": "Smith",
    "phone": "555-123-4567"
}

// Response (201)
{
    "user": {"id": 1, "email": "owner@quickfix.com", "name": "John Smith"},
    "tenant": {"id": 1, "name": "Quick Fix Auto Glass", "slug": "quick-fix-auto-glass"},
    "plan": {"name": "Trial", "days_remaining": 30},
    "token": "abc123def456...",
    "message": "Welcome to RS Systems! Your 30-day free trial has started."
}
```

### GET `/api/tenants/plans/`  List all plans
**Auth:** None (public)

```json
// Response
{
    "plans": [
        {
            "slug": "trial",
            "name": "Trial",
            "monthly_price": "0.00",
            "max_repairs_per_month": 50,
            "max_technicians": 2,
            "max_customers": 10,
            "features": {"invoicing": true, "rewards": false},
            "trial_days": 30,
            "is_free": true
        },
        ...
    ]
}
```

### GET `/api/tenants/status/`  Dashboard status
**Auth:** Token (any member)

```json
// Response
{
    "tenant": {"name": "Quick Fix Auto Glass", "slug": "quick-fix-auto-glass"},
    "plan": {"name": "Trial", "slug": "trial", "price": "$0.00"},
    "subscription_status": "trialing",
    "trial": {"active": true, "days_remaining": 25, "expires_at": "2026-02-27"},
    "usage": {
        "repairs": {"used": 12, "limit": 50, "percent": 24.0},
        "technicians": {"used": 1, "limit": 2, "percent": 50.0},
        "customers": {"used": 5, "limit": 10, "percent": 50.0},
        "storage_mb": {"used": 0, "limit": 100, "percent": 0.0}
    },
    "upgrade_url": "/api/tenants/subscribe/"
}
```

### POST `/api/tenants/subscribe/`  Start a paid subscription
**Auth:** Token (owner only)

```json
// Request
{"plan": "starter", "billing_period": "monthly"}

// Response (201)
{
    "subscription_id": "sub_xxx",
    "status": "incomplete",
    "plan": "Starter",
    "billing_period": "monthly",
    "client_secret": "pi_xxx_secret_xxx"
}
```

### POST `/api/tenants/subscription/update/`  Change plan
**Auth:** Token (owner only)

```json
// Request
{"plan": "pro"}

// Response
{"subscription_id": "sub_xxx", "new_plan": "Pro", "status": "updated"}
```

### POST `/api/tenants/subscription/cancel/`  Cancel at period end
**Auth:** Token (owner only)

```json
// Response
{
    "subscription_id": "sub_xxx",
    "status": "canceling",
    "cancel_at": 1740787200,
    "message": "Your subscription will be canceled at the end of the current billing period."
}
```

### POST `/api/tenants/subscription/reactivate/`  Un-cancel
**Auth:** Token (owner only)

```json
// Response
{"subscription_id": "sub_xxx", "status": "active", "message": "Your subscription has been reactivated."}
```

### GET `/api/tenants/usage/`  Current usage vs limits
**Auth:** Token (any member)

```json
// Response
{
    "repairs": {"used": 45, "limit": 200, "percent": 22.5},
    "technicians": {"used": 3, "limit": 5, "percent": 60.0},
    "customers": {"used": 12, "limit": 50, "percent": 24.0},
    "storage_mb": {"used": 120.5, "limit": 500, "percent": 24.1},
    "plan": "Starter",
    "subscription_status": "active",
    "trial_days_remaining": null
}
```

### GET `/api/tenants/billing-portal/`  Stripe billing portal
**Auth:** Token (owner only)

```json
// Response
{"url": "https://billing.stripe.com/session/xxx"}
```

### POST `/api/tenants/webhooks/stripe/`  Stripe webhook
**Auth:** Stripe signature verification (internal)

Handles: `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`

---

## Subscription Lifecycle

```
       subscribe()     
    SIGNUP      ACTIVE  
   (trial)                         (paid)  
   30 days                       
                            
                                 cancel()   update()
        trial expires                     
                                          
                      
   EXPIRED                       CANCELED 
   (locked)                     (end of   
                       period)  
                                  
                                       
                                 reactivate()
                                       
                                       
                                  
                                    ACTIVE  
                                  
```

**Statuses:** `trialing`  `active`  `canceled`  `expired` (also: `past_due`)

---

## Plan Tiers

| Plan | Price | Repairs/mo | Techs | Customers | Storage | Key Features |
|------|-------|-----------|-------|-----------|---------|-------------|
| **Trial** | Free (30 days) | 50 | 2 | 10 | 100 MB | Invoicing |
| **Starter** | $49/mo | 200 | 5 | 50 | 500 MB | + Rewards |
| **Pro** | $99/mo | Unlimited | 15 | Unlimited | 2 GB | + Custom branding |
| **Enterprise** | $249/mo | Unlimited | Unlimited | Unlimited | 10 GB | + API access, Priority support |

Annual pricing: ~2 months free (Starter $470/yr, Pro $950/yr, Enterprise $2,390/yr).

---

## Adding a New Plan

1. Add the plan data to `apps/tenants/management/commands/seed_plans.py`
2. Run: `python manage.py seed_plans --force`
3. Set Stripe Price IDs in the admin or via the Stripe dashboard
4. The plan will automatically appear in `GET /api/tenants/plans/`

To create a plan manually:
```python
from apps.tenants.models import SubscriptionPlan

SubscriptionPlan.objects.create(
    name='Business',
    slug='business',
    monthly_price=149.00,
    max_repairs_per_month=500,
    max_technicians=10,
    max_customers=200,
    max_storage_mb=1000,
    features={'invoicing': True, 'rewards': True, 'api_access': False},
    display_order=2,
    is_active=True,
)
```

---

## Security Model

### Role-Based Access

| Role | Can view data | Can edit data | Can manage billing | Can manage team |
|------|:---:|:---:|:---:|:---:|
| **Owner** |  |  |  |  |
| **Manager** |  |  |  |  |
| **Technician** |  |  (own) |  |  |
| **Viewer** |  |  |  |  |

### Owner-Only Billing

All billing endpoints use `_require_owner()` which verifies:
1. The request has a tenant context
2. The authenticated user has a `TenantMembership` with `role='owner'` for that tenant
3. Returns 403 if not

Protected endpoints: `subscribe`, `update_subscription`, `cancel_subscription`, `reactivate_subscription`, `billing_portal`

### Signup Security

- **Rate limited:** 5 signups per hour per IP (`SignupRateThrottle`)
- **Password validation:** Django's full validator suite (length, common passwords, numeric-only, similarity)
- **Email uniqueness:** Checked against both `User.email` and `User.username`
- **Input sanitization:** All strings stripped, email lowercased, business name length validated

### Data Isolation

Every business model has a `tenant` ForeignKey. Queries are always filtered by `request.tenant`. The middleware ensures users can only access tenants they're members of.

---

## File Structure

```
apps/tenants/
 models.py                 # Tenant, TenantMembership, SubscriptionPlan
 views.py                  # API endpoints (signup, subscribe, status, etc.)
 urls.py                   # URL routing
 middleware.py              # TenantMiddleware (request.tenant resolution)
 mixins.py                 # PlanEnforcementMixin
 admin.py                  # Django admin configuration
 webhooks.py               # Stripe webhook handler
 services/
    subscription_service.py  # Stripe lifecycle management
    usage_service.py         # Usage tracking vs plan limits
 management/commands/
    seed_plans.py            # Seed the 4 standard plans
 migrations/
     0001_create_tenant_and_membership.py
     0002_create_default_tenant_and_backfill.py
     0003_add_subscription_plan_model_and_billing_fields.py
     0004_seed_subscription_plans.py
```

---

*Author: Amelia (Clawdbot AI)  Last updated: January 29, 2026*
