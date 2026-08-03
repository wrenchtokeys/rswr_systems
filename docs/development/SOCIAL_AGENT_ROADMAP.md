# Social Agent Roadmap — Facebook AI Agent for RS Systems

**Status: DEFERRED (not built).** This document captures the complete assessment, design, and implementation plan produced in July 2026 so the project can be picked up cold — by Drake or a future Claude session — without re-deriving any of it.

**Decision (2026-07-28):** Do not build now. Ship the auto-review-email system and second-shop sales work first. Revisit per the triggers in §6.

---

## 1. Vision & Honest Assessment

### The original idea
An AI agent that runs a shop's Facebook presence: generates posts with images, replies to comments, handles Messenger conversations, qualifies leads, and acts as a scheduling middleman — the agent handles customer back-and-forth, then hands a proposed booking to the shop owner for one-tap approval. Build for Rockstar Windshield Repair first (Phase A), productize as an RS Systems Pro/Enterprise feature (Phase B).

### The case FOR
- **The scheduling middleman solves a real problem.** A solo tech under a windshield cannot answer messages, and response speed is arguably the single biggest lead-conversion factor for local service businesses. An agent that replies in 30 seconds at 9pm captures jobs that today evaporate. (Same edge as the deliberately-kept after-hours GBP listing.)
- **Genuine differentiator for RS Systems.** No auto-glass SaaS has this. "Our software runs your Facebook and books jobs while you work" sells itself to non-technical shop owners. Because tenants would connect through RS Systems' single approved Meta app, **Meta app review happens once for the platform, not per shop** — a structural moat.
- **Ideal dogfooding position.** Drake is his own pilot customer, on a page he controls, in Meta Development Mode (zero review friction), with draft-mode approval so nothing embarrassing ships. Edit-rate gives a quantitative quality signal.
- **Trivial model cost.** A busy shop lands at single-digit dollars/month in API cost against Pro-plan pricing — absurd margin.
- **The infrastructure compounds.** Approval queue, action log, tenant-scoped context builder, and intent-execution pattern are the chassis for every future AI feature (GBP posts, review responses, SMS follow-ups).

### The case AGAINST (why it's deferred)
- **Every path to value runs through one unmeasured number:** inbound Messenger volume on the Rockstar page. The agent services demand; it doesn't create it. Organic reach for small business pages without paid spend is brutal, so the posting side won't fix a quiet page.
- **Opportunity cost.** The auto-review-email system (rswr_website repo, `feature/auto-review-emails`) is *built and unshipped* while GBP sits at 3 reviews — days of work aimed at the channel that verifiably brings jobs. RS Systems just became multi-shop ready (PR #131); the bottleneck is signing shop #2, not feature work. The FB agent plan itself gates Phase B on a pilot shop committing — which doesn't exist yet.
- **Effort was underestimated.** The repo has no Celery/Redis/Anthropic SDK; realistic delivery is 5–6 focused days for the Messenger slice alone (the full plan was 3–4+ weeks), plus permanent ops surface: webhooks break silently, tokens expire, Meta changes policy, and an untended approval queue is worse than none.
- **Platform risk.** The whole feature lives at Meta's pleasure.

### Verdict
The **Messenger lead-capture + booking slice is the jewel** — worth ~a week *if the page has real inbound volume*. Posting is vanity until page data says otherwise. Sales-demo value doesn't require live infra (a seeded staging tenant works).

---

## 2. HARD CONSTRAINT: Group-Post Prospecting Is Off the Roadmap

The idea: autonomously find "who does windshield repair in [town]?" posts in local Facebook groups and reply promoting the shop.

**This cannot be built through legitimate means. Do not re-litigate this:**

- Meta **removed public post search** from the Graph API in 2018 (post–Cambridge Analytica).
- The **Groups API was deprecated in April 2024** — apps can no longer read or post to groups.
- A **Page cannot comment on posts outside its own page** via the API.
- The only technical path is scraping + automating a **personal account**, which violates Meta's Terms of Service and realistically risks permanent bans of both Drake's personal account and the Rockstar page — an existential trade for a business that depends on both.

**Legitimate alternatives that capture the same intent:**
1. **Google Local Services Ads** — literally intercepts "windshield repair near me" searches, pay-per-lead.
2. **Meta lead-gen ads** — targeted at auto-owner interests in the service area; leads land in a form or Messenger (where the agent, once built, picks them up).
3. **Manual replies when friends tag the shop** — the resulting Messenger threads land in the page inbox, which the Phase A agent handles automatically.

---

## 3. Phase A — Messenger Lead-Capture Agent (full implementation plan)

**Scope:** Rockstar's tenant only. Meta app in Development Mode (no app review — Drake admins the page). No posting, no comment replies, no Celery/Redis. ~5–6 working days.

**Flow:** customer messages the page → webhook enqueues → cron drain runs one Claude call → agent qualifies the lead (vehicle, chip vs crack, location, timing, photo) and answers FAQs → when ready to book, a BookingProposal goes to the owner (in-app + email) → owner one-tap approves → Customer + `REQUESTED` Repair created in the existing queue + Messenger confirmation sent. Angry/out-of-scope/low-confidence → "Drake will follow up personally" + owner notified. The agent **discloses it is an AI** in its first message of every conversation.

### 3.1 Dependencies + settings
- `requirements.txt`: add `anthropic` and `requests` (**both verified absent** as direct deps, July 2026).
- `rs_systems/settings/base.py` (base.py only, per CLAUDE.md):
  - `'apps.social_agent'` in `INSTALLED_APPS`.
  - Env vars (bare `os.environ.get()`, same idiom as `STRIPE_WEBHOOK_SECRET`): `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_PAGE_ACCESS_TOKEN`, `META_GRAPH_API_VERSION` (default `v21.0` — **verify current stable at build time**), `ANTHROPIC_API_KEY`, `SOCIAL_AGENT_MODEL` (default `claude-sonnet-5` — model IDs live in settings because they change), `SOCIAL_AGENT_ENABLED` (global kill switch, same idiom as `SMS_ENABLED`), `SOCIAL_AGENT_MAX_TOKENS` (default 1000).
- **Secrets stay in env vars via `eb setenv`** — Phase A is single-tenant, so no DB token storage and no new encryption-at-rest story (the repo has none today).

### 3.2 App + models (`apps/social_agent/`)
Layout: `models.py`, `webhooks.py`, `urls.py`, `views.py`, `services/{meta_client,agent_service,booking_service}.py`, `management/commands/process_social_agent_queue.py`, admin registration, migrations. Tenant FK on everything.

- **SocialAgentConfig** — `tenant` OneToOne, `enabled` (per-tenant kill switch, default False), `page_id` (indexed; maps webhook `entry.id` → tenant), `brand_voice` (short text), `knowledge_snippet` (TextField: hours, service area, FAQ — `Tenant` has **no hours or service-area fields**, so this covers them), `daily_message_cap` (default 200, runaway guard). Managed via Django admin in Phase A — no config UI.
- **AgentConversation** — `tenant`, `psid` (unique with tenant), `state` (`qualifying / awaiting_approval / booked / escalated / closed`), `lead_data` JSONField, `last_inbound_at` (drives the 24h window), `customer` FK nullable, `ai_disclosed` bool, `lead_photo` ImageField nullable.
- **AgentMessage** — **doubles as the inbound DB queue**: `conversation` FK, `direction` (`in/out`), `mid` (unique, null for outbound — dedupe via IntegrityError catch), `text`, `attachment_url/type`, `processing_status` (`pending / processed / failed / skipped`), `error`, `created_at`; index `['processing_status','created_at']`.
- **BookingProposal** — `conversation`, `tenant`, lead summary (name, phone, vehicle, damage_type, size, location, preferred_time, notes), `status` (`pending / approved / rejected / expired`), `resolved_by`, `resolved_at`, `repair` FK nullable, duplicate-customer candidate PKs (JSON).
- **AgentActionLog** — append-only audit: `tenant`, `conversation` nullable, `model`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `action` (`agent_call / send / escalate / propose / approve_booking / error`), `error`, `created_at`.

### 3.3 Webhook (enqueue-only, <100ms)
Mount `path('api/social/', include('apps.social_agent.urls'))` → `webhooks/messenger/`. One `@csrf_exempt` view — **no `@require_POST`** (Meta's verification handshake is a GET). Structural template: `apps/billing/webhooks.py` (SES webhook — always-200 after auth, per-handler try/except).

- **GET**: `hub.mode == 'subscribe'` and `hmac.compare_digest(hub.verify_token, settings.META_VERIFY_TOKEN)` → echo `hub.challenge` as plain 200; else 403.
- **POST**: HMAC-SHA256 of the **raw body** with `META_APP_SECRET`, `hmac.compare_digest` against `X-Hub-Signature-256` (strip the `sha256=` prefix); 403 on mismatch, 503 if secret unset. Then per `entry[].messaging[]`: skip `message.is_echo` and delivery/read events; resolve tenant via `SocialAgentConfig.objects.get(page_id=entry['id'], enabled=True)` (**kill-switch gate #1**, plus the global flag); `get_or_create` conversation on (tenant, psid); insert AgentMessage inside `try/except IntegrityError` for `mid` dedupe; update `last_inbound_at`; store first attachment url/type. Always 200 after auth.
- TenantMiddleware skips unauthenticated requests (verified: `apps/tenants/middleware.py:32` returns early; `/api/billing/` webhooks are the working precedent).

### 3.4 `meta_client.py`
Thin `requests` module: `send_text(psid, text)` → `POST https://graph.facebook.com/{ver}/me/messages?access_token=...` with `{recipient:{id}, message:{text}}`; `download_attachment(url)` with a 5MB cap (matches `validate_repair_photo`). **All sends funnel through one function** that re-checks global + per-tenant kill switches (**gate #2**) and the **24-hour Messenger window** (`last_inbound_at`) immediately before the HTTP call; returns a sentinel on refusal so callers notify the owner ("customer replied >24h ago — respond manually from the Page"; a human page reply reopens the window).

### 3.5 `agent_service.py` — one call per message
- `build_system_prompt(tenant, config)` — **the only place prompts are assembled** (the tenant-isolation choke point for Phase B). Stable-first order for prompt caching: persona + hard rules (disclose AI; quote only the price ladder; never promise a slot — only propose; escalate on anger/out-of-scope/insurance complexity/low confidence) → `config.brand_voice` → `config.knowledge_snippet` → tenant context (`name`, `business_phone/email/address`, `services_offered`, price ladder `repair_price_1..repair_price_5_plus` — defaults $50/$40/$35/$30/$25). No timestamps or per-request values in the system prompt; attach `cache_control={"type": "ephemeral"}` (Sonnet 5 minimum cacheable prefix: 1024 tokens; silently no-ops below that).
- Pydantic `AgentTurn(reply_text: str, action: Literal['continue','propose_booking','escalate'], lead: LeadData, confidence: float)`; `LeadData` all-Optional (vehicle_year/make/model, damage_type, size, location, preferred_time, customer_name, phone).
- `run_agent_turn(conversation, msg)`: last ~20 AgentMessages as history (in→user, out→assistant) → `client.messages.parse(model=settings.SOCIAL_AGENT_MODEL, max_tokens=..., system=[...cache_control...], messages=..., output_format=AgentTurn)`. **No `temperature`** (400 on Sonnet 5); adaptive thinking is on by default; `output_config={"effort": "low"}` is appropriate for a qualification chat. Fallback if the installed SDK lacks `parse`: `output_config={"format": {"type": "json_schema", ...}}` + `json.loads`.
- First reply: if `not conversation.ai_disclosed`, prepend the disclosure server-side (belt) in addition to the system-prompt rule (suspenders); set the flag.
- Log `response.usage.{input_tokens,output_tokens,cache_read_input_tokens}` to AgentActionLog. Merge `lead` into `lead_data` (non-null wins).
- On `anthropic.APIError`, parse failure, or `stop_reason != 'end_turn'`: mark the message `failed` / treat as `escalate` — **never send text that didn't validate**.
- Why one Sonnet call, no Haiku triage: a second round-trip adds ~1–2s latency and a second failure mode to save fractions of a cent (messages are ~2–4K input tokens). Classification is just an enum in the schema.

### 3.6 Drain command `process_social_agent_queue`
Copy the CODE-230 pattern **exactly** (`apps/technician_portal/review_service.py:130–230`): collect pending PKs with a cheap unlocked read (oldest first) → per-PK `transaction.atomic()` + `AgentMessage.objects.select_for_update(skip_locked=True).get(pk=..., processing_status='pending')` — `DoesNotExist` means another worker claimed it, skip. (Postgres limitation: `select_for_update` can't combine with `select_related` on nullable FKs — lock first, re-fetch after.) One transaction per item so one failure leaves the rest intact. Per message:
1. Kill-switch re-check → `skipped`.
2. Post-handoff states (`awaiting_approval/escalated/closed`): canned "we'll be in touch" at most (no AI calls after handoff).
3. **Coalesce** rapid-fire texts: if a newer pending inbound exists for the same conversation, mark this one processed — the newest carries the turn (prevents double replies).
4. **Download any attachment now** onto `conversation.lead_photo` — Messenger CDN URLs expire within hours; drain time (≤1 min) is safe, approval time (hours later) is not.
5. `run_agent_turn` → dispatch: `continue` → send + record outbound row · `propose_booking` → BookingProposal + `find_individual_matches(tenant, name, phone)` stashed on it; state `awaiting_approval`; reply "I've sent this to Drake to confirm"; owner notified (§3.7 pattern), email button → approval page · `escalate` (or confidence < 0.5) → state `escalated`, canned reply, owner notified with transcript summary.
6. Daily cap hit → skip + notify owner once.

### 3.7 `booking_service.py` + approval UI
- `approve(proposal, user, customer_id=None)` (atomic): guard `status='pending'` + permission (tenant owner or superuser); `UsageService(tenant).can_create_repair()` first; customer = chosen duplicate match or `create_individual(tenant, name, phone)` (`apps/technician_portal/services/customer_service.py` — creates RETAIL type, absorbs email-unique IntegrityError); technician via `get_available_technician(tenant)` (`apps/customer_portal/views.py:~2186`); then mirror the customer-portal request path (`views.py:~1853`):
  ```python
  Repair.objects.create(
      tenant=tenant, technician=tech, customer=customer,
      unit_number=vehicle_str, description=..., damage_type=mapped,
      customer_notes=f"Preferred time: {preferred_time}\nVia Messenger AI agent",
      customer_submitted_photo=conversation.lead_photo or None,
      queue_status='REQUESTED',
  )
  ```
  Map free-text damage onto the fixed choices (`'Chip','Crack','Star Break',"Bull's Eye",'Combination Break','Half-Moon','Other'`; default `'Other'`). Creating a REQUESTED repair fires existing signals (`apps/technician_portal/signals.py:50+`) that notify the assigned tech — free. Link repair + customer, state `booked`; after commit, send the Messenger confirmation (window/switch enforced).
- `reject(...)`: mark rejected; polite "Drake will reach out directly" if within window; state `closed`.
- **Owner notification pattern** (used for proposals, escalations, window refusals): copy `_notify_shop_replacement_requested` (`apps/customer_portal/views.py:~1765`) — `TechnicianNotification.objects.create(...)` + `send_branded_email(...)` to `tenant.owner.email`, each in its own try/except so notification failure never breaks the flow.
- **UI**: one owner-only list view of pending proposals inside the technician-portal URL space (login/session-tenant plumbing free): lead summary card, duplicate-customer radio options, Approve/Reject POST buttons. Use existing `.btn-*`/`.card*`/`.badge-*` component classes; run `./scripts/build_css.sh` and commit `static/css/app.css` if templates add new utilities.

### 3.8 Tests (`tests/test_social_agent.py`)
Use `create_tenant_with_owner` + `force_login` + `session['tenant_id']` per CLAUDE.md; mock `anthropic` and `requests` throughout. Cover: GET handshake good/bad token · POST signature accept/403/503 · enqueue + `is_echo` skip · `mid` dedupe · kill switches (global and per-tenant) → nothing enqueued, drain sends nothing · drain `continue` → send called + ActionLog token counts · `propose_booking` → proposal + owner notify · approve → Customer + REQUESTED Repair (tenant scoping, usage-limit refusal, duplicate-match reuse) + confirmation send · >24h window → no send + owner notified · escalation path · second drain pass finds nothing (skip_locked smoke).

### 3.9 EB cron
New `.ebextensions/12_social_agent_cron.config` with a **single top-level `files:` key** — ⚠️ `11_billing_cron.config` has two top-level `files:` keys (YAML: the second silently wins); do not copy that bug. 6-field `/etc/cron.d` format with the `webapp` user:
```
* * * * * webapp /bin/bash -c 'source /var/app/venv/*/bin/activate && cd /var/app/current && python manage.py process_social_agent_queue >> /var/log/social-agent.log 2>&1'
```
Plus a bundlelogs entry for `/var/log/social-agent.log`. `skip_locked` makes concurrent runs on multi-instance EB safe.

**Accepted compromise:** up to ~60s reply latency from the 1-minute cron — the cost of no-Celery. Still far faster than a tech under a windshield. Do not process synchronously in the webhook (Meta disables slow webhooks).

### 3.10 Manual Meta setup checklist (Drake)
1. developers.facebook.com → create app, type **Business**. It stays in **Development Mode** — no review; only app admins/developers/testers can message the page, so add Drake's personal FB as admin.
2. Add the **Messenger** product; connect the Rockstar Windshield Repair page; generate a **Page access token**.
3. `eb setenv META_APP_SECRET=<Settings→Basic> META_VERIFY_TOKEN=<random, e.g. secrets.token_urlsafe(32)> META_PAGE_ACCESS_TOKEN=<step 2> ANTHROPIC_API_KEY=<console.anthropic.com> SOCIAL_AGENT_ENABLED=true`
4. Messenger → Webhooks → callback `https://rssystems.io/api/social/webhooks/messenger/`, verify token from step 3 → subscribe to **messages** (`messaging_postbacks` optional) → Subscribe the page.
5. Django admin → create `SocialAgentConfig` for the tenant: `page_id` (Page → About), `enabled=True`, knowledge snippet (hours, service area, FAQ, pricing caveats).
6. Smoke test: message the page from Drake's account; watch `/var/log/social-agent.log` and the AgentActionLog admin.

### Schedule
Day 1: deps/settings + models · Day 2: webhook + meta_client + webhook tests · Day 3: agent_service + drain + tests · Day 4: booking + approval UI + tests · Day 5: cleanup, cron config, setup doc, live E2E against the Meta dev app.

---

## 4. Extensions That DO Bolt On Cleanly (later phases)

- **Own-page posting + comment replies** (the original Phase A1): new event types (`feed` webhook) and a post scheduler on the same chassis — draft-mode approval queue (generalize BookingProposal → ApprovalItem with a `type` field), **log every owner edit** (original vs published text; edit rate is the quality metric and the autopilot-readiness signal). Content angles: chip-repair education, before/after photos from S3 repair documentation, seasonal hooks, review highlights.
- **Instagram** — same Meta app, same architecture.
- **Phase B multi-tenant** (gated on a pilot shop committing): Facebook Login OAuth connect flow in tenant settings → page select → long-lived token exchange → **encrypted per-tenant token storage** (repo has no encryption-at-rest today; Fernet with a key from env would be the new precedent) · one-time Meta app review for RS Systems (the moat — needs business verification, screencasts; expect 1–2+ weeks) · page verification + blank-page setup wizard · per-capability draft/auto modes (default: draft everything) · canary tenant-isolation test suite (seed unique strings per test tenant; assert tenant B's canary never appears in tenant A's output — CI-blocking before Phase B ships) · plan gating (Pro/Enterprise) · edit-rate analytics.
- **Tripwires** (cheap, add with Phase B): daily token spend > N× trailing average, model error-rate spike, complaint keywords, Meta policy warnings → auto-pause tenant + notify.

---

## 5. Why Not Now — Priority Order

1. **Ship `feature/auto-review-emails`** (rswr_website repo — built, unmerged). GBP reviews feed the channel that verifiably brings jobs; Rockstar sits at 3 reviews.
2. **Second-shop sales for RS Systems** — multi-shop readiness shipped (PR #131, 2026-07-28); the bottleneck is a customer, not a feature.
3. Then this, per the triggers below.

## 6. Revisit Triggers

- **Check Meta Business Suite** (5 minutes): Rockstar page Messenger volume + post reach, trailing 90 days. **≈10+ real inquiries/month → build Phase A** (§3). Crickets → stay deferred.
- **A pilot shop asks for social features** → Phase A first on Rockstar if not built, then Phase B.
- A sales demo needs the wow factor → seeded staging tenant with scripted flows, *not* live infra.

## 7. Cost Notes (July 2026 — verify at build time)

- `claude-sonnet-5`: $3/$15 per MTok input/output (intro $2/$10 through 2026-08-31). Realistic Phase A usage (a few hundred message turns/month, ~2–4K input tokens each, prompt-cached system block) lands **well under $10/month**.
- `claude-haiku-4-5` ($1/$5) available if a cheap classification stage is ever wanted — deliberately not used in Phase A (one structured-output Sonnet call is simpler and fast enough).
- Model IDs live in settings/env, never hardcoded — they change.
