# Amelia's Implementation Roadmap

*Living document - updated as I work*
*Last Updated: January 27, 2026*

---

## 🎯 Active Projects

### 1. Invoice Automation System
**Priority**: HIGH
**Status**: Planning

#### The Problem
Drake manually:
1. Downloads photos from S3
2. Crops/renames each photo (`[unit] - before.jpg`, `[unit] - after.jpg`)
3. Creates invoice in QuickBooks Online
4. Copies repair details (unit, damage location, price)
5. Attaches photos
6. Repeats for EVERY repair

This takes 10-15 minutes per invoice. With growth, this doesn't scale.

#### The Solution

**Phase 1: PDF Invoice Generator** (Start here)
- Generate professional PDF invoices from RS Systems data
- Embed resized photos (before/after) directly in PDF
- Support per-repair AND batch invoicing (customer preference)
- Include: unit #, damage type, location, price, photos, totals
- Branding: Rockstar Windshield Repair logo/colors

**Phase 2: Stripe Integration** (Multi-tenant ready)
- Stripe Connect for multi-tenant billing
- Each glass shop (tenant) has own Stripe account
- RS Systems takes platform fee
- Automated payment collection
- Subscription billing for SaaS customers

**Phase 3: QuickBooks Integration** (Optional)
- QBO API sync for those who want it
- Export invoices to QuickBooks
- May not be needed if Stripe handles everything

#### Technical Design

```
┌─────────────────────────────────────────────────────────────┐
│                    Invoice Service                          │
├─────────────────────────────────────────────────────────────┤
│  Input: customer_id, date_range, invoice_type               │
│                                                              │
│  1. Query completed repairs for customer/date range          │
│  2. Fetch photos from S3 (resize, no cropping needed)        │
│  3. Generate PDF with ReportLab or WeasyPrint                │
│  4. Option A: Return PDF for download                        │
│  5. Option B: Send to Stripe as invoice                      │
│  6. Option C: Email directly to customer                     │
└─────────────────────────────────────────────────────────────┘
```

#### Photo Handling
- S3 photos are RAW (not cropped) - intentional for future ML training
- Customer-submitted photos: stored separately for damage assessment model
- Technician proof-of-work photos: `before/` and `after/` prefixes
- Invoice generator will resize (not crop) to fit invoice layout
- Original S3 files remain untouched

#### Customer Invoice Preferences (to add to model)
```python
class CustomerInvoicePreference(models.Model):
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE)
    invoice_frequency = models.CharField(choices=[
        ('PER_REPAIR', 'Invoice per repair'),
        ('PER_VISIT', 'Invoice per visit'),
        ('WEEKLY', 'Weekly batch'),
        ('BIWEEKLY', 'Bi-weekly batch'),
        ('MONTHLY', 'Monthly batch'),
    ])
    payment_method = models.CharField(choices=[
        ('INVOICE', 'Invoice (net 30)'),
        ('STRIPE', 'Pay online via Stripe'),
        ('CASH', 'Cash/Check on site'),
    ])
    include_photos = models.BooleanField(default=True)
    email_invoice = models.BooleanField(default=True)
    invoice_email = models.EmailField(blank=True)  # Override customer email
```

---

### 2. X (Twitter) Growth Strategy
**Priority**: HIGH
**Status**: Research

#### Handle: @wrenchtokeys

#### Content Pillars

**Pillar 1: Tradesman Who Codes**
- Unique angle: blue collar meets tech
- "I fix windshields by day, build SaaS by night"
- Relatable to both trades and dev communities

**Pillar 2: Building in Public**
- RS Systems development journey
- Lessons learned, mistakes made
- Real revenue/user numbers (when ready)

**Pillar 3: Industry Disruption**
- "The windshield repair industry still uses paper and texts"
- Pain points only an insider would know
- Why tech is finally coming to trades

**Pillar 4: Educational Content**
- Windshield repair tips (can this chip be fixed?)
- Fleet maintenance insights
- Behind-the-scenes of mobile repair business

#### Content Strategy
- 1 thread per week (in-depth, valuable)
- 2-3 short posts per day (observations, hot takes, replies)
- Engage with tech/trades/SaaS communities
- Reply to bigger accounts in the space

---

### 3. Clawdbot Endpoint Experimentation
**Priority**: MEDIUM
**Status**: Ready

#### What Exists
- Endpoint: `rockstarwindshield.repair/clawdbot/`
- Status check: `/clawdbot/`
- Health check: `/clawdbot/health/`

#### What I Can Build
- My own experimental views
- A/B test new features
- Demo invoice generation
- API endpoints for my tools

---

## 📋 Backlog

### Technical Improvements
- [ ] Split technician_portal/views.py into service layer
- [ ] Add API rate limiting to DRF endpoints
- [ ] Query optimization audit (N+1 fixes)
- [ ] Deprecate Repair.calculate_cost() static method

### SaaS Features
- [ ] Multi-tenant model (Tenant → Customer relationship)
- [ ] Customer self-registration flow
- [ ] Tenant onboarding wizard
- [ ] Subscription management

### Mobile/Real-time
- [ ] Django Channels for WebSocket support
- [ ] Push notifications (FCM)
- [ ] PWA service worker

### AI/ML (Future)
- [ ] Damage assessment from customer photos
- [ ] "Can this be repaired?" classifier
- [ ] Training data: customer-submitted photos with repair outcomes

---

## 📝 Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-27 | Start with Stripe over QuickBooks | Multi-tenant ready, modern, better DX |
| 2026-01-27 | PDF first, then Stripe | Quick win, proves value, Stripe adds complexity |
| 2026-01-27 | Don't crop S3 photos | Raw data needed for future ML training |

---

## 🔗 Related Docs
- [AMELIA_README.md](../AMELIA_README.md) - Strategic codebase assessment
- [SAAS_NOTIFICATION_STRATEGY.md](strategy/SAAS_NOTIFICATION_STRATEGY.md) - Notification architecture
