# User Flows  RS Systems

Complete user journeys for every role in the RS Systems platform.

---

## Shop Owner

The shop owner is the first person to sign up. They create the business, set up billing, invite their team, and manage everything.

### Signup  Onboarding  First Repair

1. **Sign up** at `/signup/`
   - Enter business name ("Quick Fix Auto Glass"), your name, email, password
   - Click "Start Your Free Trial"
   - You're now logged in with a 30-day trial on the Starter plan

2. **Complete onboarding** (4 steps  any can be skipped)
   - Step 1: Business info  phone number, email, address, upload logo
   - Step 2: Add your first technician  yourself or someone else
   - Step 3: Add your first customer  name, type (fleet/retail/walk-in)
   - Step 4: Done!  redirected to the owner dashboard

3. **Explore the dashboard** at `/owner/`
   - See usage meters (repairs this month, active techs, customers)
   - Quick actions to create repairs, manage team, check billing
   - Recent activity feed

### Invite Your Team

4. **Invite a technician** at `/owner/settings/#team`
   - Click "Invite Member"
   - Enter their name, email, select role (Technician)
   - Toggle abilities:  Can Repair,  Can Replace
   - Click "Send Invite"  they'll receive an email with a 7-day link
   - If email fails, copy the `/invite/<token>/` link manually

5. **Invite a manager**  same flow but select role "Manager"
   - Managers can invite technicians and viewers
   - Managers can deactivate technicians and viewers
   - Managers cannot manage billing or change other manager/owner roles

### Invite Customers

6. **Share the customer portal link** at `/owner/settings/`
   - Find the "Customer Portal" card with your shop's join URL
   - Click "Copy Link"  share via email, text, print on business card
   - URL format: `/join/<your-shop-slug>/`
   - Customers sign up themselves  no admin work needed

7. **View customers** in the Customers section at `/owner/settings/#customers`
   - See all customers, their type (Fleet/Retail/Walk-in)
   - Portal access status (has account or not)

### Manage Team

8. **Edit a team member**  click "Edit" on any member
   - Change role (owner can change anyone except themselves)
   - Toggle abilities (repairs, replacements)
   - Save changes

9. **Deactivate a team member**  click "Deactivate"
   - Soft delete  membership marked inactive
   - Can be re-activated later by re-inviting

10. **Resend invite**  for members who haven't set their password yet
    - Creates a new 7-day token and sends a fresh email

### Manage Billing

11. **View billing** at `/owner/billing/`
    - See current plan, usage breakdown, upgrade options
    - Manage Stripe subscription (upgrade, downgrade, cancel)
    - Access Stripe billing portal for payment methods

---

## Manager

Managers are invited by the shop owner. They can manage day-to-day operations, invite technicians and viewers, and handle repairs.

### Accept Invite  Get Started

1. **Receive invite email** with a link to `/invite/<token>/`
2. **Click the link**  see the shop name and your role
3. **Set your password** (min 8 characters) and confirm
4. **Auto-logged in**  redirected to the owner dashboard

### Daily Workflow

5. **Dashboard** at `/owner/`  same view as owner (minus billing controls)
6. **Settings** at `/owner/settings/`  invite technicians and viewers
7. **Tech portal** at `/tech/`  manage repairs if you have technician abilities
   - Your technician abilities are set by the owner (can_repair, can_replace)

### What Managers Can Do

-  View dashboard, settings, team members
-  Invite technicians and viewers
-  Deactivate technicians and viewers
-  Create/manage repairs and replacements (with abilities)
-  Change billing or subscription
-  Change owner/manager roles
-  Deactivate owners or other managers

---

## Technician

Technicians do the hands-on work  chip repairs, crack repairs, and full glass replacements.

### Accept Invite  Start Working

1. **Receive invite email** from shop owner or manager
2. **Click the link** at `/invite/<token>/`
3. **Set your password** and confirm
4. **Auto-logged in**  redirected to the technician dashboard at `/tech/`

### Daily Workflow

5. **Dashboard** at `/tech/`  see assigned repairs, today's queue
6. **Create a repair**:
   - Select customer, enter unit number, take before photos
   - System auto-prices: $50  $40  $35  $30  $25 progressive pricing
   - Submit  repair enters queue
7. **Create a replacement** at `/tech/replacement/new/`:
   - Full glass swap  enter parts cost, labor cost, ADAS calibration
   - Optional insurance claim details
8. **Manage customers** at `/tech/customers/`  view customer details, add new ones

### Abilities

Technician abilities are controlled by the shop owner:

| Ability | What It Allows |
|---------|---------------|
| Can Repair | Create chip/crack repairs |
| Can Replace | Create full glass replacements |

A technician with both abilities can do everything. A technician with only "Can Repair" will not see the replacement form.

---

## Customer

Customers access the portal to track repairs, approve work orders, and view invoices for their vehicles.

### Sign Up  Access Portal

1. **Receive the shop's join link**  shared by the shop via email, text, or in person
   - URL format: `/join/<shop-slug>/`
2. **Visit the join page**  see the shop's name and branding
   - Feature highlights: Track Repairs, Approve Work Orders, View Invoices
3. **Create an account**:
   - Enter first name, last name, email
   - Optional: phone number, company name (for fleet customers)
   - Set password and confirm
   - If you enter a company name  Fleet account
   - If no company  Retail (individual) account
4. **Auto-logged in**  redirected to customer dashboard at `/app/`

### Using the Portal

5. **Dashboard** at `/app/`  overview of recent services (repairs and replacements, with type badges), pending approvals, combined stats
6. **My Repairs** at `/app/repairs/`  full repair history with filtering
   - See each repair's status: Requested  Pending  Approved  In Progress  Completed
   - Click any repair for full details including photos
   - **My Replacements** at `/app/replacements/`  same for glass replacements
7. **Approve/Deny services**  when a technician discovers damage in the field, or the shop prices a replacement:
   - You'll see pending approval items (repairs and replacements) on your dashboard
   - Click to review details, then approve or deny
   - Batch approvals available for multi-break repairs
8. **Request a Repair** at `/app/repairs/request/`  submit a new repair request
   - Describe the damage, add photos, specify urgency
   - Shop receives the request and assigns a technician
9. **Request a Replacement** at `/app/replacements/request/`  request a full glass replacement
   - Both request pages share a "Chip or Crack Repair ↔ Full Glass Replacement" toggle
   - Pick the vehicle/unit, which glass (windshield, side, rear, sunroof, …), describe what happened, optionally attach a photo
   - No pricing at request time  the shop confirms the exact glass and price, which then comes back to you for approval
   - The shop is notified in-app and by email
10. **Rewards**  view referral codes, earned points, available rewards
11. **Account Settings** at `/app/account/settings/`  update profile, change password, notification preferences

### Login

After initial signup, return at any time:
- Go to `/login/` (unified login for all roles)
- Enter email and password
- Auto-routed to the customer portal at `/app/`

---

## Repair Assignment Strategies

Shop owners can configure how new repair requests are automatically assigned to technicians. This is set in **Owner Settings  Repair Assignment**.

### Strategies

| Strategy | Behavior |
|----------|----------|
| **Manual** | No auto-assignment. A manager must manually assign every incoming repair. Best for small teams that want full control. |
| **Primary Tech First** *(default)* | If the customer has a primary technician, auto-assign to them. If not, the repair stays unassigned for manual assignment. |
| **Smart Auto-Assign** | Tries the primary tech first, then falls back to the eligible technician with the fewest active jobs. Balances workload automatically. |
| **Round Robin** | Rotates assignments evenly through all eligible technicians by ID order. Ignores workload  purely rotational. |

### Primary Technician

Each customer can have a **primary technician**  a default tech for all their work. Set this in:
- **Owner Settings  Customers** (badge shown per customer)
- **Technician Portal  Customer Details** (managers/admins can change via dropdown)
- **Customer Creation Form** (select during creation)

When a customer with a primary tech submits a repair request:
1. The system checks the tenant's assignment strategy
2. If the strategy uses primary tech (primary_first, auto, round_robin respects eligibility)
3. The repair is auto-assigned and the tech gets an in-app notification

### Eligibility Checks

Auto-assignment only considers technicians who are:
- **Active** (`is_active=True`)
- **Belong to the same tenant**
- **Have the right ability**: `can_repair` for repairs, `can_replace` for replacements

### Notifications

When a repair or replacement is auto-assigned, the technician receives an in-app notification ( badge) visible in their notification panel.

---

## Configure Your Shop Flow

After completing onboarding, shop owners can fine-tune their setup using the **Configure Your Shop** page at `/owner/setup/`. A setup progress card on the owner dashboard links here until the critical sections are done.

### The 6 Setup Sections

```
1. Business Info        — Name, phone, email, address (shown on invoices)
2. Pricing Structure    — Progressive vs flat rate pricing
3. Tax Settings         — Sales tax rates and exemptions
4. Billing & Invoicing  — Invoice prefix, payment terms, defaults
5. Viscosity            — Enable temperature-based resin suggestions (optional)
6. Repair Assignment    — Manual, primary tech first, smart auto, or round robin
```

### How It Works

- Each section is an **accordion** — click to expand and edit
- Each section has its own **Save button** — changes save independently (AJAX, no page reload)
- A **progress bar** at the top shows how many of the 6 sections are configured
- An **⚠ Not configured** badge marks incomplete sections
- A **✓ Complete** badge marks finished sections
- A toast notification confirms each save

### Viscosity Auto-Populate

If you enable viscosity recommendations for the first time:
- 5 default rules are automatically created for your shop
- Rules cover: Cold (<60°F), Cool (60–75°F), Ideal (75–95°F), Warm (95–105°F), Hot >105°F
- A preview of your rules is shown in the section
- Click "Edit rules directly →" to customize them at `/tech/settings/viscosity/`

### After Setup

Once Business Info and Billing are complete, the setup progress card on the dashboard disappears. You can return to `/owner/setup/` anytime to update your configuration.

---

## Subscription Expiry Flow

What happens when a shop's trial or subscription expires.

### During Trial

```
Owner signs up
    ↓
30-day free trial begins
    ↓
7 days before trial ends:
- Owner dashboard shows "Trial Expiring Soon" warning banner
- Banner includes days remaining and an upgrade link
    ↓
Trial expires
- Owner dashboard shows "Your free trial has expired" banner
- Access is still available during the grace period
```

### When Subscription Expires (Paid or Trial)

```
Subscription expires
    ↓
30-day grace period begins
- Owners and managers: see warning banner, can still use the system
- Technicians and customers: can still access
    ↓
Grace period ends
- Subscription middleware blocks all portal access
- Everyone sees the "Subscription Blocked" screen
```

### What Each Role Sees After Grace Period

**Owners and Managers**:
```
Your Subscription Has Expired

Your RS Systems subscription is no longer active.
Upgrade now to restore full access.

[Upgrade Now →]

Questions? Email us at contact@rssystems.io
```

**Technicians**:
```
Shop Subscription Expired

Your shop's RS Systems subscription has expired.
Contact your shop owner to reactivate.

Owner: [Name] — [email@example.com]

Once the subscription is renewed, you'll regain access automatically.
```

**Customers**:
```
Portal Temporarily Unavailable

[Shop Name]'s customer portal is temporarily unavailable.
Please contact the shop directly.

[Shop Phone]
[Shop Email]
```

### Reactivating

1. Owner goes to `/owner/billing/` (still accessible even when blocked, for owners only)
2. Upgrades or renews the subscription via Stripe
3. Subscription status updates to `active`
4. All users regain access immediately — no action required from technicians or customers

Admins can also reactivate a subscription from the Django admin:
- Go to Admin → Tenants → Tenants
- Select the tenant
- Use action: **✅ Activate subscription**

---

## Statement of Account Flow

Owners can generate a Statement of Account for any customer — useful for billing disputes, collections, or customer requests.

### Accessing a Statement

```
1. Go to /owner/ (Owner Dashboard)
2. Click "Customers" or "Invoices" in the sidebar
3. Find the customer in the list
4. Click their name to view customer details
5. Look for "Statement of Account" or navigate directly:
   /owner/customers/<customer_id>/statement/
```

### What's on the Statement

The Statement of Account shows:
- Customer name and your shop's billing info
- Statement date
- All invoices for this customer with status (Paid, Sent, Overdue, etc.)
- Invoice totals, amounts paid, amounts due
- Summary: total outstanding balance

### Use Cases

- **Customer requests a summary** of all their outstanding invoices
- **Collections** — print or email the statement to a customer with overdue balances
- **Year-end accounting** — snapshot of a customer's billing history
- **Dispute resolution** — show exactly what was invoiced and when

---

## Aging Report Flow

The AR Aging Report shows all outstanding invoices grouped by how long they've been unpaid. It's a standard accounts receivable tool to identify who owes money and for how long.

### Accessing the Aging Report

```
1. Go to /owner/billing/ (Owner Invoices page)
2. The "AR Aging Report" widget appears at the top of the page
3. Data loads automatically when the page opens
```

The widget shows invoices bucketed by age:
- **Current** — due date hasn't passed yet
- **1–30 days overdue**
- **31–60 days overdue**
- **61–90 days overdue**
- **90+ days overdue**

Each bucket shows the number of invoices and total dollar amount.

### Exporting to CSV

Click **Export CSV** in the aging report widget header to download a full breakdown including customer name, invoice number, invoice date, due date, and amount due for every outstanding invoice.

**CSV URL**: `/owner/billing/aging/export/`

### How to Use It

1. **Identify priority collections** — focus on the 90+ days overdue bucket first
2. **Export the CSV** and share with your bookkeeper or accountant
3. **Cross-reference with customer statements** — generate a statement for any overdue customer at `/owner/customers/<id>/statement/`
4. **Take action**: Send reminders, call customers, or mark invoices as OVERDUE in Admin → Billing → Invoices

---

## Summary: How Everyone Connects

```
Shop Owner signs up
    
     Invites Managers (email invite  /invite/<token>/)
          Managers invite Technicians (same flow)
    
     Invites Technicians (email invite  /invite/<token>/)
          Technicians do repairs
    
     Shares customer join link (/join/<slug>/)
           Customers self-signup  track repairs  approve work
```

All users log in at `/login/`  the system automatically routes them to the correct portal based on their role.
