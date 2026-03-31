"""
CODE-242: Add db_index to GlassService.queue_status

queue_status is the most heavily filtered field in the codebase (~233
references across admin views, queryset filters, and business logic).
Without an index, every filter on queue_status required a full table scan.

This becomes a real performance issue as the repair/replacement tables grow
(fleet customers can generate thousands of repairs per year). Adding
db_index=True to the abstract base field creates indexes on both
technician_portal_repair and technician_portal_replacement tables.

Author: Amelia (Clawdbot AI)
"""
from django.test import TestCase
from django.db import connection


class QueueStatusIndexTest(TestCase):
    """Verify that queue_status has a database index on both tables."""

    def _get_indexes_for_column(self, table_name, column_name):
        """Return index names for a specific column on a table."""
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = %s AND indexdef LIKE %s",
                [table_name, f'%{column_name}%'],
            )
            return [row[0] for row in cursor.fetchall()]

    def test_repair_queue_status_has_index(self):
        """Repair.queue_status must have a DB index (CODE-242)."""
        indexes = self._get_indexes_for_column(
            'technician_portal_repair', 'queue_status'
        )
        self.assertTrue(
            len(indexes) > 0,
            "technician_portal_repair should have at least one index on queue_status"
        )

    def test_replacement_queue_status_has_index(self):
        """Replacement.queue_status must have a DB index (CODE-242)."""
        indexes = self._get_indexes_for_column(
            'technician_portal_replacement', 'queue_status'
        )
        self.assertTrue(
            len(indexes) > 0,
            "technician_portal_replacement should have at least one index on queue_status"
        )

    def test_model_field_has_db_index_flag(self):
        """GlassService.queue_status field must have db_index=True."""
        from apps.technician_portal.models import Repair, Replacement

        repair_field = Repair._meta.get_field('queue_status')
        self.assertTrue(
            repair_field.db_index,
            "Repair.queue_status should have db_index=True"
        )

        replacement_field = Replacement._meta.get_field('queue_status')
        self.assertTrue(
            replacement_field.db_index,
            "Replacement.queue_status should have db_index=True"
        )
