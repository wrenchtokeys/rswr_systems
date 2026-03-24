# Proposal: Website Integration Widget for RS Systems Shops

**Author:** Amelia  
**Date:** 2026-03-23  
**Status:** Draft — awaiting Drake's review

---

## Problem

Glass shop owners have websites (WordPress, Wix, Squarespace, plain HTML) but there's no connection between their website and RS Systems. Quote requests come in via email, phone, or website contact forms — and then someone has to manually type them into RS Systems as a customer + repair.

That's double entry, dropped leads, and zero visibility into the funnel.

## Solution: Embeddable Quote Request Widget

RS Systems provides a lightweight JavaScript snippet that any shop can drop on their website. It renders a branded contact/quote form that feeds directly into their RS Systems dashboard.

```html
<!-- One line on the shop's website -->
<script src="https://rssystems.io/widget/v1.js" data-tenant="rockstar-wr"></script>
```

### What Happens When Someone Submits

1. **Customer auto-created** (or matched by phone/email to existing)
2. **Repair request queued** as "Pending" in the shop's dashboard
3. **Owner notified** via email + in-app notification
4. **Customer gets branded confirmation** (shop's branding, not RS Systems)
5. Everything is tracked: submission → contact → repair → invoice → payment

### Shop Dashboard Additions

- **Lead Queue** — new tab showing all website submissions with status (New / Contacted / Quoted / Scheduled / Won / Lost)
- **Response time tracking** — time from submission to first contact
- **Conversion metrics** — how many website leads become paying repairs
- **Quick actions** — one-tap to call, create repair, assign tech

### Widget Features

- **Branded** — pulls shop's colors/logo from their RS Systems tenant settings
- **Responsive** — works on mobile, desktop, any screen size
- **Customizable fields** — shops choose which fields to show (service type, vehicle info, photos, insurance info)
- **Spam protection** — honeypot + rate limiting (built into our backend, not the shop's server)
- **No account needed for customers** — just fill out the form. If they want to track their repair later, they can create an account.

---

## Architecture

### Widget (Frontend)
- Vanilla JS bundle (~15KB gzipped), no dependencies
- Renders an iframe or shadow DOM form (isolated from shop's CSS)
- Posts to `https://rssystems.io/api/widget/submit/`
- Tenant identified by slug in the script tag

### Backend (New Endpoints)
- `POST /api/widget/submit/` — public, rate-limited, CSRF-exempt (like Stripe webhooks)
- Validates tenant slug, creates/matches customer, creates repair request
- Fires notifications (email + in-app)
- Returns success/error to widget

### New Models
```
WebsiteSubmission
  - tenant (FK)
  - customer (FK, nullable — created after matching)
  - repair (FK, nullable — created when tech assigned)
  - name, phone, email, service_type, vehicle_info, damage_description
  - status (new / contacted / quoted / scheduled / won / lost)
  - source_url (which page they submitted from)
  - submitted_at
  - contacted_at (first response timestamp)
  - notes
```

### Data Flow
```
Shop's Website → Widget JS → RS Systems API → WebsiteSubmission
                                            → Customer (auto-create/match)
                                            → Notification (owner + customer email)
                                            → Lead Queue (dashboard)
                                            → Repair (when tech assigned)
                                            → Invoice → Payment
```

---

## Why This Is a Killer Feature

### For Shop Owners
- **Zero double entry** — website leads flow straight into their system
- **Never lose a lead** — every submission is tracked, nothing falls through
- **Know your funnel** — see exactly how many website visitors become paying customers
- **Look professional** — branded, instant confirmation emails. Customers feel taken care of.

### For RS Systems (Business)
- **Massive stickiness** — once a shop's website is wired into RS Systems, switching costs are high. Their whole lead pipeline depends on it.
- **Upsell opportunity** — free tier gets basic form + 3 fields. Pro gets custom fields, auto-SMS, response time SLAs, conversion analytics.
- **Data moat** — aggregate (anonymized) data across shops gives us industry insights: avg ticket size by region, popular services, seasonal trends. Useful for marketing and pricing.
- **Distribution** — the widget has a tiny "Powered by RS Systems" link. Every shop's website becomes a lead gen channel for RS Systems itself.
- **Differentiator** — no other glass shop SaaS does this. Most are stuck in the "type it in manually" era.

### Pricing Angle
| Plan | Widget Features |
|------|----------------|
| **Starter** | Basic form (name, phone, service type). 50 submissions/month. |
| **Professional** | Custom fields, auto-confirmation email, lead queue dashboard. 500/month. |
| **Enterprise** | Auto-SMS, response time tracking, conversion analytics, API access. Unlimited. |

---

## Implementation Plan

### Phase 1: Backend + Internal Use (1 week)
- `WebsiteSubmission` model + migrations
- Public submit endpoint with rate limiting
- Customer auto-create/match logic
- Owner notification (branded email + in-app)
- Customer confirmation email
- Lead queue view in owner dashboard
- **Test with Rockstar's website first** (replace current S3-only contact form)

### Phase 2: Widget JS (1 week)
- Build embeddable JS bundle
- Iframe-based form that pulls tenant branding
- Setup instructions page for shop owners
- "Powered by RS Systems" footer link

### Phase 3: Analytics + Premium (later)
- Response time tracking
- Conversion funnel metrics (lead → repair → invoice → paid)
- Auto-SMS on submission (Twilio integration)
- Weekly lead summary email
- CSV export of submissions

---

## Scope & Risk

| Aspect | Assessment |
|--------|-----------|
| **Effort** | Phase 1: ~1 week. Phase 2: ~1 week. |
| **Cost** | Zero incremental infra. Uses existing DB + email. |
| **Risk** | Low. New feature, no changes to existing billing/repair flow. |
| **Dependencies** | None for Phase 1-2. Twilio for auto-SMS in Phase 3. |
| **Security** | Public endpoint needs rate limiting + spam protection. Tenant validation on every request. No auth required for submitters. |

## Dogfooding Plan

Build Phase 1, wire it into rockstarwindshield.repair to replace the current S3-only contact form. Drake uses it daily for real leads. Iron out the UX based on real usage. Then package it as an RS Systems feature.

## Decision Needed
1. Approve Phase 1 (backend + Rockstar integration)?
2. Which plan tier should the widget live in?
3. Should "Powered by RS Systems" be mandatory or optional?
