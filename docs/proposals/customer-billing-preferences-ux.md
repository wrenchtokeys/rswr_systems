# Proposal: Customer Billing Preferences on Create Form

**Author:** Amelia
**Date:** 2026-03-22
**Status:** Draft — awaiting Drake's review

---

## Problem

When a shop owner creates a new customer, they have to:
1. Fill out the create form (name, contact, invite)
2. Save
3. Go to the customer detail page
4. Open settings/preferences
5. Configure billing preferences (batch/auto/manual, billing email, payment terms)
6. Optionally set custom pricing

That's 6 steps for something that should be 1-2. Most shop owners know at creation time whether a fleet customer wants batch billing or per-ticket invoicing. Making them navigate away to configure it means many never do — and the defaults may not match the customer's actual needs.

## Solution

Add an **optional, collapsible** "Billing & Preferences" section to the customer creation form. Collapsed by default so it doesn't overwhelm quick-add users, but expandable for shops that want the full setup upfront.

### What goes in the collapsible section:

| Field | Default | Notes |
|-------|---------|-------|
| Invoice preference | Per-ticket | Radio: per_ticket / batch / manual |
| Billing email | (blank) | Optional — for AP departments with dedicated email |
| Payment terms | Shop default | Dropdown: COD, Net 15, Net 30, Net 45, Net 60 |
| Custom pricing | Off | Toggle — when on, shows 5-break price fields |
| Primary technician | (none) | Dropdown of active techs — already done via CODE-136 |

### What does NOT go here (too complex):
- Tax override per customer (rare, use settings)
- Reward program enrollment (automatic)
- Approval workflow settings (per-repair, not per-customer)

### UX Mockup (text):

```
┌─ Create Customer ──────────────────────────┐
│ Business Name: [________________]          │
│ Contact Name:  [________] [________]       │
│ Email:         [________________]          │
│ Phone:         [________________]          │
│                                             │
│ ☐ Send invite email                        │
│ ☐ Set as primary contact                   │
│                                             │
│ ▸ Billing & Preferences (optional)         │
│ ┌─────────────────────────────────────────┐ │
│ │ Invoice: ○ Per-ticket ○ Batch ○ Manual │ │
│ │ Billing email: [________________]      │ │
│ │ Payment terms: [Shop default ▾]        │ │
│ │ ☐ Custom pricing                       │ │
│ │   1st break: [$50] 2nd: [$40] ...     │ │
│ │ Primary tech: [Select... ▾]            │ │
│ └─────────────────────────────────────────┘ │
│                                             │
│ [Create Customer]                           │
└─────────────────────────────────────────────┘
```

### How it works:
- Section starts **collapsed** — "▸ Billing & Preferences (optional)"
- Click to expand — "▾ Billing & Preferences"
- All fields are optional with sensible defaults
- If collapsed and user just hits Create, everything uses shop defaults
- If expanded, preferences are saved to `CustomerRepairPreference` and `CustomerPricing` on the same POST

### Implementation:
1. Add collapsible `<details>` element to `customer_form.html`
2. In `create_customer()` view, after creating Customer + CustomerUser:
   - If billing fields present in POST, create/update `CustomerRepairPreference`
   - If custom pricing toggled on, create `CustomerPricing` record
3. Primary tech already handled by CODE-136

## Scope

- **~50 lines of template** (collapsible section with fields)
- **~30 lines of view logic** (save preferences on POST)
- **0 new models** — uses existing `CustomerRepairPreference` and `CustomerPricing`
- **0 migrations**

## Risk

| Risk | Severity | Mitigation |
|------|----------|------------|
| Form feels cluttered | Low | Collapsed by default — quick-add flow unchanged |
| Existing customers not affected | None | Only applies to new creates |
| Billing fields saved incorrectly | Low | Same models/validation as the existing settings page |

## Decision Needed

Drake: approve this approach? The key question is whether the collapsible section is the right UX or if you'd prefer a two-step wizard (create → configure) instead.
