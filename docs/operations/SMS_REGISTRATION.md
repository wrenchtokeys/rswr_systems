# SMS registration — why RS Systems cannot text, and what to do instead

**Canonical doc for A2P messaging.** Status, denial history, root cause, and the decision.
Anything else that mentions SMS status (`FIELD_OPS_SESSIONS.md` Appendix A, `ROADMAP.md`,
`PRODUCT_DIRECTION.md`) points here and must not restate a status of its own.

**Last verified against AWS: 2026-09-16** (`aws pinpoint-sms-voice-v2`, us-east-1,
account 973196283632, tier PRODUCTION).

> ## Read §3.5 first — the answer depends on WHO is being texted
>
> This doc originally concluded "the toll-free number is dead, do not submit a version 5."
> **That was too broad, and it was wrong for half the product.** It is correct for texting a
> *shop's customers* as the shop. It is wrong for texting **RS Systems' own users** — the shop
> owners and technicians with accounts on rssystems.io. For those, RS Systems *is* the brand on
> the message, and the registration is clean. **That is a version 5, and it should be filed.**

---

## 1. Current state

| Number | Number status | Registration | Usable |
|---|---|---|---|
| `+18663115189` (RS Systems) | **PENDING** | `REQUIRES_UPDATES` — **version 4 DENIED 2026-09-02 18:58 UTC** | Not yet — **version 5 (staff scope) is the live plan, §3.5** |
| `+18559394817` (Rockstar Windshield Repair) | ACTIVE | COMPLETE (approved 2026-07-30, first try) | Yes — Rockstar only |

Four versions submitted, four denied — **all four scoped as customer-facing texts sent on behalf
of shops**, which is the thing that cannot be registered here (§3). The number itself is fine and
should be **kept**: a version 5 scoped to RS Systems texting its own users (§3.5) is an ordinary
registration. It leases at $2/mo, which was never the cost that mattered; two months of blocked
feature work was.

Prod is inert, not broken: `SMS_ENABLED=true` but `SMS_ORIGINATION_IDENTITY` is unset, and
`SMSService.is_enabled()` requires both, so every send quietly no-ops with `(False, None)`.

> **`REQUIRES_UPDATES` on the registration means "your move", not "still reviewing."** The denial
> lives on the **version**. Version 4 sat denied for **14 days** before anyone looked, because
> the registration-level status reads like an unfinished form. This is the second time that has
> happened (v3 sat denied for 5 days). **Always check the version.**

```bash
aws pinpoint-sms-voice-v2 describe-registration-versions --region us-east-1 \
  --registration-id registration-3c4aceac54424845b6d540e818f2bddb \
  --query 'RegistrationVersions[].[VersionNumber,RegistrationVersionStatus,DeniedReasons[].Reason]'
```

---

## 2. Denial history

| Ver | Submitted | Outcome | Reason |
|---|---|---|---|
| 1 | 2026-08-07 | DENIED 08-11 | Unclear Opt-in Language |
| 2 | 2026-08-25 | DENIED in 3s | Missing required field — the empty-draft API trap (§6) |
| 3 | 2026-08-25 | DENIED 08-26 | Unofficial Business Email + Pre-selected Opt-in |
| 4 | 2026-08-31 | **DENIED 09-02** | **Message Use Case Mismatch + Opt-in Workflow Mismatch** |

v4's two reasons, verbatim:

> **Message Use Case Mismatch** — *"The sample message content provided does not align with your
> stated use case. Ensure message samples accurately represent the types of messages you intend to send."*

> **Opt-in Workflow Mismatch** — *"The opt-in workflow described does not match other details
> provided in your submission. Ensure consistency between your opt-in process and all other
> registration information."*

Versions 1 and 3 were submission hygiene — wording, an inherited wrong-domain email, a
screenshot staged with the box ticked. Each was fixed and each fix was correct. Version 4 is
different: **nothing about the wording was wrong.** The mismatch the reviewer is describing is
in the architecture.

---

## 3. Root cause — why every *customer-facing* version failed

Read what v4 actually submitted, side by side:

| Field | Value |
|---|---|
| `companyInfo.companyName` | **RS Systems** |
| `companyInfo.website` | rssystems.io |
| `messageSamples.messageSample1` | "**Hensley Auto Glass**: Invoice INV-1042 for $89.00 — view and pay: …" |
| `messageSamples.messageSample2` | "**Hensley Auto Glass**: Thanks, John! A quick Google review helps…" |
| `messagingUseCase.useCaseDetails` | "**On behalf of a shop** we text that shop's own customers…" |
| `messagingUseCase.optInType` | DIGITAL_FORM |
| `messagingUseCase.optInDescription` | "Customers opt in themselves **on their own invoice page**…" |

Three contradictions fall out, and they are the two denial reasons:

1. **The registrant is not the sender.** The brand on the registration is RS Systems; the brand
   on every message is a client shop. Toll-free verification registers **one** business, and
   carriers require the verification and the opt-in to reflect the **end business** — the entity
   the consumer actually consented to hear from — not the software vendor. Twilio's rejection
   code for exactly this (30506) says opt-ins that "display the ISV's branding instead of the end
   business" are rejected, and that ISV submissions must show "the end business's branding and
   language." That is Message Use Case Mismatch.

2. **The opt-in story is circular.** Consent is described as happening on the invoice page — but
   sample 1 *is the text that delivers the invoice link*. A customer cannot opt in on a page they
   reach only by receiving the message they have not consented to. That is Opt-in Workflow Mismatch.

3. **Two opt-in paths, one declared.** `optInType` is DIGITAL_FORM, but the description also
   offers a verbal path ("customers may alternatively give their mobile number to their auto
   glass shop and verbally agree"). The reviewer is told one workflow and shown two.

Contradiction 1 is not fixable by editing text. **RS Systems is an ISV sending as many different
brands from one number, and that is the specific thing a single-brand toll-free registration
cannot describe.** Rockstar was approved on its first attempt for exactly the reason RS Systems
keeps failing: there, registrant brand == message brand.

Carriers do not grant a shared-number exception for this. Toll-free verification **tightened**
on 2026-02-17 (business registration number now required for non-sole-proprietors), and multi-brand
sending from one toll-free number is the pattern the tightening targets.

**For customer-facing texts, stop resubmitting** — versions 5, 6 and 7 fail the same way. But
that verdict does not reach the other half of the product; see the next section.

---

## 3.5 The split that matters — two audiences, two different answers

RS Systems sends texts to **two populations that have nothing in common** for registration
purposes, and collapsing them is what produced four denials and one over-broad conclusion.

| | **Staff notifications** | **Customer notifications** |
|---|---|---|
| Who receives it | The shop owner / technician — **an RS Systems account holder** | A shop's customer, who has never heard of RS Systems |
| Brand on the message | **RS Systems** | The shop ("Hensley Auto Glass") |
| Registrant brand matches? | **Yes** | No — this is the denial |
| Where consent happens | Their own Settings page on rssystems.io, logged in | The public invoice page |
| Circular opt-in? | **No** — they are already a user; the text is not how they reach us | Yes — the text *is* the invoice link |
| Examples | `repair_request_submitted`, `repair_assigned`, `repair_approved`, `repair_denied`, `batch_approved`, `repair_reassigned_away`, phone-verification codes | Invoice links, review requests, `repair_pending_approval` |

**The staff half resolves all three contradictions in §3 at once.** RS Systems texting its own
users, as RS Systems, about their own account activity, with consent collected on a page they
log into, is the most ordinary A2P registration there is — it is what every SaaS product with
alerts files. The use case is `ACCOUNT_NOTIFICATIONS`, not `CUSTOMER_CARE`.

Note the verification code the product already sends: *"Your **RS Systems** verification code
is: 123456."* That message was always brand-consistent. It was filed under a registration
describing customer care on behalf of shops, which is a use-case mismatch the reviewer named
explicitly.

### What this unblocks

The urgent shop-facing events are the ones that most need a channel that isn't a bell nobody is
looking at. `repair_request_submitted` — a customer asking for work — goes to
`repair.technician` (`apps/technician_portal/signals.py:635`), an RS Systems user. Every event
in the left-hand column above is registrable **now**.

### Version 5 — scope it to staff only

- `companyInfo.companyName` **RS Systems** / `website` **rssystems.io** — unchanged, and now
  consistent with the samples.
- `messagingUseCase.useCaseCategory` → **`ACCOUNT_NOTIFICATIONS`** (was `CUSTOMER_CARE`).
- `useCaseDetails` — RS Systems is job-management software; we text **our own registered users**
  (shop owners and technicians) about activity on their own account. No message goes to a
  third party's customers under this registration.
- `messageSamples` — **all branded RS Systems, all with STOP on the first message:**
  1. `RS Systems: New repair request from Penske - Unit 4821, windshield chip. View: https://rssystems.io/tech/repairs/1042/ Reply STOP to opt out.`
  2. `RS Systems: Job #1042 assigned to you - 2019 F-150, chip repair, due today. Reply STOP to opt out.`
  3. `RS Systems: Your verification code is 123456. Expires in 10 minutes.`
- `optInType` **`DIGITAL_FORM`** — and this time it is true and non-circular: the box lives at
  **Settings → Notifications**, on a page the user must log in to reach.
- `optInImage` — a screenshot of that consent block **in its default state, unchecked**
  (see §7 trap 4). It is guarded by `tests/test_sms_consent_surface.py`.
- `privacyPolicyUrl` `https://rssystems.io/privacy/` and `termsAndConditionsUrl`
  `https://rssystems.io/terms/` — **both newly REQUIRED, see §6.**

Customer-facing texts stay off this registration and take Path C below.

### Filing it — two commands

```bash
python scripts/sms_optin_shot.py                       # -> sms_optin.png
python scripts/submit_tollfree_registration.py sms_optin.png            # validate only
python scripts/submit_tollfree_registration.py sms_optin.png --submit   # file it
```

`sms_optin_shot.py` drives the real Settings → Notifications page (reusing
`landing_shots.py`'s throwaway-DB + headless-Chrome machinery) and **refuses to save a
screenshot whose consent box is checked** — v3's denial, asserted against the live DOM rather
than the template source, because what gets reviewed is a picture of rendered HTML. It also
crops out the tenant-branded page chrome, so no shop's name or logo reaches the artifact, and
shoots a demo account so no real user's details do either.

`submit_tollfree_registration.py` copies version 4, applies the staff-scope overrides, and runs
four guards before it will write anything. The one that matters is **`assert_brand_consistency`:
every message sample must lead with the registrant's company name.** That is precisely what v4
was denied for, and no script checked it. Without `--submit` it validates and prints the payload
without opening a version — which also sidesteps trap 1, since an abort after
`create_registration_version` leaves a dead draft behind.

Two caps worth knowing, both found by running it: **`useCaseDetails` is 500 characters**, not the
1500 that `optInDescription` gets. The script re-reads both from the live schema.

---

## 4. The paths for CUSTOMER-facing texts (the staff answer is §3.5)

### Path A — one number per shop, registered to *that shop* ✅ recommended for shops that qualify

The rules-correct answer, and the one already proven in this account: Rockstar cleared on the
first try. RS Systems buys and submits on the shop's behalf; the registration carries the
**shop's** name, website, support email, support phone, and an opt-in screenshot showing that
shop's own branding.

- **Cost:** $2/mo per number + review latency (days to weeks, per shop).
- **Code change:** origination identity stops being global. `settings.SMS_ORIGINATION_IDENTITY`
  → a per-tenant field, and `SMSService.is_enabled()` becomes `is_enabled(tenant)`. The message
  composition from PRs #156/#158/#159 is unaffected.
- **Qualification bar (this is the catch):** `companyInfo.website` is REQUIRED, and
  `contactInfo.supportEmail` must be on a domain matching the business — the v3
  *Unofficial Business Email* denial is explicit that free providers (gmail, yahoo) are rejected.
  **A shop with a Facebook page and a gmail address cannot be registered.** That is a real
  fraction of the target market.
- `companyInfo.businessType` **does** offer `SOLE_PROPRIETOR`, and `taxId` is only CONDITIONAL —
  so a shop with no EIN is fine, as long as it has a domain.

### Path B — 10DLC brand + campaign per shop ❌ verified dead for the target market

The textbook ISV pattern, and unavailable here. Checked directly against the API rather than
the marketing docs:

```
$ aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
    --registration-type US_TEN_DLC_BRAND_REGISTRATION
REQUIRED  companyInfo.taxId
REQUIRED  companyInfo.legalType  OPTIONS=PRIVATE_PROFIT,PUBLIC_PROFIT,NON_PROFIT,GOVERNMENT
REQUIRED  contactInfo.website
```

**There is no `SOLE_PROPRIETOR` option and `taxId` is REQUIRED.** AWS End User Messaging does not
expose the Campaign Registry's sole-proprietor brand type. Every shop would need an EIN, a
website, and a domain email — a stricter bar than Path A for more money (~$4 brand vetting +
~$10/mo per campaign). Viable only for shops that are already LLCs. Not the base case.

### Path C — don't be the sender; hand the text to the shop's own phone ✅ recommended default

The genuinely different approach, and the only one that works this week.

RS Systems composes the message and the shop owner taps **"Text this to the customer"**, which
opens their phone's native Messages app pre-filled via an `sms:` deep link. The sender is the
shop's own mobile number — a number the customer already has in their contacts.

- **No registration, no carrier review, no per-number lease, no compliance surface for RS Systems.**
- A manually-initiated message from a business's own handset to an existing customer about work
  they authorized is conversational P2P traffic, outside the A2P regime that 10DLC and toll-free
  verification govern. The thing that makes it A2P is bulk, unattended sending — which is exactly
  what this path gives up.
- **Works on iOS and Android, and works today.** It reuses the message-composition logic already
  built and deployed; only the transport changes.
- **What it gives up:** unattended sending (the review-request cron becomes a "Send" button on the
  completed job, or stays email), delivery receipts, and per-message cost tracking.

### The decision

**Staff notifications (§3.5): file version 5 on `+18663115189` now.** Keep the number — it has a
valid registration after all, just not the one that was filed four times. This is the path that
gives RS Systems texting at all, and it covers the urgent events (`repair_request_submitted`
above all).

**Customer-facing: ship Path C as the default for every shop. Offer Path A as an opt-in upgrade**
for a shop that has its own domain and wants unattended texting, and charge the $2/mo through.

**Do not release `+18663115189`** — that was this doc's original call and it was wrong, because it
followed from "RS Systems never texts anyone as itself," which is false: it texts its own users
constantly. One number carries the staff registration; per-shop numbers carry Path A if a shop
ever takes it.

<details>
<summary>The one remaining wording play, recorded and not recommended</summary>

Brand the messages **RS Systems** instead of the shop — "RS Systems: your invoice from Hensley
Auto Glass is ready" — which would make registrant == sender and resolve contradiction 1 without
per-shop registration. It is the cheapest thing that could clear review.

Rejected on product grounds: a text from an unfamiliar brand about your windshield is worse than
one from the shop you just handed your keys to, and it still has to answer contradiction 2 (the
circular opt-in). Recorded so nobody rediscovers it as a fresh idea.
</details>

---

## 5. If Path A (per-shop customer texts) is taken — what must change

Beyond swapping the brand to the shop's:

- **`optInType` should be `VERBAL`, not `DIGITAL_FORM`.** The real first touch is the customer
  giving their number at the counter and agreeing to service texts. Declaring the digital form is
  what created the circular workflow in contradiction 2. Document the counter script; the
  invoice-page card becomes the *second*, confirming path, not the primary one.
- **Sample 2 (the review request) carries no STOP line.** Every sample should show one.
- **Two fields are now REQUIRED that v4 never submitted** — see §6.

---

## 6. ⚠️ The toll-free schema has changed since v4 — a copy-forward would auto-deny

Diffed 2026-09-16 against the live field definitions:

```
REQUIRED but absent from version 4:
  messagingUseCase.privacyPolicyUrl
  messagingUseCase.termsAndConditionsUrl
```

These became required after v4 was submitted (the same 2026-02-17 tightening wave). Both URLs
exist and can be used as-is: `https://rssystems.io/privacy/` and `https://rssystems.io/terms/`
(`apps/saas/urls.py:29-30`) — for a Path A shop registration they should be the shop's own, if
it has them.

**Re-diff before any future submission.** `scripts/submit_tollfree_registration.py` validates that
every REQUIRED path is non-empty, so it would have caught this — but only at submit time, after
the version was already open.

```bash
aws pinpoint-sms-voice-v2 describe-registration-field-definitions \
  --registration-type US_TOLL_FREE_REGISTRATION --region us-east-1 \
  --query 'RegistrationFieldDefinitions[?FieldRequirement==`REQUIRED`].FieldPath'
```

---

## 7. API traps — all four were paid for

1. **`create-registration-version` opens an EMPTY draft.** It inherits none of the previous
   version's values. Submitting straight after produced an *automated* denial in 3 seconds with no
   human review — that is version 2. Re-`put` every required field first.
2. **Copying a base version copies its mistakes.** Version 3 inherited
   `drake@rockstarwindshield.repair` from the approved *Rockstar* registration, where the domain
   legitimately matched. Under company name RS Systems it matched nothing, and cost a 30-hour
   review cycle. The script now refuses to submit unless the support email's domain equals
   `companyInfo.website`.
3. **Field values are locked while the newest version is denied.** `put-registration-field-value`
   returns `ConflictException EDIT_REGISTRATION_FIELD_VALUES_NOT_ALLOWED` until a new version is
   opened. Denied versions are not fatal; review runs on the newest.
4. **Screenshot the DEFAULT state, not a filled-in one.** The shipping checkbox
   (`templates/billing/public_invoice_view.html:182`) has never carried `checked` and is
   `required` — but v3's screenshot was staged with the box ticked and the description said "a
   checked box" meaning "a box they check". A compliance reviewer read both as pre-selected.
   Render the screenshot from the real template (it carries its own inline `<style>` and extends
   nothing, so a standalone render is pixel-faithful) and assert `checked` does not follow
   `name="sms_agree"` in the rendered HTML:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=2 --window-size=780,900 \
  --screenshot=optin.png file://$PWD/optin_page.html
```

Paid AWS actions are classifier-blocked for Claude — Drake runs them in his own terminal.

---

## 8. Activation checklist — if and when any number clears

1. `eb setenv SMS_ORIGINATION_IDENTITY=+18663115189` against `rs-systems-production`
   (expect a deploy cycle — `eb setenv` triggers the collectstatic confighooks).
   Under Path A a per-shop number becomes a per-tenant field, not this env var.
2. `python manage.py test_sms` to a real cell.
3. **Staff texts turn themselves on, one user at a time:** each owner/tech ticks
   *"Text me urgent job alerts"* at Settings → Notifications, then verifies their mobile.
   `can_send_sms()` requires all three — switch, verified number, consent record — so nobody
   is texted because somebody else ticked a box for them.
4. FIELD_OPS **N2** (tech assignment texts) is then live.
5. **Customer-facing toggles stay off** — Settings → Billing "Text Invoices" and
   Settings → Reviews "Send by Text When Possible" are Path A/C, not this registration.
   Sending a shop-branded text from this number is what got versions 1–4 denied.

---

## 9. What is already built and waiting

Deployed to prod 2026-08-09, dark ever since — PRs #156 (transport, `/sms/` disclosure page,
`manage.py test_sms`), #159 (invoice texts, consent capture, "Also text it" in every send dialog),
#158 (review-request texts, `/r/<token>/` alias, SMS→email fallback), #205 (opt-in card works when
no phone is on file).

None of it is wasted under Path C: the composition, consent storage, opt-in surfaces and toggles
all stand. Only `SMSService`'s transport call is replaced by a deep link.

## 10. What was built for the staff path (2026-09-17)

- **`SMSService.send_sms(phone_number, message, tenant=None)`** now exists. Two shipped
  phone-verification flows had been calling it since 2026-08-09 — it never existed, so both
  raised `AttributeError` into a bare `except` and failed **100% of the time in production**.
  It delegates to `send_notification_sms` so there is still exactly one transport.
- **Both verification callers now gate on `SMSService.is_enabled()`**, not `settings.SMS_ENABLED`.
  The flag alone is not the switch — without an origination identity every send no-ops, and the
  old check told the user their code was on its way when nothing had been sent.
- **A consent record**: `sms_consent_at` + `sms_consent_source` on `BaseNotificationPreference`
  (migration `core/0035`), stamped by the preference forms the first time someone turns texts on,
  and **idempotent** — the original moment is the evidence, so a later save never moves it.
- **`can_send_sms()` now requires all three** — switch, verified phone, consent record — and
  `NotificationService._queue_delivery` routes through it instead of checking the raw fields.
  An owner ticking a tech's box for them is not consent and no longer sends.
- **The consent block at Settings → Notifications** carries message types, frequency,
  "Msg & data rates may apply", STOP/HELP, and links to `/sms/`, the privacy policy and terms.
  **This is the screenshot surface for version 5.**
- **`tests/test_sms_consent_surface.py`** pins it: every required element present, and the
  checkbox asserted unchecked *in the rendered HTML* — because what version 3 was denied for was
  a screenshot of rendered HTML, not a model default.

**Also built (2026-09-17):**
- **`scripts/sms_optin_shot.py`** — regenerates the registration screenshot from the real page,
  with the unchecked-box and full-disclosure assertions baked in (§3.5).
- **`scripts/submit_tollfree_registration.py`** rewritten for the staff scope, with
  `assert_brand_consistency` — the guard that would have caught version 4.

**Still to do:** run the two commands above and file version 5 (Drake — the payload asserts
business facts, including declared monthly volume, that are his to make), then the §8 checklist.

**Unrelated fix that rode along:** `tests.test_notification_surfaces` had a test that built rows
at `now − 1h`/`now − 2h` and asserted a "Today" day-header, so it failed for anyone running the
suite between midnight and ~02:00 local — and since it is absent from the baseline,
`test_guards.sh` reported it as the running session's own regression. Rows are now anchored to
local noon. Verified both ways against `TIME_ZONE='Pacific/Noumea'`, which was at 00:45 at the
time: old code fails, new code passes.

**Related:** [`SES_OPERATIONS.md`](SES_OPERATIONS.md) · `docs/strategy/FIELD_OPS_SESSIONS.md` (N2, N4)

**Sources:** Twilio error [30506](https://www.twilio.com/docs/api/errors/30506) (ISV opt-ins must
reflect the end business) and [30527](https://www.twilio.com/docs/api/errors/30527) (BRN);
[Twilio TFV changelog](https://www.twilio.com/en-us/changelog/we-re-adding-business-registration-numbers-to-toll-free-verifica);
[Bandwidth BRN requirements](https://www.bandwidth.com/support/en/articles/12823241-business-registration-number-requirements-for-toll-free-verification);
AWS [10DLC brand registration](https://docs.aws.amazon.com/sms-voice/latest/userguide/registrations-10dlc-company.html).
