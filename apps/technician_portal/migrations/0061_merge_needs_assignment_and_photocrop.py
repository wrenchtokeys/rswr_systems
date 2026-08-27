"""Rejoin the two 0060s.

Two arcs landed a migration numbered 0060 on the same day — the job queue's
`needs_assignment` flag (#220) and Photo-ML's crop-on-a-replacement FK (#219) —
and neither could see the other because both were cut from a main that did not
yet have it. With two leaf nodes Django refuses to build the graph at all, so
`migrate`, `test` and `runserver --check` all fail on a clean checkout of main.

Nothing conflicts: both branches are purely additive and touch different
models. This is the empty merge node that says so.
"""


from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('technician_portal', '0060_add_needs_assignment'),
        ('technician_portal', '0060_photocrop_replacement_fk'),
    ]

    operations = [
    ]
