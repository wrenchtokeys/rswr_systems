"""The migration graph must stay deployable.

Two sessions that both add a migration to the same app on the same day get the
same number, and both merge green — nothing in a PR check notices. The next
`eb deploy` is where it surfaces, in the postdeploy hook
(`.platform/hooks/postdeploy/01_django_setup.sh`), as

    CommandError: Conflicting migrations detected; multiple leaf nodes in the
    migration graph: (0060_add_needs_assignment, 0060_photocrop_replacement_fk
    in technician_portal).

which happened on 2026-08-27 (#219 and #221) and on 2026-08-10 before it
(`0050_merge_20260810_1635`). The fix is always `makemigrations --merge`; this
test is so the fix happens at PR time instead of at deploy time.
"""

from collections import defaultdict

from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase


class MigrationGraphTests(SimpleTestCase):
    def test_every_app_has_exactly_one_leaf_migration(self):
        # connection=None reads the graph off disk only — no recorder query,
        # so this stays a SimpleTestCase and needs no database.
        loader = MigrationLoader(None, ignore_no_migrations=True)

        leaves_by_app = defaultdict(list)
        for app_label, name in loader.graph.leaf_nodes():
            leaves_by_app[app_label].append(name)

        conflicted = {
            app: sorted(names)
            for app, names in leaves_by_app.items()
            if len(names) > 1
        }

        self.assertEqual(
            conflicted,
            {},
            'Multiple leaf migrations — `manage.py migrate` will refuse to run '
            'and the deploy will fail in the postdeploy hook. Run '
            '`python manage.py makemigrations --merge <app>` and commit the '
            f'merge migration. Conflicts: {conflicted}',
        )
