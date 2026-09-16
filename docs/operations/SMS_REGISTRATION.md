# SMS registration — why RS Systems cannot text, and what to do instead

**Canonical doc for A2P messaging.** Status, denial history, root cause, and the decision.
Anything else that mentions SMS status (`FIELD_OPS_SESSIONS.md` Appendix A, `ROADMAP.md`,
`PRODUCT_DIRECTION.md`) points here and must not restate a status of its own.

**Last verified against AWS: 2026-09-16** (`aws pinpoint-sms-voice-v2`, us-east-1,
account 973196283632, tier PRODUCTION).

---

## 1. Current state

| Number | Number status | Registration | Usable |
|---|---|---|---|
| `+18663115189` (RS Systems) | **PENDING** | `REQUIRES_UPDATES` — **version 4 DENIED 2026-09-02 18:58 UTC** | **No** |
| `+18559394817` (Rockstar Windshield Repair) | ACTIVE | COMPLETE (approved 2026-07-30, first try) | Yes — Rockstar only |

Four versions submitted, four denied. The number has never been able to send. It has been
leasing at **$2/mo since 2026-08-09** — about **$2.50 of dead spend at time of writing**, which
is not the problem; the two months of blocked feature work is.

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

## 3. Root cause — it is structural, and no fifth version fixes it

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

**Stop resubmitting.** Versions 5, 6 and 7 fail the same way.

---

## 4. The three real paths, with the constraints verified against AWS

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

**Ship Path C as the default for every shop. Offer Path A as an opt-in upgrade** for a shop that
has its own domain and wants unattended texting, and charge the $2/mo through to them.

**Release `+18663115189`.** It is not "pending" — it is unregisterable as specified, because
RS Systems never texts anyone as itself; it always texts as a shop. There is no valid
registration for this number under the current product. Keeping it costs $2/mo to preserve the
illusion that the blocker is a carrier's clock.

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

## 5. If Path A is taken — what must change in the submission

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

1. `eb setenv SMS_ORIGINATION_IDENTITY=<number>` against `rs-systems-production`
   (expect a deploy cycle — `eb setenv` triggers the collectstatic confighooks).
   Under Path A this becomes a per-tenant field, not an env var.
2. `python manage.py test_sms` to a real cell — the invoice-text path is the easiest
   end-to-end check.
3. Flip the shop toggles: Settings → Billing "Text Invoices", Settings → Reviews
   "Send by Text When Possible", and the per-customer "OK to text" checkboxes.
4. FIELD_OPS **N2** (tech assignment texts) becomes unblocked.

---

## 9. What is already built and waiting

Deployed to prod 2026-08-09, dark ever since — PRs #156 (transport, `/sms/` disclosure page,
`manage.py test_sms`), #159 (invoice texts, consent capture, "Also text it" in every send dialog),
#158 (review-request texts, `/r/<token>/` alias, SMS→email fallback), #205 (opt-in card works when
no phone is on file).

None of it is wasted under Path C: the composition, consent storage, opt-in surfaces and toggles
all stand. Only `SMSService`'s transport call is replaced by a deep link.

**Related:** [`SES_OPERATIONS.md`](SES_OPERATIONS.md) · `docs/strategy/FIELD_OPS_SESSIONS.md` (N2, N4)

**Sources:** Twilio error [30506](https://www.twilio.com/docs/api/errors/30506) (ISV opt-ins must
reflect the end business) and [30527](https://www.twilio.com/docs/api/errors/30527) (BRN);
[Twilio TFV changelog](https://www.twilio.com/en-us/changelog/we-re-adding-business-registration-numbers-to-toll-free-verifica);
[Bandwidth BRN requirements](https://www.bandwidth.com/support/en/articles/12823241-business-registration-number-requirements-for-toll-free-verification);
AWS [10DLC brand registration](https://docs.aws.amazon.com/sms-voice/latest/userguide/registrations-10dlc-company.html).
