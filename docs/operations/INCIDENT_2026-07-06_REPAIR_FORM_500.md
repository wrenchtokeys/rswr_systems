# Incident Report — 500 on `/tech/repairs/create/`

| | |
|---|---|
| **Reported** | 2026-07-06 (owner hit it from the owner dashboard, ~04:20 UTC Jul 7) |
| **Resolved** | 2026-07-07 — commit `e1a20c31` (CODE-266/267), deployed to `rs-systems-production` |
| **Impact** | "New Repair" page returned a hard 500 for all users on the affected instance. Same defect broke pages referencing `admin/css/base.css` on the previous instance July 2–4 (12 logged 500s). EB health stayed **Green** the whole time. |
| **Severity** | High — blocked repair creation, the core workflow |

## What happened

Every EC2 instance that Elastic Beanstalk boots outside a normal deploy (autoscaling
scale-up, immutable config updates) starts the web service **before** static files are
collected:

1. EB's self-startup flips the app and runs `systemctl start web.service` (gunicorn)
   — on July 5 at `06:01:41`.
2. The `postdeploy` hook — which ran `collectstatic` — only finished at `06:01:47`.
3. Django's manifest static-files storage (WhiteNoise
   `CompressedManifestStaticFilesStorage`) loads `staticfiles.json` **once per worker
   process** and caches it forever. Workers that initialized inside that 6-second
   window (health checks arrive immediately) cached an **empty manifest**.
4. From then on, any template with `{% static %}` raised
   `ValueError: Missing staticfiles manifest entry for 'css/components/form-fields.css'`
   → 500. The files themselves were on disk and served fine; only the in-memory
   manifest was poisoned.

Two secondary defects made it worse:

- The `leader_only` collectstatic container command (`.ebextensions/06_static_files.config`)
  never runs on scale-up instances, so those instances *depended* on the postdeploy hook —
  the racy path.
- `create_repair()`'s render-failure fallback referenced `settings.DEBUG` without
  importing `settings` → `NameError`, so the intended diagnostic page became a raw 500.

## The fix (commit `e1a20c31`)

1. **Ordering (root cause)** — collectstatic moved to
   `.platform/hooks/predeploy/01_collectstatic.sh`. Predeploy hooks run against
   `/var/app/staging` *before* the app flips and gunicorn starts, on deploys **and**
   scale-up self-startup. Removed the postdeploy collectstatic and the redundant
   leader-only container command.
2. **Resilience** — static storage switched to
   `rs_systems.storage.ForgivingManifestStaticFilesStorage` (`manifest_strict = False`).
   A missing manifest entry now falls back to hashing the file on disk instead of
   500ing the page.
3. **Error handler** — added the missing `settings` import in
   `apps/technician_portal/views/repairs.py`.
4. **CODE-267 (found in the audit)** — `InvoiceEmailService` used `logger` without
   defining it; the `NameError` was swallowed by an outer `except Exception: pass`,
   silently dropping the Stripe payment link from invoice emails whenever
   payment-token generation failed. Module logger added.

## Verification

- Reproduced the exact production `ValueError` locally with the old strict storage and
  a manifest miss; the forgiving storage resolves the hashed URL
  (`form-fields.0cc2e0ed1220.css`) for the same input.
- 60 smoke tests pass (`tests.test_primary_contact`, `tests.test_e2e_today`).
- Template audit: all 11 unique `{% static %}` references across every template
  resolve via staticfiles finders.
- Pyflakes undefined-name audit over `apps/ core/ common/ rs_systems/`: one real bug
  (CODE-267, fixed); remaining hits are false positives (string annotations /
  `from __future__ import annotations`).
- Post-deploy: `/tech/repairs/create/` no longer 500s; no new
  "Missing staticfiles manifest entry" errors in `web.stdout.log`.

## Recommendations

Prioritized; none are blocking.

1. **Alert on application errors** *(highest value — this broke silently for 3 days).*
   EB health stayed Green because the ELB health check never renders a template.
   Add a CloudWatch metric filter on
   `/aws/elasticbeanstalk/rs-systems-production/var/log/web.stdout.log` matching
   `"Internal Server Error"` with an SNS email alarm — or wire up Sentry
   (free tier covers this traffic easily) for full tracebacks.
2. **Alarm on ALB 5xx** (`HTTPCode_Target_5XX_Count`) as a template-independent backstop.
3. **Run migrations before traffic flips.** `migrate` still runs in the postdeploy
   hook, so for a few seconds each deploy, new code serves against the old schema.
   Moving it to a predeploy hook has a concurrency caveat during immutable updates
   (multiple instances migrating at once) — decide deliberately.
4. **Don't leak exception text to users.** `create_repair()`'s fallback returns
   `<h1>Repair Form Error</h1><pre>{exception}</pre>` to the browser — internal paths
   and details. Log the traceback; show a friendly page.
5. **Repair-form usability** (from reading the flow):
   - Admin-must-pick-technician is only enforced after submit, via a flash message.
     Mark the field required in the form when the user is an admin.
   - Form errors surface as flash messages (`field: error`) *and* inline — pick inline.
   - `customer_types_json` serializes **every** customer into the page on each render;
     fine today, but it grows with the customer table. The data could come from the
     existing customer-search endpoint instead.
6. **Housekeeping**: `db.sqlite3` is committed and shipped in the deploy bundle
   (`.ebignore` comment says "temporarily allow"); `staticfiles.json` and `.gz`
   artifacts are publicly fetchable under `/static/`. Both harmless today, both worth
   tidying.
