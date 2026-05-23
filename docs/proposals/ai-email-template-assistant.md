# Proposal: AI-Assisted Email Template Generation

**Author:** Amelia  
**Date:** 2026-03-21  
**Status:** Draft  
**Depends on:** CODE-114 (customizable email templates)

## Problem

Shop owners aren't copywriters. The default invoice and reminder emails are functional but generic. Most owners will either:
1. Leave the defaults as-is (missed opportunity for brand voice)
2. Try to write something and end up with awkward, unprofessional text
3. Skip customization entirely

The placeholder system ({customer_name}, {total}, etc.) is powerful but intimidating for non-technical users who don't want to break anything.

## Solution

Add an "AI Assist" button next to each email template textarea that generates a custom default based on the shop's context.

### How It Works

1. Owner clicks **"✨ Generate with AI"** button next to the template textarea
2. System sends a prompt to an LLM API with:
   - Shop name, industry (auto glass), tone preference
   - Available placeholders and what they resolve to
   - Template type (invoice vs. reminder vs. overdue)
   - Optional: owner's plain-English description of what they want ("keep it friendly but firm", "we're a family business", "be direct, no fluff")
3. LLM returns a complete email template with placeholders correctly placed
4. Template populates the textarea — owner reviews, edits if needed, saves
5. Owner can regenerate as many times as they want before saving

### UI Mockup

```
Email Templates
─────────────────────────────────────
Payment Reminder Email

[Optional: Describe your style]
[e.g., "friendly but professional, mention we're a local business"]

[✨ Generate with AI]  [↻ Regenerate]

┌─────────────────────────────────────┐
│ Dear {customer_name},               │
│                                     │
│ Hope all is well! Just a quick      │
│ heads-up that invoice               │
│ {invoice_number} for {total} is     │
│ coming due on {due_date}...         │
│                                     │
│ [editable textarea]                 │
└─────────────────────────────────────┘
Placeholders: {customer_name}, {invoice_number}, ...

                          [Save Email Templates]
```

### Tone Presets (optional, v2)

Quick-select buttons instead of free-text description:
- **Professional** — formal, corporate tone
- **Friendly** — warm, personal, small-business feel  
- **Direct** — short, no-nonsense, gets to the point
- **Firm** — for overdue reminders, clear consequences

### Template Types to Generate

1. **Invoice email** — sent when a new invoice is created/sent
2. **Friendly reminder** — sent before or on due date
3. **Overdue notice** — sent after due date, escalating urgency
4. **Payment confirmation** — "thank you, we received your payment"

## Scope

### Phase 1 (MVP — small)
- Single "Generate" button per template textarea
- Fixed prompt template, no style input
- Uses whatever LLM API is cheapest/available (Claude Haiku, GPT-4o-mini, Gemini Flash)
- Client-side: button → fetch to new API endpoint → populate textarea
- **Estimate: 1-2 hours of work**

### Phase 2 (Polish)
- Style description input ("describe your tone")
- Tone preset buttons
- "Regenerate" with variation
- Preview with sample data rendered (show what it'll actually look like)
- **Estimate: 3-4 hours**

### Phase 3 (Advanced)
- Generate all 4 template types at once ("Set up my email voice")
- Learn from edits (if owner consistently removes a phrase, stop suggesting it)
- A/B test templates (track open rates if email tracking is implemented — see invoice-email-tracking proposal)
- **Estimate: 1-2 days**

## Technical Implementation

### New API Endpoint
```
POST /api/billing/generate-email-template/
{
    "template_type": "reminder",  // "invoice", "reminder", "overdue", "confirmation"
    "style_description": "friendly, we're a family business in Arkansas",
    "shop_name": "Rockstar Windshield Repair"
}
→ { "template": "Dear {customer_name},\n\n..." }
```

### LLM Prompt (example)
```
You are writing an email template for a small auto glass repair shop.

Shop name: {shop_name}
Template type: payment reminder
Style: {style_description or "professional and friendly"}

Available placeholders (use these exactly):
- {customer_name} — customer's company name
- {invoice_number} — e.g., INV-1-20260321
- {total} — invoice total, e.g., $250.00
- {amount_due} — remaining balance
- {due_date} — e.g., April 20, 2026
- {days_overdue} — number of days past due
- {company_name} — the shop's name

Write a complete email body. Keep it under 200 words.
Do not include a subject line.
Use the placeholders where appropriate — they'll be replaced with real data.
```

### API Key / Cost
- Claude Haiku or Gemini Flash: ~$0.001 per generation
- Even at 100 generations/day across all tenants: $3/month
- Could use RS Systems' own API key or let tenants bring their own (v3)

## Risk

- **Low risk.** This is purely UI assistance — the owner always reviews and saves manually
- No PII sent to LLM (just shop name and style preference)
- Templates are stored in BillingConfig, same as manual entry
- If the LLM API is down, the button just shows an error — manual entry always works
- Rate limit: max 10 generations per tenant per day (prevent abuse)

## Why This Matters

Email is the primary touchpoint between a shop and their fleet customers. A well-written, branded reminder email is the difference between getting paid in 15 days vs. 45 days. Most small shops don't have the time or skill to craft good emails — giving them AI assistance makes RS Systems feel like it has a marketing team built in.

This is also a natural upsell differentiator: free tier gets defaults only, paid tiers get AI template generation.
