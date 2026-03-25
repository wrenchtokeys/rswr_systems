# Proposal: Warranty System

**Author:** Amelia  
**Date:** 2026-03-25  
**Status:** Draft — awaiting Drake's review

---

## Problem

When a customer calls back and says "my repair failed" or "the crack spread," the shop owner currently has no way to:

1. **Look up whether it's under warranty** — they have to remember or dig through texts
2. **Create a warranty repair** — they'd create a normal repair and eat the cost manually, with no connection to the original job
3. **Track warranty rates** — no data on which techs have high callback rates, which damage types fail most, or how much warranty work costs the shop per month
4. **Set warranty policies** — every shop has different terms (lifetime chip repairs, 1 year cracks, no warranty on star breaks over 6 inches) but there's nowhere to define this

This is a real daily problem. Fleet managers especially will push back: "You repaired this 3 months ago and it failed — that should be covered." If the shop can't instantly pull up the original repair and confirm warranty status, they look unprofessional and lose trust.

### Industry Context
- Most chip repair shops offer **lifetime warranty on chip repairs** (the resin either holds or it doesn't)
- Crack repairs typically get **6 months to 1 year** (depends on crack length, location, whether it was drilled)
- Replacements usually carry **manufacturer warranty** (not the shop's problem, but shops often handle the claim)
- Some shops warranty labor only, not if the same spot gets hit again
- Fleet contracts sometimes have custom warranty terms per account

---

## Solution: Warranty Tracking + Claim Workflow

### How It Works

1. **When a repair is completed**, RS Systems calculates the warranty expiration based on the shop's policy for that damage type
2. **When a customer calls back**, the tech or owner searches for the original repair and sees: ✅ Under Warranty (expires Oct 15, 2026) or ❌ Warranty Expired
3. **If under warranty**, one click creates a **warranty claim** — a new repair linked to the original, automatically flagged as no-charge
4. **If expired**, the shop can still create a normal repair, or offer a goodwill discount

---

## Data Model

### WarrantyPolicy (per-tenant, per-damage-type)

```python
class WarrantyPolicy(models.Model):
    """Per-tenant warranty terms. Shops define their own policies."""
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE,
        related_name='warranty_policies')
    
    # IMPORTANT: These values MUST match Repair.DAMAGE_TYPE_CHOICES exactly
    # (apps/technician_portal/models.py lines 443-453) so that
    # WarrantyService.set_warranty_on_completion() can match repair.damage_type
    # to the correct policy via applies_to=repair.damage_type.
    # Using mismatched strings would silently fall through to the 'all_repairs'
    # default for every repair. (Bug fix per suggestions.md §4 / impl-plan §2)
    APPLIES_TO_CHOICES = [
        ('Chip', 'Chip Repair'),
        ('Crack', 'Crack Repair'),
        ('Star Break', 'Star Break'),
        ("Bull's Eye", "Bull's Eye"),
        ('Combination Break', 'Combination Break'),
        ('Half-Moon', 'Half-Moon'),
        ('Other', 'Other'),
        ('all_repairs', 'All Repairs (default)'),
    ]
    applies_to = models.CharField(max_length=30, choices=APPLIES_TO_CHOICES)
    
    WARRANTY_DURATION_CHOICES = [
        ('lifetime', 'Lifetime'),
        ('custom_days', 'Custom (days)'),
        ('none', 'No Warranty'),
    ]
    duration_type = models.CharField(max_length=20, choices=WARRANTY_DURATION_CHOICES,
        default='custom_days')
    duration_days = models.PositiveIntegerField(default=365,
        help_text="Days from completion. Ignored if duration_type is lifetime or none.")
    
    covers_labor = models.BooleanField(default=True)
    covers_materials = models.BooleanField(default=True)
    excludes_new_damage = models.BooleanField(default=True,
        help_text="Warranty void if new impact damage at same location")
    
    description = models.TextField(blank=True,
        help_text="Customer-facing warranty terms shown on invoices/emails")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['tenant', 'applies_to']
        ordering = ['applies_to']
    
    def get_expiry_date(self, completion_date):
        """Calculate warranty expiration from repair completion date."""
        if self.duration_type == 'lifetime':
            return None  # Never expires
        if self.duration_type == 'none':
            return completion_date  # Already expired
        return completion_date + timedelta(days=self.duration_days)
```

### Add to Repair model (warranty tracking fields)

```python
# On the existing Repair model:
warranty_expires_at = models.DateTimeField(null=True, blank=True,
    help_text="Warranty expiration. Null = lifetime warranty.")
warranty_is_lifetime = models.BooleanField(default=False)
is_warranty_claim = models.BooleanField(default=False,
    help_text="This repair is a warranty claim against an original repair")
warranty_original_repair = models.ForeignKey('self', null=True, blank=True,
    on_delete=models.SET_NULL, related_name='warranty_claims',
    help_text="Original repair this warranty claim is for")
warranty_claim_reason = models.TextField(blank=True,
    help_text="Why the original repair failed")
```

### WarrantyService

```python
class WarrantyService:
    
    @staticmethod
    def set_warranty_on_completion(repair):
        """Called when repair transitions to COMPLETED.
        Looks up tenant's warranty policy for this damage type and sets expiry."""
        policy = WarrantyPolicy.objects.filter(
            tenant=repair.tenant,
            is_active=True,
            applies_to=repair.damage_type,
        ).first()
        
        # Fall back to 'all_repairs' default policy
        if not policy:
            policy = WarrantyPolicy.objects.filter(
                tenant=repair.tenant,
                is_active=True,
                applies_to='all_repairs',
            ).first()
        
        if not policy or policy.duration_type == 'none':
            return  # No warranty
        
        if policy.duration_type == 'lifetime':
            repair.warranty_is_lifetime = True
            repair.warranty_expires_at = None
        else:
            repair.warranty_expires_at = policy.get_expiry_date(
                repair.repair_date or timezone.now()
            )
        repair.save(update_fields=['warranty_expires_at', 'warranty_is_lifetime'])
    
    @staticmethod
    def check_warranty(repair):
        """Check if a repair is still under warranty."""
        if repair.warranty_is_lifetime:
            return True, 'Lifetime warranty'
        if repair.warranty_expires_at is None:
            return False, 'No warranty'
        if repair.warranty_expires_at > timezone.now():
            days_left = (repair.warranty_expires_at - timezone.now()).days
            return True, f'Under warranty ({days_left} days remaining)'
        return False, 'Warranty expired'
    
    @staticmethod
    def create_warranty_claim(original_repair, reason, technician=None):
        """Create a new repair as a warranty claim against the original.
        No charge — warranty covers it."""
        
        is_covered, status_msg = WarrantyService.check_warranty(original_repair)
        
        claim = Repair.objects.create(
            customer=original_repair.customer,
            tenant=original_repair.tenant,
            technician=technician or original_repair.technician,
            unit_number=original_repair.unit_number,
            damage_type=original_repair.damage_type,
            damage_location_x=original_repair.damage_location_x,
            damage_location_y=original_repair.damage_location_y,
            queue_status='REQUESTED',
            is_warranty_claim=True,
            warranty_original_repair=original_repair,
            warranty_claim_reason=reason,
            # Zero cost for warranty claims
            cost_override=Decimal('0.00'),
            override_reason=f'Warranty claim against repair #{original_repair.pk}',
        )
        
        return claim, is_covered
    
    @staticmethod
    def get_warranty_stats(tenant, period_days=30):
        """Warranty analytics for the owner dashboard."""
        cutoff = timezone.now() - timedelta(days=period_days)
        
        claims = Repair.objects.filter(
            tenant=tenant,
            is_warranty_claim=True,
            created_at__gte=cutoff,
        )
        
        total_repairs = Repair.objects.filter(
            tenant=tenant,
            queue_status='COMPLETED',
            created_at__gte=cutoff,
        ).count()
        
        return {
            'claims_this_period': claims.count(),
            'total_repairs': total_repairs,
            'warranty_rate': (claims.count() / total_repairs * 100) if total_repairs else 0,
            'by_technician': claims.values(
                'technician__user__first_name'
            ).annotate(count=Count('id')).order_by('-count'),
            'by_damage_type': claims.values(
                'damage_type'
            ).annotate(count=Count('id')).order_by('-count'),
        }
```

---

## User Experience

### Tech/Owner: Looking Up Warranty Status

On the **repair detail page**, add a warranty badge:

```
┌──────────────────────────────────────────────┐
│  Repair #1045 — TRUCK-4482                   │
│  Star Break · Completed Mar 15, 2026         │
│                                              │
│  ✅ Under Warranty (expires Mar 15, 2027)    │
│  [Create Warranty Claim]                     │
│                                              │
│  — or —                                      │
│                                              │
│  ❌ Warranty Expired (expired Jan 15, 2026)  │
│  [Create New Repair]                         │
└──────────────────────────────────────────────┘
```

### Tech/Owner: Creating a Warranty Claim

Click "Create Warranty Claim" → modal:

```
┌─────────────────────────────────────────┐
│  Warranty Claim                         │
│                                         │
│  Original: Repair #1045 (Mar 15, 2026)  │
│  Unit: TRUCK-4482                       │
│  Damage: Star Break                     │
│  Warranty: ✅ Active (187 days left)    │
│                                         │
│  Reason for claim:                      │
│  ┌─────────────────────────────────┐    │
│  │ Crack spread from original      │    │
│  │ repair site after temp change   │    │
│  └─────────────────────────────────┘    │
│                                         │
│  Assign to: [Drake Duncan ▼]           │
│                                         │
│  ⚠️ This will create a $0.00 repair    │
│  linked to the original.               │
│                                         │
│  [Cancel]  [Create Warranty Repair]     │
└─────────────────────────────────────────┘
```

### Owner: Warranty Settings

**Settings → Warranty Policies**

| Damage Type | Duration | Covers |
|-------------|----------|--------|
| Chip Repair | Lifetime | Labor + Materials |
| Crack Repair | 365 days | Labor + Materials |
| Star Break | 365 days | Labor only |
| Bull's Eye | 365 days | Labor + Materials |
| Replacement | No warranty (manufacturer) | — |

Each row is editable. "Add Policy" button for custom types.

### Owner: Warranty Dashboard Widget

On the owner dashboard:

```
Warranty Claims (Last 30 Days)
├── 3 claims out of 47 repairs (6.4% rate)
├── Top reason: "Crack spread" (2)
└── By tech: Drake (2), Mike (1)
```

### Customer Portal

On the customer's repair history, show warranty status:

```
TRUCK-4482 — Star Break — Mar 15, 2026
✅ Warranty: Lifetime
[Request Warranty Service]
```

Customer can self-service request a warranty claim through their portal — goes into the queue as a warranty request for the shop to review.

### Invoice Integration

- Warranty repairs show `$0.00` on invoices with "WARRANTY CLAIM" badge
- Original repair reference on the invoice: "Warranty for Repair #1045 (Mar 15, 2026)"
- Warranty terms printed on regular repair invoices (configurable)

---

## Integration Points

### Hooks into existing systems:
- **Repair completion** → `WarrantyService.set_warranty_on_completion()` (same hook as loyalty points + review requests)
- **Invoice generation** → Warranty claims skip invoicing or generate $0.00 invoice for records
- **Loyalty points** → Warranty claims should NOT award points (no double-dipping)
- **Review requests** → Warranty claims should NOT trigger review requests (customer is already unhappy)
- **Pricing service** → `cost_override=0.00` for warranty claims bypasses progressive pricing

### Related proposals:
- [Review Request System](./review-request-system.md) — warranty claims excluded from review triggers
- [Loyalty System](./loyalty-system-overhaul.md) — warranty claims excluded from point awards
- [Website Widget](./website-integration-widget.md) — customers could submit warranty requests through website widget
- [Repair Form Efficiency](./repair-form-efficiency.md) — warranty claim form should pre-fill from original repair

---

## Implementation Plan

### Phase 1: Core (3-4 days)
- [ ] WarrantyPolicy model + migration
- [ ] Warranty fields on Repair model (expires_at, is_lifetime, is_warranty_claim, original_repair, claim_reason) + migration
- [ ] WarrantyService (set on completion, check status, create claim, stats)
- [ ] Hook into Repair.save() on COMPLETED transition
- [ ] Warranty badge on repair detail page
- [ ] "Create Warranty Claim" button + modal
- [ ] Owner settings page for warranty policies
- [ ] Default policies seeded on first access (chip=lifetime, crack=365d, replacement=none)
- [ ] Tests

### Phase 2: Reporting + Portal (2 days)
- [ ] Warranty dashboard widget (claims count, rate, by tech, by type)
- [ ] Warranty claims list page (all claims with links to originals)
- [ ] Customer portal: warranty status on repair history
- [ ] Customer portal: "Request Warranty Service" button
- [ ] Invoice integration ($0.00 warranty invoices, terms on regular invoices)

### Phase 3: Fleet + Advanced (future)
- [ ] Per-customer warranty overrides (fleet contracts with custom terms)
- [ ] Warranty certificate PDF (email to customer after repair)
- [ ] Warranty expiration reminders ("Your warranty on unit 4482 expires in 30 days")
- [ ] Analytics: warranty cost impact (lost revenue from warranty work)

---

## Scope & Risk

| Aspect | Assessment |
|--------|-----------|
| **Phase 1 effort** | 3-4 days |
| **Risk** | Low — additive, no changes to existing repair flow |
| **Migration risk** | Low — new fields are all nullable, existing repairs unaffected |
| **Breaking changes** | None |
| **Dependencies** | Repair completion hook (exists, shared with loyalty + reviews) |

## Pricing Angle

| Plan | Warranty Features |
|------|-------------------|
| **Starter** | Basic warranty tracking (expiry dates on repairs) |
| **Professional** | + Warranty claims workflow, customer portal warranty view |
| **Enterprise** | + Per-customer overrides, warranty certificates, analytics |

## Decision Needed
1. Approve Phase 1?
2. Should warranty terms print on PDF invoices by default?
3. Should customers be able to self-service warranty requests through their portal, or only via the shop?
4. Default policies: lifetime on chips, 365 days on cracks — does that match your experience?
