# Remediation Plan — Full Codebase Audit, 2026-07-09

**Repo:** `rs_systems_branch2` — multi-tenant Django SaaS for auto glass repair shops
**Audit branch:** `fix/customer-email-and-invoice-send`
**Scope:** security, business-logic correctness, dead code, documentation hygiene
**Status:** **EXECUTED 2026-07-10** on branch `fix/audit-remediation-2026-07` — see record below

---

## Execution record — 2026-07-10

One commit per task on `fix/audit-remediation-2026-07` (each cites its ID).
Regression tests in `tests/bug_fixes/test_{a1,a2,a3,a4,a5}_*.py`,
`test_b1_invoice_pdf_tenant_scope.py`, `test_b_security_fixes.py`,
`test_c_billing_secondary.py`, `test_d_workflow_state.py` — every A-task and
B3/B4 verified failing-first.

| Task | Status | Note |
|---|---|---|
| A1–A5 | **FIXED** | A4/A5 via new `InvoiceService.generate_invoice_from_record()` |
| B1 | **FIXED — was live HIGH** | Bucket policy allowed public read on `invoices/*`; policy scoped to `media/*` same day (2026-07-10, backup of old policy retained); app now serves PDFs via ownership-checked views + 300s presigned URLs |
| B2 | **FIXED** | Staff-gated, tenant-scoped, no tracebacks; both diagnostic endpoints DEBUG-only |
| B3 | **FIXED** | POST guard added; full sweep found no other unguarded mutating GET views |
| B4 | **FIXED** | Welcome bonus once per customer_user |
| B5 | **NOT-REPRODUCED** | `CustomerRepairPreference` has no `tenant` field (scoped via `customer` OneToOne); `fields='__all__'` never exposed a tenant FK |
| B6 | **PARTIAL — human** | Key ID scrubbed from CHANGELOG; deleting the root key needs the AWS IAM console |
| C1–C7 | **FIXED** | C2/C3/C7 include migrations billing.0022–0024; C7 also sets production `TIME_ZONE` env-configurable, default `America/Chicago` |
| D1 | **FIXED** | `ALLOWED_STATUS_TRANSITIONS` enforced in `Repair.save()`; COMPLETED terminal |
| D2 | **FIXED** | Sibling propagation via per-repair `save()` |
| D3 | **PARTIAL (option b)** | Quiet hours documented as suppression (in-app notification remains); honest log. Deferred-delivery queue = follow-up |
| D4 | **FIXED** | Email copy corrected (product decision: no trial grace); `unpaid`→`expired`+grace; biweekly epoch-anchored |
| E1–E8 | **DONE** | E5 partial: `repair_form_modern.html`+JS **kept** — audit premise false, live `repair_form.html` references both JS files; `dashboard_visualizations.css` kept (README ref) |
| E9 | **DEFERRED** | Not a pure duplicate (runs in `/var/app/current` at keys 98/99); static machinery changed same day (d431a5ac) — retire deliberately later |
| F1–F7 | **DONE** | F6: `docs/operations/SES_OPERATIONS.md` written; F7 no-op (already current) |
| Data cleanup | **PREPARED — human decision** | `manage.py audit_remediation_data` (read-only) + `scripts/remediation_data_cleanup.sql` (transaction, ROLLBACK by default). Run against a backup, review, then production — AFTER deploying these fixes |

Every finding below was confirmed by reading the actual code path, not by grep alone. Line
numbers were re-verified on 2026-07-09 against the working tree. If a line number has drifted,
locate the code by the quoted snippet rather than trusting the number.

---

## Executive summary

The security posture is strong. Tenant isolation is implemented correctly and consistently
across every app (no cross-tenant IDOR found), Stripe webhooks verify signatures, secrets come
from the environment, there is no SQL injection or XSS, and production settings are hardened.
Prior `CODE-xxx` hardening passes did their job.

**The material risk is billing correctness, not security.** Five high-severity defects silently
corrupt invoiced amounts, systematically underbill customers, lock out paying tenants, or email
the wrong PDF to the wrong customer. These have no compensating control and are firing in
production today.

Fix order: **BILLING-CORE → SEC → BILLING-SECONDARY → WORKFLOW → CLEANUP → DOCS.**

| Workstream | Findings | Severity ceiling | Est. |
|---|---|---|---|
| A — Billing correctness (core) | 5 | HIGH | 1–2 days |
| B — Security | 6 | HIGH (1 pending verification) | 0.5 day |
| C — Billing correctness (secondary) | 7 | MEDIUM | 1 day |
| D — Workflow & state machine | 4 | MEDIUM | 0.5 day |
| E — Dead code & repo hygiene | ~25 files | — | 0.5 day |
| F — Documentation | ~15 files | — | 0.5 day |

---

## THE PROMPT — paste this into a fresh Fable 5 session

> Copy everything between the fences into a new Claude Code session opened at the repo root.
> It is written to be self-sufficient with zero prior context.

```
You are Claude Fable 5 working in /Users/drakeduncan/projects/rs_systems_branch2, a
multi-tenant Django SaaS for auto glass repair shops (production: rssystems.io, AWS
Elastic Beanstalk). Read CLAUDE.md first — it is authoritative on commands, settings
layout, and testing patterns.

Your task: execute the remediation plan in docs/development/REMEDIATION_PLAN_2026-07-09.md.

## Non-negotiable ground rules

1. READ BEFORE YOU EDIT. Every finding cites file:line plus a quoted snippet. Open the
   file, confirm the snippet is still there, and confirm the defect is real. Line numbers
   may have drifted. If a finding does not reproduce, mark it NOT-REPRODUCED in the plan
   and move on. Do not "fix" code you have not read.

2. MONEY CODE IS LOAD-BEARING. Workstream A changes how repairs are priced and how
   invoices are generated. A wrong fix here silently corrupts customer billing, which is
   worse than the bug. For every A-task: write a failing regression test FIRST, watch it
   fail, then fix, then watch it pass. No exceptions.

3. NEVER WIDEN A QUERYSET. This codebase's core invariant is that every query touching
   tenant-owned data (Repair, Invoice, Customer, Vehicle, RewardOption, Technician,
   Payment) is scoped to request.tenant. Prior audits found zero IDOR bugs. Do not be the
   one who introduces the first. If a fix requires a new query, scope it to the tenant.

4. DECIMAL, NEVER FLOAT, for money. Billing already does this correctly throughout.
   Preserve it. float() only at JSON-serialization edges.

5. ONE COMMIT PER TASK, referencing the task ID (e.g. "A1: Stop re-pricing completed
   repairs on re-save"). Small, reviewable, revertible. Do not bundle workstreams.

6. VERIFY, DON'T ASSUME. After each workstream, run the targeted tests named in the task.
   Report actual output. If tests fail, say so with the output — never claim a fix works
   because it "should."

7. DO NOT DEPLOY. Do not run `eb deploy`. Do not push to main. Do not force-push. Commit
   to a working branch only.

## Environment

    export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
    export DJANGO_SETTINGS_MODULE=rs_systems.settings.development

    python manage.py test tests.test_primary_contact tests.test_e2e_today -v 2   # fast smoke
    python manage.py test tests/ -v 1                                            # full, ~7 min

Test-writing patterns that WILL bite you if ignored (all documented in CLAUDE.md):
  - Username is generated from first_name, NOT email. Always client.force_login(user);
    client.login(username=email) silently fails.
  - Set session['tenant_id'] = tenant.id or SubscriptionEnforcementMiddleware redirects to /login/.
  - Any test asserting on tax MUST create a TaxRate for the tenant, else TaxService sets
    tax_rate=0 and your assertion is vacuous.
  - RewardOption needs tenant=self.tenant to be visible to tenant-filtered API views.
  - Tests live in tests/ (top level), not apps/*/tests.py.

## Before you start

The working tree has ~27 uncommitted modified files from an in-flight SendGrid→SES
migration, plus two untracked files. Run `git status`. Commit or stash that work on its
own branch BEFORE starting remediation, so audit fixes do not tangle with it. Confirm a
clean tree, then branch: `git checkout -b fix/audit-remediation-2026-07`.

## Order of execution — do not reorder

  Workstream A (billing core, HIGH)  — 5 tasks. Blocking. Do these first.
  Workstream B (security)            — 6 tasks. B1 needs an AWS console check; see task.
  Workstream C (billing secondary)   — 7 tasks.
  Workstream D (workflow/state)      — 4 tasks.
  Workstream E (dead code)           — mechanical. Safe to parallelize.
  Workstream F (docs)                — mechanical. Safe to parallelize.

A and C both touch apps/billing/services/. Do not run them concurrently in worktrees;
they will conflict. E and F touch disjoint file sets and may be parallelized with
anything.

## How to delegate

Workstreams A–D are reasoning-heavy and money-critical: do them yourself, sequentially,
in the main context. Workstreams E and F are mechanical and independent — dispatch them
to subagents in parallel via the Agent tool, one agent per workstream, using the task
text verbatim as the prompt.

## Definition of done

  - Every task is either committed with a regression test, or explicitly marked
    NOT-REPRODUCED / DEFERRED with a one-line reason in the plan file.
  - `python manage.py test tests/ -v 1` passes, or every failure is a pre-existing
    failure you have identified as pre-existing by checking out the base commit and
    confirming it fails there too. Do not paper over a new failure.
  - `git log --oneline` shows one clean commit per task.
  - You write a short completion report: what was fixed, what was not, what surprised you,
    and what still needs a human decision (especially B1 and B6, which require AWS console
    access you do not have).

Begin by reading CLAUDE.md and docs/development/REMEDIATION_PLAN_2026-07-09.md in full,
then run `git status` and report what you find before making any change.
```

---

# WORKSTREAM A — Billing correctness (core)

**Severity: HIGH. These are actively corrupting billing data.** Do these first, in order.
Every task requires a failing-test-first workflow.

---

### A1 — Completed repairs are silently re-priced on any re-save

- **File:** `apps/technician_portal/models.py:792-816` (in `Repair.save()`)
- **Severity:** HIGH — corrupts already-invoiced amounts
- **Verified:** yes, read directly

**Evidence.** The first-transition guard protects only the counter increment, not the cost
recalculation beneath it:

```python
if self.queue_status == 'COMPLETED':
    if not self.pk or (self.pk and self.original_status != 'COMPLETED'):
        if not skip_progressive:
            unit_repair_count.repair_count += 1     # guarded
            unit_repair_count.save()

    if self.cost_override is not None:
        self.cost = self.cost_override
    elif self.pk and is_multi_break and self.cost:
        pass                                        # only multi-break is exempt
    else:
        self.cost = calculate_repair_cost(self.customer, unit_repair_count.repair_count)
        # ^^^ UNGUARDED: recomputes on EVERY save of an already-COMPLETED repair
```

**Failure scenario.** A fleet unit has 3 completed repairs, priced $50 / $40 / $35 by
progressive pricing. A manager opens repair #1 to attach an after-photo. The edit path
(`apps/technician_portal/views/repairs.py:607`) calls a full `updated_repair.save()`.
`queue_status` is still `COMPLETED`, `original_status` is `COMPLETED`, so the increment is
skipped — but the `else` branch fires and recomputes `cost = calculate_repair_cost(customer,
repair_count=3)` → **$35**. Repair #1's cost silently changes from $50 to $35, diverging from
the invoice line item already sent to the customer. Revenue reporting is now wrong.

Every re-save path triggers this: the edit form, a `COMPLETED`→`COMPLETED` status post, and the
Django admin.

**Fix.** Price a repair exactly once, on the transition into `COMPLETED`. Extend the existing
first-transition guard to cover the pricing block, not just the increment. `cost_override` must
still apply on any save (an owner correcting a price must work). Sketch:

```python
is_first_completion = not self.pk or self.original_status != 'COMPLETED'

if self.queue_status == 'COMPLETED':
    if is_first_completion and not skip_progressive:
        unit_repair_count.repair_count += 1
        unit_repair_count.save()

    if self.cost_override is not None:
        self.cost = self.cost_override
    elif not is_first_completion:
        pass                       # already priced; never re-price
    elif is_multi_break and self.cost:
        pass                       # batch pricing set at creation
    else:
        ...calculate...
```

Note this makes the `is_multi_break` special-case largely redundant — that branch existed only
to paper over this same bug for batches. Leave it in (harmless, and it guards the creation
path) but add a comment explaining the redundancy.

**Regression test** (`tests/bug_fixes/test_a1_no_repricing_on_resave.py`):
1. Create tenant + customer with progressive pricing enabled + a `TaxRate`.
2. Complete 3 repairs on the same `unit_number`. Assert costs are 50/40/35.
3. Re-save repair #1 unchanged (`r1.save()`), and again via the edit view.
4. Assert `r1.cost` is **still 50** and `UnitRepairCount.repair_count` is **still 3**.

**Data cleanup.** Before deploying, size the existing damage:

```sql
SELECT r.id, r.cost, li.unit_price
FROM technician_portal_repair r
JOIN billing_invoicelineitem li ON li.repair_id = r.id
WHERE r.cost <> li.unit_price;
```

Any row is a repair whose cost drifted after invoicing. Decide with the owner whether to
back-fill `repair.cost` from the invoice line item (the invoice is what the customer actually
paid, so it is the source of truth).

---

### A2 — `convert_to_batch` double-increments `UnitRepairCount`

- **File:** `apps/technician_portal/views/batch.py:741` + `apps/technician_portal/models.py:795-797`
- **Severity:** HIGH — systematic underbilling
- **Verified:** yes

**Evidence.** `convert_to_batch` increments at creation time:

```python
new_repair.save()
created_repairs.append(new_repair)

unit_count.repair_count += 1      # batch.py:741 — increment #1
unit_count.save()
```

Then `Repair.save()` increments **again** when each break transitions to `COMPLETED`. Multi-break
repairs are exempt from *re-pricing* (`models.py:802`) but **not** from the *increment*
(`models.py:795`). With the `mark_completed` checkbox on (`batch.py:748`, CODE-248), both fire in
the same request.

**Failure scenario.** Convert 1 repair + add 2 breaks on a fresh unit with `mark_completed`
checked → `repair_count` ends at **5**, not 3. The next real repair on that unit is priced as
repair #6 → **$25 floor instead of $30**. Permanent, compounding underbilling on that unit.

`create_multi_break_repair` does *not* pre-increment — it correctly relies on completion-time
increments only. The two batch flows disagree; that inconsistency is the bug.

**Fix.** Delete the manual increment at `batch.py:741-742` and let `Repair.save()` own the
counter, matching `create_multi_break_repair`. Verify that batch pricing
(`calculate_batch_pricing()`) is computed from the pre-increment count at creation, which it
already is.

**Regression test** (`tests/bug_fixes/test_a2_convert_to_batch_count.py`):
1. Fresh unit, one repair. Convert to batch adding 2 breaks, `mark_completed='on'`.
2. Assert `UnitRepairCount.repair_count == 3`.
3. Assert the three repair costs are 50/40/35.
4. Complete a 4th repair on that unit; assert cost is **30**, not 25.

**Data cleanup.** `UnitRepairCount` rows are now inflated for any unit that went through
`convert_to_batch`. Recompute authoritatively:

```sql
UPDATE technician_portal_unitrepaircount u
SET repair_count = (
  SELECT COUNT(*) FROM technician_portal_repair r
  WHERE r.customer_id = u.customer_id
    AND r.unit_number = u.unit_number
    AND r.queue_status = 'COMPLETED'
);
```

Run this **after** A1 and A2 ship, in a transaction, on a backup first.

---

### A3 — Stale `grace_period_end` locks out paying tenants (CODE-130 regression)

- **Files:** `apps/tenants/webhooks.py:392` (only setter), `apps/tenants/subscription_middleware.py:129` (reader)
- **Severity:** HIGH — paying customers lose access to their shop
- **Verified:** yes — grepped every read/write of `grace_period_end`; **nothing ever clears it**

**Evidence.** Set on subscription deletion:

```python
# webhooks.py:392, in _handle_subscription_deleted
tenant.grace_period_end = timezone.now() + timezone.timedelta(days=30)
```

Read by the middleware:

```python
# subscription_middleware.py:129
canceled_is_active = status == 'canceled' and not tenant.grace_period_end
```

The only other writer is the admin (`apps/tenants/admin.py:174`). `_handle_checkout_completed`
sets `subscription_status` and `plan` on resubscribe but **never clears `grace_period_end`**.

**Failure scenario.**
1. Tenant's subscription lapses → webhook sets `grace_period_end = now + 30d`, status `expired`.
2. Tenant resubscribes → `_handle_checkout_completed` sets status `active`. `grace_period_end`
   is left pointing at a date now in the past. Nothing notices, because active tenants never
   read that field.
3. Months later the owner clicks "Cancel at period end" → `subscription_service.py:371` sets
   status `canceled`. They have paid days remaining and should retain access.
4. Middleware: `canceled_is_active = 'canceled' and not <stale timestamp>` → **False**. And
   because the timestamp is long past, `is_in_grace_period` is also False.
5. **Immediate full lockout** despite a paid, unexpired subscription. Exactly the bug CODE-130
   claimed to fix.

**Fix.** Two parts, both required:
1. **Clear on reactivation.** In `_handle_checkout_completed` and any other path that moves a
   tenant to `active`/`trialing` (grep for `subscription_status = 'active'`), set
   `tenant.grace_period_end = None` and include it in `update_fields`.
2. **Make the middleware robust.** A stale past timestamp should not be treated as "grace was
   granted." Prefer `effective_grace_period_end` (`models.py:352`) and compare against
   `timezone.now()`, rather than testing the raw field for truthiness. A grace period that
   ended in the past is equivalent to no grace period for the `canceled_is_active` decision —
   but be careful: for a genuinely `expired` tenant, a past `grace_period_end` must still mean
   "blocked." Encode the state table explicitly and test all four quadrants.

**Regression test** (`tests/bug_fixes/test_a3_grace_period_reactivation.py`):
1. Tenant → `_handle_subscription_deleted` → assert `grace_period_end` set.
2. → `_handle_checkout_completed` → assert `grace_period_end is None` and status `active`.
3. Fast-forward past the old grace date, set status `canceled` via `subscription_service`.
4. Assert middleware **allows** the request (paid days remain).
5. Separately: an `expired` tenant with a past `grace_period_end` is still **blocked**.

**Data cleanup.** Find tenants carrying a stale timestamp right now:

```sql
SELECT id, name, subscription_status, grace_period_end
FROM tenants_tenant
WHERE grace_period_end IS NOT NULL
  AND subscription_status IN ('active','trialing');
```

Null those out. They are ticking time bombs that fire on the owner's next cancellation.

---

### A4 — Replacement-only / manual invoices can never be sent, or send the wrong PDF

- **Files:** `apps/billing/services/invoice_email_service.py:308-320`; `apps/saas/views.py:2908,2922`
- **Severity:** HIGH — customer receives another customer's repair data; or invoice is unsendable
- **Verified:** yes

**Evidence.** The PDF builder sources line items exclusively from completed *repairs*.
`owner_send_invoice` passes `repair_ids=None` when the invoice has no repair line items —
which is exactly the case for replacement-only invoices created by
`apps/billing/tasks.py::_create_batch_invoice`. With `repair_ids=None`, the service falls back
to a 30-day completed-repair lookback for that customer.

**Failure scenario.** Two branches, both bad:
- Customer has **no** repairs in the last 30 days → `"No completed repairs found for
  invoicing"` → the invoice is stuck in `DRAFT` **forever**. The shop cannot bill for a
  windshield replacement.
- Customer **does** have recent repairs → the emailed PDF contains **unrelated repair line
  items and their amounts**, bearing no relation to the invoice being sent. The invoice is then
  marked `SENT`. The customer is billed for the wrong work.

**Fix.** `send_invoice_email` must render the PDF from the **invoice's own line items**, not by
re-querying repairs. The `Invoice` already has `line_items` with `description`, `quantity`,
`unit_price`. Add a code path that serializes an existing `Invoice` → PDF directly, and use it
whenever the invoice exists (which, in `owner_send_invoice`, is always). The repair-lookback
path should only ever be used for *generating a new* invoice, never for *sending an existing*
one.

This is the deepest fix in the plan — it is a design flaw, not a typo. Budget accordingly.
Coordinate with A5, which shares the root cause.

**Regression test** (`tests/bug_fixes/test_a4_replacement_invoice_send.py`):
1. Customer with a replacement-only invoice (line items, `repair_id IS NULL`) **and** an
   unrelated completed repair from 5 days ago.
2. Call `owner_send_invoice`.
3. Assert the invoice moves to `SENT`.
4. Assert the PDF total equals the **invoice** total, and that the unrelated repair's
   description does **not** appear in the PDF bytes.

---

### A5 — Reminder emails attach a regenerated, mismatched PDF

- **File:** `apps/billing/services/reminder_service.py:92-103`
- **Severity:** HIGH — customer receives a PDF billing them for every repair they have ever had
- **Verified:** yes, read directly

**Evidence.**

```python
invoice_service = InvoiceService(tenant=invoice_tenant)
repair_ids = list(invoice.line_items.exclude(repair_id__isnull=True).values_list('repair_id', flat=True))
pdf_bytes, _ = invoice_service.generate_invoice(
    customer_id=invoice.customer_id,
    repair_ids=repair_ids if repair_ids else None,
)
```

`generate_invoice()` is called **without** `invoice_number=`, `invoice_date=`, or
`invoice_status=`. Those override parameters exist precisely for this case, and
`apps/saas/views.py` passes them correctly (per CODE-120). Here they are omitted.

**Failure scenario.** The attached PDF is freshly minted: a **new** invoice number
(`INV-<cust>-<timestamp>`), **today's** date, and amounts/tax **recomputed from current rates** —
none of which match the invoice named in the reminder's email body. The customer sees a dunning
letter for `INV-ACME-001` with a PDF for `INV-ACME-1752019200` at a different total.

Worse: for an invoice with **no repair-backed line items** (replacement-only), `repair_ids`
is `None`, and the fallback in this call site has **no date filter** — so
`get_completed_repairs` runs unbounded and the PDF bills **every completed repair in the
customer's history**.

> **Verify before fixing:** confirm the default lookback behavior of
> `InvoiceService.generate_invoice()` / `get_completed_repairs()` when `repair_ids=None` and no
> date range is supplied. The audit found it unbounded here, in contrast to
> `invoice_email_service.py`'s explicit 30-day window. Read both call sites side by side.

**Fix.** Same root cause as A4. Once A4 lands a "render this existing Invoice to PDF" path, call
it here. Until then, at minimum pass `invoice_number=invoice.invoice_number`,
`invoice_date=invoice.invoice_date`, `invoice_status=invoice.status`, and never call with an
unbounded repair query.

**Regression test** (`tests/bug_fixes/test_a5_reminder_pdf_matches_invoice.py`):
1. Invoice `INV-X-001` dated 60 days ago, one line item; customer has 5 older completed repairs.
2. Trigger the overdue reminder.
3. Assert the PDF contains `INV-X-001`, the original invoice date, and the original total.
4. Assert the PDF does **not** contain the 5 unrelated repairs.

---

# WORKSTREAM B — Security

Tenant isolation, webhook signature verification, secrets management, injection, and settings
hardening were all audited and found **clean**. The findings below are the residual issues.

---

### B1 — Invoice PDFs served via unsigned, enumerable S3 URLs

- **Files:** `apps/billing/models.py:564-592` (`Invoice.get_pdf_url`);
  `apps/billing/services/invoice_storage_service.py:85-88` (key format), `:253` (**unused**
  `generate_presigned_url`)
- **Consumers:** `templates/saas/owner_invoice_detail.html:28`,
  `templates/customer_portal/invoice_detail.html:283`
- **Severity:** **HIGH if the bucket allows public read on `invoices/*`; otherwise MEDIUM (broken links).**
- **Verified:** code confirmed. Bucket policy **not** verified — requires AWS console.

**Evidence.** `get_pdf_url()` returns a raw, unsigned URL:

```python
return f"https://{bucket}.s3.{region}.amazonaws.com/{self.s3_key}"
```

and the key is fully predictable: `invoices/{customer_id}/{year}/{invoice_number}.pdf`.

`rs_systems/settings/production.py:72` sets `AWS_DEFAULT_ACL = None`, meaning objects inherit
the bucket default rather than being explicitly public. So the exposure hinges entirely on the
**bucket policy**, which the audit could not read.

**Exploit (if public).** An unauthenticated attacker enumerates `customer_id` and sequential
invoice numbers and downloads **any tenant's invoices** — customer names, addresses, line items,
amounts — straight from S3. No login, no tenant check, no application log.

**Action — do this first, it decides the severity:**

```bash
aws s3api get-bucket-policy --bucket "$AWS_STORAGE_BUCKET_NAME"
aws s3api get-public-access-block --bucket "$AWS_STORAGE_BUCKET_NAME"
aws s3api get-object-acl --bucket "$AWS_STORAGE_BUCKET_NAME" --key "invoices/<known_id>/2026/<inv>.pdf"
```

- If `invoices/*` is publicly readable → **treat as a live data breach.** Lock the prefix
  immediately, then assess exposure from S3 access logs / CloudTrail.
- If private → the current download links are simply **broken in the browser** (403). Still fix.

**Fix (required either way).** Replace `get_pdf_url()` usage in both templates with a
short-TTL presigned URL generated by the already-written, currently-unused
`invoice_storage_service.generate_presigned_url` (`:253`). Serve it through a view that
**enforces tenant scoping and ownership** before minting the URL — a customer-portal user may
fetch only their own company's invoices; an owner only their own tenant's. Do not hand the
presigned URL to the template without that check; presigning authorizes S3, not your app.

**Regression test:** a `customer_portal` user of tenant A requests tenant B's invoice PDF view →
404/403, and no presigned URL is minted.

---

### B2 — `/test-notification/` leaks cross-tenant data and stack traces

- **File:** `core/views/test_notification.py:8` (decorator), `:64` (unscoped query)
- **Route:** `rs_systems/urls.py:50` — live in production URLs
- **Severity:** MEDIUM
- **Verified:** yes — decorator is `@login_required` only, **not** staff-gated

**Evidence.**

```python
@login_required                       # line 8 — that is the ONLY gate
def test_notification(request):
    ...
    repair = Repair.objects.first()   # line 64 — no tenant scoping
    context = {
        'unit_number': repair.unit_number,
        'customer_name': repair.customer.name if repair.customer else 'Test Customer',
        'estimated_cost': float(repair.cost) if repair.cost else 0.0,
        ...
    }
```

and the error path returns `traceback.format_exc()` in the JSON response.

**Exploit.** Any authenticated user — including a tenant-A customer-portal user — hits
`/test-notification/` and reads an arbitrary repair's customer name, unit number, and cost. With
default PK ordering that is the **oldest repair in the entire system**, i.e. almost certainly
another tenant's. The endpoint also lets any user trigger on-demand emails to themselves, and
leaks internal stack traces on error.

**Fix.** Three changes: gate with `@staff_member_required` (matching the sibling `email_preview`
view, which is already correctly gated); scope the sample repair to `request.tenant`; remove
`traceback.format_exc()` from the response body and log it server-side instead. Apply the same
treatment to `/check-notification-prefs/` (`urls.py:51`) — audit it for the same pattern.

Strongly consider removing both diagnostic endpoints from production `urlpatterns` entirely and
mounting them only when `settings.DEBUG`.

---

### B3 — State-changing batch action reachable via GET (CSRF)

- **File:** `apps/technician_portal/views/batch.py:116` (`technician_batch_start_work`), routed
  at `apps/technician_portal/urls.py:37`
- **Severity:** LOW
- **Verified:** yes — decorators are `@technician_required` + `@transaction.atomic`; **no** `@require_POST`

**Evidence.** The view transitions repairs `APPROVED → IN_PROGRESS` and calls `repair.save()`,
but has no HTTP-method guard, so it executes on `GET` — bypassing CSRF protection entirely. Its
sibling `batch_complete_all` (`batch.py:174`) **is** correctly guarded, which makes this an
oversight rather than a design choice.

**Exploit.** `<img src="https://rssystems.io/tech/batch/<uuid>/start-work/">` on any page a
logged-in technician visits flips that batch to `IN_PROGRESS`. Mitigated by the `batch_id` being
a UUIDv4 (unguessable), tenant-scoped, with a per-repair ownership guard — so it is a
low-value, own-shop status flip, not a cross-tenant write.

**Fix.** Add `@require_POST`. Update any template link that triggers it to a form POST. Then
sweep all of `apps/technician_portal/views/` and `apps/saas/views.py` for other state-changing
views missing a method guard — `git grep -n "def .*(request" | xargs` and check each that calls
`.save()` / `.delete()` / `.update()`.

---

### B4 — Referral "referred" bonus is farmable within a tenant

- **Files:** `apps/rewards_referrals/views.py:174-216`; `apps/rewards_referrals/services.py:407-460`
- **Severity:** LOW (in-tenant point inflation; **not** an isolation break)
- **Verified:** yes

**Evidence.** `process_referral` correctly blocks self-referral, cross-tenant referral, and
duplicate `(code, customer_user)` pairs. It does **not** block one user claiming the one-time
welcome bonus repeatedly using **different coworkers'** codes.

**Fix.** Grant the referred-side bonus at most once per `customer_user`: before awarding, check
for an existing `referral_received` reward transaction for that user and short-circuit if
present. Keep the referrer-side award as-is (a referrer legitimately earns per referral).

**Regression test:** user redeems codes from three distinct coworkers → exactly one
`referral_received` transaction; all three referrers still receive their referrer bonus.

---

### B5 — `fields = '__all__'` on a tenant-scoped admin ModelForm

- **File:** `apps/customer_portal/admin.py:189`
- **Severity:** LOW (staff-only surface)
- **Verified:** yes

**Evidence.** `CustomerRepairPreference`'s admin form declares `fields = '__all__'`, which makes
the `tenant` FK editable — a staff user can reassign a preference row to another tenant.

**Fix.** `exclude = ['tenant']`, or enumerate fields explicitly. Then grep the whole repo for
other `'__all__'` on tenant-scoped models: `git grep -n "fields = '__all__'"`. The audit found
this to be the only one, but re-verify after any merge.

---

### B6 — Root AWS access key ID referenced in a tracked doc

- **File:** `docs/development/CHANGELOG.md:35`
- **Severity:** LOW as committed (**ID only, no secret**), but flags a possible live root key
- **Verified:** yes — the ID is present; the referenced credentials file is **not** tracked

**Evidence.** The changelog names a root AWS access key ID (`AKIA…`) as a rotation to-do. An
access key ID is not itself a credential. The application correctly uses a scoped
`rs-systems-ses-user`, not root.

**Action (human, requires AWS console).** Confirm in IAM that this **root** access key was
actually rotated or, better, **deleted** — root account access keys should not exist at all.
Then scrub the ID from the changelog (rewrite the line, keep the historical entry). If the key
is still live, treat as an incident: delete it, audit CloudTrail for its use.

---

# WORKSTREAM C — Billing correctness (secondary)

---

### C1 — Malformed custom reminder template → email sent with an empty body

- **File:** `apps/billing/services/reminder_service.py:73-85` + `:314-327`
- **Severity:** MEDIUM
- **Verified:** yes, read directly

**Evidence.** `_render_template()` deliberately returns `''` on a malformed template "so callers
fall back to the default." The caller does not fall back:

```python
subject, body = self._build_reminder_email(invoice, reminder_type)   # good default body
if custom_body:
    body = custom_body
elif self.tenant:
    config = BillingConfig.get_for_tenant(self.tenant)
    if config.reminder_email_template:
        body = self._render_template(config.reminder_email_template, invoice)  # <-- may be ''
```

The default body computed one line earlier is **overwritten with the empty string**, and a blank
dunning email is sent to the customer. Contrast `invoice_email_service.py:392`, which correctly
guards with `if not body:`.

**Fix.** `rendered = self._render_template(...)` then `if rendered: body = rendered`. Mirror the
`invoice_email_service.py` pattern exactly.

**Regression test:** tenant with `reminder_email_template = "Hi {custome"` (stray brace) →
reminder sends with the **default** body, non-empty, and a warning is logged.

---

### C2 — Stripe payment dedup is check-then-create (double-credit race)

- **File:** `apps/billing/services/stripe_service.py:424-426`
- **Severity:** MEDIUM
- **Verified:** yes

**Evidence.**

```python
if invoice.payments.filter(stripe_payment_id=stripe_payment_id).exists():
    return {'success': True, 'duplicate': True}
```

An unlocked `.exists()` check, with **no unique constraint** on `Payment.stripe_payment_id`.

**Failure scenario.** Stripe fires both `checkout.session.completed` and
`payment_intent.succeeded` for the same card payment, carrying the same `pi_…` id. Delivered
concurrently (Stripe does this, and retries on timeout), both requests pass the `.exists()`
check before either inserts. Two `Payment` rows → `amount_paid` doubled → invoice marked `PAID`
with a phantom overpayment.

**Fix.** Add a DB-level guarantee, which is the only thing that actually closes the race:
a migration adding `unique=True` (or a partial unique index where `stripe_payment_id IS NOT
NULL`) on `Payment.stripe_payment_id`. Then wrap the record in `get_or_create` /
`transaction.atomic` + `IntegrityError` catch, returning `{'duplicate': True}` on conflict.
Back-fill: find and merge existing duplicate rows **before** applying the constraint, or the
migration will fail on production data.

```sql
SELECT stripe_payment_id, COUNT(*) FROM billing_payment
WHERE stripe_payment_id IS NOT NULL
GROUP BY stripe_payment_id HAVING COUNT(*) > 1;
```

---

### C3 — Automated overdue reminders: no same-day dedup, and skipped on missed cron days

- **File:** `apps/billing/tasks.py:76-91` (`_send_overdue_reminder` call site)
- **Severity:** MEDIUM
- **Verified:** yes

**Evidence.**

```python
days_overdue = (today - invoice.due_date).days
if days_overdue in reminder_days:            # exact-match membership test
    sent = _send_overdue_reminder(invoice, config, days_overdue)
```

`_send_overdue_reminder` writes to `internal_notes` but never reads it — unlike
`ReminderService.process_overdue_reminders`, which does check.

**Two failure modes.**
- **Duplicates:** running the command twice in a day (a manual run plus the cron, or a cron
  retry) emails the customer the same reminder twice.
- **Silent misses:** `days_overdue in reminder_days` is an exact match. If the cron does not run
  on the day an invoice hits exactly 7 days overdue (deploy, outage, DST), that reminder tier is
  **never** sent — the invoice jumps past it.

**Fix.** Record the last-sent tier on the invoice (a real column beats parsing `internal_notes` —
consider `last_reminder_days_overdue = IntegerField(null=True)`), then send when
`days_overdue >= tier` and `tier > last_sent_tier`. That makes the job **idempotent** (safe to
run twice) and **catch-up** (a missed day still sends). Reuse `ReminderService`'s dedup logic
rather than maintaining two implementations — ideally, delete this duplicate path and call the
service.

---

### C4 — Tax rate lookup ignores customer location

- **File:** `apps/billing/services/tax_service.py:64-75`
- **Severity:** MEDIUM
- **Verified:** yes

**Evidence.**

```python
def _get_tenant_default_tax_rate(self, tenant):
    """Get the default (most recently created active) TaxRate for this tenant."""
    return (TaxRate.objects
            .filter(tenant=tenant, is_active=True)
            .order_by('-effective_date', '-id')
            .first())
```

Returns the newest active rate regardless of the customer's city/state — despite the `TaxRate`
model's own docstring specifying "Lookup by city+state when calculating invoice tax."

**Failure scenario.** A shop serving Little Rock (6.5%) and North Little Rock (7.0%) charges
**every** customer whichever rate was added most recently. Under-collection is a liability the
shop eats; over-collection is a refund and a compliance problem.

**Fix.** Resolve by the customer's `city` + `state` first, falling back to a state-level rate,
then to the tenant default. Preserve the existing "no rate → tax 0" behavior (CLAUDE.md documents
it and tests depend on it). Note `Repair.save()` calls `TaxService(tenant=…).calculate_tax()`, so
this fix interacts with A1 — land A1 first, or completed repairs will be re-taxed on re-save.

---

### C5 — `UnitRepairCount` increments are non-atomic

- **Files:** `apps/technician_portal/models.py:796-797`; `apps/technician_portal/views/batch.py:741`
- **Severity:** MEDIUM (LOW after A2 removes the second call site)
- **Verified:** yes

**Evidence.** Plain read-modify-write with no `F()` expression and no `select_for_update()`:

```python
unit_repair_count.repair_count += 1
unit_repair_count.save()
```

**Failure scenario.** Two technicians complete repairs on the same unit concurrently. Both read
`repair_count = 2`, both write `3`. One increment is lost: both repairs are priced at the same
tier, and the counter is permanently understated → every future repair on that unit is
overpriced by one tier.

**Fix.** `select_for_update()` on the `UnitRepairCount` row inside the existing
`transaction.atomic` block (you need the post-increment value to price with, so `F()` alone is
insufficient — you would have to `refresh_from_db()`). Confirm `Repair.save()` is always called
within a transaction; if not, wrap it.

---

### C6 — Auto-invoice swallows the Invoice-record failure, then emails anyway

- **File:** `apps/billing/services/auto_invoice_service.py:155-157`, email at `:172-181`
- **Severity:** MEDIUM — leads to double billing
- **Verified:** yes

**Evidence.**

```python
except Exception as e:
    # Log but don't fail - PDF was generated successfully
    logger.warning(f"Could not create invoice record: {e}")
```

Execution continues: the PDF is uploaded to S3 and **emailed to the customer**, but no `Invoice`
row exists.

**Failure scenario.** The customer receives and pays an invoice that the system has no record
of. Because no `Invoice` row links the repair, the repair still counts as "uninvoiced" and the
**next batch run bills it again**. The shop dunnings a customer who already paid.

**Fix.** If `create_invoice_from_repairs` fails, **do not email**. Abort the whole unit of work
for that repair, roll back the S3 upload (or write it only after the DB row commits), escalate
from `logger.warning` to `logger.error`, and surface the failure in the batch job's summary so a
human sees it. Wrap PDF-upload + Invoice-create + email in a transaction where the email fires
only on `transaction.on_commit`.

---

### C7 — Date/timezone drift in invoice dates and filenames

- **Files:** `apps/billing/models.py:342` (`invoice_date = DateField(default=timezone.now)`);
  `apps/billing/services/auto_invoice_service.py:238` (naive `datetime.now()`)
- **Severity:** LOW
- **Verified:** yes

**Evidence.** `DateField(default=timezone.now)` coerces an aware UTC datetime to the **UTC**
date. A shop in `America/Chicago` creating an invoice at 7pm local on the 8th gets
`invoice_date = the 9th`. Due-date arithmetic, aging buckets, and the overdue cron all inherit
the off-by-one.

**Fix.** Use a callable returning `timezone.localdate()` (respecting `TIME_ZONE` / the tenant's
timezone if one is modeled). Replace the naive `datetime.now()` at
`auto_invoice_service.py:238` with `timezone.now()`. Audit for other naive `datetime.now()` /
`date.today()` in billing: `git grep -n "datetime.now()\|date.today()" apps/billing/`.

---

# WORKSTREAM D — Workflow & state machine

---

### D1 — No repair status state machine; out-of-order transitions allowed

- **File:** `apps/technician_portal/views/repairs.py:718-751` (`update_queue_status`)
- **Severity:** MEDIUM
- **Verified:** yes

**Evidence.** The view accepts **any** `new_status in dict(Repair.QUEUE_CHOICES)` from **any**
current state:

```python
new_status = request.POST.get('status')
if new_status in dict(Repair.QUEUE_CHOICES):
    ...
    repair.queue_status = new_status
    repair.save()
```

**Failure scenario.** A technician cycles `COMPLETED → APPROVED → COMPLETED`. Each cycle
re-increments `UnitRepairCount` and re-awards loyalty points, because `original_status` is
refreshed on every save — defeating the idempotency guard in
`apps/technician_portal/hooks.py:57`. Repeat to inflate a customer's points arbitrarily.

**Fix.** Define the legal transition table for
`REQUESTED → PENDING → APPROVED → IN_PROGRESS → COMPLETED` (plus `DENIED`, and whatever
admin-only reversals the business genuinely needs), enforce it in `Repair.save()` or a
`transition_to()` method — **not** only in the view, since the admin and batch paths bypass
views — and reject illegal transitions with a `ValidationError`.

Note A1 already prevents the re-pricing half of this. D1 closes the re-award half. Ship A1
first.

---

### D2 — Batch sibling propagation bypasses `save()`

- **File:** `apps/technician_portal/views/repairs.py:812`
- **Severity:** LOW
- **Verified:** yes (per audit)

**Evidence.** Batch approve/deny propagates to sibling breaks with a queryset `.update(
queue_status=…)`, which **skips `Repair.save()`**, and therefore skips `post_save` signals, tax
recalculation, and notification emails. Siblings silently change status with no customer
notification.

**Fix.** Iterate and call `.save()` per repair inside `transaction.atomic`, or explicitly fire
the notification hooks after the bulk update. Given A1 makes `save()` idempotent for completed
repairs, the loop is now safe. Watch the N+1 — acceptable at batch sizes here.

---

### D3 — Quiet hours silently drop notifications

- **File:** `core/services/notification_service.py:279-284`
- **Severity:** LOW
- **Verified:** yes (per audit)

**Evidence.** `_should_deliver()` returns `False` and logs `"delayed by quiet hours"` — but
nothing ever reschedules the message. The email/SMS is **never sent**. "Delayed" is a lie; it is
dropped.

**Fix.** Either (a) queue it with a `send_after` timestamp and add a cron to drain the queue, or
(b) if deferral is not wanted, send immediately and fix the log message. Do not leave a log line
claiming a delay that never resolves. Option (a) is correct for repair-lifecycle notifications;
customers expect them.

---

### D4 — Subscription-state gaps

- **Files:** `apps/tenants/management/commands/check_subscription_alerts.py:235`;
  `apps/tenants/webhooks.py:315`; `apps/tenants/subscription_middleware.py:146`
- **Severity:** LOW
- **Verified:** yes (per audit)

Two distinct issues:

1. **The trial-expiry email promises a grace period that does not exist.** The email tells
   expired-trial owners they have 30 days of read-only access, but `effective_grace_period_end`
   is `None` for trials, so the middleware **full-blocks immediately**. Either grant the grace
   period or fix the email copy. Interacts with A3 — decide the grace semantics once, in one
   place.

2. **Stripe `unpaid` never blocks.** `webhooks.py:315` maps `unpaid` (Stripe's terminal
   "retries exhausted" state) to `past_due`, which the middleware only **warns** on
   (`subscription_middleware.py:146`). The tenant keeps full access indefinitely, for free,
   until Stripe eventually deletes the subscription. Map `unpaid` to a blocking state (or to
   `expired` with a grace period).

3. **Biweekly batch schedule uses ISO week parity** (`apps/billing/tasks.py:311-314`:
   `isocalendar()[1] % 2`), which breaks across 53-week years — producing either two consecutive
   runs or a three-week gap at the year boundary. Anchor the schedule to a fixed epoch date
   instead: `(today - EPOCH).days // 14`.

---

# WORKSTREAM E — Dead code & repo hygiene

**Mechanical and independent. Safe to delegate to a subagent and to parallelize with F.**
Repo hygiene is otherwise good: **zero** tracked files in `staticfiles/` or `media/`, no `.pyc`,
no `.sqlite3`, no `.DS_Store`, no logs, no coverage artifacts.

Delete each item **only after** re-confirming zero references:
`git grep -n "<basename-without-extension>"`.

### E1 — Shadowed modules that Python never loads (the notable find)

Both of these coexist with same-named **packages**. A package always wins over a module of the
same name, so these files have **never once been imported**. Verified: both
`core/models.py` + `core/models/__init__.py` and `core/views.py` + `core/views/__init__.py`
exist and are git-tracked; `rs_systems/urls.py:27` resolves `from core.views import …` to the
package.

- `core/models.py` — **delete.** Labeled "backward compatibility"; also stale, missing `Vehicle`
  and `EmailBrandingConfig` which the real package exports.
- `core/views.py` — **delete.** Holds an obsolete copy of `test_notification`; the live one is
  `core/views/test_notification.py`.

Order note: B2 edits `core/views/test_notification.py` (the real one). Do E1 after B2 to avoid
confusion about which file you are editing.

### E2 — Stray settings file that survived the settings cleanup

- `rs_systems/production.py` — **delete.** Superseded by `rs_systems/settings/production.py`;
  zero references (wsgi, Procfile, and EB all use `rs_systems.settings.production`). CLAUDE.md
  states the old settings files "are deleted — do not recreate"; this one was missed.

### E3 — Tracked file explicitly marked do-not-commit

- `scripts/configure_rds.sh` — listed in `.gitignore` under a `SECURITY: DO NOT COMMIT` heading
  **yet still tracked**, because `.gitignore` does not untrack already-tracked files. No literal
  passwords found in it, but the intent was explicit. Run `git rm --cached scripts/configure_rds.sh`.
  Then verify no secret ever landed in history: `git log --oneline -- scripts/configure_rds.sh`.

### E4 — Confirmed cruft

- `rs_systems_branch2.code-workspace` — tracked editor config. Remove; add `*.code-workspace` to `.gitignore`.
- `templates/technician_portal/repair_form_old.html.bak` — a tracked `.bak`.
- `deployment/celery-beat.service`, `deployment/celery-worker.service` — `deployment/README.md`
  itself says "legacy Celery service files (no longer used)… kept for reference only." Celery/Redis
  removed 2026-03-12.

### E5 — Dead templates (verified orphans)

Certain:
- `templates/saas/owner_tax_rates.html` — its view (`apps/saas/views.py:2669`) now only redirects.
- `templates/home.html` — `views.home` renders `landing.html`.
- `templates/customer_login.html`, `templates/technician_login.html`, `templates/login_router.html`
  — legacy; the login views render `saas/login.html`.

Likely (confirm before deleting):
- `templates/technician_portal/repair_form_modern.html` — superseded by `repair_form.html`.
  **Deleting it also orphans `static/js/form_autosave.js` and `static/js/repair_form.js`**, which
  are referenced only by this template. Delete all three together, or none.
- `templates/style_guide.html` — no route.
- `templates/customer_portal/referrals/rewards_compact.html` — never included.
- `static/css/base.css`, `static/css/dashboard_visualizations.css` — zero template references.

**Not dead — do not delete:** `templates/admin/core/notification/change_list.html` is
auto-discovered by Django admin path convention.

### E6 — Unreferenced services and scripts (confirm, then remove)

- `core/services/metrics_service.py` — CloudWatch metrics; zero references repo-wide.
- `apps/billing/services/invoice_storage_service.py` — **DO NOT DELETE.** The audit flagged it as
  unreferenced, but **B1 requires its `generate_presigned_url` (line 253).** Wire it up instead.
  *(This is exactly why every deletion needs a fresh grep: the dead-code and security findings
  disagreed, and security wins.)*
- `reset_tenant_to_trial.py` (repo root) — one-off, hardcoded to the "Rockstar" tenant.
- `scripts/configure_https.py`, `scripts/cost_monitor.py`, `scripts/reset_database.py`,
  `scripts/setup_admin.py` — zero references in code, docs, or EB configs.
  **Keep** `scripts/create_test_data.py` and `scripts/load_test_simple.py` — referenced by `tests/README.md`.
- `deployment/scripts/setup_cloudwatch_alarms.py` — zero references, but may be a live ops tool.
  **Ask before deleting.**
- `core/management/commands/verify_test_emails.py` — dev helper, zero refs.
- `apps/technician_portal/management/commands/fix_batch_integrity.py` — one-off data fixer.
  **Keep until A2's data cleanup is done** — it may be useful, and A2 creates exactly the kind of
  integrity drift it was written for.
- `core/management/commands/setup_db.py` — referenced only by `docs/DEVELOPER_GUIDE.md`; runs
  `makemigrations` at deploy time, which is dangerous. Superseded by the `migrate` + `createsu` EB
  hooks. Remove and update the doc.

**Not dead:** management commands `test_ses`, `test_direct_email`, `test_sns` were already
rewritten for SES/SNS. EB configs actively invoke `createsu`, `sync_email_verification`,
`check_notifications`, `set_stripe_prices`, `setup_notification_templates`, plus the six cron
commands.

### E7 — `.gitignore` gaps

Add: `.coverage`, `htmlcov/`, `coverage.xml`, `.pytest_cache/`, `*.code-workspace`, `.claude/`.
Note `.claude/worktrees/` holds a stale ~10MB worktree copy of the repo on disk (untracked).

### E8 — Vestigial surface (do not delete; plan a deprecation)

`apps/clawdbot` is **live** (in `INSTALLED_APPS`, routed at `/clawdbot/`), but per its own
docstring its billing endpoints are backward-compat proxies for `/api/billing/`. Worth a
deprecation plan, not a deletion. Also: `apps/technician_portal/api/tests.py` is 31 lines,
untouched since 2025-08-02, using pre-multi-tenancy patterns — likely stale.

### E9 — Redundant EB config

`.ebextensions/07_debug_static.config` is a debug-era `collectstatic --verbose` leftover that
duplicates `03_django.config`'s collectstatic. Harmless but redundant. Note: a staticfiles race
caused a production incident (`docs/operations/INCIDENT_2026-07-06_REPAIR_FORM_500.md`) — read
that before touching **any** collectstatic config.

---

# WORKSTREAM F — Documentation

**Mechanical and independent. Safe to delegate; parallelize with E.**

### F1 — Stale SendGrid references (code is on SES; docs are not)

The SendGrid→SES migration is complete in code (`git grep -i sendgrid` over `.py` is clean except
one test filename). These docs still tell people to use SendGrid:

- `deployment/README.md:15,52` — **highest priority.** Still lists SendGrid as the production
  email provider and `SENDGRID_API_KEY` as a required EB env var. This is deploy-facing: a
  deployer following it configures the wrong provider.
- `apps/billing/README.md:149` — `SENDGRID_API_KEY=SG...` listed as required email config.
- `apps/tenants/README.md:333` — "Emails sent from notifications@rssystems.io via SendGrid."
- `docs/proposals/suggestions.md:398`, `docs/proposals/invoice-email-tracking.md:234,238` —
  treat "SendGrid credits exhausted" as the current blocking state; SES resolved it.

**Leave alone (correctly historical):** `docs/development/CHANGELOG.md` (documents the migration),
everything under `docs/archive/`, and `README.md`'s transitional SPF-cleanup note.

### F2 — References to deleted settings modules

CLAUDE.md states `settings.py` and `settings_aws.py` are deleted and must not be recreated. These
docs still reference them as live; repoint each to `rs_systems/settings/{base,development,production}.py`:

- `docs/deployment/AWS_DEPLOYMENT.md:206,226` — `settings_aws.py` snippets
- `docs/security/INCIDENT_RESPONSE.md:133,365`
- `docs/TROUBLESHOOTING.md:210,217,370,457,495,692,706` — many
- `docs/development/notifications/NOTIFICATION_CONFIGURATION_GUIDE.md:198,385` — "uncomment SES in settings.py"
- `docs/user-guides/ADMIN_GUIDE.md:965` — greps `rs_systems/settings.py`

Archive files also reference these — **leave them**, they are historical.

### F3 — `docs/TODO.md` is rotting

- **Self-contradicts:** lines 50–53 say the Review Request System is "proposal written, awaiting
  approval"; lines 60–63 say "Phase 1 shipped (CODE-208)."
- Last updated Mar 26 2026 while `CHANGELOG.md` runs to Jul 9 2026.
- Not in the docs index.
- Line 111 cites `docs/archive/BUG_AUDIT_2026-03-29_to_04-01.md`. **Correction to the original
  audit:** that file **does exist on disk** — it is simply **untracked** (`git ls-files` returns
  nothing for it). It is not a dead link; it is an uncommitted file. Decide whether to commit it
  or delete it.

**Fix:** fold `TODO.md` into `docs/development/ROADMAP.md` and delete it, or bring it current and
index it. Do not leave two disagreeing status trackers.

### F4 — Orphaned and misplaced docs

Not linked from `docs/README.md`: `PRICING_TIERS.md`, `SCALING.md`, `SOFT_DELETE.md`, `TODO.md`.
Either index them or move them:
- `docs/SOFT_DELETE.md` → `docs/development/`
- `docs/development/MANAGER_SETTINGS_ROADMAP.md` → `docs/proposals/` (it is a roadmap)
- `docs/development/notifications/ADMIN_DASHBOARD_GUIDE.md` → out of `notifications/` (it is about
  the admin dashboard, misfiled)
- `docs/proposals/implementation-plan.md`, `docs/proposals/suggestions.md` → `docs/archive/`
  (working meta-docs, not proposals; both stale)
- `docs/proposals/stripe-connect-implementation-plan.md` → `docs/archive/` (marked ✅ SHIPPED)

### F5 — Duplication to collapse

- **Billing:** `docs/BILLING_GUIDE.md` (user-facing) + `apps/billing/README.md` (internals) +
  `docs/archive/BILLING_ROADMAP.md` (history). Four live docs still link into the *archived*
  roadmap (`apps/billing/README.md:178`, `docs/development/SUBSCRIPTION_LIFECYCLE.md:120`,
  `docs/development/CHANGELOG.md:656`, `docs/operations/NOTIFICATION_OPERATIONS.md:343`) — if it is
  still canonical history, it is not really archived. Either promote a billing-history section into
  the changelog, or add a header to the archive noting intentional inbound history links.
- **Notifications:** a five-doc cluster with overlapping setup/testing/config material. Merge
  `SIMPLE_TESTING_GUIDE.md` + `NOTIFICATION_CONFIGURATION_GUIDE.md` into
  `docs/development/notifications/README.md`.
- **Testing:** `docs/development/TESTING.md`, `tests/README.md`, and CLAUDE.md's testing section
  overlap heavily. Keep one canonical doc; have the others link to it.
- **Status tracking:** `docs/TODO.md`, `docs/development/ROADMAP.md`, `docs/proposals/README.md`
  independently track shipped/planned status and **disagree**. Collapse to one.
- **Pricing:** `docs/PRICING_TIERS.md` duplicates the plan table in `README.md`.

### F6 — Missing docs (gaps for an S-tier SaaS)

- **No maintained API reference.** `README.md` points at `docs/user-guides/ADMIN_GUIDE.md` as "API
  Docs," which it is not. The only API doc is `apps/customer_portal/API_DOCUMENTATION.md`, which
  **self-flags as pre-multi-tenant-isolation and stale.** There is a live `/api/schema/swagger-ui/`
  but no maintained guide covering `/api/billing/` and `/api/tenants/`.
- **No SES operations runbook** — and you now need one. Bounce/complaint handling, the suppression
  list, and DKIM/SPF are mentioned only in README prose. **A bounce-rate spike on SES gets your
  sending paused**, which silently breaks every repair notification and invoice in the product.
  This is the single most valuable doc to write.
- **No billing-cron runbook** (what to do when `process_batch_invoices` or a Stripe webhook fails).
- **No `SECURITY.md`** / disclosure policy at repo root.
- **No data model / ERD**, no migration-strategy doc, no contribution guide / PR checklist.

### F7 — Doc drift in CLAUDE.md

CLAUDE.md described `test_ses` as "Test SendGrid delivery" though the command is now SES. *(This
appears already corrected in the working tree — verify.)*

---

## Verification protocol

After each workstream:

```bash
export LOCAL_DATABASE_URL="postgresql://amelia_test:AmeliaTest2026!@localhost:5432/rs_systems_test"
export DJANGO_SETTINGS_MODULE=rs_systems.settings.development

python manage.py test tests.test_primary_contact tests.test_e2e_today -v 2   # smoke, fast
python manage.py test tests/bug_fixes -v 1                                   # regression suite
python manage.py test tests/ -v 1                                            # full, ~7 min
```

Then:

```bash
python manage.py check --deploy       # settings hardening
python manage.py makemigrations --check --dry-run   # no uncommitted model changes
python manage.py security_audit
```

**On pre-existing failures.** Some tests may already fail on `main`. Before attributing any
failure to your change, `git stash` and re-run to confirm whether it fails on the base commit
too. Report pre-existing failures separately from regressions. **Never edit a test to make it
pass** unless the test itself encodes the bug you are fixing — and if you do, say so explicitly
in the commit message.

**On the A-workstream specifically.** After A1+A2 land, run the two data-cleanup SQL queries
against a **restored production backup**, never against live, and report the row counts to the
owner before anyone runs an `UPDATE`.

---

## Sequencing and conflicts

```
A1 ──▶ A2 ──▶ (data cleanup: recompute UnitRepairCount)
 │              ▲
 │              └── C5 (atomic increments) — land with or after A2
 ├──▶ C4 (tax lookup)  — MUST land after A1, else completed repairs get re-taxed on re-save
 └──▶ D1 (state machine) — A1 fixes re-pricing; D1 fixes re-awarding. A1 first.

A4 ──▶ A5   — shared root cause. A4 builds the "render existing Invoice to PDF" path; A5 uses it.

B1 ──▶ (needs E6's invoice_storage_service.py — DO NOT let E delete it)
B2 ──▶ E1  — B2 edits core/views/test_notification.py; E1 deletes the shadowing core/views.py

E ∥ F       — disjoint file sets, safe to parallelize with each other and with A–D.
A ∥ C       — ✗ CONFLICT. Both touch apps/billing/services/. Do not run concurrently.
```

**The one trap in this plan:** the dead-code audit flagged
`apps/billing/services/invoice_storage_service.py` as unreferenced and deletable. The security
audit needs its `generate_presigned_url()` to fix B1. **Security wins — do not delete it.**
Re-grep before every deletion; findings from independent audits can contradict each other.

---

## What still needs a human

These cannot be resolved from inside the repo:

1. **B1 — the S3 bucket policy.** Run the `aws s3api` commands above. This single answer swings
   B1 between "unauthenticated cross-tenant data breach, drop everything" and "download links are
   quietly broken." **Do this before anything else in Workstream B.**
2. **B6 — the root AWS key.** Confirm in the IAM console that the key ID in
   `CHANGELOG.md:35` was rotated or deleted. Root access keys should not exist.
3. **A1/A2 data cleanup.** Someone must decide whether to back-fill drifted `repair.cost` values
   from invoice line items (recommended: the invoice is what the customer actually paid) and
   approve the `UnitRepairCount` recompute.
4. **D4 — grace-period policy.** The trial-expiry email promises 30 read-only days that the
   middleware does not grant. Product decision: honor the email, or change the copy?
5. **Uncommitted work.** ~27 modified files and 2 untracked files
   (`docs/archive/BUG_AUDIT_2026-03-29_to_04-01.md`,
   `tests/bug_fixes/test_ses_migration_welcome_email.py`) are sitting in the working tree.
   Commit or stash before starting.

---

## Appendix — areas audited and found clean

Recorded so future audits do not re-plow this ground.

**Security.** Tenant isolation verified across `apps/billing/views.py` (all `@requires_api` +
`Invoice.objects.for_tenant()`), `apps/clawdbot/views.py`, all of
`apps/technician_portal/views/*` and `api/views.py` (every `get_object_or_404` uses a
tenant-pre-filtered queryset; consistently avoids the unscoped `request.user.technician`
OneToOne trap), all of `apps/customer_portal/views.py`, and `apps/saas/views.py`
(`_get_owner_tenant()` verifies active owner/manager membership per request). **No cross-tenant
IDOR found.** DRF defaults to `IsAuthenticated` + session auth; legacy token auth deliberately
disabled. `AllowAny` endpoints (`signup`, `list_plans`) are appropriately public. Public token
endpoints use UUIDv4 / `secrets.token_urlsafe(32)` / Django's token generator with expiry and
single-use. Both Stripe webhook handlers verify signatures via `construct_event` and refuse to
process without a secret in production. No hardcoded live secrets anywhere tracked. No
`.raw()`/`.extra()`/string-formatted `cursor.execute`; no `eval`/`exec`/`pickle`/`yaml.load`.
The single `|safe` and all `mark_safe`/`format_html` sites interpolate choices/ints/color-map
values, not user free-text. `production.py`: `DEBUG=False`, `SECRET_KEY` required, no SQLite,
HSTS 1yr + preload, secure/HttpOnly/SameSite cookies, SSL redirect, `X_FRAME_OPTIONS=DENY`,
nosniff, `CSRF_TRUSTED_ORIGINS` set. Login `?next=` and password reset use
`url_has_allowed_host_and_scheme`; the public pay link uses constant-time HMAC compare.

**Correctness.** Money math uses `Decimal` throughout billing (`float()` only at
JSON-serialization edges); tax quantized `ROUND_HALF_UP`. `owner_record_payment` and the billing
API both do locked, TOCTOU-safe overpayment checks; `Payment.save()/delete()` reconcile totals
under `select_for_update`. Loyalty: `award_points`/`redeem_reward`/`manual_adjustment` correctly
lock the `Reward` row; negative balances guarded; redemption rolls back on failed deduction;
point expiry clamps at zero. Invoice numbering uses a retry loop plus a DB unique constraint (the
residual race fails loudly — acceptable). Signup service is atomic with an `iexact` email check
and unique slug/username loops backstopped by constraints. Tenant middleware resolution order and
membership verification are correct. `InvoiceLineItem.save()`'s `is None` guard (CODE-151) is
correct. SES migration is clean in code — no lingering SendGrid references.

**Repo.** Zero tracked files in `staticfiles/` or `media/`. No `.pyc`, `.sqlite3`, `.DS_Store`,
logs, dumps, or coverage artifacts tracked. All `apps/saas/views.py` public functions are routed.

---

*Generated 2026-07-09 from a four-agent parallel audit (security, business-logic bugs, dead code,
documentation). All HIGH findings independently re-verified against source before publication.*
