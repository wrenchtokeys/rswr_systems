# Proposal: Repair Form Efficiency Overhaul

**Author:** Amelia  
**Date:** 2026-03-23  
**Status:** Draft — awaiting Drake's review  
**Priority:** High (this is the most-used form in the entire app)

---

## Problem

The repair form currently has 12+ fields spread across 5 sections. A technician in the field — standing next to a truck, phone in one hand — has to scroll through the entire form for every single repair. Most of the time they're logging the same customer, same damage type, over and over.

For a tool designed to replace paper, the form needs to be *faster* than paper.

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

## Success Metrics

- **Time to log a repair** — measure from form open to submit (JS timestamp). Target: under 30 seconds for a quick repair, under 60 seconds for a full one.
- **Form abandonment rate** — track how often the form is opened but not submitted.
- **Fields filled per repair** — are techs actually using optional fields, or skipping them?

These can be tracked with simple JS event logging, no analytics SDK needed.
