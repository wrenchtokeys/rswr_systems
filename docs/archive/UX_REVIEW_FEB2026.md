# UX Review — February 2026

*Reviewed by: Amelia*
*Date: February 25, 2026*
*Scope: Full app walkthrough — all four roles (Tech, Owner, Manager, Customer)*

---

## 🔧 Technician Portal (`/tech/`)

**What's working well:** Dashboard has solid quick actions up top, work summary stats, and a notification bell. Repair creation with multi-break support is a nice power feature. Viscosity recommendation system is thoughtful.

### Suggestions

#### 1. Mobile-First Repair Entry Wizard ⭐ HIGH PRIORITY
Techs are in parking lots and truck yards. The repair form is 670–783 lines — that's a LOT of scrolling on a phone. Break it into a stepper/wizard:

**Customer → Vehicle/Unit → Damage Details → Photos → Pricing → Submit**

Each step fits one screen. Progress bar at top. Back/Next buttons. Auto-save between steps.

#### 2. "Start My Day" Work Queue ⭐ HIGH PRIORITY
Techs should see their assigned work for today in priority order — not a generic dashboard. Think: a simple queue. Tap the top card, do the job, mark done, next. Like a delivery driver app.

#### 3. Faster Photo Capture
Before/after photos are proof of work. Current image upload fields should use the device camera directly (`capture="environment"` on the input element). Ideal flow: tap a big camera button → snap → auto-attach. Don't make techs browse their file system.

#### 4. Offline / PWA Support (Future)
Mobile glass techs often work in areas with spotty signal (truck yards, rural). Consider a Progressive Web App with service worker for offline repair entry that syncs when connection returns.

#### 5. Prominent "Collect Payment" Button
`tech_collect_payment` exists but there's no prominent button on the repair detail after completion. Cash/check collection should be one tap from the completed repair screen.

#### 6. Route / Schedule View (Future)
If a tech has 5 jobs across a metro area, they need a map or at least an ordered list with addresses. This is the #1 thing that makes a tech love or hate a field service app.

---

## 👔 Owner Portal (`/owner/`)

**What's working well:** Revenue summary, trial banner with urgency, plan badges, invoice management, tax rate management — all the right building blocks for a business owner.

### Suggestions

#### 7. Profitability / P&L View
Owner sees revenue but not costs. Even a simple "revenue minus tech payouts" would be valuable. Glass shop owners live on margins.

#### 8. Customer Health Dashboard
Which customers are growing? Which are declining? Two simple lists:
- **Top customers by revenue** (this month / last 90 days)
- **Customers with no repairs in 30+ days** (churn risk)

#### 9. Batch Invoice Generation ⭐ HIGH PRIORITY
BILLING_ROADMAP Phase 6 (batch invoicing) is TODO. This is a blocker for shops with 20+ fleet customers — nobody wants to generate invoices one at a time.

#### 10. Tax Rate Auto-Suggest by ZIP
Owner currently adds state+county+city rates manually. Even a "look up by ZIP code" that pre-fills would save time and reduce errors.

#### 11. Settings Hub with Status Indicators
Team, billing, tax, viscosity rules are all separate pages. A settings hub showing status ("3 team members active", "Tax: enabled, 2 rates configured") gives owners confidence their setup is complete.

---

## 👷 Manager Portal (shared with owner, `/tech/settings/`)

### Suggestions

#### 12. Scope Owner Dashboard by Role
Managers route to `owner_dashboard` which shows revenue and billing info. Do managers need billing access? Consider showing/hiding dashboard sections based on role. Managers should focus on: tech performance, work assignment, customer approvals.

#### 13. Work Assignment UI
`can_assign_work` exists on the Technician model, but there's no assignment UI. Managers should see unassigned repairs and assign them to available techs in a few clicks — even a simple dropdown per repair row would help.

#### 14. Elevate Team Management
Team overview is at `/tech/settings/team/` — buried under settings. Managing the team is a manager's core job; it should be a top-level nav item for that role.

---

## 🏢 Customer Portal (`/app/`)

**What's working well:** Clean layout, approval/deny flow, invoice viewing and Stripe payment, team management, rewards/referrals, multi-unit repair request, replacements section.

### Suggestions

#### 15. Simplify Navigation for Fleet Managers
Seven nav items (Dashboard, My Repairs, Replacements, Request Repair, Invoices, Rewards, Team) is a lot. Fleet managers want: "What needs my attention?" Consolidate the dashboard: pending approvals at top, recent activity, outstanding invoices — all on one screen.

#### 16. Unit Picker for Repeat Customers
If EOS Trucking has 50 trucks, they should pick from known units (autocomplete from fleet), not re-enter vehicle info each time. The "restore data from previous session" feature is nice, but a fleet unit picker would be better.

#### 17. One-Click Approval Deep Links ⭐ HIGH PRIORITY
Notification emails should include a tokenized one-click approve/deny link. Fleet managers are busy — requiring login → navigate → find repair → click approve has too much friction. A secure token link that lets them approve from their inbox would dramatically improve response times.

#### 18. Reduce Invoice Payment Friction
Customer flow: invoices list → detail → pay → Stripe. For overdue invoices, the dashboard should show a prominent "Pay $X Now" button that goes straight to Stripe checkout.

#### 19. Repair History Export
Fleet customers need to report repair costs to accounting. A simple CSV/PDF export of repairs by date range would be high-value, low-effort.

---

## 🌐 Cross-Cutting Issues

#### 20. Consolidate Base Templates
Two separate base templates (`base_app.html` for tech/owner, `base_customer.html` for customer) duplicate Tailwind config, font loading, and similar-but-different navbars. This leads to visual drift. Consider a single `base.html` with role-conditional navigation.

#### 21. Compile Tailwind CSS ⭐ HIGH PRIORITY
Multiple templates load `cdn.tailwindcss.com` with their own `tailwind.config` objects. This means:
- No tree-shaking (larger payload)
- Config drift between templates
- Slower page loads

Should build Tailwind once and serve a compiled CSS file.

#### 22. End-to-End Onboarding Audit
Login is unified (good!), but onboarding diverges:
- Shop owners → `/onboarding/`
- Customers → `/app/register/` or `/join/<slug>/`
- Techs → admin registration

Each happy path should be documented and tested E2E. Likely edge cases where someone falls through.

#### 23. Loading States / Optimistic UI
Forms submit synchronously with full page reloads. For mobile techs especially, a spinner or skeleton screen during submission would prevent double-submits and reduce perceived latency.

#### 24. Notification Preferences Discovery
Both tech and customer portals have notification preferences pages, but they're only reachable via direct URL — no prominent links in nav or settings. Users who don't discover them will get all notifications and eventually tune out.

---

## 🎯 Top 5 Priorities

| Priority | Item | Impact |
|----------|------|--------|
| 1 | ✅ Mobile wizard for repair entry (#1) | Where techs live — daily usability |
| 2 | ✅ One-click approval deep links (#17) | Removes biggest customer friction |
| 3 | ✅ Daily work queue for techs (#2) | Makes app feel like a tool, not a database |
| 4 | Batch invoicing (#9) | Blocker for scaling beyond a few customers |
| 5 | Compiled Tailwind (#21) | Technical debt that worsens with every template |

## Implementation Log

### Feb 25, 2026 — First pass (Amelia)

**✅ #2 — Today's Work Queue** (`feature/tech-work-queue`)
- Added priority-ordered queue to tech dashboard (IN_PROGRESS → APPROVED → PENDING)
- Color-coded status bars and action buttons (Continue / Start / View)
- Collapsible overflow for 5+ items, empty state with coffee emoji
- Files: `views/dashboard.py`, `templates/technician_portal/dashboard.html`

**✅ #17 — One-Click Approval Links** (`feature/one-click-approvals`)
- `ApprovalToken` model: UUID4, 72hr expiry, single-use, paired (approve+deny)
- Token pair auto-generated in `_notify_pending_approval` signal
- `/app/quick-approve/<token>/` and `/app/quick-deny/<token>/` — no login required
- Confirmation pages show repair details before final POST action
- Email template updated with big green Approve / red Deny buttons
- Migration: `0010_add_approval_token`

**✅ #1 — Mobile Repair Wizard** (`feature/repair-wizard`)
- 6-step wizard: Customer → Vehicle → Damage → Photos → Pricing → Review
- Progress bar with step dots, sticky Back/Next buttons
- Camera capture with `capture="environment"` for direct phone camera
- Photo preview thumbnails, draft auto-save to localStorage (24hr)
- Viscosity auto-suggestion on temperature input
- Review step with per-section Edit buttons
- Old form preserved as `repair_form_legacy.html`
