# RS Systems — Improvement Sessions

**Created:** 2026-08-07
**Author:** Amelia (from a live walkthrough of the running app)
**Status:** Proposed — pending Drake's review
**Companion to:** `docs/strategy/PRODUCT_DIRECTION.md` (June 2026). This document does not
supersede it; it adds an execution layout and adds two strategic items that document omits
(insurance/TPA billing, NAGS).

---

## What this document is

A prioritized backlog of everything worth improving in RS Systems, written so that **each
session is a self-contained unit of work that a fresh AI (or a fresh you) can pick up cold**
without reading the other sessions or re-deriving the findings.

Every session carries:

| Field | Meaning |
|---|---|
| **Goal** | One sentence. What "done" means. |
| **Size** | XS (<1h) · S (half day) · M (1–3 days) · L (1–2 weeks) · XL (a month+) |
| **Depends on** | Sessions that must land first, or `—` |
| **Why it matters** | The business reason. Read this before deciding to skip it. |
| **Verified current state** | What I actually observed, with `file:line` anchors. Trust these; they were checked against the code, not remembered. |
| **Considerations** | Tradeoffs, gotchas, and things that will bite you. |
| **Decisions needed** | Questions only Drake can answer. If unanswered, the session is blocked or must proceed on a stated assumption. |
| **Acceptance criteria** | Checkable. |
| **Out of scope** | Explicit, to stop scope creep. |

### How a fresh AI should use this

1. Read **§0 Context Primer** (below) — that's the minimum shared context.
2. Read **only the one session** you've been assigned.
3. Read **Appendix A** before reporting any bug you think you found — three plausible-looking
   bugs in an earlier pass turned out to be artifacts of seeded test data, and they're listed
   there so nobody chases them again.
4. Use **Appendix B** to stand up a running app with realistic data.

Do not read the whole document to do one session. That is the entire point of the format.

---

## §0 Context Primer

*(~400 words. Everything a session needs to know about the product that isn't in `CLAUDE.md`.)*

RS Systems is a multi-tenant Django SaaS for auto glass shops. Three audiences use it:

- **Shop owner / manager** — `/owner/…`, templates in `templates/saas/`, shell `base_app.html`.
  Runs the business: jobs, customers, invoices, loyalty, settings, plan.
- **Technician** — `/tech/…`, templates in `templates/technician_portal/`, same shell.
  Mostly on a phone in the field. Logs and completes jobs.
- **Fleet/retail customer** — `/app/…`, templates in `templates/customer_portal/`, shell
  `base_customer.html`. Approves work, requests service, pays invoices.

Plus a **public marketing surface**: `templates/landing.html`, `templates/saas/pricing.html`,
signup, and the public invoice-pay page.

**Two job types**, both subclassing the abstract `GlassService`
(`apps/technician_portal/models.py:275`):
- `Repair` — chip/crack. Progressively priced ($50→$40→$35…) per unit via `UnitRepairCount`.
- `Replacement` — full glass. Priced as `parts_cost + labor_cost`, hand-entered.

**Status flow:** `REQUESTED → PENDING → APPROVED → IN_PROGRESS → COMPLETED`. Shop-created
work auto-approves; customer-portal requests enter as `REQUESTED`.

**What the product does well today** (do not "fix" these — they are the good parts):
the single job form at `/tech/jobs/new/`, the tech's mobile queue, the Uninvoiced Completed
Work panel on `/owner/invoices/`, the settings checklist, tenant-scoped invoice branding.

**What does not exist at all** (verified by model inventory — do not go looking):
no `Quote`/`Estimate` model, no `Appointment`/`Schedule`/calendar model, no inventory or
purchase orders, no parts catalog, no timesheets, no commission tracking, no two-way
messaging, no communication log.

**What exists but is inert:** insurance fields on `GlassService`
(`apps/technician_portal/models.py:381–398`: `insurance_claim`, `insurance_company`,
`claim_number`, `deductible`, `authorization_number`) are captured and displayed but drive no
workflow. `Replacement.nags_number` (`:1516`) is free text with no catalog behind it.
`core/services/sms_service.py` sends outbound SMS via AWS SNS; nothing receives inbound.

**Strategic frame used throughout:** RS Systems is currently a *very good job-tracking and
invoicing tool*. It is not yet *load-bearing* — a shop can cancel it tomorrow and still get
paid, because money and customer communication flow through their insurance biller and their
phone, not through RS Systems. Sessions are ranked by how much they move that needle.

---

## §1 The strategic fork (read before sequencing anything)

There are two coherent products here and they want different roadmaps. This is the one
decision that changes everything downstream.

**Path A — "Simplest thing that works" (current stated positioning).**
Target: 1–5 tech shops running on sticky notes, texts, and Excel. Win on being *pleasant and
obvious*. Compete against paper, not against GlasPacLT. Ceiling: a real business, modest ACV,
churn risk whenever a shop grows past you.

**Path B — "System of record."**
Target: established shops doing insurance/TPA volume. Win by being where the money flows.
Requires insurance/TPA billing (D1) and NAGS pricing (D2) — 6–12 months and a data licensing
bill. Ceiling: genuinely un-leavable, much higher ACV, and the "industry standard" outcome.

**They are not mutually exclusive in the long run, but they are in the next two quarters.**
Tracks A, B and C below are valuable on *either* path — do those regardless. Track D is
Path B only, and each Track D session starts with a decision memo, not code.

My recommendation: **run Tracks A → B → C now** (they are all "would have done anyway" work),
and use that time to answer D1's market question by talking to five shops that do insurance
volume. Decide Path B on evidence, not on ambition.

---

## Track A — Craft & coherence

*Small, independent, low-risk. These are what separate "nice software" from "software that
feels expensive." Any of them can be done in isolation, in any order.*

---

### A1 · Unify the button/color system

**Goal:** One visual language for actions. A primary action looks the same everywhere.
**Size:** M · **Depends on:** —

**Why it matters.** Right now blue and green *both* mean "primary," which means neither means
anything. On the technician dashboard's Quick Actions card, three stacked buttons are green
(*New Job*), blue (*Multi-Break Entry*), and green-outline (*View All Jobs*) — one card, three
treatments, no logic. "New Job" is blue on `/tech/jobs/`; "New Customer" is green on
`/tech/customers/`. A prospect can't articulate why the app feels less polished than it is;
this is a large part of why.

**Verified current state.**
- A component layer exists: `static/css/src/input.css:58–73` defines `.btn-primary`,
  `.btn-secondary`, `.btn-danger`, `.btn-ghost`, `.btn-sm`, `.btn-lg`. There is **no**
  `.btn-success` — yet green buttons are everywhere, built ad-hoc.
- Usage across `templates/`: `btn-primary` ×67, `btn-secondary` ×51, `btn-danger` ×9 — but
  raw `bg-blue-600` ×120 and raw `bg-green-600` ×60. **The ad-hoc utilities outnumber the
  component classes roughly 2:1.** The design system exists and is losing.

**Considerations.**
- Decide *semantics first, colors second*. A defensible rule: **blue = primary/navigational,
  green = money/completion (Complete, Mark Paid, Save & Send Invoice), red = destructive,
  grey = secondary.** Under that rule most current green buttons are wrong and should be blue.
- Do **not** start by mass-replacing `bg-blue-600` → `btn-primary`. Sweep **one surface at a
  time** (tech dashboard, then jobs, then customers, then invoices, then settings, then
  portal), building each screenshot into the review. A global find-replace will silently
  restyle badges, links, and nav-active states that legitimately use the same utility.
- `brand_color` per tenant already overrides portal colors via `--brand-N` CSS variables
  (`apps/tenants/branding.brand_shades`). The **owner/tech app is not tenant-branded** and
  shouldn't be — keep the RS palette there. Only the portal follows the shop's color.
- Every template/JS class change requires `./scripts/build_css.sh` and committing
  `static/css/app.css`. Dynamically composed classes must be safelisted in
  `tailwind.config.js` or purge drops them.

**Decisions needed.** Confirm the blue/green semantic rule above, or supply your own.

**Acceptance criteria.**
- A documented rule in `docs/development/UI_DESIGN_GUIDE.md` stating what each color means.
- `.btn-success` either added (if green is a real semantic) or explicitly rejected in the doc.
- Raw `bg-blue-600`/`bg-green-600` on *button elements* reduced to near zero; badges, links,
  and nav states may keep utilities.
- Tech dashboard Quick Actions renders one primary + two secondaries.

**Out of scope.** Typography, spacing scale, icon set, dark mode.

---

### A2 · Customer-facing display bugs

**Goal:** No customer ever sees a null, a raw enum, or a placeholder.
**Size:** XS · **Depends on:** —

**Why it matters.** These are cheap and they're on the surface a paying fleet customer looks
at. One of them literally prints the word "None."

**Verified current state.**
1. **`None` rendered to customers.** `templates/customer_portal/dashboard.html:241` and `:264`
   render `{{ service.description|truncatechars:50 }}` with no `|default`. `description` is
   `TextField(blank=True, null=True)` on `GlassService`. A shop that creates a replacement
   without typing a description shows the customer:
   `Windshield — None`. This is a genuine product bug, reproducible without odd data.
2. **Inconsistent enum rendering.** `templates/customer_portal/repair_detail.html:80` uses raw
   `{{ repair.damage_type }}`; every other template uses `get_damage_type_display`
   (`batch_detail.html:62`, `repair_approve.html:88`, `repair_deny.html:89`,
   `batch_approve_confirm.html:29`, `batch_deny_confirm.html:29`). Harmless *today* because
   `DAMAGE_TYPE_CHOICES` keys happen to equal their labels
   (`apps/technician_portal/models.py:663–672`) — but it breaks the moment anyone shortens a
   key, and it's an inconsistency a reviewer will flag.
3. **Unit number missing from the portal home screen.** `dashboard.html:241/:264` lead with the
   description; `/app/services/` correctly leads with `Unit 7955`. Result: a fleet manager
   landing on the portal home sees "Rock chip, driver side lower" three times identically and
   cannot tell which truck is which. For a fleet account the unit number *is* the identity.

**Considerations.**
- For (1), prefer a real fallback over an empty string — `{{ service.description|default:"Glass
  service" }}` reads better than a dangling em-dash. Check the em-dash separator logic too:
  when description is blank the `—` should disappear, not trail.
- For (3), the fix is a template reorder, but confirm `unit_number` is populated for
  retail/individual customers (it often isn't — it's a fleet concept). Fall back to
  year/make/model, then to the description.
- Add a regression test under `tests/bug_fixes/` per the existing convention.

**Decisions needed.** None.

**Acceptance criteria.** A replacement with `description=None` and a repair with a blank
description both render cleanly on `/app/` and `/app/services/`. Portal home leads with unit
number (or vehicle) when available. `repair_detail.html:80` uses the display method.

**Out of scope.** Redesigning the portal home layout (see B4).

---

### A3 · Shop-branding fallback in the customer portal

**Goal:** A shop with no uploaded logo still looks like *that shop*, not like RS Systems.
**Size:** XS · **Depends on:** —

**Why it matters.** The portal is the shop's brand surface in front of *their* customer.
Custom branding is a paid Pro feature; the free-tier fallback currently advertises us instead.

**Verified current state.** `templates/customer_portal/base_customer.html:40–50`. When
`request.tenant.logo` is set, the shop's logo renders correctly — branding works. When it is
**not** set, the fallback is a hardcoded `RS` monogram in a `bg-brand-500` square, sitting next
to the shop's name. The footer's "Powered by RS Systems" (`:190`, `:298`) is fine and
deliberate; the header monogram is not.

**Considerations.**
- Correct fallback: the shop's own initial(s) derived from `tenant.name`, on the tenant's
  `brand_color` background. Same visual weight, zero RS branding above the fold.
- Two-letter initials from multi-word names ("Clearview Auto Glass" → `CA`) read better than
  one letter. Watch single-word shop names and non-ASCII.
- Also check the mobile/off-canvas nav (`:184–187`) which has the same fallback pattern.
- Keep the footer attribution — that's intentional product marketing and costs nothing.

**Decisions needed.** Confirm the footer "Powered by RS Systems" stays on all plans (I'd keep
it; it's a lead source).

**Acceptance criteria.** A tenant with `logo=None` and `brand_color` set shows their initials
on their brand color in the portal header and mobile nav. No `RS` string above the footer.

**Out of scope.** Logo upload UX, custom domains, email template branding (already correct).

---

### A4 · De-duplicate the technician dashboard

**Goal:** One job appears once, in one place, with the right next action.
**Size:** S · **Depends on:** —

**Why it matters.** The tech dashboard is the most-used screen in the product and it currently
shows the same jobs twice with two different verbs. That's confusing on desktop and actively
wasteful on a phone, where it means scrolling past a list you already saw.

**Verified current state.**
- `templates/technician_portal/dashboard.html:46` — "Today's Queue," first 5 items visible,
  rest hidden behind `queue-overflow-item`. Action button is *Continue* (IN_PROGRESS) or
  *Start* (APPROVED).
- `templates/technician_portal/dashboard.html:422–426` — a separate "🔧 In Progress" card,
  further down, listing **the same IN_PROGRESS jobs** with a *Complete* button.
- **"Today's Queue" is a misnomer.** It's ordered by service date and, on my seeded shop,
  contained jobs dated Jun 19, Jun 27 and Jul 6 while "today" was Aug 7. It is "my open
  jobs," not today's.

**Considerations.**
- Two defensible resolutions: (a) merge into one list where each row's button is
  status-appropriate (*Start* / *Continue* / *Complete*), or (b) keep two sections but make
  them genuinely disjoint ("In progress" vs "Not started"). (a) is simpler and better on
  mobile.
- Renaming: until scheduling exists (B1), the honest label is **"My Jobs"** or **"Open Work."**
  Once B1 lands, a real "Today" becomes possible and the rename should be revisited — flag
  this dependency in the commit message.
- The emoji in the `<h2>` (`🔧 In Progress`) is inconsistent with every other heading in the
  app, which uses Font Awesome icons. Drop it while you're in there.
- Preserve the overflow/"Show all" behavior — it's good.

**Decisions needed.** Merge vs. disjoint sections. I recommend merge.

**Acceptance criteria.** No job ID appears in two lists on `/tech/`. The heading does not claim
"today" unless the list is filtered to today. Mobile view fits the primary action without
horizontal overflow.

**Out of scope.** Adding address/phone to the card — that's B1.

---

### A5 · Self-host front-end assets

**Goal:** No third-party CDN in the request path.
**Size:** S · **Depends on:** —

**Why it matters.** `CLAUDE.md` already forbids the Tailwind CDN. The same reasoning —
offline/latency/privacy/availability — applies to the three CDNs still loaded on every page,
and it's inconsistent to ban one and keep three. A shop on bad rural connectivity (very common
for a mobile glass tech) feels this directly.

**Verified current state.**
- `templates/includes/head_assets.html` — Google Fonts (`fonts.googleapis.com`) and Font
  Awesome 6.4.0 (`cdnjs.cloudflare.com`). Loaded by **every** shell.
- `templates/base_app.html:8` (CSS) and `:219` (JS) — flatpickr from `cdn.jsdelivr.net`.
- Only three templates reference external CDNs: `base_app.html`, `head_assets.html`,
  `base_customer.html`.

**Considerations.**
- Font Awesome is the big one: the full `all.min.css` ships ~2,000 icons for the ~40 in use.
  Self-hosting a subset is a meaningful payload win, but subsetting requires care — icons
  referenced from JS strings or Django template variables won't be found by a static scan.
  **Safer first step: self-host the full package, then subset later with a verified icon
  inventory.**
- Fonts: self-host Inter with `font-display: swap` and preload the two weights actually used.
- flatpickr is only used for `input[type="datetime-local"]` enhancement (`base_app.html:221`).
  Worth asking whether it earns its weight at all — native mobile date pickers are good now,
  and this is a mobile-first app. Removing it may be better than vendoring it.
- No npm in this repo, by design. Vendor the files into `static/js/vendor/` and
  `static/css/vendor/` the way `driver.iife.js` already is.
- EB deploys `staticfiles` unchanged; manifest storage handles cache busting. Confirm the
  vendored files land in `collectstatic` output before deploying.

**Decisions needed.** Keep flatpickr or drop it?

**Acceptance criteria.** Zero external hostnames in `head_assets.html`, `base_app.html`,
`base_customer.html`. App renders correctly with the network blocked to non-origin hosts.

**Out of scope.** A build pipeline, bundling, or npm.

---

### A6 · Plan-limit upsell moment

**Goal:** Hitting a plan limit becomes an upgrade prompt, not a red bar.
**Size:** S · **Depends on:** —

**Why it matters.** This is free revenue. A shop that has outgrown its plan is the single
warmest upgrade lead you will ever have, and right now the product notices and says nothing.

**Verified current state.** Enforcement **does exist and works** —
`apps/tenants/services/usage_service.py` provides `can_create_repair`, `can_add_technician`,
`can_add_customer`, each returning `(ok, message)` with upgrade-flavored copy already written
(e.g. `:130` "Upgrade to Pro for unlimited jobs."). It's wired through
`apps/tenants/mixins.py:130` and `:221` (`PlanEnforcementMixin`).

The gap is **presentation, not enforcement**: the owner dashboard stat cards render a usage bar
that turns red when over limit ("Technicians 3 — of 2 on your plan") with **no link, no CTA,
and no explanation of what happens next.** The good copy in `usage_service` never reaches that
surface.

**Considerations.**
- Three distinct moments deserve different treatment: **approaching** (≥80% — soft nudge),
  **at limit** (blocked action — the existing message, plus a direct link to `/owner/billing/`),
  and **over limit** (grandfathered data from a downgrade — explain the state honestly).
- Over-limit-after-downgrade is the delicate one. Never imply their data is at risk. Say what
  is and isn't possible ("you can keep your 3 technicians; you can't add a 4th until you
  upgrade").
- Don't put a modal in the way. A dashboard card that turns into a CTA is enough.
- Check `SubscriptionPlan.max_*` for `None` = unlimited (`usage_service.py:124`, `:147`,
  `:170`) — an unlimited plan must render no bar at all, not a full one.

**Decisions needed.** Do you want a hard block at limit, or soft (warn + allow)? Current code
blocks. Note that hard-blocking a trial user mid-job is a churn risk.

**Acceptance criteria.** Every over-limit or near-limit stat card links to the plan page with
specific copy. The `usage_service` messages are used, not duplicated.

**Out of scope.** Changing plan limits or prices; the trial-expiry email campaign.

---

## Track B — Adoption features

*These remove the reason a shop says "this doesn't fit how we work." Bigger, sequenced.*

---

### B1 · Field dispatch: get the tech to the vehicle

**Goal:** A technician can go from the job list to the customer's door without leaving the app.
**Size:** M · **Depends on:** —

**Why it matters.** This is the most conspicuously missing thing in the entire product and it's
cheap. A tech on a phone currently sees `Unit 5422 · Penske Truck Leasing · $50.00` and has no
idea **where to go or who to call.** They switch to their contacts app and their maps app,
which means the phone — not RS Systems — is where their day actually lives. Fixing this is the
highest ratio of daily-felt value to engineering cost on the list.

**Verified current state.**
- The tech's job card (`templates/technician_portal/dashboard.html:55–110`) renders: customer
  name, unit number, service-type badge, status badge, cost, service date. **No address, no
  phone, no map link.**
- The data mostly exists already: `Customer.phone`, `.address`, `.city`, `.state`, `.zip_code`
  (`core/models/customer.py:75–84`).
- What's missing on the model: a **per-job service address**. Mobile glass work happens where
  the vehicle is, which is frequently *not* the customer's billing address (a fleet yard, a
  job site, a driveway). There is no field for this today.

**Considerations.**
- Scope this as **display + one new field**, not as scheduling. Deliberately no calendar here.
- Add `service_address` (and probably `service_city`/`service_state`/`service_zip`, or a single
  text field — prefer structured if you ever want mapping) to `GlassService` so both Repair and
  Replacement inherit it. Default/prefill from the customer's address; let the tech override.
- `tel:` and maps links are trivial and platform-specific. `https://maps.apple.com/?q=` and
  `https://www.google.com/maps/search/?api=1&query=` both work; a plain `geo:` URI is
  unreliable on iOS. Simplest robust choice: Google Maps universal URL, which opens the native
  app on both platforms.
- Tap targets: these go on a phone. 44px minimum, and don't put *Call* next to *Complete* —
  a misfire that completes a job is annoying to undo.
- Privacy: don't put customer addresses in URL query strings that get logged. Build the maps
  URL client-side from data already on the page.
- Watch the walk-in/individual case where there is no address at all — the card must degrade
  gracefully, not render an empty row.

**Decisions needed.** Structured address fields vs. a single free-text service address?
(Recommend structured — it's the foundation for any future routing/calendar work.)

**Acceptance criteria.** From `/tech/` on a phone: tap-to-call the customer, tap-to-navigate to
the service address, both one tap from the queue. A job with no address shows no broken UI. The
job form lets a tech set a service address different from the billing address.

**Out of scope.** Calendars, time slots, route optimization, ETA calculation, live tracking.

---

### B2 · Two-way SMS

**Goal:** The shop can text a customer from RS Systems, and the reply comes back into it.
**Size:** L · **Depends on:** B1 (nice-to-have, not hard)

**Why it matters.** Glass customers text. Right now every real conversation happens on a
personal phone, invisible to the shop owner and unrecorded against the job. "Marcus is on his
way, ETA 2:15" plus a photo of the finished windshield is the moment a small shop *feels*
professional — and it's the single biggest driver of review volume, which feeds the review
system you already built (`apps/technician_portal/review_service.py`). It also converts RS
Systems from a system of record into a system of *communication*, which is much harder to
cancel.

**Verified current state.** `core/services/sms_service.py` — AWS SNS, outbound only, E.164
validation, 160-char truncation, retry with backoff, per-message cost tracking
(`SMS_COST_PER_MESSAGE = 0.00645`), delivery logging to `NotificationDeliveryLog`. Invoked from
`core/services/notification_service.py:206–216` gated on
`preferences.receive_sms_notifications`. **There is no inbound path, no conversation model, and
no per-tenant phone number.**

**Considerations — read all of these before estimating; this is the session most likely to be
underestimated.**
- **SNS cannot do two-way.** Inbound SMS requires a provider with a real number and a webhook:
  AWS End User Messaging (formerly Pinpoint), Twilio, or Telnyx. This is a provider migration,
  not a feature flag. Note the org already has production SMS experience on another product
  (see the `rswr-sms-production-access` memory) — reuse that hard-won knowledge.
- **A2P 10DLC registration is mandatory** for US application-to-person SMS. Every tenant needs
  a registered brand and campaign, or carriers filter the messages. This has a per-tenant cost,
  a multi-day approval latency, and real paperwork. **It is the single biggest hidden cost of
  this session and it must be designed for, not discovered.** Decide early: one shared RS
  Systems number with the shop name in the message body (simpler registration, weaker
  branding), or a provisioned number per tenant (better experience, much heavier ops).
- **Opt-in and STOP/HELP handling are legal requirements**, not features. You need recorded
  consent per recipient, automatic STOP honoring, and an audit trail. TCPA exposure is real.
- **Cost changes shape.** Outbound notification SMS is a trickle; a conversation surface is a
  flood. Per-tenant metering and a plan limit will be needed, or margins erode silently.
- **Model work:** a `Conversation`/`Message` pair scoped to tenant + customer (+ optional job),
  with direction, provider message ID, and delivery status. This is also the natural home for
  the "customer communication log" named in `PRODUCT_DIRECTION.md` — build them as one thing,
  not two.
- Do **not** put photos in SMS (MMS pricing, deliverability). Send a link to the job page, the
  way invoices already link to the public invoice page.

**Decisions needed.** (1) Shared number or per-tenant number? (2) Which provider? (3) Is this
all-plans or a Pro+ feature (it has real marginal cost, which argues for gating)?

**Acceptance criteria.** A shop can send and receive texts with a customer from inside RS
Systems; the thread is visible to the owner and attached to the customer (and job where
relevant); STOP is honored automatically; per-tenant usage is metered.

**Out of scope.** WhatsApp, group messaging, AI-drafted replies, marketing blasts.

**Recommended first step.** A one-page decision memo answering the three questions above
*before* any code. This session has more product/legal surface than engineering surface.

---

### B3 · Quotes / estimates

**Goal:** Send a priced quote, get it approved, turn it into a job.
**Size:** L · **Depends on:** —

**Why it matters.** Named as an adoption blocker in `PRODUCT_DIRECTION.md` §Phase B. Fleet
procurement and every insurance-adjacent workflow require a formal estimate *before*
authorization. Without one, a whole class of shop bounces in the first demo. It is also the
natural precursor to D1 — an insurance claim is, structurally, a quote with a third-party
payer.

**Verified current state.** No `Quote` or `Estimate` model exists anywhere in the codebase
(confirmed against the full model inventory). The closest existing thing is
`Repair.is_multi_break_estimate` (`apps/technician_portal/models.py:707`), which is unrelated —
it flags a multi-break batch, not a customer-facing estimate.

**Considerations.**
- The approval machinery already exists and should be reused, not rebuilt: `ApprovalToken`,
  the quick-approve/deny confirm flow (`templates/customer_portal/quick_approve_*`), and the
  customer-portal approval views. A quote is a new record type flowing through proven rails.
- **Decide the relationship to `Repair`/`Replacement` up front.** Two options: (a) a separate
  `Quote` model that converts into a job on acceptance, or (b) a pre-`REQUESTED` status on the
  existing job models. (a) is cleaner (a quote can be declined, versioned, or expire without
  polluting job history and job counts) and is what I'd recommend — but it means duplicating
  line-item and pricing logic, so plan to extract that logic rather than copy it.
- Quotes must **expire**. Glass pricing moves. An accepted 90-day-old quote at last quarter's
  price is a real loss.
- Versioning: "here's a revised quote" is a normal interaction. Design for at least a
  supersede/replace relationship even if the UI is minimal.
- Reuse `BillingConfig.allocate_invoice_number()`'s row-locked pattern for quote numbering —
  do not hand-format numbers (see `CLAUDE.md`).
- Watch the interaction with progressive repair pricing: a quote for repair #3 on a unit prices
  differently than repair #1, and the count may change between quoting and doing the work.
  Decide whether a quote locks its price. (It should.)
- `PRODUCT_DIRECTION.md` flags that the customer portal has ~16 tests for 30+ views. This
  session builds directly on those views — **write portal integration tests first.**

**Decisions needed.** Separate `Quote` model or job status? Default expiry window? Does an
accepted quote auto-create the job, or does the shop still confirm?

**Acceptance criteria.** Shop creates a quote with line items → customer receives a branded
email → approves or declines in the portal → approval creates the job with the quoted price
locked → declined and expired quotes are visible and don't pollute job counts or revenue.

**Out of scope.** Insurance claim submission (D1), NAGS-priced line items (D2), e-signature.

---

### B4 · Make the customer page a command center

**Goal:** Every question an owner asks about a customer is answerable without leaving the page.
**Size:** M · **Depends on:** — (composes well with B2)

**Why it matters.** The customer page is where an owner lands when the phone rings. Today it
answers "who are they" and "what work have we done," but not the two questions actually asked
on that call: **"what do they owe me"** and **"what did we last tell them."** The page also has
a large empty right column at desktop width, so this is filling space that's already reserved.

**Verified current state.** `/tech/customers/<id>/` renders: name, type badge, email, phone,
address, primary technician selector, portal-access invite, rewards balance, and a job history
list. **Missing:** outstanding balance / AR, the customer's invoices, their vehicle and unit
roster, any notes or communication history, and lifetime value.

**Considerations.**
- **AR is the highest value addition** and the data already exists — `Invoice` is tenant- and
  customer-scoped, and the aging logic behind the "Owed to you" card on `/owner/invoices/` can
  be reused per-customer. Beware trashed and `PAID`/`CANCELLED` invoices, which the existing
  aging logic already excludes; match that behavior exactly or the two numbers will disagree
  and destroy trust in both.
- **The vehicle/unit roster matters enormously for fleets.** `Vehicle` is already FK'd to
  `Customer`. For a Penske with 40 trucks, the unit roster *is* the account. Include per-unit
  repair counts, since progressive pricing is per-unit (`UnitRepairCount`) and "what does the
  next repair on unit 5422 cost" is a real question owners ask.
- **A notes/communication log is the same object as B2's message thread.** If B2 is on the
  roadmap, build the model once and let this page render it. If B2 is deferred, a simple
  manual `CustomerNote` (timestamp, author, body) is still worth it and is ~2 hours.
- Beware query count. This page will fan out to invoices, vehicles, jobs, points, and notes.
  Use `select_related`/`prefetch_related` and check the query count in a test.
- Retail/individual customers need a different emphasis than fleets — no unit roster, no
  portal team. `Customer.customer_type` already distinguishes them; use it to vary the layout
  rather than showing empty cards.

**Decisions needed.** Does the notes log wait for B2, or ship standalone now?

**Acceptance criteria.** From the customer page: current balance and aging, invoice list with
status, vehicle/unit roster with per-unit repair counts, and a chronological activity log.
Retail customers don't see empty fleet-only cards. Page issues a bounded number of queries.

**Out of scope.** Editing invoices from this page; credit limits; statements (already exist at
`customer_statement.html`).

---

## Track C — Go to market

---

### C1 · Marketing site credibility

**Goal:** A shop owner who lands cold believes this is real software used by real shops.
**Size:** M · **Depends on:** —

**Why it matters.** The site is clean and the copy is good, but it currently *undersells the
product and oversells the traction* — exactly backwards. The best asset (a working, genuinely
well-designed app, built by an actual shop owner) is nearly invisible, while the weakest
material (small numbers, filler stats) is above the fold.

**Verified current state — `templates/landing.html`.**
- **The trust bar (`:195–219`) hurts more than it helps.** Four stats: "500+ Jobs Tracked,"
  "$50K+ Invoiced," "100% Mobile Friendly," "24/7 Access Anywhere." The last two are not
  statistics, they're padding — and a visitor notices. The first two are small enough to read
  as "brand new, nobody uses this." Advertising modest scale is worse than advertising none.
- **The hero product shot (`:120–190`) is a hand-built HTML mock**, not the real app — a fake
  browser chrome with hardcoded "$8,420.00" and "47 repairs." The real owner dashboard is
  *better looking than the mock*. This is the single strangest choice on the page.
- **One testimonial, and it's the founder** (`:353–368`). No customer proof anywhere.
- **Nothing addresses switching.** No migration/import story, no "moving from GlasPac or
  spreadsheets," no comparison content. Switching cost is the #1 objection in this market and
  the site is silent on it.
- No demo video, no interactive sandbox, no way to see the product without signing up.

**Considerations.**
- **Cut the trust bar entirely** rather than inflate it. Replace with the founder story, which
  is your one asset the incumbents structurally cannot copy — and move it *up*, not down.
- Replace the mock with real screenshots. Cheapest credible version: 3–4 clean captures of the
  actual owner dashboard, job form, and customer portal on a phone. (A seeded demo tenant makes
  these easy to produce and re-shoot — see Appendix B.)
- A **read-only demo login** is the highest-converting asset you could add and needs no new
  marketing copy. It also demos the product's real strength, which is that it's pleasant to
  use. Requires care: a shared demo tenant with reset-on-schedule and writes disabled.
- Do not claim customer counts you don't have. "Built by a shop owner, used in his own shop
  every day" is both true and stronger than "500+ jobs."
- Structured data (`:21–38`) already declares `AggregateOffer` 0–249. Keep it in sync with
  actual plan pricing or it's a rich-snippet liability.

**Decisions needed.** Are you willing to stand up a public demo tenant? Do you have any shop
besides your own and your dad's that would give a quote?

**Acceptance criteria.** No filler statistics. Real product imagery. Founder story above the
fold. At least one page or section addressing "how do I switch."

**Out of scope.** SEO content programs, paid acquisition, the embeddable lead widget (already
proposed in `docs/proposals/website-integration-widget.md`).

---

### C2 · Pricing page correctness audit

**Goal:** The comparison table tells the truth, and the plan ladder justifies its own prices.
**Size:** XS · **Depends on:** —

**Why it matters.** A prospect comparing plans is the highest-intent visitor on the site. Two
things on that table are working against the sale.

**Verified current state.**
1. **The "Customer portal" row may render as "not included" on every plan.**
   `templates/saas/pricing.html:129` gates on `{% if plan.features.customer_portal %}`.
   `apps/tenants/management/commands/seed_plans.py` sets `'customer_portal': True` on all four
   plans (`:34`, `:55`, `:76`, `:97`) — **but it skips plans that already exist** ("Skipped
   'enterprise' — already exists (use --force to update)"). On a database where plans were
   created by an earlier migration seed rather than by this command, the `features` JSON has no
   `customer_portal` key at all and the row renders a dash for Starter, Pro **and** Enterprise.
   I reproduced this on a fresh local DB: all four plans' `features` contained only
   `rewards`, `invoicing`, `api_access`, `custom_branding`, `priority_support`.
   **Production may or may not be affected** — a fetch of the live pricing page shows the
   Support row *is* correctly differentiated ("Email support" / "Priority email support"),
   which suggests prod plan data is newer than my local seed. The check-mark icons can't be
   read from the fetched markup. **Action: open `https://rssystems.io/pricing/` in a browser
   and look at the Customer portal row before doing anything else.** If it shows dashes, the
   flagship differentiator currently reads as unavailable on every plan.
2. **Support tiering is flattened locally.** All three plans showed "Email support" on my local
   DB despite `priority_support: true` existing on the `enterprise` plan's features JSON. Prod
   appears correct. Same root cause as (1) — stale plan rows.

**Considerations.**
- The real fix is **not** editing the pricing template. It's making plan feature data
  authoritative and drift-proof: either a data migration that merges missing keys into existing
  plans, or making `seed_plans` idempotently upsert feature keys instead of skipping whole
  rows. Prefer the latter — it prevents recurrence.
- Any new plan feature key added to `seed_plans` in the future will hit exactly this bug again
  unless the skip behavior changes. That's the actual defect.
- While in here: `landing.html` plan cards say "200 jobs a month" while the compare table says
  "Repairs per month: 200." Jobs and repairs are different things in this product (replacements
  are jobs too). Pick one word and use it in both places — this ambiguity has a real billing
  implication a customer could dispute.
- Add a smoke test asserting every plan's `features` dict contains every key the pricing
  template reads. Cheap, and it makes this class of bug impossible.

**Decisions needed.** None — but verify production first.

**Acceptance criteria.** Every feature row on `/pricing/` reflects reality on prod. Running
`seed_plans` twice produces plans with a complete feature set. A test fails if the template
reads a key no plan defines. "Jobs" vs "repairs" is consistent between landing and pricing.

**Out of scope.** Changing prices or plan structure.

---

## Track D — Strategic bets (Path B only)

*Do not start these as engineering work. Each begins with a decision memo. Both are gated on
the §1 fork.*

---

### D1 · Insurance / third-party billing

**Goal (eventual):** A shop can bill a TPA from inside RS Systems.
**Size:** XL · **Depends on:** §1 decision, and realistically B3

**Why it matters.** This is the honest answer to "why can't a shop afford to leave?" A large
share of retail auto glass revenue is billed not to the driver but to a third-party
administrator — Safelite Solutions, LYNX Services, and similar — over EDI. Until a shop can
submit from RS Systems, RS Systems is permanently a *second* system alongside the one they
actually get paid through. Second systems get cancelled in the first budget review. This is the
single largest determinant of whether RS Systems becomes industry-standard or stays a good
small-shop tool.

**Verified current state.** The data model already anticipates it and does nothing with it:
`GlassService` carries `insurance_claim` (bool), `insurance_company`, `claim_number`,
`deductible`, `authorization_number` (`apps/technician_portal/models.py:381–398`). These are
captured on the job form and displayed on detail pages. **No workflow, no submission, no
status tracking, no remittance reconciliation.** `EDI` appears in the codebase only as an
incidental substring, never as a feature.

**Considerations — this is a business-development project with a software component, not the
reverse.**
- **Access is the gate, not code.** TPA EDI connectivity requires commercial relationships and
  certification. You cannot build your way in. Step one is finding out whether a shop of your
  size can even get credentialed, and what an aggregator/clearinghouse would charge to broker
  it.
- Scope has natural tiers, and the first is genuinely useful alone:
  1. **Claim tracking** (no EDI): record the claim, its status, expected vs. received amount,
     and reconcile against payment. Pure internal workflow. Would immediately make RS Systems
     the place a shop knows what's outstanding — meaningful even without submission.
  2. **Assisted submission**: generate the paperwork/format a human submits.
  3. **True EDI integration**: the endgame.
  **Tier 1 is a Track B-sized project and delivers most of the day-to-day value.** Consider
  doing only Tier 1 regardless of the §1 fork.
- Insurance money arrives partially, late, and short. Reconciliation ("they paid $312 on a $380
  claim") is where the actual pain is, and it's largely independent of how the claim was
  submitted.
- Regulatory: claim data is sensitive. Retention, access logging, and tenant isolation all get
  stricter. `apps/security` audit logging exists and should be extended, not bypassed.

**Decisions needed.** The §1 fork. Then: can you get credentialed? What does an aggregator
cost? Would 5 real shops pay more for this? **Go interview them before writing a line.**

**Acceptance criteria (for the memo, not the code).** A written answer to: is TPA access
achievable at our size, at what cost, on what timeline, and do target shops say it changes
their buying decision.

**Out of scope until the memo lands.** All code.

---

### D2 · NAGS parts catalog and pricing

**Goal (eventual):** Replacements price themselves from the industry catalog.
**Size:** XL · **Depends on:** §1 decision

**Why it matters.** NAGS (National Auto Glass Specifications) is the pricing lingua franca of
the industry: part numbers, list prices, labor hours, and the discount-off-list conventions
that shops and insurers negotiate against. A system that doesn't speak it makes every
replacement a hand-priced guess — which is exactly what RS Systems does today.

**Verified current state.** `Replacement.nags_number`
(`apps/technician_portal/models.py:1516`) is a free-text `CharField` with a help_text calling
it the "industry standard identifier." Nothing reads it. Pricing is `parts_cost + labor_cost`
(`:1521`, `:1526`), both hand-entered by the shop. `requires_adas_calibration` and
`adas_calibration_cost` (`:1531`, `:1535`) are likewise manual. There is no parts catalog,
no vehicle→glass lookup, and no inventory anywhere in the model inventory.

**Considerations.**
- **The data is licensed and it costs money** (NAGS is a Mitchell product). This is a recurring
  vendor cost that must be priced into plans before it's built, not after. It likely only makes
  sense on a higher tier.
- The catalog is large and updates periodically. You need an ingestion pipeline, versioning
  (a quote priced against last month's catalog must remain explicable), and storage that
  doesn't balloon per tenant — this is shared reference data, not tenant data, which is a
  different shape from everything else in this codebase.
- The genuinely valuable part isn't the part number — it's **vehicle → correct glass → price →
  labor hours**, plus ADAS calibration flagging. ADAS is increasingly where the margin is, and
  getting "does this vehicle need recalibration" right is a safety matter as much as a pricing
  one.
- **A much cheaper 80% exists**: let each shop build their *own* price book (vehicle/glass
  type → their price), seeded from their history. No licensing, no ingestion, and it captures
  most of the daily time savings. Progressive repair pricing already proves the pattern —
  `CustomerPricing` and the shop-level price book are the precedent. **Strongly consider this
  before licensing anything.**
- If D1 is pursued, D2 becomes near-mandatory — TPA billing is conducted in NAGS terms.

**Decisions needed.** The §1 fork. Then: get an actual NAGS licensing quote before estimating.
And explicitly evaluate the shop-owned price book alternative first.

**Acceptance criteria (for the memo).** Licensing cost, update cadence, and a
build-vs-shop-price-book recommendation with numbers.

**Out of scope until the memo lands.** All code.

---

## §2 Suggested sequence

Assuming Path A for now and one developer:

| Order | Session | Rationale |
|---|---|---|
| 1 | **C2** | Minutes of work; may be actively costing sales right now. Verify prod first. |
| 2 | **A2** | Customer-visible nulls. Embarrassing, trivial. |
| 3 | **B1** | Biggest daily-felt gain per hour spent in the whole document. |
| 4 | **A4** | Small, and B1 touches the same template — do them together. |
| 5 | **A1** | The coherence fix. Do it before the marketing screenshots in C1. |
| 6 | **A3, A6, A5** | Independent small wins; slot as filler. |
| 7 | **C1** | Now the screenshots are of a coherent app. |
| 8 | **B4** | Owner-facing depth; composes with whatever B2 becomes. |
| 9 | **B3** | Larger, and the gateway to Path B. |
| — | **B2** | Start the *memo* early (long lead time on 10DLC); build when the memo lands. |
| — | **D1, D2** | Interviews now, code only after the §1 fork is decided. |

`PRODUCT_DIRECTION.md`'s parallel platform-health items still stand and are unchanged by this
document: set `SENTRY_DSN` in EB, fix the pre-existing test failures, add portal test coverage
before B3 builds on those views.

---

## Appendix A — Findings retracted (do not re-chase)

An earlier pass reported these as bugs. They were artifacts of hand-seeded test data that
bypassed model validation. **They are not defects. Do not "fix" them.**

| Reported | Reality |
|---|---|
| Damage types render as raw enums (`half_moon`, `bullseye`) in the jobs list | `DAMAGE_TYPE_CHOICES` (`apps/technician_portal/models.py:663–672`) are already human-readable (`Half-Moon`, `Bull's Eye`) and `job_list.html` correctly uses `get_damage_type_display`. The seed script wrote values not in `choices`; Django's `get_FOO_display` returns the raw value in that case. **Templates are correct.** |
| Glass position renders lowercase (`windshield`) in the portal | `GLASS_POSITION_CHOICES` keys are uppercase (`WINDSHIELD` → `Windshield`, `:1484–1495`). Same seeding cause. **Templates are correct.** |
| Plan limits aren't enforced (3 technicians on a 2-seat plan, no block) | Enforcement exists and works via `UsageService` + `PlanEnforcementMixin` (`apps/tenants/mixins.py:130`, `:221`). The seed created `Technician` rows directly in the ORM, bypassing the view layer. The *real*, smaller finding is A6: over-limit stat cards have no upgrade CTA. |
| The customer portal isn't white-labeled — it shows the RS Systems logo | It is white-labeled when `tenant.logo` is set (`base_customer.html:40–41`). The tenant used for testing had no logo uploaded. The *real*, smaller finding is A3: the no-logo **fallback** is an RS monogram. |
| The job-form onboarding tour renders detached/broken | The first step of each tour is an intentional element-less intro modal, which driver.js centers by design (`static/js/tours.js:19`, `:61`, `:71`). Working as built. Whether a centered intro modal over the damage diagram is the *best* first impression is a judgment call, not a bug — low priority if pursued at all. |

Also worth recording: creating a `Technician` without a corresponding `TenantMembership`
produces a user who cannot log in, with the message *"No shop account found."* This is correct
behavior for a data state the UI can't produce (the canonical path is `team_service`), so it
isn't a bug — but it's a sharp edge for anyone seeding data or writing tests.

---

## Appendix B — Reproducing the walkthrough environment

This is how the findings above were produced. Reuse it for screenshots (C1) and manual QA.

```bash
source venv/bin/activate
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_uxaudit"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development

createdb -U amelia_test -h localhost rs_uxaudit     # use a distinct DB per session
python manage.py migrate
python manage.py seed_plans
python manage.py setup_groups
python manage.py setup_notification_templates

python manage.py runserver 127.0.0.1:8021 --noreload   # 8000 is usually taken
```

**Seeding a realistic shop.** Signup has a Turnstile captcha, so create the tenant through the
same service the view calls:

```python
from apps.tenants.services.signup_service import create_tenant_with_owner
res = create_tenant_with_owner(
    business_name='Clearview Auto Glass', email='owner@clearview.test',
    password='auditpass123!', first_name='Drake', last_name='Owner',
)
```

**Three traps that cost time in this pass — avoid them:**

1. **Technicians need a `TenantMembership`**, not just a `Technician` row, or they can't log
   in. Prefer `apps/technician_portal`'s `team_service` over direct ORM creation.
2. **Choice fields are not validated on `save()`.** Use exact `choices` keys
   (`'Half-Moon'`, not `'half_moon'`; `'WINDSHIELD'`, not `'windshield'`) or the UI will render
   raw values and you'll report phantom bugs. See Appendix A.
3. **Plan limits are enforced in the view layer**, so ORM-created records bypass them. Seed
   through services when testing limit behavior.

For a customer-portal login, create a `CustomerUser` linked to an existing `Customer`
(note: `CustomerUser` has no `is_active` field). Log in at `/login/` with the **email**, not the
username — usernames are generated from first names.

---

## Document history

| Date | Change |
|---|---|
| 2026-08-07 | Initial version — from a live four-audience walkthrough of the running app. |
