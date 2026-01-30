# User Flows — RS Systems

Complete user journeys for every role in the RS Systems platform.

---

## Shop Owner

The shop owner is the first person to sign up. They create the business, set up billing, invite their team, and manage everything.

### Signup → Onboarding → First Repair

1. **Sign up** at `/signup/`
   - Enter business name ("Quick Fix Auto Glass"), your name, email, password
   - Click "Start Your Free Trial"
   - You're now logged in with a 30-day trial on the Starter plan

2. **Complete onboarding** (4 steps — any can be skipped)
   - Step 1: Business info — phone number, email, address, upload logo
   - Step 2: Add your first technician — yourself or someone else
   - Step 3: Add your first customer — name, type (fleet/retail/walk-in)
   - Step 4: Done! → redirected to the owner dashboard

3. **Explore the dashboard** at `/owner/`
   - See usage meters (repairs this month, active techs, customers)
   - Quick actions to create repairs, manage team, check billing
   - Recent activity feed

### Invite Your Team

4. **Invite a technician** at `/owner/settings/#team`
   - Click "Invite Member"
   - Enter their name, email, select role (Technician)
   - Toggle abilities: ✅ Can Repair, ❐ Can Replace
   - Click "Send Invite" — they'll receive an email with a 7-day link
   - If email fails, copy the `/invite/<token>/` link manually

5. **Invite a manager** — same flow but select role "Manager"
   - Managers can invite technicians and viewers
   - Managers can deactivate technicians and viewers
   - Managers cannot manage billing or change other manager/owner roles

### Invite Customers

6. **Share the customer portal link** at `/owner/settings/`
   - Find the "Customer Portal" card with your shop's join URL
   - Click "Copy Link" → share via email, text, print on business card
   - URL format: `/join/<your-shop-slug>/`
   - Customers sign up themselves — no admin work needed

7. **View customers** in the Customers section at `/owner/settings/#customers`
   - See all customers, their type (Fleet/Retail/Walk-in)
   - Portal access status (has account or not)

### Manage Team

8. **Edit a team member** — click "Edit" on any member
   - Change role (owner can change anyone except themselves)
   - Toggle abilities (repairs, replacements)
   - Save changes

9. **Deactivate a team member** — click "Deactivate"
   - Soft delete — membership marked inactive
   - Can be re-activated later by re-inviting

10. **Resend invite** — for members who haven't set their password yet
    - Creates a new 7-day token and sends a fresh email

### Manage Billing

11. **View billing** at `/owner/billing/`
    - See current plan, usage breakdown, upgrade options
    - Manage Stripe subscription (upgrade, downgrade, cancel)
    - Access Stripe billing portal for payment methods

---

## Manager

Managers are invited by the shop owner. They can manage day-to-day operations, invite technicians and viewers, and handle repairs.

### Accept Invite → Get Started

1. **Receive invite email** with a link to `/invite/<token>/`
2. **Click the link** → see the shop name and your role
3. **Set your password** (min 8 characters) and confirm
4. **Auto-logged in** → redirected to the owner dashboard

### Daily Workflow

5. **Dashboard** at `/owner/` — same view as owner (minus billing controls)
6. **Settings** at `/owner/settings/` — invite technicians and viewers
7. **Tech portal** at `/tech/` — manage repairs if you have technician abilities
   - Your technician abilities are set by the owner (can_repair, can_replace)

### What Managers Can Do

- ✅ View dashboard, settings, team members
- ✅ Invite technicians and viewers
- ✅ Deactivate technicians and viewers
- ✅ Create/manage repairs and replacements (with abilities)
- ❌ Change billing or subscription
- ❌ Change owner/manager roles
- ❌ Deactivate owners or other managers

---

## Technician

Technicians do the hands-on work — chip repairs, crack repairs, and full glass replacements.

### Accept Invite → Start Working

1. **Receive invite email** from shop owner or manager
2. **Click the link** at `/invite/<token>/`
3. **Set your password** and confirm
4. **Auto-logged in** → redirected to the technician dashboard at `/tech/`

### Daily Workflow

5. **Dashboard** at `/tech/` — see assigned repairs, today's queue
6. **Create a repair**:
   - Select customer, enter unit number, take before photos
   - System auto-prices: $50 → $40 → $35 → $30 → $25 progressive pricing
   - Submit → repair enters queue
7. **Create a replacement** at `/tech/replacement/new/`:
   - Full glass swap — enter parts cost, labor cost, ADAS calibration
   - Optional insurance claim details
8. **Manage customers** at `/tech/customers/` — view customer details, add new ones

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

### Sign Up → Access Portal

1. **Receive the shop's join link** — shared by the shop via email, text, or in person
   - URL format: `/join/<shop-slug>/`
2. **Visit the join page** — see the shop's name and branding
   - Feature highlights: Track Repairs, Approve Work Orders, View Invoices
3. **Create an account**:
   - Enter first name, last name, email
   - Optional: phone number, company name (for fleet customers)
   - Set password and confirm
   - If you enter a company name → Fleet account
   - If no company → Retail (individual) account
4. **Auto-logged in** → redirected to customer dashboard at `/app/`

### Using the Portal

5. **Dashboard** at `/app/` — overview of active repairs, pending approvals, stats
6. **My Repairs** at `/app/repairs/` — full repair history with filtering
   - See each repair's status: Requested → Pending → Approved → In Progress → Completed
   - Click any repair for full details including photos
7. **Approve/Deny repairs** — when a technician discovers damage in the field:
   - You'll see pending approval items on your dashboard
   - Click to review details, then approve or deny
   - Batch approvals available for multi-break repairs
8. **Request a Repair** at `/app/repairs/request/` — submit a new repair request
   - Describe the damage, add photos, specify urgency
   - Shop receives the request and assigns a technician
9. **Rewards** — view referral codes, earned points, available rewards
10. **Account Settings** at `/app/account/settings/` — update profile, change password, notification preferences

### Login

After initial signup, return at any time:
- Go to `/login/` (unified login for all roles)
- Enter email and password
- Auto-routed to the customer portal at `/app/`

---

## Repair Assignment Strategies

Shop owners can configure how new repair requests are automatically assigned to technicians. This is set in **Owner Settings → Repair Assignment**.

### Strategies

| Strategy | Behavior |
|----------|----------|
| **Manual** | No auto-assignment. A manager must manually assign every incoming repair. Best for small teams that want full control. |
| **Primary Tech First** *(default)* | If the customer has a primary technician, auto-assign to them. If not, the repair stays unassigned for manual assignment. |
| **Smart Auto-Assign** | Tries the primary tech first, then falls back to the eligible technician with the fewest active jobs. Balances workload automatically. |
| **Round Robin** | Rotates assignments evenly through all eligible technicians by ID order. Ignores workload — purely rotational. |

### Primary Technician

Each customer can have a **primary technician** — a default tech for all their work. Set this in:
- **Owner Settings → Customers** (badge shown per customer)
- **Technician Portal → Customer Details** (managers/admins can change via dropdown)
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

When a repair or replacement is auto-assigned, the technician receives an in-app notification (🔧 badge) visible in their notification panel.

---

## Summary: How Everyone Connects

```
Shop Owner signs up
    │
    ├── Invites Managers (email invite → /invite/<token>/)
    │     └── Managers invite Technicians (same flow)
    │
    ├── Invites Technicians (email invite → /invite/<token>/)
    │     └── Technicians do repairs
    │
    └── Shares customer join link (/join/<slug>/)
          └── Customers self-signup → track repairs → approve work
```

All users log in at `/login/` — the system automatically routes them to the correct portal based on their role.
