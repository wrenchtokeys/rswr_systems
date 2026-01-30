# RS Systems — Complete Redesign Plan

**Author:** Amelia  
**Date:** January 30, 2026  
**Status:** PLAN — for Drake's review before execution

---

## Vision

RS Systems should be the Jobber/Housecall Pro of windshield repair. Any glass shop — from a one-person truck to a 50-tech fleet — signs up and is productive in under 5 minutes. The system scales with you. Start solo, add people as you grow. Never outgrow it.

---

## Who Actually Runs a Glass Shop?

Let's forget about "roles" and "portals" for a minute. Let's look at real shops:

### The Solo Operator
One person. They ARE the shop. They drive the truck, fix the glass, take the photos, bill the customer, chase the payments. They might do 5-10 repairs a day.

**What they need:** A tool that's basically a smart clipboard. Log what I did, who I did it for, what they owe me. Don't make me think about anything else.

### The Small Shop (2-5 people)
An owner and a few techs. Owner still does repairs but also manages the business — scheduling, billing, customer relationships. Techs go out and do the work.

**What they need:** Owner sees everything. Techs see their work. Customers can check their repair status. Simple team management.

### The Medium Shop (5-20 people)
Owner, a couple managers, a team of techs, maybe an office person who handles billing. Multiple trucks out at once. Need to coordinate.

**What they need:** Managers can oversee and assign work. Office staff can handle invoicing without seeing tech operations. More granular permissions.

### The Large Operation (20+ people)
Multiple locations or regions. Fleet of trucks. Full office staff. Probably has dedicated billing, dispatch, and management.

**What they need:** Multi-location support, advanced reporting, role-based access that separates billing from field ops from management.

### The Customer (All Sizes)
A fleet manager at a trucking company. Or a dealership service manager. Or just a regular person who got their windshield fixed.

**What they need:** See what was done to my vehicle(s). Approve work requests. See what I owe. Pay.

---

## The Insight: It's Not About Roles, It's About Permissions

The current system has hard-coded roles: Owner, Manager, Technician, Viewer. That's rigid. A one-person shop doesn't need roles at all — they ARE every role. A medium shop needs different people to see different things.

**The right model: Capabilities, not titles.**

Every user who works at the shop is a **team member**. What they can DO is determined by their permissions, not their title. The system doesn't need to know if you're an "owner" or a "manager" — it needs to know if you can create invoices, manage the team, and do repairs.

### Capabilities

```
FIELD WORK
  ✓ Log repairs            — Can create and complete repairs
  ✓ Manage customers       — Can add/edit customer accounts
  
OFFICE WORK  
  ✓ Create invoices        — Can generate and send invoices
  ✓ Record payments        — Can log payments received
  ✓ View reports           — Can see revenue and business metrics
  
MANAGEMENT
  ✓ Manage team            — Can invite/remove team members
  ✓ Set permissions        — Can change what others can do
  ✓ Business settings      — Can edit shop info, pricing rules, plan
```

### How It Maps to Real Shops

| Capability | Solo Op | Small Shop Owner | Manager | Tech | Office Staff |
|-----------|---------|-----------------|---------|------|-------------|
| Log repairs | ✓ | ✓ | ✓ | ✓ | |
| Manage customers | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create invoices | ✓ | ✓ | ✓ | | ✓ |
| Record payments | ✓ | ✓ | ✓ | | ✓ |
| View reports | ✓ | ✓ | ✓ | | |
| Manage team | ✓ | ✓ | | | |
| Set permissions | ✓ | ✓ | | | |
| Business settings | ✓ | ✓ | | | |

**The solo operator gets ALL capabilities by default.** They see everything because they ARE everything.

**When they add their first tech,** that tech gets field work capabilities only. The owner doesn't have to think about "what role should this be?" — they just uncheck the things the tech shouldn't do.

**When they add office staff,** that person gets invoicing capabilities but not field work. Again — not a "role", just what they can do.

### Presets (Not Roles)

We still use presets for easy setup — you don't HAVE to configure capabilities one by one:

| Preset | What it enables | When to use |
|--------|----------------|-------------|
| **Full Access** | Everything | Shop owner, partners |
| **Field Tech** | Log repairs, manage customers | Techs in the field |
| **Field Manager** | Field Tech + invoices + reports | Senior techs who also handle billing |
| **Office** | Customers, invoices, payments, reports | Billing/admin staff not in the field |

But these are starting points, not boxes. You can customize any team member's capabilities after adding them.

---

## One Interface, Adapted

Here's the key: **there's ONE interface.** Everyone logs into the same app. What they SEE depends on what they can DO.

### Navigation Adapts to Capabilities

```
EVERYONE SEES:
  Dashboard              — Personalized to what you do

IF you can log repairs:
  Repairs                — Your repairs (or all repairs if you can manage team)

IF you can manage customers:
  Customers              — Customer list and details

IF you can create invoices:
  Invoices               — Invoice list, create, send

IF you can manage team OR business settings:
  Settings               — Team, business info, pricing, plan

IF you can view reports:
  (Dashboard shows)      — Revenue, metrics, charts
```

### What Each Person Sees

**Solo operator (all capabilities):**
```
Dashboard | Repairs | Customers | Invoices | Settings
```
Dashboard shows: revenue, today's repairs, outstanding invoices, setup checklist.

**Tech (field work only):**
```
Dashboard | Repairs | Customers
```
Dashboard shows: my assigned repairs today, recent completed, notifications.
Customers is read-mostly — they can look up info but not change billing details.

**Office staff (invoices + customers):**
```
Dashboard | Customers | Invoices
```
Dashboard shows: outstanding balances, recent payments, invoices needing attention.
No repair queue — they don't need it.

**Customer (external):**
```
Dashboard | Repairs | Invoices
```
Dashboard shows: pending approvals, recent repairs, balance due.
This is scoped to THEIR company only.

### One URL Structure

```
# Public
/                       → Marketing landing page
/signup/                → Sign up
/login/                 → Log in  
/pricing/               → Pricing page
/join/<slug>/           → Customer self-signup

# App (authenticated — what you see depends on capabilities)
/dashboard/             → Personalized dashboard
/repairs/               → Repair list (all or mine, based on capabilities)
/repairs/new/           → Create repair
/repairs/<id>/          → Repair detail
/customers/             → Customer list
/customers/new/         → Add customer
/customers/<id>/        → Customer detail + their repairs + invoices
/invoices/              → Invoice list
/invoices/new/<cust>/   → Create invoice for customer
/invoices/<id>/         → Invoice detail
/team/                  → Team management
/team/invite/           → Invite someone
/settings/              → Business settings, pricing, plan
/profile/               → My profile + notification preferences

# Customer-facing (external users)
/my/                    → Customer dashboard (scoped to their company)
/my/repairs/            → Their repairs
/my/repairs/<id>/       → Repair detail + approve/deny
/my/invoices/           → Their invoices + pay
/my/company/            → Company info

# System
/api/                   → REST API
/admin/                 → Django admin (superusers only)
```

**Internal team and external customers have clearly separated URL spaces:**
- `/dashboard/`, `/repairs/`, `/customers/`, etc. → shop team (owner, techs, staff)
- `/my/` → external customers

There are no "portals" to switch between. You log in, you see what you can do.

---

## The Experience (Step by Step)

### Day 1: Solo Operator Signs Up

**Signup page:** Business name, your name, email, password. [Start Free Trial]

**What happens behind the scenes:**
1. Create Django User
2. Create Tenant (the shop) with trial plan
3. Create TenantMembership with all capabilities enabled
4. Log them in, redirect to `/dashboard/`

No Technician model, no Groups, no is_staff. Just a user with capabilities on a tenant.

**Dashboard (first visit):**
```
┌────────────────────────────────────────────────────────┐
│  RS Systems    Dashboard  Repairs  Customers  Invoices │
│  [Drake's Glass]                     Settings   [DM]   │
├────────────────────────────────────────────────────────┤
│                                                        │
│  Welcome to RS Systems, Drake! 👋                      │
│                                                        │
│  Let's get you set up:                                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ✅ Create your account                           │  │
│  │ 👉 Add your first customer        [Add Customer] │  │
│  │ ○  Log your first repair          [Log Repair]   │  │
│  │ ○  Set up your pricing            [Set Pricing]  │  │
│  │ ○  Send your first invoice        (after repair)  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ 0        │ │ 0        │ │ $0       │               │
│  │ Repairs  │ │ Customers│ │ Revenue  │               │
│  │ this mo  │ │          │ │ this mo  │               │
│  └──────────┘ └──────────┘ └──────────┘               │
│                                                        │
│  No activity yet. Add a customer to get started!       │
│                                                        │
└────────────────────────────────────────────────────────┘
```

They click "Add Customer":
```
┌────────────────────────────────────────────────────────┐
│  RS Systems    Dashboard  Repairs  Customers  Invoices │
│  [Drake's Glass]                     Settings   [DM]   │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ← Back to Customers                                   │
│                                                        │
│  Add Customer                                          │
│                                                        │
│  Customer Type:  ● Fleet Account                       │
│                  ○ Individual / Retail                  │
│                  ○ Walk-In                              │
│                                                        │
│  Company Name:   [EOS Trucking               ]         │
│  Email:          [billing@eostrucking.com    ]         │
│  Phone:          [(555) 123-4567             ]         │
│                                                        │
│  [Save Customer]                                       │
│                                                        │
└────────────────────────────────────────────────────────┘
```

Saves → redirects to customer detail page → checklist updates → "Log your first repair" is next.

They click "Log Repair":
```
┌────────────────────────────────────────────────────────┐
│  RS Systems    Dashboard  Repairs  Customers  Invoices │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ← Back to Repairs                                     │
│                                                        │
│  Log Repair                                            │
│                                                        │
│  Customer:       [EOS Trucking            ▾]           │
│  Unit Number:    [847                      ]           │
│  Damage Type:    [Star Break              ▾]           │
│                                                        │
│  Photos:         [📷 Take Photo] [📁 Upload]           │
│                                                        │
│  Notes:          [Driver reported rock hit on I-35  ]  │
│                                                        │
│  Status:         ● Completed  ○ In Progress            │
│  Date:           [Jan 30, 2026            ]            │
│                                                        │
│  [Save Repair]                                         │
│                                                        │
└────────────────────────────────────────────────────────┘
```

**That's it.** Three forms in 5 minutes: signup, add customer, log repair. They're productive.

### Week 2: Owner Adds a Technician

Business is growing. Drake hires someone. Goes to Settings → Team:

```
┌────────────────────────────────────────────────────────┐
│  Settings                                              │
│                                                        │
│  Business Info  │  Team  │  Pricing  │  Plan            │
│                 │ [====] │           │                  │
├─────────────────┴────────┴───────────┴─────────────────┤
│                                                        │
│  Your Team                                             │
│                                                        │
│  Drake Morrison        Full Access       [Edit]        │
│  (you)                 All capabilities                │
│                                                        │
│  [+ Invite Team Member]                                │
│                                                        │
└────────────────────────────────────────────────────────┘
```

Clicks "Invite Team Member":

```
│  Invite a Team Member                                  │
│                                                        │
│  Name:    [Jake              ] [Sullivan           ]   │
│  Email:   [jake@drakesglass.com                    ]   │
│                                                        │
│  What can they do?                                     │
│                                                        │
│  Quick setup:  ● Field Technician                      │
│                ○ Field Manager                          │
│                ○ Office / Billing                       │
│                ○ Full Access                            │
│                ○ Custom                                 │
│                                                        │
│  ┌─ Field Technician includes: ──────────────────┐     │
│  │ ✓ Log and manage repairs                      │     │
│  │ ✓ View customer info                          │     │
│  │ ✗ Create invoices                             │     │
│  │ ✗ View revenue / reports                      │     │
│  │ ✗ Manage team or settings                     │     │
│  └───────────────────────────────────────────────┘     │
│                                                        │
│  [Send Invite]                                         │
```

Jake gets an email → clicks link → sets password → logs in → sees:

```
Dashboard | Repairs | Customers
```

Only what he needs. No invoices, no settings, no business metrics. Clean.

### The Customer Experience

A fleet manager at EOS Trucking gets a join link from Drake. They sign up at `/join/drakes-glass/`:

```
│  Drake's Glass & Repair invites you to                 │
│  track your windshield repairs online.                 │
│                                                        │
│  Your Company:   EOS Trucking  (already on file)       │
│  Your Name:      [                         ]           │
│  Email:          [                         ]           │
│  Password:       [                         ]           │
│                                                        │
│  [Create Account]                                      │
```

After signup → auto-login → `/my/`:

```
┌────────────────────────────────────────────────────────┐
│  RS Systems           Dashboard  Repairs  Invoices     │
│  Drake's Glass                        Company   [SM]   │
├────────────────────────────────────────────────────────┤
│                                                        │
│  EOS Trucking                                          │
│                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ 47       │ │ 2        │ │ $625     │               │
│  │ Repairs  │ │ Need your│ │ Balance  │               │
│  │ total    │ │ approval │ │ due      │               │
│  └──────────┘ └──────────┘ └──────────┘               │
│                                                        │
│  ⚠ Needs Your Approval                                │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Unit 847  │ Star break  │ Est $45  │ [✓] [✗]   │   │
│  │ Unit 302  │ Bullseye    │ Est $55  │ [✓] [✗]   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                        │
│  Recent Repairs                                        │
│  ┌─────────────────────────────────────────────────┐   │
│  │ Unit 1205 │ Completed Jan 28  │ $45            │   │
│  │ Unit 009  │ In Progress       │ $45            │   │
│  └─────────────────────────────────────────────────┘   │
│                                                        │
└────────────────────────────────────────────────────────┘
```

Clean. Scoped to their company. They see what they need, nothing else.

---

## Technical Architecture

### Data Model Changes

**TenantMembership gets capabilities:**

```python
class TenantMembership(models.Model):
    tenant = models.ForeignKey(Tenant, ...)
    user = models.ForeignKey(User, ...)
    
    # Capability flags (replaces role field)
    can_repair = models.BooleanField(default=False)          # Log/manage repairs
    can_manage_customers = models.BooleanField(default=False) # Add/edit customers
    can_invoice = models.BooleanField(default=False)          # Create/send invoices
    can_record_payments = models.BooleanField(default=False)  # Log payments
    can_view_reports = models.BooleanField(default=False)     # See revenue/metrics
    can_manage_team = models.BooleanField(default=False)      # Invite/remove members
    can_manage_settings = models.BooleanField(default=False)  # Edit shop info/pricing/plan
    
    # Keep role field for backward compat + quick permission presets
    ROLE_CHOICES = [
        ('owner', 'Owner'),        # All capabilities, cannot be removed
        ('manager', 'Manager'),    # Preset: all except manage_settings
        ('technician', 'Technician'), # Preset: repair + customers
        ('office', 'Office Staff'),   # Preset: customers + invoicing + payments
        ('custom', 'Custom'),         # Individual capability selection
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='technician')
    
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['tenant', 'user']
```

**Presets auto-set capabilities:**

```python
ROLE_PRESETS = {
    'owner':      {'can_repair': True, 'can_manage_customers': True, 'can_invoice': True, 
                   'can_record_payments': True, 'can_view_reports': True, 
                   'can_manage_team': True, 'can_manage_settings': True},
    'manager':    {'can_repair': True, 'can_manage_customers': True, 'can_invoice': True,
                   'can_record_payments': True, 'can_view_reports': True,
                   'can_manage_team': False, 'can_manage_settings': False},
    'technician': {'can_repair': True, 'can_manage_customers': True, 'can_invoice': False,
                   'can_record_payments': False, 'can_view_reports': False,
                   'can_manage_team': False, 'can_manage_settings': False},
    'office':     {'can_repair': False, 'can_manage_customers': True, 'can_invoice': True,
                   'can_record_payments': True, 'can_view_reports': True,
                   'can_manage_team': False, 'can_manage_settings': False},
}
```

**Why this is better than hard roles:**
- Solo operator: gets everything. No role confusion.
- Small shop: pick a preset. Done.
- Medium shop: customize. Office staff can invoice but not repair. Manager can do reports but not change settings.
- Large shop: full granularity. Custom permissions per person.
- **No one needs to understand "portals" or "access levels."** It's just checkboxes: what can this person do?

**Technician model stays** — it stores tech-specific data (phone, abilities like can_repair vs can_replace, manager status). But it's no longer used for access control. `TenantMembership` capabilities are the source of truth.

**CustomerUser model stays** — it links a Django user to a Customer record. External customers don't have TenantMembership on the shop — they have their own separate access via CustomerUser.

### Permission System

```python
# common/auth.py — THE permission system

def get_membership(user, tenant=None):
    """Get user's TenantMembership, cached on request."""
    if not user.is_authenticated:
        return None
    
    qs = TenantMembership.objects.filter(user=user, is_active=True)
    if tenant:
        qs = qs.filter(tenant=tenant)
    return qs.select_related('tenant').first()

def can(user, capability, tenant=None):
    """Check if user has a specific capability."""
    if user.is_superuser:
        return True
    membership = get_membership(user, tenant)
    if not membership:
        return False
    return getattr(membership, f'can_{capability}', False)

def is_customer(user):
    """Check if user is an external customer."""
    from apps.customer_portal.models import CustomerUser
    return CustomerUser.objects.filter(user=user).exists()

# Decorators
def capability_required(*capabilities):
    """Require one or more capabilities."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            tenant = getattr(request, 'tenant', None)
            for cap in capabilities:
                if not can(request.user, cap, tenant):
                    messages.warning(request, "You don't have permission for that.")
                    return redirect('dashboard')
            
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator

# Usage:
@capability_required('repair')
def create_repair(request): ...

@capability_required('invoice')
def create_invoice(request): ...

@capability_required('manage_team')
def invite_member(request): ...

@capability_required('manage_settings')
def business_settings(request): ...
```

**That's the entire permission system.** One function (`can`), one decorator (`capability_required`). Replaces: `technician_required`, `admin_required`, `owner_or_manager_required`, `customer_required`, `manager_required`, `is_tenant_admin`, `has_technician_access`, and all `is_staff`/`is_superuser` checks.

### Template Architecture

```
templates/
  base.html                  → HTML skeleton: head, Tailwind, Inter font, body
  layouts/
    app_shell.html           → Nav + content area (extends base.html)
    nav.html                 → Dynamic nav based on capabilities
    customer_shell.html      → Customer-specific shell (extends base.html)
    nav_customer.html        → Customer nav
  
  pages/                     → All page content (extends appropriate shell)
    dashboard.html           → Personalized dashboard
    repairs/
      list.html
      detail.html
      form.html
    customers/
      list.html
      detail.html
      form.html
    invoices/
      list.html
      detail.html
      create.html
    settings/
      index.html             → Tabs: Business | Team | Pricing | Plan
      team.html
      invite.html
      pricing.html
      billing.html
    profile.html
    setup_checklist.html     → Included in dashboard for new users
    
  customer/                  → Customer-facing pages (extends customer_shell)
    dashboard.html
    repairs.html
    repair_detail.html
    invoices.html
    company.html
    
  public/                    → No auth required
    landing.html
    signup.html
    login.html
    pricing.html
    join.html
    invite_accept.html
```

**Nav renders dynamically:**

```html
<!-- layouts/nav.html -->
<nav>
  <a href="/dashboard/">Dashboard</a>
  
  {% if perms.can_repair %}
    <a href="/repairs/">Repairs</a>
  {% endif %}
  
  {% if perms.can_manage_customers %}
    <a href="/customers/">Customers</a>
  {% endif %}
  
  {% if perms.can_invoice %}
    <a href="/invoices/">Invoices</a>
  {% endif %}
  
  {% if perms.can_manage_team or perms.can_manage_settings %}
    <a href="/settings/">Settings</a>
  {% endif %}
</nav>
```

A context processor injects the user's capabilities as `perms` into every template. The nav builds itself.

### Middleware (Simplified)

```python
class AccessMiddleware:
    """
    Two jobs:
    1. Customers can only access /my/ and public pages
    2. Team members must have at least one capability (active membership)
    
    Everything else is handled by @capability_required on views.
    """
    def process_request(self, request):
        if not request.user.is_authenticated:
            return None
        
        path = request.path
        
        # Public pages — everyone can access
        if self._is_public(path):
            return None
        
        # Customer pages — only external customers
        if path.startswith('/my/'):
            if not is_customer(request.user):
                return redirect('dashboard')
            return None
        
        # App pages — only team members
        if self._is_app_page(path):
            if is_customer(request.user):
                return redirect('/my/')
            membership = get_membership(request.user, request.tenant)
            if not membership:
                messages.error(request, "You don't have access to this shop.")
                return redirect('login')
        
        return None
```

---

## Signup Flow

```python
def signup(request):
    # Collect: business_name, first_name, last_name, email, password
    
    user = User.objects.create_user(username=email, email=email, ...)
    
    tenant = Tenant.objects.create(
        name=business_name,
        owner=user,
        plan='trial',
        ...
    )
    
    # Owner gets ALL capabilities
    TenantMembership.objects.create(
        tenant=tenant,
        user=user,
        role='owner',
        can_repair=True,
        can_manage_customers=True,
        can_invoice=True,
        can_record_payments=True,
        can_view_reports=True,
        can_manage_team=True,
        can_manage_settings=True,
    )
    
    login(request, user)
    return redirect('dashboard')
```

No Technician model creation. No Groups. No onboarding wizard. Straight to dashboard.

**Setup checklist** appears on dashboard (stored in `Tenant.setup_checklist` JSON field):

```python
DEFAULT_CHECKLIST = {
    'account_created': True,
    'first_customer': False,
    'first_repair': False,
    'pricing_set': False,
    'first_invoice': False,
}
```

Each action updates the checklist. When all items are complete (or user dismisses it), it disappears.

---

## Migration Path

We're not rewriting from scratch. We're restructuring what exists.

### What We Keep As-Is
- All data models (Customer, Repair, Invoice, Technician, etc.)
- All services (pricing, billing, invoicing, email, Stripe)
- All API endpoints
- Database schema (add capability fields, keep existing)
- Email templates
- Rewards/referrals system

### What We Restructure
- **Views:** Create new view files for the unified structure. Many will be thin wrappers around existing logic.
- **Templates:** New template set in `templates/pages/` and `templates/customer/`. Old templates stay until migration is complete.
- **URLs:** New URL config. Old URLs get 301 redirects.
- **Permissions:** New `capability_required` decorator. Old decorators stay until all views are migrated.
- **Onboarding:** Replace wizard with setup checklist. Old onboarding views deprecated.

### Migration Steps
1. Add capability fields to TenantMembership (database migration)
2. Populate capabilities from existing roles (data migration)
3. Build new base templates
4. Build new views one section at a time (dashboard → repairs → customers → invoices → settings)
5. Wire up new URLs alongside old ones
6. Test extensively
7. Flip: new URLs become primary, old URLs become redirects
8. Remove old views/templates/decorators

---

## Execution Plan

### Phase 0: Data & Permissions Foundation
| # | Task | Time |
|---|------|------|
| 0.1 | Add capability fields to TenantMembership + migration | 1 hr |
| 0.2 | Data migration: populate capabilities from existing roles | 30 min |
| 0.3 | Create `common/auth.py` with `can()`, `get_membership()`, `capability_required` | 1 hr |
| 0.4 | Create capabilities context processor | 30 min |
| 0.5 | Fix signup to create membership with all capabilities (no Technician/Group) | 30 min |
| 0.6 | Fix login routing to use capabilities | 30 min |
| **Total** | | **4 hrs** |

### Phase 1: Base Templates
| # | Task | Time |
|---|------|------|
| 1.1 | Create `base.html` (Tailwind, Inter, HTML skeleton) | 1 hr |
| 1.2 | Create `layouts/app_shell.html` (nav + content + messages) | 1 hr |
| 1.3 | Create `layouts/nav.html` (capability-driven nav) | 1 hr |
| 1.4 | Create `layouts/customer_shell.html` + `nav_customer.html` | 1 hr |
| 1.5 | Create shared components (stat cards, tables, forms, buttons) | 2 hrs |
| **Total** | | **6 hrs** |

### Phase 2: Core Pages (Owner/Full Access)
| # | Task | Time |
|---|------|------|
| 2.1 | Dashboard (stats + checklist + today's work + outstanding) | 3 hrs |
| 2.2 | Customer list (search, sort, repair/balance counts) | 2 hrs |
| 2.3 | Customer detail (info + repairs + invoices + balance) | 3 hrs |
| 2.4 | Customer form (create/edit) | 1 hr |
| 2.5 | Repair list (filter by status/customer/tech/date) | 2 hrs |
| 2.6 | Repair detail (status, photos, history, cost) | 2 hrs |
| 2.7 | Repair form (create, with inline customer picker) | 2 hrs |
| 2.8 | Invoice list (status, filters, totals) | 2 hrs |
| 2.9 | Invoice detail (line items, payments, send/remind) | 2 hrs |
| 2.10 | Invoice creation (select repairs → generate) | 2 hrs |
| **Total** | | **21 hrs** |

### Phase 3: Settings & Team
| # | Task | Time |
|---|------|------|
| 3.1 | Settings layout (tabs: Business | Team | Pricing | Plan) | 1 hr |
| 3.2 | Business info form | 1 hr |
| 3.3 | Team list + invite flow (with capability presets) | 3 hrs |
| 3.4 | Team member edit (change capabilities) | 1 hr |
| 3.5 | Pricing rules page | 1 hr |
| 3.6 | Subscription/plan page (Stripe integration) | 2 hrs |
| **Total** | | **9 hrs** |

### Phase 4: Customer Portal
| # | Task | Time |
|---|------|------|
| 4.1 | Customer dashboard (stats + approvals + recent) | 2 hrs |
| 4.2 | Customer repair list | 1 hr |
| 4.3 | Customer repair detail + approve/deny | 1 hr |
| 4.4 | Customer invoice list + pay (Stripe) | 2 hrs |
| 4.5 | Company info page | 30 min |
| 4.6 | Join flow (/join/<slug>/) | 1 hr |
| **Total** | | **7.5 hrs** |

### Phase 5: Migration & Polish
| # | Task | Time |
|---|------|------|
| 5.1 | URL routing (new URLs + old URL redirects) | 2 hrs |
| 5.2 | Smoke test script (all core flows) | 3 hrs |
| 5.3 | Error handling audit (no 500s, no dead ends) | 2 hrs |
| 5.4 | Mobile responsiveness pass | 3 hrs |
| 5.5 | Remove old views/templates/decorators | 2 hrs |
| 5.6 | Deploy to AWS | 1 hr |
| **Total** | | **13 hrs** |

### Summary

| Phase | What | Time |
|-------|------|------|
| 0 | Data & permissions | 4 hrs |
| 1 | Base templates | 6 hrs |
| 2 | Core pages | 21 hrs |
| 3 | Settings & team | 9 hrs |
| 4 | Customer portal | 7.5 hrs |
| 5 | Migration & polish | 13 hrs |
| **Total** | | **~60 hrs** |

**Recommended build order:**
1. Phase 0 (foundation) — nothing works without this
2. Phase 1 (templates) — sets the visual standard
3. Phase 2 (core pages) — the actual product
4. Phase 3 (settings) — team management
5. Phase 4 (customer portal) — external users
6. Phase 5 (migration) — deploy

Phase 0+1+2 = a usable product (~31 hrs). Ship that. Then add team management, customer portal, polish.

---

## Non-Negotiables

1. **One interface per person.** No portal switching. What you see is based on what you can do.
2. **5-minute time to value.** Signup → add customer → log repair in 5 minutes.
3. **No dead ends.** Every click goes somewhere useful. Access denied → redirect to your dashboard with a message.
4. **Scales from 1 to 100 people** without restructuring. Solo operator uses the same codebase as a 50-tech fleet.
5. **Mobile-ready.** Techs are in parking lots. Large touch targets, camera access, readable on a phone.

---

*This plan replaces all previous planning documents.*
