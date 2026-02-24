# SaaS Notification System Strategy
## Email & SMS Notifications for Multi-Tenant Windshield Repair Platform

**Document Purpose:** Strategic roadmap for scaling the notification system as the platform grows from single-shop to multi-shop SaaS product.

**Last Updated:** December 6, 2025
**Author:** Strategic Planning
**Status:** Phase 1 Complete - Email Working via SendGrid

---

## Executive Summary

This document outlines the notification system strategy for scaling from a single windshield repair shop to a multi-tenant SaaS platform serving multiple independent glass shops.

**Key Decision:** Use **SendGrid** instead of AWS SES as the primary email service provider.

**Why SendGrid Wins for SaaS:**
- Multi-tenant architecture built-in
- No per-customer domain verification required
- Scales from 10 to 10,000,000 emails seamlessly
- Custom branding per tenant
- Industry-proven for SaaS platforms

**Cost Projection:**
- 10 shops Ã 100 emails/day = 1,000 emails/day = ~$20/month
- 50 shops Ã 100 emails/day = 5,000 emails/day = ~$80/month
- 100 shops Ã 100 emails/day = 10,000 emails/day = ~$120/month

---

## Current State (December 2025)  OPERATIONAL

### What We Have Today

**Infrastructure:**
-  AWS Elastic Beanstalk (application hosting)
-  AWS RDS PostgreSQL (database)
-  AWS ElastiCache Redis (task queue)
-  Celery workers (async task processing)
-  Django notification system (templates, preferences, delivery logs)
-  **SendGrid email delivery** (production-ready, no sandbox restrictions)

**Notification Features:**
-  8 notification templates (repair status, approvals, assignments)
-  User notification preferences (opt-in/opt-out per category)
-  Email delivery tracking (pending, delivered, failed)
-  Quiet hours support
-  Priority-based delivery (urgent, high, medium, low)
-  Email branding system (logo, colors, custom footer)

**Resolved Blockers:**
-  Switched from AWS SES to SendGrid (SES rejected twice)
-  Domain authenticated with DKIM/SPF in SendGrid
-  Can send to any email address (no sandbox restrictions)

**Remaining:**
-  SMS not yet enabled (Twilio migration planned, see Phase 2)

---

## SaaS Architecture Requirements

### What Changes When Going Multi-Tenant?

#### 1. Per-Tenant Branding
Each glass shop needs their own branding:
```
Shop A: notifications@glassproaustin.com
        Logo: Glass Pro Austin
        Colors: Blue/White

Shop B: notifications@quickfixglass.com
        Logo: QuickFix Glass
        Colors: Red/Black
```

#### 2. Per-Tenant Configuration
Each shop controls their own:
- Notification templates (custom wording)
- Email signature
- Notification timing preferences
- Which notifications to enable

#### 3. Subdomain/Domain Support
Options for shop access:
```
Option 1: Subdomains
  - glassproaustin.rssystems.io
  - quickfixglass.rssystems.io

Option 2: Custom Domains (White-Label)
  - app.glassproaustin.com
  - app.quickfixglass.com
```

#### 4. Data Isolation
- Each shop's customers only see their data
- Notifications only go to that shop's customers
- Complete data separation (security/privacy)

---

## Email Service Provider Comparison

### SendGrid vs AWS SES for SaaS

| Feature | SendGrid | AWS SES |
|---------|----------|---------|
| **Multi-tenant ready** |  Built for it |  Complex setup |
| **Domain verification** | 1 domain for all tenants | Need verification per tenant |
| **Sandbox mode** | No sandbox | Sandbox per domain |
| **Custom FROM addresses** | Easy per-tenant setup | Requires domain verification |
| **White-label support** |  Native |  Manual per domain |
| **Approval process** | Instant | 24-48 hours (or rejected) |
| **Free tier** | 100 emails/day forever | Same as SendGrid |
| **Paid pricing** | $20/month for 40k emails | $0.10 per 1,000 emails |
| **Deliverability** | Industry-leading | Excellent |
| **API simplicity** |  Very simple |  Simple |
| **Track record** | Used by Uber, Spotify | Used by Netflix, Airbnb |

### SendGrid Pricing Tiers

```
Free:          100 emails/day     = $0/month
Essentials:    40,000/month       = $20/month  (1,300/day)
Pro:           100,000/month      = $90/month  (3,300/day)
Premier:       Unlimited          = Custom pricing
```

### Cost Projections by Shop Count

**Assumptions:**
- Average shop: 10 active customers
- Each customer: 10 repairs/year
- 3 emails per repair (pending, approved, completed)
- = 30 emails/customer/year
- = 300 emails/shop/year
- = ~1 email/shop/day (25/month average, spikes to 100/month)

**Projections:**

| Shops | Emails/Month | Tier | Cost/Month | Cost/Shop |
|-------|--------------|------|------------|-----------|
| 1 | 25 | Free | $0 | $0 |
| 10 | 250 | Free | $0 | $0 |
| 100 | 2,500 | Free | $0 | $0 |
| 500 | 12,500 | Essentials | $20 | $0.04 |
| 1,000 | 25,000 | Essentials | $20 | $0.02 |
| 1,500 | 37,500 | Essentials | $20 | $0.01 |
| 2,000 | 50,000 | Pro | $90 | $0.045 |
| 5,000 | 125,000 | Premier | ~$200 | $0.04 |

**Key Insight:** Email costs are NEGLIGIBLE for SaaS pricing. Even with 5,000 shops, email costs only $200/month while you're making $50,000-$500,000/month in SaaS revenue.

---

## SMS Provider Strategy

### Why SMS Matters for Windshield Repair

SMS has **4x higher open rates** than email:
- Email open rate: ~20-30%
- SMS open rate: ~98%
- SMS response time: <90 seconds average

**Critical notifications for SMS:**
-  URGENT: Repair approved (tech can start immediately)
-  URGENT: Repair denied (don't drive to location)
-  HIGH: New assignment

### Twilio for SMS (Industry Standard)

**Why Twilio:**
-  Integrates with SendGrid
-  Built for SaaS/multi-tenant
-  Phone number per tenant (optional)
-  Two-way SMS support
-  International support (when expanding)

**Pricing:**
```
Programmable SMS:
  - US/Canada: $0.0079 per SMS (~0.8 cents)
  - Phone number: $2/month (optional, can use shared pool)

Example costs:
  - 100 SMS/month = $0.79/month
  - 1,000 SMS/month = $7.90/month
  - 10,000 SMS/month = $79/month
```

**Multi-Tenant Approach:**

**Option A: Shared Phone Number Pool (Cheaper)**
```
All shops use: +1-555-REPAIR-1 (shared SendGrid/Twilio number)
SMS says: "QuickFix Glass: Your repair for unit #123 has been approved"
Cost: $0 monthly + usage
```

**Option B: Dedicated Phone Per Shop (Premium)**
```
Shop A: +1-512-555-0101
Shop B: +1-512-555-0102
SMS from shop's own number
Cost: $2/month per shop + usage
Good for: Premium tier customers who want brand consistency
```

---

## Implementation Roadmap

### Phase 1: Get Email Working (Week 1)
**Goal:** Functional email notifications for single shop (current state)

**Tasks:**
1.  Sign up for SendGrid account (15 min)
2.  Verify sending domain: rssystems.io (30 min)
3.  Update Django settings to use SendGrid backend (30 min)
4.  Test notifications end-to-end (1 hour)
5.  Deploy to AWS production (30 min)
6.  Verify Celery workers processing tasks (30 min)

**Deliverable:** Emails working for verified addresses

**Code Changes:**
```python
# settings_aws.py
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'apikey'
EMAIL_HOST_PASSWORD = os.environ.get('SENDGRID_API_KEY')
DEFAULT_FROM_EMAIL = 'notifications@rssystems.io'
```

**Environment Variables:**
```bash
SENDGRID_API_KEY=SG.xxxxxxxxxxxx
```

---

### Phase 2: Add Branding Configuration (Month 1)
**Goal:** Support custom email branding per shop (multi-tenant foundation)

**Database Changes:**
```python
# New model: ShopBrandingConfig
class ShopBrandingConfig(models.Model):
    shop = models.OneToOneField('Shop', on_delete=models.CASCADE)

    # Email settings
    from_email = models.EmailField(default='notifications@rssystems.io')
    from_name = models.CharField(max_length=100)  # "QuickFix Glass Notifications"
    reply_to_email = models.EmailField(blank=True)

    # Branding
    logo_url = models.URLField(blank=True)
    primary_color = models.CharField(max_length=7, default='#1a73e8')  # Hex color

    # Signature
    email_signature = models.TextField(default='')

    # Notification toggles (shop-level)
    notifications_enabled = models.BooleanField(default=True)
```

**Templates Update:**
```html
<!-- emails/notifications/base.html -->
<div style="background-color: {{ shop.branding.primary_color }}">
    <img src="{{ shop.branding.logo_url }}" alt="{{ shop.name }}">
</div>

<p>{{ notification.message }}</p>

<p>{{ shop.branding.email_signature }}</p>
```

**Migration to Multi-Tenant:**
- Notification templates become per-shop
- FROM email becomes configurable
- Logo/colors per shop

---

### Phase 3: SendGrid Subuser Architecture (Month 2)
**Goal:** Proper multi-tenant email isolation

**SendGrid Subusers:**
SendGrid supports "subusers" - isolated email accounts under one parent account.

**Architecture:**
```
Parent Account: Rockstar Windshield (main billing)
   Subuser: shop-glassproaustin
        FROM: notifications@rssystems.io
        Reply-To: glassproaustin@gmail.com
        Tracking: Separate stats
  
   Subuser: shop-quickfixglass
        FROM: notifications@rssystems.io
        Reply-To: quickfixglass@gmail.com
        Tracking: Separate stats
```

**Benefits:**
-  Per-shop email analytics
-  Isolate deliverability issues (one bad shop doesn't hurt others)
-  Per-shop API keys (security)
-  Per-shop unsubscribe management

**Implementation:**
```python
# core/services/email_service.py
def get_sendgrid_client(shop):
    """Get SendGrid client for specific shop."""
    if shop.sendgrid_subuser_api_key:
        return sendgrid.SendGridAPIClient(shop.sendgrid_subuser_api_key)
    else:
        return sendgrid.SendGridAPIClient(settings.SENDGRID_API_KEY)
```

---

### Phase 4: Custom Domain Support (Month 3-4)
**Goal:** White-label emails from shop's own domain

**Examples:**
```
Shop A: notifications@glassproaustin.com
Shop B: notifications@quickfixglass.com
```

**How It Works:**
1. Shop registers their own domain
2. Shop adds DNS records (we provide instructions)
3. We verify domain in SendGrid
4. Emails send from their domain

**DNS Records to Add:**
```
# CNAME records (shop's DNS)
em123.glassproaustin.com   u123456.wl.sendgrid.net
s1._domainkey.glassproaustin.com  s1.domainkey.u123456.wl.sendgrid.net
s2._domainkey.glassproaustin.com  s2.domainkey.u123456.wl.sendgrid.net
```

**Pricing Tier:**
- Basic tier: Uses rssystems.io (free)
- Premium tier: Custom domain support (+$20/month)

---

### Phase 5: SMS Integration via Twilio (Month 4-5)
**Goal:** Add SMS notifications for urgent messages

**Twilio Setup:**
```python
# settings_aws.py
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
```

**SMS Service:**
```python
# core/services/sms_service.py
from twilio.rest import Client

def send_sms(recipient_phone, message, shop=None):
    """Send SMS via Twilio."""
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    # Get shop's dedicated number or use shared pool
    from_number = shop.twilio_phone_number if shop.twilio_phone_number else settings.TWILIO_PHONE_NUMBER

    message = client.messages.create(
        body=message,
        from_=from_number,
        to=recipient_phone
    )

    return message.sid
```

**SMS Templates:**
```python
# Only for URGENT priority notifications
SMS_TEMPLATES = {
    'repair_approved': '{shop_name}: Repair approved for unit {unit_number}. You can proceed. - {shop_phone}',
    'repair_denied': '{shop_name}: Repair DENIED for unit {unit_number}. Do not proceed. - {shop_phone}',
}
```

**Cost Optimization:**
- Only send SMS for URGENT priority
- Email for everything else
- Estimated 10% of notifications = SMS

---

### Phase 6: Analytics Dashboard (Month 5-6)
**Goal:** Shop owners can see their email/SMS metrics

**Metrics to Track:**
- Total notifications sent (by type)
- Email open rates
- Email click rates
- SMS delivery rates
- Failed deliveries
- Unsubscribe rates

**SendGrid Webhooks:**
```python
# views/webhooks.py
@csrf_exempt
def sendgrid_webhook(request):
    """
    Receive SendGrid events:
    - delivered
    - opened
    - clicked
    - bounced
    - unsubscribed
    """
    events = json.loads(request.body)
    for event in events:
        # Update NotificationDeliveryLog
        update_delivery_status(event)
```

**Dashboard UI:**
```
Shop Dashboard > Notifications
   This Month: 234 emails sent, 187 delivered (80% open rate)
   This Month: 12 SMS sent, 12 delivered
   Top Notifications:
       - Repair Approved: 89 sent
       - Repair Pending: 67 sent
       - Repair Completed: 45 sent
   Failures: 3 bounced emails (invalid addresses)
```

---

## Database Schema Updates

### Shop Model (Multi-Tenant Foundation)
```python
class Shop(models.Model):
    """
    Represents an independent glass repair shop using the platform.
    In single-tenant mode, there's only one Shop record.
    In SaaS mode, each customer is a Shop.
    """
    # Basic info
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)  # quickfixglass

    # Contact
    email = models.EmailField()
    phone = models.CharField(max_length=20)

    # Subdomain
    subdomain = models.CharField(max_length=50, unique=True)  # quickfixglass.rssystems.io
    custom_domain = models.CharField(max_length=100, blank=True)  # app.quickfixglass.com

    # Notification config
    sendgrid_subuser_api_key = models.CharField(max_length=200, blank=True)
    twilio_phone_number = models.CharField(max_length=20, blank=True)

    # Billing
    plan = models.CharField(max_length=20, choices=[
        ('free', 'Free Trial'),
        ('basic', 'Basic - $99/month'),
        ('pro', 'Pro - $199/month'),
        ('enterprise', 'Enterprise - Custom'),
    ])

    # Status
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### All Models Get Shop Foreign Key
```python
class Customer(models.Model):
    shop = models.ForeignKey('Shop', on_delete=models.CASCADE)  # NEW
    # ... rest of fields

class Technician(models.Model):
    shop = models.ForeignKey('Shop', on_delete=models.CASCADE)  # NEW
    # ... rest of fields

class Repair(models.Model):
    shop = models.ForeignKey('Shop', on_delete=models.CASCADE)  # NEW
    # ... rest of fields

class Notification(models.Model):
    shop = models.ForeignKey('Shop', on_delete=models.CASCADE)  # NEW
    # ... rest of fields
```

### Row-Level Security
```python
# Automatic filtering by shop
class ShopQuerySet(models.QuerySet):
    def for_shop(self, shop):
        return self.filter(shop=shop)

# Usage
repairs = Repair.objects.for_shop(request.user.shop)
```

---

## Migration Strategy: Single Tenant  Multi-Tenant

### Step 1: Add Shop Model (Non-Breaking)
```python
# Create Shop model
# Add nullable shop foreign keys to all models
# Backfill: Create one Shop record for current business
# Update code to always filter by shop
```

### Step 2: Enforce Shop Isolation
```python
# Middleware to set current shop
# All queries automatically filter by shop
# Test data isolation thoroughly
```

### Step 3: Enable Multi-Shop Support
```python
# Add shop registration flow
# Add subdomain routing
# Add shop admin dashboards
```

---

## Cost Analysis: SaaS Notification System

### Monthly Costs by Customer Count

| Customers | Email Cost | SMS Cost | Total/Month | Cost/Customer |
|-----------|------------|----------|-------------|---------------|
| 10 shops | $0 (free tier) | $8 | $8 | $0.80 |
| 50 shops | $0 (free tier) | $40 | $40 | $0.80 |
| 100 shops | $0 (free tier) | $79 | $79 | $0.79 |
| 500 shops | $20 | $395 | $415 | $0.83 |
| 1,000 shops | $20 | $790 | $810 | $0.81 |
| 5,000 shops | $200 | $3,950 | $4,150 | $0.83 |

**Key Takeaway:** Notification costs are **~$0.80 per customer per month**, regardless of scale.

### Revenue Impact

If you charge **$99/month per shop**:
```
100 shops Ã $99/month = $9,900/month revenue
Notification costs: $79/month
Profit margin on notifications: 99.2%
```

**Notifications are essentially free** relative to SaaS pricing.

---

## Risk Analysis

### Risk: SendGrid Account Suspension
**Probability:** Low (if following best practices)

**Mitigation:**
- Maintain low bounce rates (<5%)
- Maintain low complaint rates (<0.1%)
- Verify email addresses before sending
- Implement double opt-in for new users
- Honor unsubscribes immediately

**Backup Plan:**
- Keep AWS SES configured as fallback
- Can switch in <1 hour if needed
- Use multiple providers (SendGrid primary, SES secondary)

### Risk: Twilio Costs Spike
**Probability:** Medium (if SMS enabled for all notifications)

**Mitigation:**
- Only use SMS for URGENT priority
- Implement per-shop SMS budgets
- Alert when shop exceeds budget
- Disable SMS if budget exceeded (fall back to email)

### Risk: Shop Sends Spam
**Probability:** Low but possible

**Mitigation:**
- Rate limiting per shop (max 1,000 emails/day)
- Monitor bounce/complaint rates per shop
- Suspend shop if rates exceed thresholds
- Subuser isolation prevents one shop from hurting others

---

## Competitive Analysis

### How Other SaaS Products Handle Notifications

**Stripe** (Payment SaaS):
- Uses SendGrid for transactional emails
- Supports custom FROM domains
- Per-tenant branding

**Shopify** (E-commerce SaaS):
- Uses SendGrid + Mailgun + AWS SES (multi-provider)
- Custom domains for each shop
- Millions of emails/day

**HubSpot** (Marketing SaaS):
- Own email infrastructure
- But started with SendGrid
- Switched to own infrastructure at 10M+ customers

**Key Insight:** Start with SendGrid. Switch to custom infrastructure only after 10,000+ customers.

---

## Recommendations

### Phase 1: Email Working  COMPLETED (December 6, 2025)

1.  **Sign up for SendGrid** (Free tier - 100 emails/day)
2.  **Domain authentication** via Route 53 DNS records
   - DKIM keys: s1._domainkey, s2._domainkey
   - Sender identity: em3661.rssystems.io
3.  **Update Django settings** to use SendGrid SMTP
4.  **Deploy to AWS Elastic Beanstalk**
5.  **Test email delivery** - confirmed working

### Phase 2: Next Steps (Ready to Start)

1.  **Add SMS via Twilio** (see implementation notes below)
   - Sign up for Twilio account
   - Refactor `core/services/sms_service.py` from AWS SNS to Twilio
   - Enable SMS for URGENT priority notifications

2.  **Test with real customers**
   - Gather feedback on email content
   - Monitor SendGrid analytics for open rates

3.  **Email branding refinement**
   - Custom logo upload working
   - Color customization working
   - Gather feedback and iterate

### Phase 3: Multi-Tenant SaaS (When Scaling)

1.  Implement SendGrid subusers (per-shop isolation)
2.  Custom domain support (premium tier)
3.  Per-shop analytics dashboard

### Phase 4: Long-Term (Year 1-2)

1.  Scale to 100+ shops
2.  A/B test notification content
3.  Notification scheduling
4.  International SMS support
5.  Consider custom email infrastructure (if 10,000+ shops)

---

## Success Metrics

### Phase 1 Success (Month 1)
- [ ] 100% of notifications delivered successfully
- [ ] <2% bounce rate
- [ ] <0.1% spam complaint rate
- [ ] >30% email open rate

### Phase 2 Success (Month 3)
- [ ] 10 shops onboarded
- [ ] Each shop has custom branding
- [ ] 95%+ customer satisfaction with notifications

### Phase 3 Success (Month 6)
- [ ] 50 shops using the platform
- [ ] SMS enabled for urgent notifications
- [ ] Analytics dashboard live
- [ ] <$1 notification cost per shop per month

### Phase 4 Success (Year 1)
- [ ] 200+ shops using the platform
- [ ] Custom domain support for premium customers
- [ ] Multi-provider redundancy (SendGrid + fallback)
- [ ] 99.9% notification delivery rate

---

## Conclusion

**Recommendation:** Proceed with SendGrid as the primary email service provider.

**Why:**
1.  **Immediate unblocking** - Works today, no AWS approval needed
2.  **SaaS-native** - Built for multi-tenant architecture
3.  **Scalable** - Proven at massive scale (Uber, Spotify)
4.  **Cost-effective** - Negligible cost relative to SaaS revenue
5.  **Future-proof** - Supports custom domains, white-label, etc.

**AWS SES Strategy:**
- Keep configured as backup
- Revisit in 6-12 months with proven sending history
- Use for internal notifications (not customer-facing)

**Status:**  SendGrid integration COMPLETE as of December 6, 2025.

**Next Steps:**
1. Add SMS via Twilio for urgent notifications (optional, ~3 hours)
2. Monitor email deliverability in SendGrid dashboard
3. Consider upgrading from free tier if exceeding 100 emails/day

---

## Appendix A: Alternative Providers Considered

| Provider | Pros | Cons | Verdict |
|----------|------|------|---------|
| **SendGrid** | SaaS-ready, proven, easy | Costs money at scale |  **RECOMMENDED** |
| **AWS SES** | Cheap, AWS-native | Rejected our account |  Not viable now |
| **Mailgun** | Good API, Rackspace-backed | More expensive than SendGrid |  Backup option |
| **Postmark** | Excellent deliverability | Expensive ($15/month minimum) |  Premium option |
| **SparkPost** | Good analytics | Complex setup |  Not worth it |
| **Twilio SendGrid** | Same as SendGrid | Same as SendGrid |  (Same company) |

---

## Appendix B: SendGrid Setup Checklist

- [ ] Sign up at https://sendgrid.com
- [ ] Verify email address
- [ ] Create API key with "Mail Send" permissions
- [ ] Add API key to AWS EB environment variables
- [ ] Verify sending domain (rssystems.io)
- [ ] Add DNS records (SPF, DKIM, DMARC)
- [ ] Wait 24-48 hours for DNS propagation
- [ ] Send test email
- [ ] Monitor deliverability in SendGrid dashboard
- [ ] Set up webhooks for delivery tracking
- [ ] Configure unsubscribe management

---

## Appendix C: Future Enhancements

**Advanced Features for Later:**

1. **In-App Notifications** (Bell icon)
   - Real-time notifications via WebSockets
   - "You have 3 unread notifications"

2. **Notification Digest** (Daily/Weekly summary)
   - "This week: 5 repairs approved, 3 completed"

3. **Two-Way SMS** (Customer can reply)
   - Customer: "What time will you arrive?"
   - Tech: "Around 2pm"

4. **Rich Email Templates**
   - Interactive buttons in emails
   - Approve/deny directly from email

5. **Push Notifications** (Mobile app)
   - iOS/Android push via Firebase

6. **Voice Notifications** (Phone calls)
   - Twilio voice calls for critical alerts
   - "Press 1 to approve, 2 to deny"

---

**Document Version:** 1.0
**Next Review:** After Phase 1 completion
**Questions?** Contact technical team
