# Proposal: Form Efficiency Overhaul — Repair, Replacement, Multi-Break

**Author:** Amelia  
**Date:** 2026-03-23  
**Status:** Draft — awaiting Drake's review  
**Priority:** High (these are the most-used forms in the entire app)

---

## Problem

All three creation forms have friction that slows down field work:

**Repair Form** — 12+ fields across 5 sections. A tech standing next to a truck has to scroll through the entire form for every repair. Most of the time it's the same customer, same damage type, over and over.

**Replacement Form** — 15+ fields across 5 cards (Assignment, Vehicle, Pricing, Insurance, Photos). Better organized with toggleable sections (ADAS, insurance), but pricing requires manual entry every time and there's no way to save common configs.

**Multi-Break Form** — Good concept (base info + modal per break) but each break modal still has 6+ fields, and there's no way to carry over damage type/viscosity/temp from the previous break (they're usually the same).

For a tool designed to replace paper, these forms need to be *faster* than paper.

---

## Ideas

### 1. Quick Repair Mode (stripped-down form)

**What:** A toggle or separate entry point — just 4 fields: Customer, Unit #, Damage Type, Photo. Everything else gets sensible defaults (status = COMPLETED, date = now, no notes). Tech can expand to full form if needed.

**Why:** 80% of repairs need the same 4 pieces of info. The other 8 fields are nice-to-have documentation that slows down the common case.

**Effort:** Medium — new view or JS toggle on existing form.  
**Risk:** Low. Full form stays available. Quick mode just hides optional fields.

---

### 2. Save & New (batch entry flow)

**What:** Add a "Save & New" button next to "Create Repair." After saving, redirects back to the form pre-filled with the same customer (and optionally same damage type). Counter shows "3 repairs logged this session."

**Why:** When a tech does 8 trucks for EOS Trucking in a parking lot, they shouldn't re-select the customer 8 times. This is the single biggest time waste in the current flow.

**Effort:** Low — add a hidden input (`save_and_new=1`), redirect to `create_repair?customer=X` instead of `repair_detail`.  
**Risk:** None. Additive change.

---

### 3. Collapsible Sections (progressive disclosure)

**What:** Technical Conditions (temp, viscosity) and Photo Documentation start collapsed on mobile. Required fields (Customer, Unit, Damage, Status) stay expanded. Sections expand on tap with smooth animation. State remembered via localStorage.

**Why:** The form is 4 scrolls long on mobile. Collapsing optional sections cuts it to 1-2 scrolls. Techs who care about temp/viscosity can expand; most won't.

**Effort:** Low — CSS/JS only, no backend changes.  
**Risk:** Low. Collapsed fields still submit their values (empty = optional). Just need to ensure photo requirement warning still surfaces when status = COMPLETED.

---

### 4. Damage Type as Tap Cards

**What:** Replace the damage type dropdown with visual icon cards (Star Break ⭐, Bullseye 🎯, Crack ➖, Combo 🔀, Chip ◻️). One tap selects it. Selected card gets a highlight ring.

**Why:** Dropdowns are the slowest mobile input. Tap targets are faster, more intuitive, and look better. Most shops have 4-6 damage types — perfect for a card grid.

**Effort:** Low-Medium — replace `<select>` with styled radio buttons, update form handling.  
**Risk:** Low. Same data, better input method. Needs to degrade gracefully if shop has custom damage types we haven't iconified.

---

### 5. Smart Defaults

**What:**
- **Status defaults to COMPLETED** for new repairs (most repairs are logged after the fact)
- **Remember last customer** in localStorage — pre-select on next form load
- **Remember last damage type** — pre-select (most techs do the same type all day)
- **Auto-fill date to now** (already done ✅)

**Why:** Every default that matches reality is one less field the tech has to touch.

**Effort:** Low — JS localStorage + one backend default change.  
**Risk:** Low. The "remember" behavior is per-browser, per-device. Status default change could surprise techs who use PENDING as a workflow step — might need a tenant-level setting.

---

### 6. Auto-fill Temperature from Weather

**What:** When the tech opens the form, fetch current temperature from a weather API (wttr.in or Open-Meteo) based on the shop's configured address or browser geolocation. Pre-fill the windshield temp field with ambient temp. Show a small "📍 Auto-filled from weather" hint.

**Why:** Windshield temp correlates with ambient temp. Pre-filling saves a field entry and improves data quality (techs often skip it or guess).

**Effort:** Medium — need geolocation permission or shop address lookup, API call, JS to populate field.  
**Risk:** Low-Medium. Geolocation prompts can be annoying on mobile. Fallback: use shop's city from settings, no GPS needed. Also, windshield temp in direct sun can be 20-40°F above ambient — field should be labeled "suggested" not "actual."

---

### 7. Reorder Fields for Speed

**What:** Move the most-changed fields to the top:
1. Customer (required)  
2. Unit # / Vehicle (required)
3. Damage Type (required)
4. Status (frequently changed)
5. Photos (expand on tap)
6. Notes (expand on tap)
7. Technical Conditions (expand on tap)
8. Date (auto-filled, rarely changed)

**Why:** Current order buries Status and Date at the bottom under 3 optional sections. On edit, techs scroll past photos and notes to change status from PENDING to COMPLETED.

**Effort:** Low — template reorder only.  
**Risk:** None. Pure UX improvement.

---

### 8. Unit Number Autocomplete

**What:** When a customer is selected, fetch their known unit numbers (from previous repairs) and show as autocomplete suggestions. Tech types "10" and sees "TRUCK-1045, TRUCK-1099" as options.

**Why:** Fleet customers have the same trucks coming back. Typing the full unit number every time is wasted effort, and typos create duplicate units in reports.

**Effort:** Medium — API endpoint to fetch units by customer, JS autocomplete widget.  
**Risk:** Low. Additive. Autocomplete suggests but doesn't force — tech can still type a new unit number.

---

### 9. Barcode/QR Scan for Unit Number

**What:** Add a camera icon next to the unit number field. Tapping it opens the camera in barcode scan mode. Reads the truck's barcode/QR sticker and fills the unit number.

**Why:** Many fleet trucks have barcode stickers on the windshield or door frame. Scanning is faster and eliminates typos.

**Effort:** High — need a JS barcode scanning library (e.g., QuaggaJS or ZXing-js), camera permissions, testing across devices.  
**Risk:** Medium. Not all trucks have scannable codes. Camera permission UX varies by browser. This is a differentiator feature though — no other windshield repair app does this.

---

### 10. Multi-Repair Wizard (one truck, multiple breaks)

**What:** We already have multi-break batch forms, but improve the flow: after logging break #1, show a "Add another break on this unit?" button that duplicates the form with customer + unit pre-filled, incrementing the break number.

**Why:** Multi-break repairs on one windshield are common. The current batch flow requires going through the multi-break form upfront — this alternative lets the tech decide as they go.

**Effort:** Medium — extend the Save & New concept with batch linking.  
**Risk:** Low. Builds on existing batch infrastructure.

---

### 11. Voice Notes Instead of Typing

**What:** Add a microphone button next to the Technician Notes field. Tap to record, uses browser Speech Recognition API to transcribe. Shows the text in the field for review before saving.

**Why:** Typing notes on a phone in the field is painful. Voice is 3-5x faster. The Web Speech API is free and works on Chrome/Safari mobile.

**Effort:** Medium — JS Speech Recognition API, fallback for unsupported browsers, audio recording as backup.  
**Risk:** Medium. Speech recognition accuracy varies. Wind/traffic noise in the field could degrade quality. Should be labeled "beta" initially.

---

### 12. Offline Mode (Service Worker)

**What:** Cache the form and customer list via Service Worker. If the tech has no signal (rural areas, parking garages), they can still fill out and "save" the form. Repairs queue locally and sync when connection returns. Show a sync indicator.

**Why:** Mobile windshield techs go to truck yards, rural routes, underground parking. Losing a repair because of no signal is a dealbreaker.

**Effort:** High — Service Worker, IndexedDB for local queue, sync logic, conflict resolution.  
**Risk:** High complexity. Needs robust error handling for sync failures, duplicate detection, and clear UX for "pending sync" state. This is a v3.0 feature, not a quick win.

---

## Recommended Implementation Order

**Phase 1 — Quick Wins (1-2 days):**
- #2 Save & New
- #5 Smart Defaults (status = COMPLETED, remember customer)  
- #7 Reorder Fields
- #3 Collapsible Sections

**Phase 2 — UX Polish (2-3 days):**
- #4 Damage Type Tap Cards
- #8 Unit Number Autocomplete
- #1 Quick Repair Mode

**Phase 3 — Differentiators (1-2 weeks):**
- #6 Auto-fill Temperature
- #11 Voice Notes
- #10 Multi-Repair Wizard improvements

**Phase 4 — Big Bets (future):**
- #9 Barcode/QR Scan
- #12 Offline Mode

---

---

## Replacement Form Ideas

### R1. NAGS Number Autocomplete / Lookup

**What:** When the tech types a NAGS number (e.g., "FW04567"), show the matching glass description (year/make/model, glass type, features). If they select a customer + unit first, suggest the NAGS number from the last replacement on that unit.

**Why:** NAGS numbers are cryptic. Auto-lookup eliminates transcription errors and helps the tech confirm they've got the right glass. For repeat vehicles, it's one tap instead of looking it up again.

**Effort:** Medium — need a NAGS lookup data source or partner API. Could start with a local cache of previously-used NAGS numbers per tenant.  
**Risk:** Low. Additive. NAGS database licensing could be a cost consideration for the full lookup. Local cache (from past replacements) is free.

---

### R2. Insurance Company Autocomplete

**What:** When insurance claim is toggled on, the insurance company field should show autocomplete from previously entered values (per tenant). "State Farm", "Geico", "Progressive" etc.

**Why:** Techs misspell insurance company names, creating duplicates in reports. Autocomplete standardizes entries and saves typing.

**Effort:** Low — JS autocomplete from a distinct values API endpoint.  
**Risk:** None.

---

### R3. Saved Pricing Templates

**What:** Let shop owners define pricing templates: "Standard Windshield" ($350 parts, $150 labor), "Back Glass" ($200, $100), "ADAS Required" ($350, $150, +$250 ADAS). When creating a replacement, the tech picks a template and costs auto-fill. Can still override.

**Why:** Most shops have 5-10 common job types. Typing $350.00 and $150.00 every time is tedious and error-prone.

**Effort:** Medium — new PricingTemplate model, owner settings page to manage templates, dropdown on replacement form.  
**Risk:** Low. Templates are suggestions, not constraints. Tech can always override.

---

### R4. Insurance Claim Flow Shortcut

**What:** Add a "Quick Insurance Claim" button on the replacement form. When tapped, it toggles insurance ON, expands the fields, and focuses the insurance company input. On the dashboard, add a "New Insurance Replacement" quick action separate from "New Replacement."

**Why:** Insurance replacements are a different workflow mentally. Having a dedicated entry point signals "this is for insurance work" and pre-expands the right fields.

**Effort:** Low — JS toggle + new dashboard button routing to `replacement_create?insurance=1`.  
**Risk:** None.

---

### R5. Glass Position as Visual Picker

**What:** Replace the glass position dropdown with a visual car diagram. Tap the windshield, rear glass, or side windows to select. Highlighted selection shows which glass is being replaced.

**Why:** More intuitive than a text dropdown, especially for techs who think visually. Also reduces errors — "REAR_QUARTER_LEFT" vs "REAR_QUARTER_RIGHT" confusion goes away when you tap the actual position.

**Effort:** Medium-High — SVG car diagram, click handlers, responsive layout.  
**Risk:** Low-Medium. Needs to look good on mobile. Accessibility: keep the dropdown as a fallback or add ARIA labels.

---

### R6. Auto-Calculate Total with Live Display

**What:** Already partially done ✅ — the form calculates parts + labor + ADAS. Improve by: showing the total prominently at the top (sticky on mobile), showing per-item breakdown, and including deductible in the calculation (total to customer = total - deductible, or total to insurance = total - deductible).

**Effort:** Low — JS enhancement to existing calculation.  
**Risk:** None.

---

### R7. Save & New for Replacements

**What:** Same as repair form — add a "Save & Create Another" button. Pre-fills customer (and optionally technician) from the previous replacement.

**Why:** When a shop is doing a fleet of replacements (10 trucks, all getting windshields), re-selecting the customer each time wastes effort.

**Effort:** Low — same pattern as repair Save & New.  
**Risk:** None.

---

## Multi-Break Form Ideas

### M1. Carry Forward Break Details

**What:** When adding break #2, #3, etc., pre-fill damage type, windshield temp, and resin viscosity from the previous break. Tech just changes what's different (usually just damage type, sometimes nothing).

**Why:** If you're repairing 4 breaks on one windshield, the temp and viscosity are the same for all of them. Making the tech re-enter them 4 times is pointless.

**Effort:** Low — JS: when opening the break modal, copy values from the last break in the array.  
**Risk:** None. Pre-filled fields can be changed.

---

### M2. Quick-Add Break (One-Tap)

**What:** Add a "Quick Add" button that creates a break with just the damage type (selected from icon cards, not a modal). No modal, no scrolling. Temp/viscosity/notes inherit from break #1. Tech taps ⭐ Star Break → break added to the list instantly.

**Why:** The current modal is overkill for break #3 and #4 when everything except damage type is the same. The modal has 6 fields, but usually only 1 changes.

**Effort:** Medium — new inline UI alongside the existing modal flow. Keep modal as "detailed add" option.  
**Risk:** Low. Additive. Detailed modal stays available.

---

### M3. Batch Photo Upload

**What:** Instead of per-break photos in the modal, add a single photo upload zone at the bottom. Tech takes all their photos, uploads them as a batch, then optionally assigns each photo to a specific break (or leaves them as "batch photos"). AI could auto-match photos to breaks by analyzing damage type.

**Why:** Taking a photo, going back to the modal, selecting it, saving, opening a new modal, taking another photo — this interrupts the flow. Let the tech take all photos first, organize later.

**Effort:** High — multi-file upload, photo assignment UI, optional AI matching.  
**Risk:** Medium. Photo-to-break assignment needs a clear UI or techs will skip it. MVP: just upload batch, don't require assignment.

---

### M4. Live Break Counter + Summary Bar

**What:** Sticky bar at the bottom showing: "4 breaks · $180 total · [Submit All]". Updates live as breaks are added/removed. Shows progressive pricing breakdown (break 1: $55, break 2: $50, break 3: $40, break 4: $35).

**Why:** Currently the total and submit button are hidden until breaks are added, and the pricing preview is a separate section. A sticky bar gives constant feedback and a persistent submit target.

**Effort:** Low — CSS sticky + JS updates. Pricing data already available.  
**Risk:** None.

---

### M5. Duplicate to New Unit

**What:** After submitting a multi-break batch for TRUCK-1045, show a "Same customer, different unit?" button. Clears unit number, keeps customer + date + technician. Resets breaks list but remembers damage type defaults.

**Why:** A tech doing fleet work might repair 3 trucks in a row, each with 2-3 breaks. This bridges the gap between multi-break (same unit) and Save & New (different unit).

**Effort:** Low — post-submit redirect with pre-filled query params.  
**Risk:** None.

---

## Cross-Form Ideas (Apply to All Three)

### X1. Form Analytics

**What:** Track time from form open to submit, fields filled vs skipped, abandonment rate. Simple JS timestamps stored via a lightweight API endpoint. Dashboard in owner settings.

**Why:** Without data, we're guessing which fields matter. With data, we can prune unused fields and optimize the common path.

**Effort:** Medium — new API endpoint, JS instrumentation, simple analytics view.  
**Risk:** Low. Non-invasive.

---

### X2. Persistent Draft Recovery

**What:** The repair form already has autosave (FormAutosave). Extend this to the replacement and multi-break forms. If the tech closes the tab mid-form, they get a "Restore draft?" prompt when they come back.

**Why:** Losing a half-filled form to an accidental tap or phone call is infuriating. Autosave prevents data loss.

**Effort:** Low for replacement (same JS library). Medium for multi-break (need to serialize break array).  
**Risk:** Low. Autosave already proven on repair form.

---

### X3. Unified "New Job" Entry Point

**What:** Instead of separate "New Repair" / "New Replacement" / "Multi-Break" buttons, show a single "New Job" button that asks: "What are you doing?" → Repair (single break) / Repair (multiple breaks) / Glass Replacement. One entry point, three paths.

**Why:** New techs don't know the difference between the three forms. A guided entry point reduces confusion.

**Effort:** Low — modal or intermediate page with 3 cards.  
**Risk:** Low. Power users can bookmark specific form URLs to skip the picker.

---

## Updated Implementation Order

**Phase 1 — Quick Wins (1-2 days, all forms):**
- Save & New (repair + replacement) [#2, R7]
- Smart Defaults (status = COMPLETED, remember customer) [#5]
- Reorder Fields for speed [#7]
- Collapsible Sections on mobile [#3]
- Carry Forward break details in multi-break [M1]
- Live summary bar in multi-break [M4]

**Phase 2 — UX Polish (2-3 days):**
- Damage Type Tap Cards (repair + multi-break) [#4]
- Unit Number Autocomplete [#8]
- Quick Repair Mode [#1]
- Insurance Company Autocomplete [R2]
- Quick-Add Break (one-tap) [M2]
- Duplicate to New Unit [M5]

**Phase 3 — Differentiators (1-2 weeks):**
- Auto-fill Temperature from weather [#6]
- Voice Notes [#11]
- Saved Pricing Templates [R3]
- Glass Position Visual Picker [R5]
- Form Analytics [X1]
- Autosave for replacement + multi-break [X2]

**Phase 4 — Big Bets (future):**
- Barcode/QR Scan for unit number [#9]
- Offline Mode [#12]
- NAGS Lookup [R1]
- Batch Photo Upload + AI matching [M3]
- Unified "New Job" entry point [X3]

---

## Success Metrics

- **Time to log a repair** — measure from form open to submit (JS timestamp). Target: under 30 seconds for a quick repair, under 60 seconds for a full one.
- **Time to log a replacement** — target: under 90 seconds including pricing.
- **Multi-break entry speed** — target: under 15 seconds per additional break after break #1.
- **Form abandonment rate** — track how often forms are opened but not submitted.
- **Fields filled per job** — are techs actually using optional fields, or skipping them?

These can be tracked with simple JS event logging, no analytics SDK needed.
