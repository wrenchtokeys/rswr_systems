# Soft-Delete: Repairs & Invoices

> Added 2026-03-17

RS Systems uses **soft-deletion** for repairs and invoices. Instead of permanently removing a record, a `deleted_at` timestamp is set. Soft-deleted records are invisible to all normal querysets and UIs, but can be restored within 30 days before being permanently purged.

---

## How It Works

### Models

Both `Repair` (technician_portal) and `Invoice` (billing) have a new field:

```python
deleted_at = models.DateTimeField(null=True, blank=True)
```

Each model also has two managers:

| Manager | Usage | Behavior |
|---|---|---|
| `Repair.objects` | Default — all normal views | Filters out `deleted_at__isnull=False` |
| `Repair.all_objects` | Admin, archived views, restore logic | Returns everything including deleted |

Same pattern applies to `Invoice.objects` / `Invoice.all_objects`.

**No existing call sites needed to change** — the default manager silently excludes deleted records everywhere.

---

## Delete Flow

1. Owner or manager opens a repair's detail page
2. Clicks the **Delete** button (only visible to owners/managers)
3. A confirmation modal appears with a warning and a link to the Archived Repairs page
4. On confirm (POST to `/tech/repairs/<id>/delete/`):
   - If **any payment exists** on any invoice linked to this repair → blocked with error message
   - If clear: `repair.deleted_at = now()` is set
   - All invoices that have a line item for this repair are also soft-deleted (cascades atomically)
5. Redirect to customer detail page with success message

**Repairs with payments cannot be deleted.** Void the payment first (or use the admin) if truly needed.

---

## Restore Flow

Deleted repairs appear in the **Archived Repairs** page (`/tech/repairs/archived/`), accessible to owners and managers.

- Each deleted repair has a **Restore** button
- POSTs to `/tech/repairs/<id>/restore/`
- Clears `deleted_at` on the repair
- Also clears `deleted_at` on any invoice linked to that repair that was archived at the same time
- **Blocked after 30 days** — once past the window, restore is no longer available

Archived invoices are shown on the same page but restore automatically when their repair is restored. There is no standalone invoice restore button.

---

## Permanent Purge

Run this management command periodically (nightly cron recommended):

```bash
# Dry run — shows what would be deleted
python manage.py purge_deleted_records

# With a custom window (e.g. 60 days)
python manage.py purge_deleted_records --days 60

# Actually delete
python manage.py purge_deleted_records --apply
```

The command handles the `PROTECT` constraint by deleting in the correct order:
1. `InvoiceLineItem` rows (referencing both Invoice and Repair with PROTECT)
2. `Invoice` records
3. `Repair` records

**Purged records cannot be restored.** The default 30-day window aligns with the restore window.

### Suggested cron (in OpenClaw or system cron)

```
# 2am UTC daily — purge records older than 30 days
0 2 * * * cd /path/to/rswr_systems && python manage.py purge_deleted_records --apply
```

---

## Access Control

| Action | Required Role |
|---|---|
| Delete a repair | Owner or Manager |
| View archived repairs | Owner or Manager |
| Restore a repair | Owner or Manager |
| Run purge command | Server/cron (any Django admin user) |

Regular technicians cannot delete, view archived, or restore repairs.

---

## Data Visibility

After soft-deletion, the repair and its invoices are hidden from:
- Technician portal repair list and queues
- Customer portal repair history
- Billing invoice lists and portals
- Owner dashboard stats
- Any queryset using `Repair.objects` or `Invoice.objects`

They are still visible in:
- Django admin (via `all_objects` or direct admin queryset)
- The `/tech/repairs/archived/` page
- The `purge_deleted_records` management command output

---

## Edge Cases

- **Batch repairs**: Each repair in a batch is deleted individually. Soft-deleting one break does not auto-delete the others.
- **Replacement records**: The `Replacement` model does not currently support soft-delete. Use Django admin to handle those manually.
- **Invoice with multiple repairs**: If an invoice has line items for Repair A and Repair B, and only Repair A is deleted, the invoice is still soft-deleted (it's linked to a deleted repair). Restore Repair A to restore the invoice. Consider voiding/re-generating the invoice for Repair B separately.
- **Payments**: Repairs with any payment on a linked invoice are blocked from deletion. This is intentional — financial records must remain intact.
