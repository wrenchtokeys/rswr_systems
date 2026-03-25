# RS Systems — TODO & Feature Gaps

*Things the system doesn't have yet, organized by priority.*
*Last Updated: March 25, 2026*

---

## 🔴 Missing Features (Needed for Real Shops)

### Warranty System
- **Gap:** No way to track warranty periods on repairs or handle warranty claims
- **What's needed:**
  - Warranty period per repair (e.g., "lifetime on chip repairs", "1 year on replacements")
  - Configurable per tenant (owner sets their warranty policy)
  - When a customer calls back about a repair failing, tech can look up the original repair and see if it's still under warranty
  - Warranty claim creates a new repair linked to the original, flagged as warranty (no charge)
  - Warranty repairs shouldn't generate invoices
  - Reporting: how many warranty claims per month, which techs have highest warranty rate
- **Proposal needed:** Yes

### Customer Communication Log
- **Gap:** No record of calls, texts, or conversations with customers
- **What's needed:** Simple activity log per customer — "Called re: unit 4482, will schedule for Thursday"
- Shop owners and techs currently track this in their heads or text messages

### Scheduling / Calendar
- **Gap:** No scheduling — repairs have a date but no calendar view, no time slots, no route planning
- **What's needed:** At minimum a daily view showing who's going where
- Drake said no /schedule page for Rockstar site, but the SaaS product needs this eventually

### Estimates / Quotes
- **Gap:** No formal quote/estimate workflow before a repair
- **What's needed:** Generate a quote, send to customer, customer approves → converts to repair
- Currently: customer requests repair → tech shows up → invoices after. No quote step.

---

## 🟡 Approved / In Progress

### Loyalty System Phases 2-4
- **Phase 2:** Engagement hooks (early payment bonus, review bonus, manual adjustments, expiry management command)
- **Phase 3:** Tiers (Pro-only — configurable Bronze/Silver/Gold/Platinum with point multipliers)
- **Phase 4:** Dashboards (customer loyalty view, owner analytics, liability report)
- **Status:** Phase 1 shipped. Drake approved. Phases 2-4 queued.
- → `docs/proposals/loyalty-system-overhaul.md`

### Review Request System
- **Status:** Proposal written, awaiting approval
- Smart Google review requests after repair completion, throttled by customer type
- → `docs/proposals/review-request-system.md`

### Website Integration Widget
- **Status:** Proposal written, awaiting approval
- Embeddable quote form for shop websites → auto-creates customers + repairs
- → `docs/proposals/website-integration-widget.md`

### Stripe Connect Phase 3 — Dashboard
- **Status:** Connect is live, dashboard (payout history, balance, fee reporting) still pending
- → `docs/proposals/stripe-connect-implementation-plan.md`

---

## 🟢 Proposed (Awaiting Review)

| Proposal | What It Does | Doc |
|----------|-------------|-----|
| Repair Form Efficiency | 12 ideas for faster repair entry | `proposals/repair-form-efficiency.md` |
| AI Plan Recommendation | Suggest plans based on trial usage | `proposals/ai-plan-recommendation.md` |
| Customer Billing Preferences | Payment terms on customer create form | `proposals/customer-billing-preferences-ux.md` |
| Reward Redemption UX | Better redemption modal (partially done) | `proposals/reward-redemption-ux-overhaul.md` |
| Invoice Email Tracking | Open/click tracking on invoices | `proposals/invoice-email-tracking.md` |
| AI Email Template Assistant | AI-generated emails per shop | `proposals/ai-email-template-assistant.md` |
| Competition Pool | Gamification between techs | `proposals/competition-pool.md` |

---

## 🔵 Infrastructure / DevOps

### Sentry Error Tracking
- Integration wired in code, just needs `SENTRY_DSN` env var
- Would catch 500s instantly instead of waiting for user reports

### Tailwind CDN → Production Build
- Loading from cdn.tailwindcss.com (shows console warning, slower)
- Need to bundle via PostCSS or Tailwind CLI

### CI/CD Pipeline
- No automated tests on PR — I run tests locally before merge
- GitHub Actions workflow would catch regressions automatically

### Test Coverage Gaps
- Customer portal views: 30+ views, only ~16 tests
- ConnectService payment routing: lightly tested
- 8 pre-existing test failures in test_step5_nav / test_step3_signup / test_rewards / test_user_flow

---

## 📋 Backlog (Someday)

- **QuickBooks integration** — export invoices, sync customers
- **QR code on PDF invoices** — scan-to-pay from printed invoices
- **SMS notifications** (Twilio) — fleet managers prefer texts
- **Multi-location support** — one tenant, multiple shop locations
- **PWA / offline mode** — techs in areas with no signal
- **Mobile native app** — React Native
- **AI damage assessment** — auto-classify damage type from photos
- **White-label branding** — custom colors/logo per shop beyond just name
- **API for third-party integrations** — let shops connect other tools
- **Lot walking scheduler** — route optimization for parking lot jobs
- **Vehicle history** — see all repairs for a specific VIN across time
- **Parts inventory** — track resin, blades, seals (probably overkill for most shops)

---

## How This Works
- Missing features go here when discovered
- If it needs design, write a proposal in `docs/proposals/`
- Drake approves via chat or PR before any building starts
- Shipped items get moved to CHANGELOG.md and removed from here
