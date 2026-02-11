# RS Systems Billing Guide

> How billing, invoicing, and automation work in RS Systems.  
> Last updated: February 11, 2026

---

## Customer Invoice Preferences

Each customer has an **invoice preference** that controls when and how they receive invoices. Set this in Customer → Edit → Billing Preferences.

| Preference | Behavior | Best For |
|------------|----------|----------|
| **Per Ticket** | Invoice generated immediately when repair is marked complete | Retail customers, one-off jobs |
| **Batch** | Repairs accumulate; single invoice generated on schedule | Fleet accounts with multiple vehicles |
| **Manual** | No auto-invoicing; owner creates invoices manually | Special billing arrangements |

### Example: Customer A (Per Ticket)
1. Tech completes repair on Unit #123
2. Repair marked "Complete"
3. **Immediately**: Invoice `INV-001` created with 1 line item
4. If auto-send enabled: Email sent to customer with PDF

### Example: Customer B (Batch)
1. Tech completes repair on Unit #123 (Monday)
2. Tech completes repair on Unit #456 (Wednesday)
3. Tech completes repair on Unit #789 (Friday)
4. **No invoices yet** - repairs accumulate
5. Saturday (batch day): Invoice `INV-002` created with 3 line items
6. If auto-send enabled: Single email with consolidated invoice

---

## Auto Invoice Generation

**Location**: Settings → Billing & Tax → Auto Invoice Generation

When **enabled**:
- Repairs marked "Complete" trigger invoice creation
- Follows customer's invoice preference (per_ticket vs batch)
- Per-ticket customers get immediate invoices
- Batch customers wait for scheduled batch run

When **disabled**:
- No automatic invoice creation
- Owner must manually create all invoices
- Useful for testing or special situations

---

## Batch Invoicing

**Location**: Settings → Billing & Tax → Batch Invoicing

### Settings

| Setting | Description |
|---------|-------------|
| **Frequency** | How often to run: Weekly, Bi-weekly, Monthly, or Disabled |
| **Day** | When to run. Weekly: 0=Monday, 6=Sunday. Monthly: 1-28 |
| **Auto-Send** | If ON, invoices are sent immediately. If OFF, created as Draft |

### How It Works

1. **Celery task runs daily at 6 AM**
2. Task checks if today matches the configured schedule
3. For each customer with `invoice_preference = 'batch'`:
   - Find all completed repairs NOT yet on an invoice
   - Find all completed replacements NOT yet on an invoice
   - If any found: Create single consolidated invoice
4. If Auto-Send is ON: Email invoice to customer
5. If Auto-Send is OFF: Invoice created as DRAFT for review

### What Gets Included

Only repairs/replacements that are:
- ✅ Status = "Completed"
- ✅ Not already on another invoice
- ✅ Not marked `skip_invoicing = True`
- ✅ Belong to a customer with `invoice_preference = 'batch'`

### Example Schedule

**Weekly on Monday (Day = 0)**:
- Runs every Monday at 6 AM
- Invoices all batch customers' completed work from the past week

**Monthly on the 1st (Day = 1)**:
- Runs on the 1st of each month at 6 AM
- Invoices all batch customers' completed work from the past month

**Bi-weekly on Friday (Day = 4)**:
- Runs every other Friday at 6 AM
- Invoices completed work from the past two weeks

---

## Overdue Reminders

**Location**: Settings → Billing & Tax → Overdue Reminders

### Settings

| Setting | Description |
|---------|-------------|
| **Enabled** | Toggle automatic reminder emails ON/OFF |
| **Reminder Days** | Days after due date to send reminders (comma-separated) |
| **Email Subject** | Template for reminder email subject line |

### How It Works

1. **Celery task runs daily at 8 AM**
2. Updates invoice status: SENT → OVERDUE if past due date
3. For each overdue invoice:
   - Calculate days overdue
   - If days matches one of the reminder days → send email
4. Reminder is logged in invoice's internal notes

### Email Subject Variables

Use these placeholders in the subject template:
- `{invoice_number}` → "INV-001"
- `{customer_name}` → "EOS Trucking"
- `{amount_due}` → "$150.00"
- `{days_overdue}` → "14"

**Example**: `Reminder: Invoice #{invoice_number} is {days_overdue} days overdue`
→ "Reminder: Invoice #INV-001 is 14 days overdue"

### Reminder Schedule Example

**Setting**: `7,14,30`

| Days Overdue | Action |
|--------------|--------|
| 1-6 days | No reminder |
| 7 days | First reminder email |
| 8-13 days | No reminder |
| 14 days | Second reminder email |
| 15-29 days | No reminder |
| 30 days | Third reminder email |
| 31+ days | No more automatic reminders |

---

## Invoice Lifecycle

```
┌─────────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│   DRAFT     │ ──▶ │   SENT   │ ──▶ │ OVERDUE  │ ──▶ │   PAID   │
└─────────────┘     └──────────┘     └──────────┘     └──────────┘
      │                   │                │
      │                   │                │
      ▼                   ▼                ▼
 ┌──────────┐       ┌──────────┐     ┌──────────┐
 │ CANCELLED│       │ PARTIAL  │     │ PARTIAL  │
 └──────────┘       └──────────┘     └──────────┘
```

| Status | Description |
|--------|-------------|
| **DRAFT** | Created but not sent. Can be edited. |
| **SENT** | Emailed to customer. Clock starts on due date. |
| **PARTIAL** | Customer made partial payment. Shows remaining balance. |
| **OVERDUE** | Past due date and not fully paid. Triggers reminders. |
| **PAID** | Fully paid. No further action needed. |
| **CANCELLED** | Voided. Not counted in reports. |

---

## Sales Tax

**Location**: Settings → Billing & Tax → Sales Tax

### How It Works

1. Set your tax rate components (state, county, city, special)
2. Total rate auto-calculates
3. Tax applied to repairs when saved
4. Tax applied to invoices when created

### Per-Customer Exemption

Some customers (government, resellers) may be tax-exempt:
1. Go to Customer → Edit
2. Check "Tax Exempt"
3. All invoices for this customer will have $0 tax

---

## Payment Methods

RS Systems supports multiple payment methods:

| Method | How It Works |
|--------|--------------|
| **Stripe (Online)** | Customer clicks "Pay Online" link in email |
| **Check** | Owner records manual payment |
| **Cash** | Owner records manual payment |
| **ACH/Wire** | Owner records manual payment |

### Recording Manual Payments

1. Go to Invoices → Find invoice
2. Click "Record Payment"
3. Enter amount, method, reference number
4. Invoice status updates automatically

---

## Celery Tasks Reference

| Task | Schedule | Description |
|------|----------|-------------|
| `billing.process_overdue_invoices` | Daily 8 AM | Update overdue status, send reminders |
| `billing.process_batch_invoices` | Daily 6 AM | Generate batch invoices (checks config) |
| `billing.generate_aging_report` | On-demand | Generate A/R aging report |

### Running Tasks Manually

```bash
# In Django shell
from apps.billing.tasks import process_overdue_invoices, process_batch_invoices

# Run overdue processing now
process_overdue_invoices.delay()

# Run batch invoicing now  
process_batch_invoices.delay()
```

---

## Troubleshooting

### Invoice not generated for completed repair

1. Check customer's invoice preference (per_ticket vs batch)
2. Check if Auto Invoice Generation is enabled
3. Check if repair is marked "Complete"
4. Check if repair has `skip_invoicing = True`

### Batch invoice missing some repairs

1. Verify repairs are marked "Complete"
2. Verify repairs aren't already on another invoice
3. Verify customer has `invoice_preference = 'batch'`

### Reminder emails not sending

1. Check Overdue Reminders is enabled
2. Check invoice is actually overdue (past due_date)
3. Check days overdue matches reminder_days setting
4. Check customer has valid email address
5. Verify Celery Beat is running

### Celery tasks not running

```bash
# Check Celery Beat is running
ps aux | grep celery

# Start Celery Beat
celery -A rs_systems beat -l info

# Start Celery Worker
celery -A rs_systems worker -l info
```
