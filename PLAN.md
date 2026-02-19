# RS Systems  The Real Plan

**Author:** Amelia  
**Date:** January 30, 2026  
**Status:** Steps 15 COMPLETE  | Step 6 (deploy) pending

---

## Honest Assessment

I've been over-planning. Three versions of this document in one night, each more ambitious than the last. The last one proposed a capabilities-based permission system for handling 50-person shops. We have zero customers.

Let me say what I actually think.

### What's Good
The **data model** is solid. Customer, Repair, Invoice, Payment, Technician, Tenant  these are the right entities with the right relationships. The repair model handles damage types, photos, pricing, status transitions, batch repairs. This is real domain modeling. It works.

The **services layer** is well-built. 19 service files handling pricing, invoicing, billing, email, Stripe, reporting, tenant management. This is the hard stuff and it's done right. Clean separation of concerns.

The **owner dashboard** template (`base_owner.html`) is modern, clean Tailwind with responsive design. It looks professional. The dashboard itself has revenue cards, usage meters, quick actions, recent activity. This is actually good.

### What's Bad
The **permission system** is the core problem. 182 permission checks across the codebase using 7+ different mechanisms (`is_staff`, `is_superuser`, Technicians group, Technician model, TenantMembership role, CustomerUser model, various decorators). They disagree. That's why everything breaks.

The **template situation** has three parallel universes:
- `base_owner.html`  modern Tailwind, sticky nav, looks like 2026
- `base.html`  old-school HTML nav with `<ul>`, checks `is_superuser` and group membership to decide what to show, then individual templates bolt on Tailwind via `<script>` tag
- `base_customer.html`  modern Tailwind, different from owner

When the owner clicks "New Customer" on their nice modern dashboard, they land on a page that extends `base.html`  completely different nav, different styling, and the nav shows "Customer Portal" because they're not `is_superuser` and not in the Technicians group. It's jarring.

The **onboarding wizard** has a bug where form failures silently advance to the next step, potentially leaving the user without a Technician profile. This is probably why Drake can't do anything after signup.

### What Doesn't Need Changing
- The data models
- The services
- The billing/invoicing backend
- The API endpoints
- The email system
- The rewards/referrals system
- The owner dashboard design (it's good  the quick actions just need to work)

### What Does

**Two things:**
1. One permission system that works
2. One template system that doesn't break when an owner clicks "New Customer"

That's it. Not a rewrite. Not a new URL structure. Not a capabilities framework. Just make the two broken things work.

---

## The Actual Plan

### Step 1: One Permission Function (4 hours)  DONE

Create `common/auth.py` with one function:

```python
def can_access(user, area, tenant=None):
    """
    Can this user access this area?
    
    Areas: 'repairs', 'customers', 'invoices', 'reports', 'team', 'settings'
    
    Rules:
    - Superusers: yes to everything
    - Owner/Manager TenantMembership: yes to everything
    - Technician TenantMembership: repairs, customers
    - Viewer TenantMembership: nothing (they're external customers)
    - CustomerUser: customer portal only
    """
```

Create one decorator:

```python
@requires('repairs')
def create_repair(request): ...

@requires('invoices')  
def create_invoice(request): ...

@requires('team')
def invite_member(request): ...
```

Create one context processor that gives templates `user_can_repair`, `user_can_invoice`, etc.

Then replace all 182 permission checks. Not new logic  just routing the existing role system through one function instead of seven.

**What this fixes:** Owner clicks "New Customer"  `@requires('customers')`  checks TenantMembership  owner role  allowed. Done.

### Step 2: One Base Template (6 hours)  DONE

Don't build a new template from scratch. Take `base_owner.html`  it's already good  and make it THE base template for everyone who works at the shop.

```
base_app.html             renamed from base_owner.html, nav adapts to capabilities
base_customer.html        keep as-is for external customers (it's fine)
base.html                 retire (old tech portal base)
```

The nav in `base_app.html` uses the context processor:

```html
<nav>
  <a href="/dashboard/">Dashboard</a>
  {% if user_can_repair %}<a href="{% url 'repair_list' %}">Repairs</a>{% endif %}
  {% if user_can_customers %}<a href="{% url 'technician_customers' %}">Customers</a>{% endif %}
  {% if user_can_invoice %}<a href="{% url 'billing_settings' %}">Invoices</a>{% endif %}
  {% if user_can_settings %}<a href="{% url 'owner_settings' %}">Settings</a>{% endif %}
</nav>
```

Then update tech portal templates to extend `base_app.html` instead of `base.html`:

```
templates/technician_portal/customer_form.html:    {% extends "base.html" %}
                                                  {% extends "base_app.html" %}
```

That's ~25 template files. Search and replace. The content doesn't change  just the shell around it.

**What this fixes:** Owner clicks "New Customer"  lands on customer_form.html  sees their normal nav (Dashboard, Repairs, Customers, etc.)  same styling  feels like the same app.

### Step 3: Fix Signup & Onboarding (2 hours)  DONE

**Signup:**
In `create_tenant_with_owner()`, after creating the TenantMembership, also create a Technician profile and add to Technicians group. Every owner starts as a tech. The Technicians group and Technician model are still used by existing code throughout  we're not removing them, just making sure they exist.

```python
# In create_tenant_with_owner():
Technician.objects.create(tenant=tenant, user=user, is_manager=True, is_active=True)
Group.objects.get_or_create(name='Technicians')
user.groups.add(tech_group)
```

**Onboarding:**
Fix the step progression bug  only advance on valid form. But also: make step 2 (add technician) about adding ANOTHER tech, not yourself. You're already set up.

Or even simpler: cut onboarding to 2 steps:
1. Business info (phone, email, address, logo)  
2. Done  redirect to dashboard with setup checklist

The setup checklist on the dashboard handles the rest (add customer, log repair, etc.) by linking to real pages. No more wizard that can fail silently.

### Step 4: Fix Redirects (1 hour)  DONE

Audit every `return redirect('home')` for authenticated users. Replace with:

```python
# common/auth.py
def redirect_to_portal(user):
    """Send user to their correct home page."""
    if is_customer_user(user):
        return redirect('customer_dashboard')
    return redirect('dashboard')  # owner_dashboard for now
```

Find them all:

```bash
grep -rn "redirect('home')" --include='*.py' | grep -v venv
```

Replace each one.

### Step 5: Owner Nav Update (1 hour)  DONE

The owner nav currently says: `Dashboard | Billing | Settings | [Tech Portal]`

Change to: `Dashboard | Repairs | Customers | Invoices | Settings`

These link to existing pages:
- Repairs  `/tech/repairs/` (repair_list view  already exists)
- Customers  `/tech/customers/` (customer_list view  already exists)
- Invoices  `/owner/billing/` (billing_view  already exists, rename to "Invoices")

The URLs stay the same. We're just putting them in the nav where the owner expects them.

### Step 6: Deploy (1 hour)  NEXT

Push. Merge to main or deploy from amelia. Get it on AWS.

**Note (Feb 2026):** All billing work (v2.1.0, v2.2.0) was built on this foundation. The unified permissions and base_app.html template are load-bearing  every new feature since Jan 30 depends on them. Deploy includes all of v2.02.2.

---

## What This Gives Us

After ~15 hours of work:

1. **Owner signs up  dashboard  clicks "New Customer"  it works.** The form loads with the correct nav, saves successfully, redirects back to the customer list.

2. **One permission system.** `@requires('area')` on every view. One function, one decorator, one context processor. No more `is_staff` vs groups vs model checks.

3. **One visual experience.** Every page extends `base_app.html`. Same nav, same styling, same feel. The owner never sees a "different app."

4. **No dead ends.** Access denied  redirect to dashboard with a message. Never to the landing page.

5. **Onboarding that works.** Auto-technician on signup. Short wizard or no wizard. Setup checklist on the dashboard.

---

## What This Doesn't Do (Yet)

- **New URL structure.** URLs stay as `/tech/repairs/`, `/owner/billing/`, etc. They work. Changing them is cosmetic and can happen later.
- **Capability flags on TenantMembership.** The current role field (owner/manager/technician/viewer) maps cleanly to permissions. Adding granular flags is a v2 feature when shops actually need "office staff who can invoice but not repair."
- **Template redesign.** The tech portal pages will have the owner nav wrapped around them. The content inside is functional. Making it prettier is polish.
- **Mobile optimization.** Important, but a separate effort after the basics work.
- **Customer portal restructure.** It works. The login routing fix (already coded) gets customers to `/app/` correctly.

---

## Schedule

| Day | What | Hours | Status |
|-----|------|-------|--------|
| 1 | Step 1: Permission function + decorator + replace checks | 4 |  Done |
| 1 | Step 3: Fix signup (auto-tech) + onboarding (step progression) | 2 |  Done |
| 1 | Step 2: base_app.html + migrate tech templates | 6 |  Done |
| 1 | Step 4: Fix redirects | 1 |  Done |
| 1 | Step 5: Owner nav update | 1 |  Done |
| - | Step 6: Test everything + deploy | 1-2 |  Next |
| **Total** | | **~15 hours** | **5/6 done** |

**Completed:** January 30, 2026  all pre-deploy steps done in one session.
**28 tests passing** across permissions, templates, signup, redirects, and navigation.

Three days of focused work. Not three weeks. Not sixty hours.

---

## After This Ships

Once the foundation is stable and deployed:

1. **Owner customer/repair pages**  Create owner-native pages at `/customers/` and `/repairs/` that extend `base_app.html` natively instead of wrapping tech portal pages. Better UX, same data.

2. **Invoice UI**  Owner can generate invoices from the customer detail page. One-click "Invoice uninvoiced repairs."

3. **Capability flags**  When real shops need granular permissions (office staff, etc.), add capability fields to TenantMembership.

4. **Mobile optimization**  Touch-friendly repair logging for techs in the field.

5. **Customer portal refresh**  Move to `/my/`, unify with `base_app.html` styling.

Each of these is a focused sprint. Not a rewrite. Build on the stable foundation.

---

## My Honest Take

This codebase isn't slop. The data model and services are genuinely well-built for what they do. What's broken is the glue between components  permissions and templates. That's fixable in days, not weeks.

The three-portal architecture was a reasonable decision when each portal was being built. The problem is they were never integrated into a coherent experience. That's what we're doing now  not replacing the bones, but connecting them.

The biggest risk isn't the code. It's scope creep. Every time I sit down to plan, I add more. "While we're at it, let's also..." is the enemy. The plan above does the minimum to make the product work. Everything else comes after.

---

*Ship it, then improve it. Not the other way around.*
