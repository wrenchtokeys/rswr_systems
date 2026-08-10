# UI/UX: from "clean Tailwind" to "Apple magic"

**Date**: 2026-08-09
**Method**: live walkthrough of the real app (landing → signup → login → owner dashboard →
jobs → repair form → settings → customer portal) on a seeded local tenant, plus a
template/CSS audit. Every claim below has a file reference or a count.

The app is not ugly. It is *unauthored*: it looks like the default output of the tools
that built it. "Apple magic" is not gradients and glass — it's **one accent colour, a real
material hierarchy, an actual type scale, and motion that only ever exists to explain a
change.** That's the target.

---

## Part 1 — Why it reads as bland (diagnosis)

### 1. Three competing accent colours inside one product

| Surface | Accent |
|---|---|
| Landing, nav, links, most buttons | `blue-600` |
| Owner dashboard revenue hero, repair form header, floating action button | `green-600` |
| Setup banners | `amber/orange-600` |
| Jobs page active filter pills | `gray-900` (black) |

Nothing signals "someone decided this." Apple-feel comes from **one** accent with
neutrals doing 95% of the work, and colour reserved for meaning.

Refs: `templates/saas/owner_dashboard.html` (green gradient hero),
`templates/technician_portal/repair_form.html` (green header + green section icons),
`templates/technician_portal/job_list.html` (black active pills).

### 2. The design system exists — and ~62% of templates bypass it

- `354` hardcoded `blue-600` occurrences vs `315` `brand-*` token uses.
- **101 of 162 templates** hardcode `blue-*`.
- Only **27 templates** use the `brand-*` token at all, and 20 of those are the customer portal.
- `{% tenant_brand_css %}` appears in exactly **one** file: `templates/customer_portal/base_customer.html:31`.

**This is a trust problem, not just a taste problem.** The pricing page sells
*"Your logo & colors on everything"* as a Pro-plan bullet. In reality a shop's
`Tenant.brand_color` only retints the customer portal — and even there, 21 customer-portal
templates hardcode blue over it. The owner app, tech app, settings, and invoicing UI stay
RS-Systems blue no matter what the shop picks.

### 3. Everything sits at the same depth

`.card` is `bg-white rounded-xl border border-gray-200` (`static/css/src/input.css:77`).
No shadow token, no hover state, no layering. Apple's premium feel is a strict material
ladder — base / raised / floating / modal — each with its own soft, wide, low-opacity
shadow. A 1px grey border is the flattest possible choice.

### 4. No type scale, and numbers don't line up

Page titles are `text-xl sm:text-2xl` (owner dashboard), `text-3xl` (Jobs),
`text-4xl md:text-6xl` (landing). Weights jump between 600/700/800 arbitrarily. No
tracking correction on large text (Apple tightens as size grows). Critically:
**no `tabular-nums`** — the `$50.00` column in the Jobs table doesn't align, which is
the single clearest "not a finished product" tell in a money app.

### 5. Icon language is dated and heavy

`1,281` Font Awesome **solid** icon usages. FA solid reads 2016. The thin, geometric,
consistent-stroke line icon set is most of what people mean by "Apple-like." It's also a
CDN dependency (below).

### 6. Three external CDNs remain — a perf *and* security issue

Despite the project's own no-CDN rule for Tailwind:
- `templates/includes/head_assets.html` — Google Fonts (Inter) + Font Awesome 6.4.0
- `templates/base_app.html:8` and `:219` — flatpickr CSS + JS from jsdelivr
- `templates/customer_portal/base_customer.html:9` — flatpickr CSS

Render-blocking third-party requests cause the visible font flash on the landing hero,
leak visitor IPs to Google/Cloudflare/jsDelivr, and make a strict CSP impossible for an
app that takes card payments. **Self-hosting fonts + inlining an SVG icon sprite is
simultaneously the biggest "feels premium" win and the biggest security win.** Do it first.

### 7. Motion is absent where it matters and wrong where it exists

The only motion in the product is the landing page's `[data-reveal]` scroll fade-up
(`templates/landing.html:43`). At real scroll speed it fires *after* you've passed the
section — during the walkthrough the pricing cards rendered as a blank void, then popped
in. Meanwhile nothing animates in the app itself: status changes, saves, and list updates
all happen via hard page reloads with no continuity.

`--transition: all 0.3s ease` (`input.css:38`) is the anti-pattern — animating `all` with
a generic curve.

### 8. The busiest page in the app is the least designed

`/tech/jobs/` presents, above the first job row: 4 stat tiles → 3 rows of **17 filter
pills** → "More Filters" → per-page select → sort select → table header. ~25 controls
before content. Row actions are two tiny text links (`View | Edit`). A green floating
`+` button duplicates the "New Job" button already on screen.

The stat tile numbers are colour-coded orange/blue/green for no semantic reason.

### 9. Numbers with no meaning

The dashboard hero is `$400.00` on a green slab. No comparison, no trend, no period
toggle. A big number with nothing to compare it to is the definition of bland — and it's
the first thing every owner sees every morning.

### 10. Auth pages say the brand three times and don't fill the screen

`/login/` renders the marketing nav ("RS Systems"), a brand panel ("RS Systems"), and a
card ("Welcome back — Log in to your RS Systems account"). The split panel stops
mid-viewport leaving dead white space below.

### 11. Landing page specifics

- The hero "product shot" is **hand-built fake HTML** inside fake browser chrome
  (`landing.html:120-190`). It has already drifted from reality: the mock shows a *blue*
  revenue banner; the real dashboard is *green*. Showing a fake of your own product is
  the opposite of trustworthy.
- The trust bar reads `500+ Jobs Tracked · $50K+ Invoiced · 100% Mobile Friendly ·
  24/7 Access Anywhere`. Two are unverifiable self-reported numbers, and two aren't stats
  at all. This pattern actively lowers trust with a skeptical shop owner.
- Structure is 6 identical centred-text stacked sections: eyebrow → h2 → subhead → grid.
  No rhythm, no asymmetry, no dark ground for contrast, no product story.
- The only testimonial is from the founder.

### 12. Missing in-between states

No skeletons, no optimistic updates, no success moment when a job completes or an invoice
gets paid. Every state change is a full page reload.

**Worth noting:** the **customer portal is the best-designed surface in the product** —
brand tokens, `.btn-primary`, proper nav, a real CTA card, sensible stat tiles. It's proof
the team can do this. The owner/tech app simply never got the same pass.

---

## Part 2 — The rules (what "Apple magic, on brand" actually means here)

### R1. One accent. Green means money, not decoration.

- Everything interactive → `brand-*` tokens (which is blue by default). No hardcoded `blue-*`.
- Green is **reserved for money-positive semantics only**: paid, collected, completed. It
  is never a surface, never a header, never the FAB.
- Amber = needs your attention. Red = destructive/overdue. Nothing else gets colour.
- Kill the green revenue slab, the green repair-form header, the green FAB, the black pills.

**This one change does most of the work**, and it makes `Tenant.brand_color` finally
deliver the thing the Pro plan already promises.

### R2. Materials, not borders

Add to `input.css`:

```css
:root {
  --surface-base:    #f7f8fa;   /* page ground, slightly cool */
  --surface-raised:  #ffffff;
  --surface-overlay: #ffffff;

  /* Two-stop, wide, very low opacity — the Apple shadow signature */
  --shadow-raised:  0 1px 2px rgb(16 24 40 / .04), 0 8px 24px -8px rgb(16 24 40 / .08);
  --shadow-float:   0 2px 4px rgb(16 24 40 / .04), 0 16px 40px -12px rgb(16 24 40 / .14);
  --shadow-overlay: 0 8px 12px rgb(16 24 40 / .06), 0 32px 64px -16px rgb(16 24 40 / .24);
}
```

`.card` becomes `bg-[--surface-raised] rounded-2xl shadow-[--shadow-raised]` with a
hairline border only where cards touch. Radii go up a step (`xl` → `2xl`) — larger,
consistent corner radii are a big part of the "expensive" read.

### R3. A real type scale with optical corrections

Seven steps, one weight jump, tracking tightens as size grows, and money is always tabular:

```css
.t-display { font-size: 3.5rem; font-weight: 600; letter-spacing: -0.028em; line-height: 1.05; }
.t-h1      { font-size: 2rem;   font-weight: 600; letter-spacing: -0.021em; line-height: 1.15; }
.t-h2      { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.017em; }
.t-h3      { font-size: 1.125rem; font-weight: 600; letter-spacing: -0.011em; }
.t-body    { font-size: 0.9375rem; line-height: 1.55; }
.t-sub     { font-size: 0.875rem; color: var(--text-secondary); }
.t-caption { font-size: 0.75rem; letter-spacing: 0.01em; }

.num, td.money, .stat-value { font-variant-numeric: tabular-nums; }
```

Drop `font-extrabold` everywhere. 600 at a tight tracking looks more expensive than 800.

**Optional but high-impact:** self-host Inter with `cv11, ss01` features on, or give
*display* text one distinctive face while body stays Inter. Default-settings Inter is
precisely what "generic Tailwind" looks like.

### R4. Three motion primitives, nothing else

```css
--ease-out: cubic-bezier(0.32, 0.72, 0, 1);  /* the iOS curve */
--dur-fast: 140ms;
--dur-base: 220ms;
```

1. **Enter/exit** — 220ms, `--ease-out`, opacity + 4px translate. Menus, modals, toasts.
2. **Press feedback** — `active:scale-[0.98]` on every actionable, 140ms. This alone makes
   the whole app feel responsive.
3. **Continuity** — View Transitions API on list→detail navigation (works with plain
   Django page loads, degrades silently). A job row expanding into its detail page is the
   single most "magic" thing you can add for the least code.

**Delete the scroll-reveal fade on the landing page.** It's the only motion you have and
it's making the page worse.

Every animation wrapped in `@media (prefers-reduced-motion: reduce)`.

### R5. Stage complexity — show 3 things, hide 20

Jobs page target: search + one segmented control (All / Repairs / Replacements) + one
status dropdown. Everything else behind a "Filters" button showing an active count.
Row actions collapse to one kebab revealed on hover/focus. Stat tiles collapse into a
single summary line. Remove the FAB on any page that already has a primary button.

### R6. Give every number a comparison

Revenue card: `$400.00` + `↑ 12% vs last month` + a 30-day sparkline + a period toggle.
This is the highest-impact single change on the owner dashboard.

### R7. Design the in-between

Skeletons matched to final layout, optimistic status updates, and one genuine success
moment when an invoice is paid — a brief, restrained confirmation, not confetti.

---

## Part 3 — The landing page (pre-signup)

1. **Replace the fake mock with the real product.** A high-res screenshot of the actual
   owner dashboard, or better: a scroll-scrubbed 4-frame sequence telling the loop —
   *chip photo → job created → invoice sent → paid*. Never ship a hand-drawn imitation of
   your own UI; it drifts (it already has) and it reads as vapourware.
2. **Replace vanity stats with verifiable trust.** Drop "100% Mobile Friendly" and
   "24/7 Access Anywhere". Replace with things a skeptical shop owner can check:
   *Payments processed by Stripe · Your data exports anytime · Built and run by a working
   glass shop in Arkansas · No contract, cancel in one click.*
   Keep real usage numbers **only** if they're accurate and attributed.
3. **Give the page rhythm.** Alternate light and one dark section. Break the
   centred-stack monotony with one asymmetric split (copy left, product right) and one
   full-bleed moment.
4. **Sharpen the promise.** "Manage your glass shop without the headache" is generic.
   Lead with the specific thing nobody else does — e.g. the multi-break progressive
   pricing, or "from chip photo to paid invoice without touching a spreadsheet."
5. **Get a real testimonial.** A founder quote in the testimonial slot is a tell that you
   have no customers. Until there's a second shop, reframe it explicitly as a founder
   note — honest beats hollow.
6. **Self-host the fonts** so the hero stops reflowing on load. This is visible today.

---

## Part 4 — Guardrails (so polish never costs trust or security)

- **Self-host fonts + icons; remove all three CDNs.** Then add a strict CSP. This is a
  payments app.
- **Never animate money.** Payment confirmation, invoice send, and delete flows stay
  explicit, boring, and reversible. Magic belongs in navigation and feedback, not consent.
- **Invoices and receipts stay documents.** No marketing polish on anything a customer
  files for taxes. The existing SES content rules (no emoji, no bracketed subjects) stay.
- **Never ship a claim the UI doesn't honour.** Either make brand colour work everywhere
  or soften the "your colors on everything" plan bullet.
- **Reduced-motion support on every animation**, no exceptions.
- **Contrast ≥ 4.5:1** for all text, including on the new tinted surfaces. Techs use this
  on a phone in daylight.

---

## Part 5 — Sequencing

Each phase is independently shippable and independently valuable.

### Phase 1 — Foundation (biggest ratio of impact to risk)
1. Self-host Inter; replace Font Awesome with an inlined SVG sprite; self-host or drop
   flatpickr. Removes 3 CDNs, fixes the font flash, enables CSP.
2. Add material, type-scale, and motion tokens to `input.css`.
3. Codemod `blue-*` → `brand-*` across all 101 templates; add `{% tenant_brand_css %}` to
   `base_app.html` and `base_auth.html`. **Shop brand colour now actually works.**
4. `tabular-nums` on every money and count field.

### Phase 2 — The daily surfaces
5. Owner dashboard: kill the green slab; revenue card gets delta + sparkline + period toggle.
6. Jobs page: collapse 17 pills to 3 controls; kebab row actions; remove the duplicate FAB.
7. Repair/job form: remove the green header and the ALL-CAPS icon-tile section heads;
   quiet, well-spaced field groups.

### Phase 3 — Feel
8. Press feedback + enter/exit motion everywhere; View Transitions on list→detail.
9. Skeletons and optimistic status changes.
10. Auth pages: drop the marketing nav, fill the viewport, say the brand once.

### Phase 4 — The front door
11. Real product imagery; trust bar rewrite; page rhythm; sharper promise;
    delete the scroll-reveal.

**If only one phase ships: Phase 1.** It fixes a security gap, a broken paid-plan promise,
and the root cause of the blandness in one pass — before a single screen is redesigned.
