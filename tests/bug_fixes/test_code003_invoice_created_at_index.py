"""
Regression tests for CODE-003: Invoice.created_at missing db_index.

Verifies that:
  1. Invoice.created_at has a database index named 'billing_invoice_created_at_idx'
  2. The index is present in the migration (0012_add_invoice_created_at_index)
  3. The Invoice Meta.indexes list includes a created_at index
  4. The index covers queries that filter/sort by created_at (common in aging reports
     and date-range filters on the invoices dashboard).
"""

from django.test import TestCase
from django.db import connection


class InvoiceCreatedAtIndexTest(TestCase):
    """Invoice.created_at should have a database index."""

    def test_invoice_meta_indexes_includes_created_at(self):
        """Invoice.Meta.indexes must contain an index on created_at."""
        from apps.billing.models import Invoice

        index_fields = [
            tuple(idx.fields) for idx in Invoice._meta.indexes
        ]
        self.assertIn(
            ('created_at',),
            index_fields,
            "Invoice.Meta.indexes must include an index on 'created_at'",
        )

    def test_invoice_created_at_index_name(self):
        """The created_at index should be named 'billing_invoice_created_at_idx'."""
        from apps.billing.models import Invoice

        index_names = [idx.name for idx in Invoice._meta.indexes]
        self.assertIn(
            'billing_invoice_created_at_idx',
            index_names,
            "Expected index named 'billing_invoice_created_at_idx' on Invoice",
        )

    def test_database_index_exists(self):
        """The index must actually exist in the database after migration."""
        with connection.cursor() as cursor:
            # PostgreSQL introspection: check pg_indexes for our index
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'billing_invoice'
                  AND indexname = 'billing_invoice_created_at_idx'
                """
            )
            rows = cursor.fetchall()

        self.assertEqual(
            len(rows),
            1,
            "Index 'billing_invoice_created_at_idx' not found in the database. "
            "Did you run the 0012_add_invoice_created_at_index migration?",
        )

    def test_invoice_created_at_field_present(self):
        """Invoice.created_at field should still exist and be auto_now_add."""
        from apps.billing.models import Invoice

        field = Invoice._meta.get_field('created_at')
        self.assertTrue(
            field.auto_now_add,
            "Invoice.created_at should be auto_now_add=True",
        )

    def test_migration_file_exists(self):
        """Migration 0012_add_invoice_created_at_index must exist."""
        import importlib
        try:
            migration = importlib.import_module(
                'apps.billing.migrations.0012_add_invoice_created_at_index'
            )
        except ImportError:
            self.fail(
                "Migration 'apps/billing/migrations/0012_add_invoice_created_at_index.py' "
                "not found. The index must be created via a Django migration."
            )

        # Verify the migration adds an index (not removes it)
        migration_class = migration.Migration
        ops = migration_class.operations
        op_types = [type(op).__name__ for op in ops]
        self.assertIn(
            'AddIndex',
            op_types,
            "Migration must contain an AddIndex operation",
        )
