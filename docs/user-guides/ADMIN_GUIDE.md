# Admin Interface Guide

Complete guide for administrators managing RS Systems via Django admin.

## Table of Contents
- [Getting Started](#getting-started)
- [Admin Dashboard](#admin-dashboard)
- [Tenant Filtering](#tenant-filtering)
- [Subscription Management](#subscription-management)
- [Customer Management](#customer-management)
- [Technician Management](#technician-management)
- [Pricing Configuration](#pricing-configuration)
- [Repair Preferences](#repair-preferences)
- [User Management](#user-management)
- [CSV Exports](#csv-exports)
- [Bulk Invoice Generation](#bulk-invoice-generation)
- [Audit Log](#audit-log)
- [Global Search](#global-search)

---

## Getting Started

### Accessing Admin

```
URL: https://[your-domain]/admin/
Credentials: Superuser account required
```

**Important**: The admin interface is restricted to superusers. Regular staff accounts cannot log in. Contact your system administrator to request superuser access.

### Admin Dashboard Overview

When you first log in at `/admin/`, you land on a **custom metrics dashboard** instead of the default Django list view. The dashboard shows real business data at a glance.

**Sections on the dashboard**:
- **Subscription Overview** — active, trialing, in grace period, expired tenant counts
- **This Month** — repairs completed, invoices created, revenue collected, outstanding balance
- **Recent Activity** — last 10 repairs and last 5 invoices across all tenants

Below the metrics, the standard model list is still available:

```
AUTHENTICATION AND AUTHORIZATION
- Groups
- Users

CORE
- Customers

CUSTOMER_PORTAL
- Customer preferences
- Customer pricing
- Customer users
- Repair approvals
- Customer repair preferences

TECHNICIAN_PORTAL
- Repairs
- Replacements
- Technicians
- Unit repair counts
- Viscosity recommendations

TENANTS
- Tenants
- Tenant memberships
- Subscription plans

BILLING
- Invoices
- Payments
- Tax rates
- Billing config

DJANGO ADMIN LOG
- Log entries (Audit Log)
```

---

## Admin Dashboard

The admin dashboard (`/admin/`) shows live business metrics pulled from the database.

### Subscription Overview

| Metric | What It Means |
|--------|---------------|
| **Active** | Tenants with a live paid subscription |
| **Trialing** | Tenants on free trial |
| **Expiring Soon** | Trial tenants with ≤ 7 days remaining |
| **Grace Period** | Expired tenants still within the 30-day grace window |
| **Expired** | Tenants whose subscription and grace period have ended |
| **Canceled** | Tenants who explicitly canceled |
| **Total** | All tenants in the system |

### This Month's Stats

| Metric | Source |
|--------|--------|
| **Repairs** | Completed repairs with a service date in the current calendar month |
| **Invoices** | Invoices created this month |
| **Revenue** | Payments collected this month (PAID + PARTIAL invoices) |
| **Outstanding** | Total unpaid balance across all tenants (SENT + PARTIAL + OVERDUE) |

### Recent Activity Feed

- **Recent Repairs** — last 10 repairs created, showing customer, tech, tenant, and status
- **Recent Invoices** — last 5 invoices, showing customer, status, and total

---

## Tenant Filtering

RS Systems is a multi-tenant platform. The admin is tenant-aware:

- **Superusers** see all data across every tenant. A "Tenant" filter appears in list views so you can narrow by shop.
- **Non-superuser staff** only see data belonging to their own tenant. The tenant filter is hidden since it would be redundant.

This applies to: Repairs, Replacements, Invoices, Payments, Customers, Technicians, and any other model with a tenant relationship.

**Practical example**: A staff member at "Acme Glass" logs into `/admin/` and opens Repairs — they only see Acme Glass repairs. A superuser sees all repairs from all shops.

---

## Subscription Management

**Navigation**: Admin → Tenants → Tenants

The Tenants list provides bulk actions for managing shop subscriptions without touching Stripe directly.

### Available Actions

Select one or more tenants, then choose an action from the dropdown:

| Action | What It Does |
|--------|-------------|
| **⏱ Extend trial by 7 days** | Pushes the trial expiry 7 days forward. Only affects tenants on the `trial` plan. |
| **⏱ Extend trial by 30 days** | Same as above but 30 days. Useful for customer service situations. |
| **✅ Activate subscription** | Sets `subscription_status` to `active` and marks the tenant as active. Use after manual payment or account resolution. |
| **🚫 Deactivate subscription** | Sets status to `expired` and grants a 30-day grace period. The shop owner sees an upgrade prompt; technicians and customers see a blocked screen. |

### Tenant Detail View

Opening a tenant shows its full subscription state:

- **Plan** — `trial`, `starter`, `pro`, etc.
- **Subscription Status** — `trialing`, `active`, `expired`, `canceled`
- **Grace Period End** — if in grace, shows the expiry date
- **Had Paid Subscription** — whether this tenant ever had a paid plan (affects what they see when expired)
- **Stripe IDs** — linked customer and subscription IDs for Stripe lookups

### Grace Period Behavior

When you deactivate a subscription or a payment fails, the system grants a **30-day grace period**. During grace:
- The shop owner sees a warning banner but can still access the system
- Technicians and customers can still work
- After grace expires, all non-superuser access is blocked until the subscription is reactivated

---

## CSV Exports

Several models support exporting selected records to CSV directly from the admin list view. Select the rows you want, choose the export action from the dropdown, and click **Go**.

| Model | Action | File |
|-------|--------|------|
| **Repairs** | 📥 Export selected repairs as CSV | `repairs.csv` |
| **Customers** | 📥 Export selected customers as CSV | `customers.csv` |
| **Invoices** | 📥 Export selected invoices as CSV | `invoices.csv` |

**What's included**:
- **Repairs CSV**: ID, Tenant, Customer, Unit #, Technician, Status, Damage Type, Cost, Service Date
- **Customers CSV**: ID, Name, Tenant, Email, Phone, Address, Customer Type, Tax Exempt
- **Invoices CSV**: Invoice #, Customer, Invoice Date, Due Date, Payment Terms, Status, Subtotal, Tax, Total, Amount Paid, Amount Due

---

## Bulk Invoice Generation

**Navigation**: Admin → Technician Portal → Customers

You can generate draft invoices for multiple customers at once:

1. Select one or more customers using the checkboxes
2. Choose **🧾 Generate draft invoices for selected customers** from the Actions dropdown
3. Click **Go**

**What happens**:
- For each selected customer, the system finds all **completed repairs** that haven't been billed yet
- Creates one **DRAFT invoice** per customer covering all their unbilled repairs
- Each repair becomes a line item on the invoice
- Invoices use the payment terms from Billing Config (default: NET30)
- Customers with no unbilled completed repairs are skipped

**After generation**:
- Go to Billing → Invoices to review the drafts
- Set status to **SENT** when ready to bill
- Use the "Mark as Sent" action or open the invoice and change status manually

---

## Audit Log

**Navigation**: Admin → Django Admin Log → Log entries

Every change made through the Django admin is automatically recorded. The audit log shows:

| Column | What It Shows |
|--------|---------------|
| **Time** | When the action happened |
| **User** | Who made the change (links to their user record) |
| **Action** | Color-coded badge — Added (green), Changed (blue), Deleted (red) |
| **Content Type** | Which model was affected (Repair, Invoice, Tenant, etc.) |
| **Object** | The specific record that was changed |
| **Changes** | A summary of what changed |

**The audit log is read-only** — you cannot add, edit, or delete entries. This is intentional; the log is an immutable record.

**Filtering options**:
- By action type (Added / Changed / Deleted)
- By content type (model)
- By date range (date hierarchy at the top)
- Search by username, email, object name, or change description

---

## Global Search

**URL**: `/admin/search/`

The global search lets you find anything across the system from one place. Enter a name, email, unit number, or invoice number and get results grouped by type:

- **Customers** — matches on company name or email
- **Repairs** — matches on unit number or customer name
- **Invoices** — matches on invoice number or customer name
- **Users** — matches on username, email, first name, or last name

Up to 20 results per category are shown. Click any result to go straight to its admin edit page.

You can also access global search from the admin navigation bar (look for the search link in the top navigation).

---

## Customer Management

### Viewing Customers

**Navigation**: Admin → Core → Customers

**List View Shows**:
- Company name
- Contact person
- Email
- Phone
- Address

### Creating New Customer

```
1. Click "Add customer" button
2. Fill required fields:
   - Name (company name)
   - Contact_name
   - Email
   - Phone
   - Address
3. Save
```

### Customer Fields

| Field | Description | Required |
|-------|-------------|----------|
| Name | Company name |  |
| Contact_name | Primary contact person |  |
| Email | Contact email |  |
| Phone | Contact phone |  |
| Address | Company address |  |

---

## Technician Management

### Viewing Technicians

**Navigation**: Admin → Technician Portal → Technicians

**List Shows**:
- User (linked Django account)
- Email
- Full Name
- Phone
- Expertise
- Manager ( if manager)
- Active ( if active)
- Repairs (completed count)

### Creating Technician Profile

**Prerequisites**: User account must exist first

```
1. Admin → Technician Portal → Technicians
2. Click "Add technician"
3. Select user from dropdown
4. Fill basic info:
   - Phone number
   - Expertise (e.g., "Senior Technician")
   - Is active: 
5. Save
```

### Promoting to Manager

```
1. Click technician name to edit
2. Scroll to "Manager Capabilities" section
3. Configure:
    Is manager
   Approval limit: 150.00         Max override amount
    Can assign work
    Can override pricing
   Managed technicians: [Select team members]
4. Save
```

**Approval Limits**:
- **$50**: New managers, small adjustments only
- **$150**: Standard managers, most situations
- **$500**: Senior managers, major exceptions
- **Blank**: Unlimited (use carefully!)

### Manager Capabilities Explained

| Permission | Effect |
|------------|--------|
| **Is manager** | Grants manager status, sees REQUESTED repairs |
| **Can assign work** | Can assign repairs to team members |
| **Can override pricing** | Shows override section in repair forms |
| **Approval limit** | Maximum override amount allowed |
| **Managed technicians** | Team members this manager supervises |

### Performance Tracking

```
Performance Metrics section:
- Repairs completed: [Auto-updated]
- Average repair time: [Manual entry]
- Customer rating: [Manual entry, 1.00-5.00]
```

### Schedule Management

```
Working hours: JSON format

Example:
{
  "monday": ["9:00", "17:00"],
  "tuesday": ["9:00", "17:00"],
  "wednesday": ["9:00", "17:00"],
  "thursday": ["9:00", "17:00"],
  "friday": ["9:00", "17:00"],
  "saturday": ["9:00", "13:00"],
  "sunday": []
}
```

---

## Pricing Configuration

### Customer Pricing

**Navigation**: Admin → Customer Portal → Customer Pricing

### Creating Custom Pricing

```
1. Click "Add customer pricing"
2. Customer & Settings:
   - Customer: [Select from dropdown]
    Use custom pricing
   - Notes: "VIP customer - 10% discount on all repairs"

3. Custom Repair Pricing:
   - Repair 1 price: 45.00    (Leave blank for default $50)
   - Repair 2 price: 36.00    (Leave blank for default $40)
   - Repair 3 price: 31.50    (Leave blank for default $35)
   - Repair 4 price: 27.00    (Leave blank for default $30)
   - Repair 5+ price: 22.50   (Leave blank for default $25)

4. Volume Discounts:
   - Threshold: 10            (Number of repairs to qualify)
   - Percentage: 15.00        (Discount percentage, e.g., 15%)

5. Save
```

### Common Pricing Scenarios

#### Scenario 1: Flat Discount (10% off everything)
```
Customer: ABC Logistics
Use custom pricing: 
Repair 1: 45.00   (10% off $50)
Repair 2: 36.00   (10% off $40)
Repair 3: 31.50   (10% off $35)
Repair 4: 27.00   (10% off $30)
Repair 5+: 22.50  (10% off $25)
```

#### Scenario 2: Volume Discount Only
```
Customer: City Delivery Co
Use custom pricing: 
(Leave all repair prices blank - uses defaults)
Volume threshold: 15
Volume percentage: 20.00
```

#### Scenario 3: Contract Pricing + Volume Bonus
```
Customer: Enterprise Fleet
Use custom pricing: 
Repair 1: 40.00
Repair 2: 40.00   (Same rate for first 2)
(Leave 3-5 blank - defaults apply)
Volume threshold: 25
Volume percentage: 15.00
```

### How Pricing Works

**Calculation Order**:
1. Check if custom pricing enabled
2. Get tier price (1st, 2nd, 3rd, 4th, or 5th+ repair)
3. If tier price blank, use default
4. If volume discount qualified, apply percentage
5. If manager override present, use override

**Example**:
```
Customer: ABC Logistics (custom pricing + volume)
Unit: #45 (3rd repair for this unit)
Total customer repairs: 12 (exceeds threshold of 10)

Calculation:
- Base price (3rd repair): $31.50 (custom tier)
- Volume discount: 15%
- Final price: $31.50 � 0.85 = $26.78
```

---

## Repair Preferences

### Customer Repair Preferences

**Navigation**: Admin → Customer Portal → Customer Repair Preferences

### Approval Modes

**Three Options**:

1. **AUTO_APPROVE**: All field repairs auto-approved
   - Use for: Trusted customers, emergency services
   - Result: Tech can fix what they find immediately

2. **REQUIRE_APPROVAL**: Customer must approve every field repair
   - Use for: Cost-conscious customers, strict budget control
   - Result: Customer sees PENDING repairs on dashboard

3. **UNIT_THRESHOLD**: Auto-approve up to X units per visit
   - Use for: Flexible control, predictable costs
   - Result: First X units auto-approved, rest require approval

### Creating Preference

```
1. Click "Add customer repair preference"
2. Select customer
3. Choose approval mode:
    Auto-approve all field repairs
    Require approval for all
    Unit threshold per visit

   If "Unit threshold" selected:
   - Units per visit threshold: 3

4. Save
```

### Lot Walking Service Configuration

**Same Interface**: Admin → Customer Portal → Customer Repair Preferences

Configure scheduled lot walking service for customers:

```
1. Edit existing preference or create new
2. Scroll to "Lot Walking Service Settings" section
3. Configure service:
    Enable lot walking service

   Frequency: [Dropdown]
   - Weekly
   - Bi-weekly (Every 2 weeks)
   - Monthly
   - Quarterly (Every 3 months)

   Preferred time: 09:00 AM    (Time picker)

   Preferred Days for Lot Walking:
    Monday
    Wednesday
    Friday
    Tuesday
    Thursday
    Saturday
    Sunday

4. Save
```

**Field Validation**:
- If lot walking is enabled, only frequency is required
- Time is optional (can be left blank if no preferred time)
- Days are optional (can be left blank if no preferred days)
- Time uses 24-hour format in admin (e.g., 14:00 for 2:00 PM)

**List View Shows**:
- Customer name
- Approval mode
- Lot walking enabled (/)
- Lot walking frequency
- Last updated

**Filtering Options**:
- Filter by lot walking enabled (Yes/No)
- Filter by frequency (Weekly/Bi-weekly/Monthly/Quarterly)
- Filter by approval mode
- Filter by update date

### Examples

**Example 1: Trusted Customer**
```
Customer: ABC Logistics
Mode: AUTO_APPROVE

Result:
- Tech finds 5 chips during lot walk
- All 5 auto-approved
- Tech can complete immediately
- Customer invoiced at end
```

**Example 2: Budget-Conscious Customer**
```
Customer: Startup Delivery
Mode: REQUIRE_APPROVAL

Result:
- Tech finds 2 chips
- Both go to PENDING
- Customer sees yellow alert on dashboard
- Must approve before work starts
```

**Example 3: Hybrid Approach**
```
Customer: Mid-Size Fleet
Mode: UNIT_THRESHOLD
Threshold: 3

Result:
- Tech finds 5 chips during visit
- First 3: Auto-approved (under threshold)
- Units 4-5: PENDING (require approval)
- Customer approves additional 2
```

**Example 4: Lot Walking Customer**
```
Customer: Enterprise Fleet Services
Mode: AUTO_APPROVE
Lot Walking: Enabled
Frequency: Weekly
Preferred Time: 9:00 AM
Preferred Days: Monday, Wednesday, Friday

Result:
- Scheduled lot walks on Mon/Wed/Fri at 9:00 AM
- Tech walks lot and identifies damage
- All repairs auto-approved (AUTO_APPROVE mode)
- Tech completes work same visit
- Customer billed weekly
```

---

## User Management

### Creating Users

```
1. Admin → Authentication and Authorization → Users
2. Click "Add user"
3. Enter:
   - Username
   - Password (twice)
4. Save
5. Edit user to add:
   - First name
   - Last name
   - Email address
   - Staff status (if admin)
   - Groups (if technician)
6. Save
```

### User Roles

**Customers**:
- Regular user (not staff)
- Has CustomerUser profile
- Can access /app/* portal

**Technicians**:
- Regular user (not staff)
- Has Technician profile
- Member of "Technicians" group
- Can access /tech/* portal

**Managers**:
- Regular user (not staff)
- Has Technician profile with is_manager=True
- Member of "Technicians" group
- Additional manager permissions
- Can access /tech/* portal

**Admins**:
- Staff status enabled
- Superuser (optional, for full access)
- Can access /admin/* interface

### Groups & Permissions

**Technicians Group**:
- View/Add/Change repairs
- View customers (read-only)
- View/Change own technician profile
- View/Update notifications

**Creating Group** (if needed):
```bash
python manage.py setup_groups
```

---

## Common Admin Tasks

### Task 1: Set Up New Customer with Special Pricing

```
1. Create customer (Core  Customers)
2. Create customer pricing (Customer Portal  Customer Pricing)
   - Configure tiers and/or volume discount
3. Create repair preference (Customer Portal  Customer Repair Preferences)
   - Choose appropriate approval mode
4. Test with sample repair
```

### Task 2: Promote Technician to Manager

```
1. Technician Portal  Technicians
2. Click technician name
3. Manager Capabilities section:
    Is manager
   Approval limit: 150.00
    Can assign work
    Can override pricing
   Select managed technicians
4. Save
5. Verify manager can see override section in repair forms
```

### Task 3: Give Customer Auto-Approval

```
1. Customer Portal  Customer Repair Preferences
2. Add or edit preference
3. Select customer
4. Mode: AUTO_APPROVE
5. Save
6. Test: Tech creates field repair  should be APPROVED immediately
```

### Task 4: Audit Manager Overrides

```
1. Technician Portal  Repairs
2. Add filter: "Cost override is not null"
3. Review overrides:
   - Check override amounts
   - Review override reasons
   - Verify within approval limits
4. Discuss patterns with team
```

### Task 5: Deactivate Technician Temporarily

```
1. Technician Portal  Technicians
2. Click technician name
3. Uncheck "Is active"
4. Save

Result:
- Won't appear in assignment lists
- Can't login to portal
- Existing assignments preserved
```

### Task 6: Configure Lot Walking Service for Customer

```
1. Customer Portal  Customer Repair Preferences
2. Find or create preference for customer
3. Scroll to "Lot Walking Service Settings"
4. Enable and configure:
    Enable lot walking service
   Frequency: Weekly
   Preferred time: 09:00
   Days:  Monday  Wednesday  Friday
5. Save

Result:
- Customer preferences saved in database
- Settings visible in customer portal (if implemented)
- Ready for scheduling system integration (future feature)
```

---

## Filtering & Searching

### Customer Pricing
- **Filter by**: Use custom pricing (Yes/No), Created date
- **Search**: Customer name, Notes

### Technicians
- **Filter by**: Is manager, Is active, Can assign work, Can override pricing
- **Search**: Username, Email, First name, Last name, Phone

### Repairs
- **Filter by**: Status, Customer, Technician, Date range
- **Search**: Unit number, Notes

---

## Maintenance Tasks

### Weekly
- [ ] Review new customer pricing requests
- [ ] Check manager override usage
- [ ] Update technician performance metrics
- [ ] Review repair approval patterns

### Monthly
- [ ] Audit all custom pricing configurations
- [ ] Review manager approval limits
- [ ] Clean up inactive users
- [ ] Update technician working hours
- [ ] Audit S3 storage for orphaned files

### Quarterly
- [ ] Review all pricing contracts
- [ ] Audit manager permissions
- [ ] Update volume discount thresholds
- [ ] Prepare performance review data
- [ ] Clean up orphaned repair photos in S3

---

## Storage Management

### Auditing Repair Photos in S3

**Purpose**: Identifies and removes orphaned photo files that remain in S3 storage after repairs are deleted.

**When to Use**:
- Monthly maintenance to identify storage waste
- After bulk repair deletions
- When investigating unexpected storage costs
- During system audits

**Command**:
```bash
# Audit only (dry run - safe to run anytime)
python manage.py audit_repair_photos

# Delete orphaned files (use with caution)
python manage.py audit_repair_photos --delete
```

### How It Works

The command:
1. Connects to your S3 bucket (`AWS_STORAGE_BUCKET_NAME`)
2. Lists all files in `media/repair_photos/` directory
3. Compares S3 files against database photo references
4. Identifies:
   - **Orphaned files**: In S3 but not referenced in database (should be deleted)
   - **Missing files**: Referenced in database but not in S3 (indicates a problem)

### Example Output

**Audit Run (Dry Run)**:
```
Starting repair photo audit...
Fetching files from S3...
Found 14 files in S3

Fetching photo references from database...
Found 8 photo references in database

================================================================================
AUDIT RESULTS
================================================================================

Found 6 ORPHANED files (in S3 but not in database):
Total size: 12.45 MB
Estimated monthly cost: $0.0003

  - media/repair_photos/before/IMG_0433.jpeg (2.1 MB, modified: 2025-10-30 09:53:38)
  - media/repair_photos/after/IMG_0434.jpeg (2.3 MB, modified: 2025-10-30 09:53:38)
  - media/repair_photos/before/IMG_0436.jpeg (2.0 MB, modified: 2025-10-30 09:55:42)
  - media/repair_photos/after/IMG_0437.jpeg (1.9 MB, modified: 2025-10-30 09:55:43)
  - media/repair_photos/before/IMG_0439.jpeg (2.1 MB, modified: 2025-11-01 18:35:21)
  - media/repair_photos/after/IMG_0440.jpeg (2.0 MB, modified: 2025-11-01 18:35:21)

No missing files!

================================================================================
DRY RUN MODE: No files were deleted. Use --delete to actually remove orphaned files.
================================================================================

Audit complete!
```

**Delete Run**:
```bash
python manage.py audit_repair_photos --delete
```
```
Starting repair photo audit...
[... audit results ...]

================================================================================
DELETING ORPHANED FILES
================================================================================

Deleted: media/repair_photos/before/IMG_0433.jpeg
Deleted: media/repair_photos/after/IMG_0434.jpeg
Deleted: media/repair_photos/before/IMG_0436.jpeg
Deleted: media/repair_photos/after/IMG_0437.jpeg
Deleted: media/repair_photos/before/IMG_0439.jpeg
Deleted: media/repair_photos/after/IMG_0440.jpeg

Deleted 6 files

Audit complete!
```

### Understanding the Results

**Orphaned Files**:
- Photos that remain after repairs are deleted
- Before November 2025: Photos were NOT automatically deleted
- After November 2025: `django-cleanup` automatically deletes photos
- Safe to delete orphaned files - they're no longer referenced

**Missing Files**:
- Database references photos that don't exist in S3
- Indicates:
  - Manual file deletion without updating database
  - S3 bucket misconfiguration
  - File upload failures
- **Action Required**: Investigate why files are missing

**Storage Costs**:
- S3 Standard Storage: ~$0.023 per GB per month
- Command calculates estimated monthly cost of orphaned files
- Small files have negligible cost, but accumulation matters

### Safety & Best Practices

**Before Deleting**:
1.  Run audit without `--delete` first
2.  Review the list of files to be deleted
3.  Check modification dates (recent files need review)
4.  Ensure you have database backups
5.  Consider taking S3 snapshot if deleting many files

**When to Delete**:
-  Files are older than 30 days
-  Audit shows reasonable file count (<100 files)
-  You've verified against recent repair deletions
-  Storage costs justify cleanup effort

**When NOT to Delete**:
-  Files modified in last 7 days (might be active uploads)
-  Large number of files (>500) without investigation
-  Missing files reported (indicates bigger problem)
-  During active repair operations

### Task: Monthly Storage Audit

**Recommended Process**:
```bash
# 1. Run audit to identify orphaned files
python manage.py audit_repair_photos

# 2. Review output:
#    - Note total size and cost
#    - Check modification dates
#    - Look for patterns

# 3. If orphaned files > 50 MB or > 30 files:
#    - Document findings
#    - Get approval if needed
#    - Run deletion

# 4. Delete orphaned files
python manage.py audit_repair_photos --delete

# 5. Verify deletion
python manage.py audit_repair_photos

# 6. Document in maintenance log
```

### Automatic Photo Deletion (November 2025+)

**New Behavior**:
Since November 2025, the system automatically deletes photos when repairs are deleted using the `django-cleanup` package. The `audit_repair_photos` command is now primarily for:
- Cleaning up historical orphaned files (pre-November 2025)
- Periodic verification that automatic deletion is working
- Troubleshooting unexpected storage growth

**Verification**:
```bash
# Check if django-cleanup is installed
pip list | grep django-cleanup
# Should show: django-cleanup==9.0.0

# Check rs_systems/settings/base.py
grep -A 40 "INSTALLED_APPS" rs_systems/settings/base.py | grep django_cleanup
# Should show: 'django_cleanup.apps.CleanupConfig',
```

---

## Troubleshooting

### Issue: Manager Can't See Override Section

**Check**:
1. User has technician profile 
2. Technician marked as manager 
3. "Can override pricing" checked 
4. User logging into /tech/ portal (not /admin/) 

### Issue: Custom Pricing Not Applying

**Check**:
1. CustomerPricing record exists 
2. "Use custom pricing" checked 
3. Tier prices set (blank = default) 
4. Test with shell command:
   ```bash
   python manage.py shell -c "
   from apps.technician_portal.services.pricing_service import calculate_repair_cost
   from core.models import Customer
   customer = Customer.objects.get(name='ABC Logistics')
   print(calculate_repair_cost(customer, 1))
   "
   ```

### Issue: Approval Preference Not Working

**Check**:
1. CustomerRepairPreference exists 
2. Correct approval mode selected 
3. Unit threshold set (if using UNIT_THRESHOLD mode) 
4. Test with new repair creation 

---

## Best Practices

### Security
- Limit admin access to necessary personnel only
- Use strong, unique passwords for all admin accounts
- Review permissions regularly
- Document all pricing arrangements in notes field

### Data Management
- Back up before major changes
- Test pricing on development before production
- Keep notes updated in all configurations
- Regular audit of user accounts and permissions

### Communication
- Document pricing agreements
- Notify team of manager permission changes
- Keep customers informed of preference changes
- Maintain changelog of admin modifications

---

## Quick Reference Commands

```bash
# Test customer pricing
python manage.py shell -c "
from apps.customer_portal.pricing_models import CustomerPricing
from apps.technician_portal.services.pricing_service import calculate_repair_cost
from core.models import Customer
customer = Customer.objects.get(name='customer_name')
print(f'Repair cost: \${calculate_repair_cost(customer, 1)}')
"

# Check manager permissions
python manage.py shell -c "
from apps.technician_portal.models import Technician
tech = Technician.objects.get(user__username='username')
print(f'Is manager: {tech.is_manager}')
print(f'Approval limit: \${tech.approval_limit}')
"

# List all custom pricing
python manage.py shell -c "
from apps.customer_portal.pricing_models import CustomerPricing
for p in CustomerPricing.objects.filter(use_custom_pricing=True):
    print(f'{p.customer.name}: Tier 1 = \${p.repair_1_price}')
"

# Audit S3 storage for orphaned files
python manage.py audit_repair_photos              # Dry run (safe)
python manage.py audit_repair_photos --delete     # Delete orphaned files

# Count total repairs by customer
python manage.py shell -c "
from apps.technician_portal.models import Repair
from core.models import Customer
from django.db.models import Count
repairs = Repair.objects.values('customer__name').annotate(count=Count('id')).order_by('-count')
for r in repairs[:10]:
    print(f'{r[\"customer__name\"]}: {r[\"count\"]} repairs')
"
```

---

**Last Updated**: March 13, 2026
**For**: RS Systems v2.4
**Target Users**: System Administrators
