# Proposal: Invoice Email Open Tracking

**Author:** Amelia  
**Date:** 2026-03-20  
**Status:** Proposed  
**Priority:** Medium — customer-requested feature, QuickBooks parity

---

## Problem

Shop owners send invoices via email but have zero visibility into whether the customer actually opened them. When a fleet manager says "I never got the invoice," the shop owner has no evidence. This creates:

- **Payment delays** — owners don't know if non-payment is because the customer didn't see the invoice or is ignoring it
- **Awkward follow-ups** — calling to ask "did you get my invoice?" feels unprofessional
- **Lost invoices** — emails legitimately go to spam with no way to detect it
- **QuickBooks gap** — competitors show open/view status; we don't

## Solution

Add email event tracking (open tracking via pixel + click tracking via redirect) to invoice emails. Display a QuickBooks-style activity timeline on invoice detail views.

---

## Design

### 1. New Model: `InvoiceEmailEvent`

```python
class InvoiceEmailEvent(models.Model):
    """Tracks email engagement events for invoices."""
    
    EVENT_TYPES = [
        ('SENT', 'Email Sent'),
        ('DELIVERED', 'Delivered'),       # Future: SES webhooks
        ('OPENED', 'Opened'),
        ('CLICKED', 'Link Clicked'),
        ('BOUNCED', 'Bounced'),           # Future: SES webhooks
        ('COMPLAINED', 'Marked as Spam'), # Future: SES webhooks
    ]
    
    invoice = models.ForeignKey(
        'billing.Invoice',
        on_delete=models.CASCADE,
        related_name='email_events',
    )
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, db_index=True)
    
    # Tracking metadata
    recipient_email = models.EmailField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # For CLICKED events — which link was clicked
    clicked_url = models.URLField(blank=True)
    
    # Unique token for this email send (groups events to a single send)
    tracking_token = models.UUIDField(db_index=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['invoice', 'event_type']),
            models.Index(fields=['tracking_token']),
        ]
```

### 2. Tracking Endpoints

Two new lightweight views (no auth required — token-based):

```
GET /billing/track/<uuid:token>/pixel.gif    → 1x1 transparent GIF, logs OPENED event
GET /billing/track/<uuid:token>/click/       → ?url=<encoded_url>, logs CLICKED, redirects
```

**Security considerations:**
- Token is a UUID4 — not guessable, not the invoice ID
- Pixel endpoint returns proper cache headers (`Cache-Control: no-store`) to prevent false deduplication
- Click redirect validates URL against an allowlist (our domain only — Stripe hosted URLs + customer portal)
- Rate-limit: max 50 events per token per hour (prevent abuse/bot loops)
- No PII in the URL — just the UUID token

### 3. Email Changes

**Current state:** Emails are plain text via Django's `EmailMessage`.

**Required change:** Switch to `EmailMultiAlternatives` to send both plain text (fallback) and HTML (with tracking pixel).

```python
from django.core.mail import EmailMultiAlternatives

email = EmailMultiAlternatives(
    subject=subject,
    body=plain_text_body,      # Existing plain text (unchanged)
    from_email=settings.DEFAULT_FROM_EMAIL,
    to=[recipient_email],
)

# HTML version with tracking pixel
html_body = render_to_string('billing/email/invoice_email.html', {
    'invoice_data': invoice_data,
    'payment_link': payment_link,
    'tracking_pixel_url': f'{base_url}/billing/track/{token}/pixel.gif',
    'pay_url': f'{base_url}/billing/track/{token}/click/?url={encoded_pay_url}',
})
email.attach_alternative(html_body, 'text/html')
```

**HTML template:** Clean, mobile-friendly, matches RS Systems branding. Not a heavy redesign — just a structured version of the existing plain text with the pixel embedded before `</body>`.

### 4. Invoice Model Addition

Add a convenience property to `Invoice`:

```python
@property
def email_status(self):
    """Returns the most advanced email engagement status."""
    events = self.email_events.values_list('event_type', flat=True)
    if 'CLICKED' in events:
        return 'clicked'
    if 'OPENED' in events:
        return 'viewed'
    if 'DELIVERED' in events:
        return 'delivered'
    if 'SENT' in events:
        return 'sent'
    return None

@property
def first_opened_at(self):
    """When was this invoice first opened?"""
    event = self.email_events.filter(event_type='OPENED').order_by('timestamp').first()
    return event.timestamp if event else None

@property 
def open_count(self):
    """How many times was this invoice opened?"""
    return self.email_events.filter(event_type='OPENED').count()
```

### 5. UI Changes

#### Invoice List View (Owner Portal)
Add an email status column/badge:

| Invoice | Customer | Amount | Status | Email |
|---------|----------|--------|--------|-------|
| INV-42 | EOS Trucking | $2,350.00 | Sent | 👁 Viewed Mar 20 |
| INV-43 | Penske | $600.00 | Sent | ✉️ Sent |
| INV-44 | West Tree | $200.00 | Draft | — |

Badge logic:
- No events → "—"
- SENT only → "✉️ Sent" (gray)  
- OPENED → "👁 Viewed" (blue) + relative timestamp
- CLICKED → "🔗 Clicked" (green)

#### Invoice Detail View (Owner Portal)
Activity timeline below the invoice summary:

```
📋 Invoice Timeline
─────────────────────
✉️  Sent to dispatch@eostrucking.com         Mar 20, 9:15 AM
👁  Opened (3 times, last: Mar 20, 2:30 PM)   Mar 20, 10:42 AM
🔗  Clicked "Pay Now"                          Mar 20, 2:31 PM
💰  Payment received — $2,350.00               Mar 20, 2:35 PM
```

#### Optional: Owner Notification
When an invoice is first opened, create a `TechnicianNotification`:
> "EOS Trucking viewed Invoice #INV-42 ($2,350.00)"

This lets the owner know the ball is in the customer's court — useful for follow-up timing.

---

## Implementation Plan

### Phase 1: Core Tracking (MVP)
1. Create `InvoiceEmailEvent` model + migration
2. Build tracking pixel endpoint (`/billing/track/<token>/pixel.gif`)
3. Build click redirect endpoint (`/billing/track/<token>/click/`)
4. Generate tracking token on invoice email send, log `SENT` event
5. Switch `InvoiceEmailService.send_invoice_email()` to `EmailMultiAlternatives`
6. Create minimal HTML email template with embedded pixel
7. Add `email_status`, `first_opened_at`, `open_count` properties to Invoice
8. Tests: model tests, endpoint tests, email integration tests

### Phase 2: UI
9. Add email status badge to owner invoice list view
10. Add activity timeline to owner invoice detail view
11. Add email status badge to technician invoice views (read-only)

### Phase 3: Notifications + Polish
12. Fire notification on first open ("Customer viewed your invoice")
13. Add open tracking to reminder emails (reuse same infrastructure)
14. Dashboard widget: "X invoices viewed but unpaid" — nudge for follow-up

### Future (not in scope now)
- **SES webhook integration** — get DELIVERED, BOUNCED, COMPLAINED events from the email provider (much more reliable than pixel tracking alone)
- **Aggregate analytics** — "Average time from sent to viewed: 4.2 hours" per customer
- **Auto-reminder triggers** — "If not opened after 3 days, auto-send reminder"

---

## Scope

- **New model:** 1 (`InvoiceEmailEvent`)
- **New views:** 2 (pixel endpoint, click redirect)
- **Modified files:** `invoice_email_service.py`, invoice list/detail templates, Invoice model
- **New template:** 1 HTML email template
- **Migration:** 1
- **Estimated tests:** ~25-30
- **LOC estimate:** ~400-500 (model + views + service changes + templates + tests)

## Risk

| Risk | Impact | Mitigation |
|------|--------|------------|
| Apple Mail Privacy Protection pre-fetches pixels → false opens | Low — inflates open count slightly | Show "Viewed (may include auto-opens)" tooltip; deduplicate by IP within short window |
| Gmail image proxy caches pixel → miss repeat opens | Low — first open still tracked | Accept limitation; note in docs |
| Email clients block images entirely → miss opens | Medium — some customers invisible | Click tracking still works; future SES webhooks provide delivery confirmation |
| Bot/scanner pre-fetching → false positives | Low | Rate limit per token; ignore known bot user agents (Barracuda, Mimecast, etc.) |
| HTML email rendering issues | Low | Keep HTML simple; test against Litmus/Email on Acid basics; plain text fallback always works |
| ~~SendGrid credits exhausted~~ | Resolved 2026-07-09 | No longer blocking: email now sends via Amazon SES (production access, 50k/day) |

## Dependencies

- ~~**Email sending must work**~~ — resolved 2026-07-09. Email sends via Amazon SES (production access granted; 50,000 msg/day).
- No new Python packages required
- No architecture changes — fits cleanly into existing billing app

---

## Why This Matters

For a small glass shop owner chasing fleet invoices, knowing that "Penske dispatch opened your $4,200 invoice 3 times but hasn't paid" is a completely different conversation than "I sent the invoice, I think." It's the difference between a confident follow-up call and a hesitant one.

Every serious invoicing tool has this. We should too.
