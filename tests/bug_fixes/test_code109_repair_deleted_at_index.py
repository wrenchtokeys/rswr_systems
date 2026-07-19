"""
CODE-109 Regression tests: Repair.deleted_at missing index.

RepairSoftDeleteManager appends deleted_at__isnull=True to every query,
but the column had no index.  The fix adds a partial composite index
(tenant_id, queue_status) WHERE deleted_at IS NULL to cover the most common
query pattern: tenant-scoped repair list filtered by status.

Tests verify:
  1. The index exists in the database with the correct name.
  2. The index is partial (has a predicate / WHERE clause).
  3. The index covers (tenant_id, queue_status).
  4. RepairSoftDeleteManager correctly excludes soft-deleted repairs (baseline).
  5. Repair.all_objects includes soft-deleted repairs.
  6. Soft-deleted repairs are excluded from tenant-scoped status filter.
"""

from django.test import TestCase
from django.db import connection
from apps.technician_portal.models import Repair


class RepairDeletedAtIndexTests(TestCase):
    """Verify the partial index for soft-delete performance exists and is correct."""

    INDEX_NAME = 'repair_live_tenant_status_idx'

    def _get_index_info(self):
        """Return (indexname, indexdef) for our partial index, or None."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE tablename = 'technician_portal_repair'
                  AND indexname = %s
                """,
                [self.INDEX_NAME],
            )
            row = cursor.fetchone()
        return row

    def test_index_exists(self):
        """The partial index must be present in the database."""
        row = self._get_index_info()
        self.assertIsNotNone(
            row,
            f"Expected partial index '{self.INDEX_NAME}' to exist on "
            "technician_portal_repair but it was not found.",
        )

    def test_index_is_partial(self):
        """The index definition must contain a WHERE predicate (partial index)."""
        row = self._get_index_info()
        self.assertIsNotNone(row, "Index not found — cannot check partialness.")
        indexdef = row[1]
        self.assertIn(
            'WHERE',
            indexdef.upper(),
            f"Expected a partial index with WHERE clause, got: {indexdef}",
        )

    def test_index_covers_deleted_at_null(self):
        """The WHERE clause must reference deleted_at IS NULL."""
        row = self._get_index_info()
        self.assertIsNotNone(row, "Index not found.")
        indexdef = row[1]
        self.assertIn(
            'deleted_at',
            indexdef,
            f"WHERE clause should reference deleted_at, got: {indexdef}",
        )
        # PostgreSQL renders NULL checks as 'deleted_at IS NULL'
        self.assertIn(
            'IS NULL',
            indexdef.upper(),
            f"Partial predicate should be IS NULL, got: {indexdef}",
        )

    def test_index_covers_tenant_and_queue_status(self):
        """The index must cover tenant_id and queue_status columns."""
        row = self._get_index_info()
        self.assertIsNotNone(row, "Index not found.")
        indexdef = row[1]
        self.assertIn('tenant_id', indexdef,
                      "Index should include tenant_id column.")
        self.assertIn('queue_status', indexdef,
                      "Index should include queue_status column.")


class RepairSoftDeleteManagerTests(TestCase):
    """Verify soft-delete manager behaviour (unrelated to the index, but baseline)."""

    def setUp(self):
        from django.contrib.auth.models import User
        from apps.tenants.models import Tenant, TenantMembership
        from apps.technician_portal.models import Technician
        from core.models import Customer

        self.user = User.objects.create_user('indextest', password='x')
        self.tenant = Tenant.objects.create(
            name='Test Shop', slug='test-shop-index', owner=self.user
        )
        TenantMembership.objects.create(user=self.user, tenant=self.tenant, role='owner')
        self.technician = Technician.objects.create(
            user=self.user, tenant=self.tenant, expertise='auto_glass'
        )
        self.customer = Customer.objects.create(
            name='Index Test Co', tenant=self.tenant
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )

    def _make_repair(self, deleted=False, status='PENDING'):
        from django.utils import timezone
        r = Repair.all_objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            queue_status=status,
            damage_type='chip',
        )
        if deleted:
            r.deleted_at = timezone.now()
            r.save(update_fields=['deleted_at'])
        return r

    def test_default_manager_excludes_soft_deleted(self):
        """Repair.objects must not return soft-deleted repairs."""
        live = self._make_repair(deleted=False)
        dead = self._make_repair(deleted=True)

        qs = Repair.objects.filter(customer=self.customer)
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(live.id, ids)
        self.assertNotIn(dead.id, ids)

    def test_all_objects_includes_soft_deleted(self):
        """Repair.all_objects must include soft-deleted repairs."""
        live = self._make_repair(deleted=False)
        dead = self._make_repair(deleted=True)

        qs = Repair.all_objects.filter(customer=self.customer)
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(live.id, ids)
        self.assertIn(dead.id, ids)

    def test_status_filter_excludes_deleted(self):
        """
        Tenant + status filter (the pattern covered by the partial index)
        must exclude soft-deleted repairs.
        """
        live = self._make_repair(deleted=False, status='PENDING')
        dead = self._make_repair(deleted=True, status='PENDING')

        qs = Repair.objects.filter(tenant=self.tenant, queue_status='PENDING')
        ids = list(qs.values_list('id', flat=True))
        self.assertIn(live.id, ids)
        self.assertNotIn(dead.id, ids)
