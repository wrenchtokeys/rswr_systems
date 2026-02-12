# RS Systems Test Workflow

> Complete testing checklist for Phase 6 & 7 features  
> Created: February 12, 2026

---

## Prerequisites

1. **Fresh test tenant** - Create via `/signup` (NOT rsadmin)
2. **Stripe test mode** - Use test card `4242 4242 4242 4242`
3. **Celery running** (for automation tests):
   ```bash
   celery -A rs_systems worker -l info &
   celery -A rs_systems beat -l info &
   ```

---

## 1. Subscription Billing (Phase 7)

### 1.1 New Subscription (Trial → Paid)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Sign up new account at `/signup` | Creates tenant on Trial plan |
| 2 | Go to Settings → Billing | Shows "Free Trial" badge, plan selection |
| 3 | Click "Starter" plan ($49) | Redirects to Stripe Checkout |
| 4 | **Don't pay yet** - check billing page | Plan should still be "Trial" (not Starter) |
| 5 | Complete payment with test card | Redirects back to billing page |
| 6 | Verify plan updated to "Starter" | Badge shows "Starter", limits updated |

**Security check**: Plan must NOT upgrade until payment completes.

### 1.2 Upgrade (Starter → Pro)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | From Starter plan, click "Pro" ($99) | Redirects to Stripe Billing Portal |
| 2 | Complete upgrade payment | Plan updates to "Pro" |
| 3 | Check usage limits | Should show Pro limits (unlimited repairs, 15 techs) |

### 1.3 Downgrade (Pro → Starter)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | From Pro plan, click "Starter" | Shows "scheduled" message |
| 2 | Check current plan | Still shows "Pro" (keeps access until period end) |
| 3 | Check Stripe Dashboard | Shows scheduled downgrade |

### 1.4 Abandoned Checkout Recovery

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Start upgrade to Enterprise | Redirects to Stripe Checkout |
| 2 | Close checkout without paying | Return to billing page |
| 3 | Click different plan (Starter) | Old incomplete subscription voided, new checkout starts |
| 4 | Check Stripe Dashboard | Only one active/incomplete subscription |

### 1.5 Canceled Subscription Recovery

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Cancel subscription in Stripe Dashboard | Status becomes "canceled" |
| 2 | Go to RS Systems billing page | |
| 3 | Click any plan | Should start fresh checkout (not error) |

---

## 2. Invoice Creation & Sending

### 2.1 Manual Invoice (Save as Draft)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create customer with some completed repairs | |
| 2 | Go to Invoices page | |
| 3 | Find customer row, click "Create Invoice" | Modal opens with repair list |
| 4 | Select 2 of 5 repairs | Total updates |
| 5 | Click "Save Draft" | Invoice created with DRAFT status |
| 6 | Check invoice list | Shows draft invoice, no email sent |

### 2.2 Create & Send with Custom Recipients

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create invoice, click "Create & Send" | Send modal opens |
| 2 | Verify subject preview | Shows "[RS Systems] Invoice #XXX - Customer" |
| 3 | Verify To field | Pre-filled with customer email |
| 4 | Add CC: `test1@example.com, test2@example.com` | |
| 5 | Click "Send Invoice" | Email sent to all recipients |
| 6 | Check invoice status | Changed to SENT |

### 2.3 Partial Manual + Batch Invoice

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Customer has 5 completed repairs | |
| 2 | Set customer preference to "Batch" | |
| 3 | Manually create invoice for 2 repairs | Creates invoice with 2 line items |
| 4 | Run batch invoicing (manually or wait) | |
| 5 | Check new batch invoice | Should have only 3 repairs (not the 2 already invoiced) |

---

## 3. Billing Automation (Phase 6)

### 3.1 Overdue Reminders Setup

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Settings → Billing & Tax | |
| 2 | Find "Overdue Reminders" section | Shows enable toggle, days field, subject field |
| 3 | Enable reminders | Toggle turns green |
| 4 | Set days to "7,14,30" | |
| 5 | Save settings | Success message |

### 3.2 Test Overdue Processing

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create invoice with due date in past | |
| 2 | Send invoice (status = SENT) | |
| 3 | Run task manually: | |
| | `python manage.py shell` | |
| | `from apps.billing.tasks import process_overdue_invoices` | |
| | `process_overdue_invoices()` | |
| 4 | Check invoice status | Changed to OVERDUE |
| 5 | If 7+ days overdue with reminders on | Reminder email sent |
| 6 | Check invoice internal notes | Shows reminder log entry |

### 3.3 Batch Invoicing Setup

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to Settings → Billing & Tax | |
| 2 | Find "Batch Invoicing" section | Shows frequency, day, auto-send |
| 3 | Set frequency to "Weekly" | |
| 4 | Set day to "1" (Monday) | |
| 5 | Leave auto-send OFF | |
| 6 | Save settings | Success message |

### 3.4 Test Batch Invoice Generation

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create customer with preference = "Batch" | |
| 2 | Complete 3 repairs for this customer | |
| 3 | Run task manually: | |
| | `python manage.py shell` | |
| | `from apps.billing.tasks import process_batch_invoices` | |
| | `process_batch_invoices()` | |
| 4 | Check invoice list | New DRAFT invoice with 3 line items |
| 5 | If auto-send was ON | Invoice status = SENT, email sent |

### 3.5 Aging Report

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create invoices with various due dates: | |
| | - 1 current (not yet due) | |
| | - 1 from 15 days ago | |
| | - 1 from 45 days ago | |
| | - 1 from 100 days ago | |
| 2 | Run: | |
| | `from apps.billing.tasks import generate_aging_report` | |
| | `report = generate_aging_report()` | |
| | `print(report)` | |
| 3 | Check buckets | Each invoice in correct bucket |

---

## 4. Manager Permissions

### 4.1 Manager Invoice Access

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create user with "Manager" role | |
| 2 | Log in as manager | |
| 3 | Go to Invoices page | Should have access (not 403) |
| 4 | Create invoice | Should work |
| 5 | Send invoice | Should work |
| 6 | Record payment | Should work |

### 4.2 Technician Invoice Access

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Log in as technician | |
| 2 | Try to access Invoices page | Should be blocked (no access) |

---

## 5. Edge Cases

### 5.1 Customer with No Email

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create customer without email | |
| 2 | Create invoice, click "Create & Send" | |
| 3 | Check To field in modal | Empty - user must enter email |
| 4 | Enter email manually, send | Works |

### 5.2 Tax Exempt Customer

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Enable tax in Settings (e.g., 6.5%) | |
| 2 | Create customer, check "Tax Exempt" | |
| 3 | Create invoice for this customer | |
| 4 | Check invoice total | Tax amount = $0 |

### 5.3 Skip Invoicing Flag

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Complete a repair | |
| 2 | On invoice modal, click "Dismiss" on that repair | |
| 3 | Repair marked `skip_invoicing = True` | |
| 4 | Run batch invoicing | Repair not included |

---

## 6. Stripe Webhook Testing

### 6.1 Test with Stripe CLI

```bash
# Install Stripe CLI
# https://stripe.com/docs/stripe-cli

# Login
stripe login

# Forward webhooks to local
stripe listen --forward-to localhost:8000/api/tenants/webhooks/stripe/

# In another terminal, trigger test events
stripe trigger checkout.session.completed
stripe trigger customer.subscription.updated
stripe trigger invoice.paid
```

### 6.2 Verify Webhook Handling

| Event | Expected Result |
|-------|-----------------|
| `checkout.session.completed` | Plan upgraded, subscription_id saved |
| `customer.subscription.updated` (active) | Plan synced from Stripe |
| `customer.subscription.updated` (incomplete) | Plan NOT changed |
| `invoice.paid` | Status updated if applicable |
| `customer.subscription.deleted` | Plan reverted to trial |

---

## Quick Command Reference

```bash
# Run overdue processing
python manage.py shell -c "from apps.billing.tasks import process_overdue_invoices; print(process_overdue_invoices())"

# Run batch invoicing  
python manage.py shell -c "from apps.billing.tasks import process_batch_invoices; print(process_batch_invoices())"

# Generate aging report
python manage.py shell -c "from apps.billing.tasks import generate_aging_report; import json; print(json.dumps(generate_aging_report(), indent=2))"

# Reset tenant to trial (replace with actual tenant slug)
python manage.py shell -c "
from apps.tenants.models import Tenant, SubscriptionPlan
t = Tenant.objects.get(slug='your-tenant-slug')
t.plan = 'trial'
t.subscription_plan = SubscriptionPlan.objects.get(slug='trial')
t.subscription_status = 'trialing'
t.stripe_subscription_id = ''
t.save()
print(f'Reset {t.name} to trial')
"
```

---

## Checklist Summary

- [ ] 1.1 New subscription flow
- [ ] 1.2 Upgrade flow  
- [ ] 1.3 Downgrade flow
- [ ] 1.4 Abandoned checkout recovery
- [ ] 1.5 Canceled subscription recovery
- [ ] 2.1 Manual invoice (draft)
- [ ] 2.2 Send with custom recipients + CC
- [ ] 2.3 Partial manual + batch
- [ ] 3.1 Overdue reminders setup
- [ ] 3.2 Overdue processing
- [ ] 3.3 Batch invoicing setup
- [ ] 3.4 Batch invoice generation
- [ ] 3.5 Aging report
- [ ] 4.1 Manager access
- [ ] 4.2 Technician blocked
- [ ] 5.1 Customer no email
- [ ] 5.2 Tax exempt
- [ ] 5.3 Skip invoicing
- [ ] 6.1 Webhook testing
