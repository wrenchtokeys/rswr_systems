"""Shared phrasing for in-app notification messages.

These messages are built as f-strings in view code rather than from a
NotificationTemplate, so there is nowhere else for the shared rules to
live. Two rules, both learned the hard way:

1. No emoji. A green tick, a red cross and a bell emoji were carried in
   fourteen of these strings; they render as hollow boxes in some clients,
   they add nothing a category icon does not already say, and they are the
   first thing that makes a product look unserious.

2. Never concatenate a bare noun onto a possibly-empty field. Writing
   f"... on Unit {job.unit_number}" ends the sentence on the word "Unit"
   for every retail customer, because an individual's job leaves
   unit_number blank and is identified by their vehicle instead. This is
   the same bug that printed "Unit #Silver Camry" on invoices.
"""


def on_vehicle(job):
    """' on Unit #4471' / ' on a 2019 Ford F-150' / '' for inline prose.

    Leading space included so callers can concatenate without deciding
    whether one is needed. Returns '' when the job has no vehicle on
    record, so the sentence closes cleanly instead of trailing a noun.

    get_vehicle_label() is the authority on how a job's vehicle is named —
    unit number for a fleet, the vehicle itself for an individual, never
    unit-number framing for a person's own car.
    """
    try:
        label = job.get_vehicle_label()
    except Exception:
        return ''
    if not label:
        return ''
    # 'Unit #4471' is already self-describing; a vehicle description reads
    # as prose and takes an article.
    if label.startswith('Unit #'):
        return f" on {label}"
    return f" on a {label}"
