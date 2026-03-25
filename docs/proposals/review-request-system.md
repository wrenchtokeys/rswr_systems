# Proposal: Automated Review Request System

**Author:** Amelia  
**Date:** 2026-03-25  
**Status:** Draft — awaiting Drake's review

---

## Problem

Glass shops live and die by Google reviews. A shop with 4.8 stars and 200 reviews gets the call over a shop with 4.2 stars and 30 reviews — every time. But shop owners are terrible at asking for reviews because:

1. They forget — the job ends, the tech drives away, nobody follows up
2. They don't want to annoy fleet customers who send 50 trucks/month
3. They have no system — it's "hey can you leave us a review?" via text, maybe
4. They don't know which customers already reviewed them

RS Systems tracks every repair from request to completion. We know *exactly* when a job is done, who the customer is, whether they're a fleet or one-time, and whether they've been asked before. That's the perfect trigger for automated review requests.

## Solution: Smart Review Request Engine

After a repair is marked COMPLETED, RS Systems sends a branded email asking the customer to leave a Google review — but **only when it makes sense**.

### Smart Throttling Rules

Not every completed repair should trigger a review request. The system needs to be intelligent:

| Customer Type | Rule | Rationale |
|--------------|------|-----------|
| **One-time retail** | Ask after every completed repair | They may never come back — get the review now |
| **Repeat customer** (non-fleet) | Ask once per 90 days max | Don't nag regulars, but they're still individuals |
| **Fleet account** | Ask the **primary contact** once per 180 days max | Fleet managers don't want an email for every truck. One ask every 6 months is respectful. |
| **Already reviewed** | Never ask again (unless shop resets) | Once is enough. Pestering reviewers is a bad look. |
| **Denied/negative experience** | Never ask | If the customer denied a repair or had a dispute, don't ask for a review |

### Timing

- **Delay:** Send review request 2 hours after repair marked COMPLETED (not immediately — let the resin cure, let the tech leave, let the customer see the result)
- **Window:** Only send during business hours (9am–7pm in shop's timezone). If completion happens at 9pm, queue for next morning.
- **Cooldown:** Per-customer cooldown tracked in DB. No double-sends.

---

## Data Model

### ReviewRequest (new model)

```python
class ReviewRequest(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    customer = models.ForeignKey('core.Customer', on_delete=models.CASCADE)
    customer_user = models.ForeignKey('customer_portal.CustomerUser', 
        on_delete=models.SET_NULL, null=True, blank=True)
    repair = models.ForeignKey('technician_portal.Repair', 
        on_delete=models.SET_NULL, null=True, blank=True)
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),        # Queued, waiting for send window
        ('sent', 'Sent'),              # Email delivered
        ('clicked', 'Clicked'),         # Customer clicked the review link
        ('reviewed', 'Reviewed'),       # Confirmed review left (manual or webhook)
        ('skipped', 'Skipped'),         # Throttled — too soon, fleet cooldown, etc.
        ('suppressed', 'Suppressed'),   # Customer opted out or had negative experience
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    skip_reason = models.CharField(max_length=100, blank=True)  # "fleet_cooldown", "already_reviewed", "recent_request", etc.
    
    scheduled_at = models.DateTimeField()  # When to send (respects business hours)
    sent_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'customer', '-created_at']),
            models.Index(fields=['status', 'scheduled_at']),
        ]
```

### ReviewConfig (per-tenant settings)

```python
class ReviewConfig(models.Model):
    tenant = models.OneToOneField('tenants.Tenant', on_delete=models.CASCADE)
    
    is_active = models.BooleanField(default=False)  # Opt-in, not opt-out
    
    # Google Business integration
    google_place_id = models.CharField(max_length=255, blank=True,
        help_text="Google Place ID for direct review link")
    google_review_url = models.URLField(blank=True,
        help_text="Direct Google review URL (auto-generated from Place ID)")
    
    # Throttling
    retail_cooldown_days = models.PositiveIntegerField(default=90,
        help_text="Min days between review requests for repeat retail customers")
    fleet_cooldown_days = models.PositiveIntegerField(default=180,
        help_text="Min days between review requests for fleet accounts")
    
    # Timing
    delay_hours = models.PositiveIntegerField(default=2,
        help_text="Hours after repair completion before sending review request")
    send_window_start = models.TimeField(default='09:00',
        help_text="Earliest time to send review requests")
    send_window_end = models.TimeField(default='19:00',
        help_text="Latest time to send review requests")
    
    # Customization
    email_subject = models.CharField(max_length=200, 
        default="How was your experience with {shop_name}?")
    email_message = models.TextField(blank=True,
        help_text="Custom message body. Leave blank for default template.")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    @classmethod
    def get_for_tenant(cls, tenant):
        config, _ = cls.objects.get_or_create(tenant=tenant)
        return config
    
    @property
    def review_link(self):
        """Generate direct Google review URL from Place ID."""
        if self.google_place_id:
            return f"https://search.google.com/local/writereview?placeid={self.google_place_id}"
        return self.google_review_url or ''
```

---

## Service: ReviewRequestService

```python
class ReviewRequestService:
    
    @staticmethod
    def on_repair_completed(repair):
        """Called when a repair transitions to COMPLETED.
        Evaluates whether to queue a review request."""
        
        config = ReviewConfig.get_for_tenant(repair.tenant)
        if not config.is_active or not config.review_link:
            return None
        
        customer = repair.customer
        
        # 1. Find the right person to email
        #    For fleets: primary contact only
        #    For retail: the customer user (or primary contact)
        customer_user = CustomerUser.objects.filter(
            customer=customer,
            is_primary_contact=True,
        ).first() or CustomerUser.objects.filter(
            customer=customer,
        ).first()
        
        if not customer_user or not customer_user.user.email:
            return None  # No one to email
        
        # 2. Check suppression: negative experience
        if repair.queue_status_history_contains('DENIED'):
            return ReviewRequest.objects.create(
                tenant=repair.tenant, customer=customer,
                customer_user=customer_user, repair=repair,
                status='suppressed', skip_reason='negative_experience',
                scheduled_at=timezone.now(),
            )
        
        # 3. Check if already reviewed (ever)
        if ReviewRequest.objects.filter(
            tenant=repair.tenant, customer=customer,
            status='reviewed',
        ).exists():
            return ReviewRequest.objects.create(
                tenant=repair.tenant, customer=customer,
                customer_user=customer_user, repair=repair,
                status='skipped', skip_reason='already_reviewed',
                scheduled_at=timezone.now(),
            )
        
        # 4. Check cooldown
        is_fleet = customer.is_fleet  # or customer.customer_users.count() > 1
        cooldown_days = config.fleet_cooldown_days if is_fleet else config.retail_cooldown_days
        
        last_request = ReviewRequest.objects.filter(
            tenant=repair.tenant, customer=customer,
            status__in=['sent', 'clicked'],
        ).order_by('-sent_at').first()
        
        if last_request and last_request.sent_at:
            days_since = (timezone.now() - last_request.sent_at).days
            if days_since < cooldown_days:
                return ReviewRequest.objects.create(
                    tenant=repair.tenant, customer=customer,
                    customer_user=customer_user, repair=repair,
                    status='skipped', 
                    skip_reason=f'cooldown_{days_since}d_of_{cooldown_days}d',
                    scheduled_at=timezone.now(),
                )
        
        # 5. Calculate send time (respect business hours)
        send_at = timezone.now() + timedelta(hours=config.delay_hours)
        send_at = ReviewRequestService._adjust_to_business_hours(
            send_at, config.send_window_start, config.send_window_end
        )
        
        # 6. Queue the request
        return ReviewRequest.objects.create(
            tenant=repair.tenant, customer=customer,
            customer_user=customer_user, repair=repair,
            status='pending', scheduled_at=send_at,
        )
    
    @staticmethod
    def send_pending_requests():
        """Management command / cron: send all pending requests whose time has come."""
        now = timezone.now()
        pending = ReviewRequest.objects.filter(
            status='pending', scheduled_at__lte=now,
        ).select_related('tenant', 'customer', 'customer_user__user', 'repair')
        
        for request in pending:
            config = ReviewConfig.get_for_tenant(request.tenant)
            if not config.is_active:
                request.status = 'skipped'
                request.skip_reason = 'config_deactivated'
                request.save(update_fields=['status', 'skip_reason'])
                continue
            
            success = ReviewRequestService._send_review_email(request, config)
            if success:
                request.status = 'sent'
                request.sent_at = now
            else:
                request.status = 'skipped'
                request.skip_reason = 'email_failed'
            request.save(update_fields=['status', 'sent_at', 'skip_reason'])
    
    @staticmethod
    def _send_review_email(request, config):
        """Send the branded review request email."""
        from core.email_utils import send_branded_email
        
        review_url = config.review_link
        # Add tracking param so we can detect clicks
        tracking_url = f"https://rssystems.io/r/{request.pk}/{request.repair_id}/"
        
        context = {
            'customer_name': request.customer.name,
            'shop_name': request.tenant.name,
            'review_url': tracking_url,
            'repair_unit': request.repair.unit_number if request.repair else '',
            'custom_message': config.email_message,
        }
        
        return send_branded_email(
            tenant=request.tenant,
            to_email=request.customer_user.user.email,
            subject=config.email_subject.format(shop_name=request.tenant.name),
            template='emails/review_request.html',
            context=context,
        )
```

---

## Review Request Email Template

Clean, branded, one clear CTA:

```
Subject: How was your experience with Rockstar Windshield Repair?

Hi [Customer Name],

Thanks for choosing [Shop Name] for your recent windshield repair
on unit [TRUCK-4482].

If you had a great experience, we'd really appreciate a quick
Google review — it helps other drivers find us.

        [ ⭐ Leave a Review ]
        (links to Google review page)

It only takes 30 seconds and means the world to our team.

Thanks,
[Shop Name]
```

---

## Click Tracking

Simple redirect endpoint:

```
GET /r/<request_id>/<repair_id>/
```

1. Marks ReviewRequest as `clicked` with timestamp
2. Redirects to the Google review URL
3. No login required — public URL with non-guessable IDs (UUID or HMAC token)

This gives shops visibility into: "We sent 50 review requests this month, 15 were clicked."

---

## Google Business Integration

### Setup (Owner Portal → Settings → Reviews)

1. Shop owner enters their Google Business name
2. We use Google Places API (or a simple search) to find their Place ID
3. Auto-generate the direct review URL: `https://search.google.com/local/writereview?placeid=ChIJ...`
4. Owner can test the link before activating

**Alternative (no API needed):** Owner pastes their Google review link directly. Most shop owners know how to find this — it's in their Google Business dashboard.

### Future: Google Business API Integration

With the Google Business Profile API, we could:
- Pull review count and average rating into the RS Systems dashboard
- Show "You have 3 new reviews this week" on the owner dashboard
- Detect when a review is actually left (close the loop on `clicked` → `reviewed`)
- Display reviews in the customer portal as social proof

This would require OAuth + Google Business Profile API access. Phase 2.

---

## Integration with Website Widget

The website widget proposal already creates customers and repairs from quote requests. The review system hooks into the same flow:

```
Website visitor submits quote → Customer created → Repair queued
    → Tech completes repair → Review request sent (if eligible)
        → Customer clicks → Leaves Google review
            → Shop gets more reviews → More website visitors
```

This is a **flywheel**: more reviews → better Google ranking → more quote requests → more repairs → more review opportunities.

---

## Owner Portal UI

### Settings → Reviews

- **Toggle:** Enable/disable review requests
- **Google Business:** Enter Place ID or paste review URL (with "Test link" button)
- **Timing:** Delay after completion (default 2h), send window (9am–7pm)
- **Cooldowns:** Retail (default 90 days), Fleet (default 180 days)
- **Custom message:** Optional custom text for the email
- **Preview:** See what the email looks like before activating

### Dashboard Widget

- **Review Requests This Month:** Sent / Clicked / Reviewed
- **Click-through rate:** % of sent that were clicked
- **Last 5 requests:** Customer, status, date

---

## Implementation Plan

### Phase 1: Core (2-3 days)
- [ ] ReviewRequest + ReviewConfig models + migrations
- [ ] ReviewRequestService with smart throttling
- [ ] Hook into repair completion (Repair.save signal)
- [ ] Review request email template (branded HTML)
- [ ] Click tracking redirect endpoint
- [ ] Management command: `send_review_requests` (add to cron)
- [ ] Owner settings page for ReviewConfig
- [ ] Tests

### Phase 2: Dashboard + Analytics (1-2 days)
- [ ] Dashboard widget showing request stats
- [ ] Review request history page (all requests with status)
- [ ] CSV export of review request data

### Phase 3: Google Business API (future)
- [ ] OAuth flow for Google Business Profile
- [ ] Pull review count + rating into dashboard
- [ ] Auto-detect when review is actually left
- [ ] Display reviews as social proof

---

## Scope & Risk

| Aspect | Assessment |
|--------|-----------|
| **Phase 1 effort** | 2-3 days |
| **Risk** | Low — additive, no existing behavior changes |
| **Dependencies** | `send_branded_email` (exists), repair completion hook (exists) |
| **External deps** | Google Places API for auto-lookup (optional — manual URL works) |
| **Privacy** | Email only sent to existing customers. Unsubscribe link included. |
| **Competitor landscape** | Jobber, Housecall Pro have this. No glass-specific SaaS does. |

## Pricing Angle

| Plan | Review Features |
|------|----------------|
| **Starter** | Manual review link in emails (no automation) |
| **Professional** | Automated review requests with throttling |
| **Enterprise** | + Google Business API integration, analytics |

---

## Decision Needed

1. Approve Phase 1?
2. Google Place ID lookup: use Google API or just let owners paste the URL?
3. Should the review request email include the shop's logo (like our branded emails)?
4. Add an SMS option in addition to email? (Would need Twilio integration)
