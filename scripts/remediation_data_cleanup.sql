-- =============================================================================
-- Remediation data cleanup (plan 2026-07-09; branch fix/audit-remediation-2026-07)
--
-- RUN BY A HUMAN, MANUALLY, AFTER:
--   1. `python manage.py audit_remediation_data` output has been reviewed
--   2. a fresh backup / restored copy has been tested first
--   3. the code fixes (A1/A2/A3/C2) are DEPLOYED — otherwise the bugs
--      re-corrupt the data you just fixed
--
-- Everything is wrapped in a transaction. Review each section's SELECT
-- before letting its UPDATE run. COMMIT is intentionally commented out.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- A3: null stale grace stamps on live tenants (lockout time bombs).
-- Safe and unambiguous — run as-is.
-- -----------------------------------------------------------------------------
SELECT id, name, subscription_status, grace_period_end
FROM tenants_tenant
WHERE grace_period_end IS NOT NULL
  AND subscription_status IN ('active', 'trialing');

UPDATE tenants_tenant
SET grace_period_end = NULL
WHERE grace_period_end IS NOT NULL
  AND subscription_status IN ('active', 'trialing');

-- -----------------------------------------------------------------------------
-- A1: back-fill repair.cost from the invoiced amount (the invoice is what
-- the customer actually paid — source of truth). Only single-quantity,
-- repair-backed line items.  REVIEW the SELECT first: if a repair appears
-- on multiple invoices, resolve by hand instead.
-- -----------------------------------------------------------------------------
SELECT r.id AS repair_id, r.cost AS current_cost, li.unit_price AS invoiced,
       i.invoice_number
FROM technician_portal_repair r
JOIN billing_invoicelineitem li ON li.repair_id = r.id AND li.quantity = 1
JOIN billing_invoice i ON i.id = li.invoice_id
WHERE r.cost IS DISTINCT FROM li.unit_price;

UPDATE technician_portal_repair r
SET cost = li.unit_price
FROM billing_invoicelineitem li
WHERE li.repair_id = r.id
  AND li.quantity = 1
  AND r.cost IS DISTINCT FROM li.unit_price;

-- -----------------------------------------------------------------------------
-- A2: recompute UnitRepairCount from actual completed repairs.
-- CAUTION: retail/walk-in and progressive-pricing-disabled customers
-- legitimately have stored < actual (their completions never increment).
-- Recomputing them to the actual count would CHANGE their future pricing
-- tier. Therefore only fix rows that are INFLATED (stored > actual) —
-- those are the convert_to_batch double-counts.
-- -----------------------------------------------------------------------------
SELECT u.id, u.repair_count AS stored,
       (SELECT COUNT(*) FROM technician_portal_repair r
        WHERE r.customer_id = u.customer_id
          AND r.unit_number = u.unit_number
          AND r.queue_status = 'COMPLETED'
          AND (u.tenant_id IS NULL OR r.tenant_id = u.tenant_id)) AS actual
FROM technician_portal_unitrepaircount u
WHERE u.repair_count >
      (SELECT COUNT(*) FROM technician_portal_repair r
       WHERE r.customer_id = u.customer_id
         AND r.unit_number = u.unit_number
         AND r.queue_status = 'COMPLETED'
         AND (u.tenant_id IS NULL OR r.tenant_id = u.tenant_id));

UPDATE technician_portal_unitrepaircount u
SET repair_count = sub.actual
FROM (
    SELECT u2.id,
           (SELECT COUNT(*) FROM technician_portal_repair r
            WHERE r.customer_id = u2.customer_id
              AND r.unit_number = u2.unit_number
              AND r.queue_status = 'COMPLETED'
              AND (u2.tenant_id IS NULL OR r.tenant_id = u2.tenant_id)) AS actual
    FROM technician_portal_unitrepaircount u2
) sub
WHERE sub.id = u.id
  AND u.repair_count > sub.actual;

-- -----------------------------------------------------------------------------
-- C2: duplicate stripe payments. Migration billing.0022 does NOT fail on
-- duplicates: it keeps the earliest Payment per stripe_payment_id and renames
-- each later duplicate to '<stripe_id>-dup<pk>' so the unique constraint can
-- apply. Those renamed rows ARE the webhook double-counts. Find them:

SELECT p.id AS payment_id, p.stripe_payment_id, p.amount,
       i.id AS invoice_id, i.invoice_number, i.amount_paid, i.total, i.status
FROM billing_payment p
JOIN billing_invoice i ON i.id = p.invoice_id
WHERE p.stripe_payment_id LIKE '%-dup%'
ORDER BY p.id;

-- NO generic UPDATE here — resolve each by hand: delete the renamed row,
-- then recompute the invoice it double-counted:
--
--   DELETE FROM billing_payment WHERE id = <renamed_row_id>;
--   UPDATE billing_invoice SET amount_paid = (
--       SELECT COALESCE(SUM(amount), 0) FROM billing_payment WHERE invoice_id = <invoice_id>
--   ) WHERE id = <invoice_id>;
--   -- then recheck status: SELECT amount_paid, total, status FROM billing_invoice WHERE id = <invoice_id>;
-- -----------------------------------------------------------------------------

-- Review everything above, then uncomment:
-- COMMIT;
ROLLBACK;
