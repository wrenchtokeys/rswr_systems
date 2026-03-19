"""
Regression tests for CODE-085:
unit_repair_data_api() in customer_portal/views.py created UnitRepairCount records
without including tenant= in the update_or_create() lookup keys, and also queried
UnitRepairCount without a tenant filter.

Root cause:
    The fallback path in unit_repair_data_api() that auto-creates UnitRepairCount
    records used:

        UnitRepairCount.objects.update_or_create(
            customer=customer,
            unit_number=repair['unit_number'],
            defaults={'repair_count': repair['count']}
        )

    Omitting tenant= from the lookup keys means:
      (a) If no existing row exists: a new row is created with tenant=NULL.
          NULL-tenant rows are invisible to the tenant-scoped manager and
          interfere with the pricing engine which uses tenant-scoped counts.
      (b) If a NULL-tenant row already exists (left by an older codepath):
          the update matches it and never sets the correct tenant, so the
          NULL-tenant row persists indefinitely.
      (c) A subsequent call that DOES include tenant= (e.g., mark_unit_replaced)
          may then create a SECOND row for the same (tenant, customer, unit_number)
          triplet if the NULL-tenant row still exists — or hit a UniqueConstraint
          violation if it doesn't.

    The initial queryset also lacked a tenant filter:
        UnitRepairCount.objects.filter(customer=customer)
    Customers at multiple shops (edge case) would see counts aggregated across
    all their tenants.

Fix:
    Both the queryset and the update_or_create() call now include tenant=customer.tenant.
    This mirrors the explicit comment + pattern used in customers.py mark_unit_replaced().

Tests:
    A. API returns counts scoped to the correct tenant only (cross-tenant isolation).
    B. update_or_create fallback creates records WITH tenant set (not NULL).
    C. Existing NULL-tenant rows are NOT returned by the scoped queryset.
    D. A customer with repairs at two different tenants only sees their own shop's data.
    E. Authenticated non-customer users get 404 (no CustomerUser record).
"""

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, UnitRepairCount, Repair
from apps.customer_portal.models import CustomerUser
from core.models import Customer

User = get_user_model()


def _make_tenant(slug, name=None):
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='ownerpass123!',
    )
    return Tenant.objects.create(
        name=name or slug,
        slug=slug,
        is_active=True,
        subscription_status='trialing',
        owner=owner,
    )


def _make_user(email, password='pass1234!'):
    u = User.objects.create_user(
        username=email.split('@')[0],
        email=email,
        password=password,
    )
    return u


def _make_customer(tenant, name='Test Fleet'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='FLEET',
    )


def _make_customer_user(user, customer, primary=True):
    return CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=primary,
    )


_tech_counter = 0


def _make_technician(tenant):
    """Create a dummy technician for a tenant."""
    global _tech_counter
    _tech_counter += 1
    tech_user = User.objects.create_user(
        username=f'tech_{tenant.slug}_{_tech_counter}',
        email=f'tech_{tenant.slug}_{_tech_counter}@example.com',
        password='techpass!',
    )
    return Technician.objects.create(
        tenant=tenant,
        user=tech_user,
        is_active=True,
    )


def _make_repair(tenant, customer, unit_number, status='COMPLETED', technician=None):
    if technician is None:
        technician = _make_technician(tenant)
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number=unit_number,
        queue_status=status,
        cost=50,
    )


class UnitRepairDataApiTenantScopeTests(TestCase):
    """Tests for CODE-085: unit_repair_data_api tenant scoping."""

    def setUp(self):
        self.client = Client()

        # Two shops
        self.shop_a = _make_tenant('shop-a', 'Shop A')
        self.shop_b = _make_tenant('shop-b', 'Shop B')

        # Customer at Shop A
        self.user_a = _make_user('customer_a@example.com')
        self.customer_a = _make_customer(self.shop_a, 'Fleet A')
        self.cu_a = _make_customer_user(self.user_a, self.customer_a)
        TenantMembership.objects.create(tenant=self.shop_a, user=self.user_a, role='viewer', is_active=True)

        # Customer at Shop B
        self.user_b = _make_user('customer_b@example.com')
        self.customer_b = _make_customer(self.shop_b, 'Fleet B')
        self.cu_b = _make_customer_user(self.user_b, self.customer_b)
        TenantMembership.objects.create(tenant=self.shop_b, user=self.user_b, role='viewer', is_active=True)

    def _get_api(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('unit_repair_data_api'))

    # ── Test A: Returned counts belong only to the requesting customer's tenant ──

    def test_a_returns_only_own_tenant_counts(self):
        """API must return UnitRepairCount rows scoped to the user's own tenant."""
        # Create counts for both shops on the SAME unit number
        UnitRepairCount.objects.create(
            tenant=self.shop_a,
            customer=self.customer_a,
            unit_number='UNIT-001',
            repair_count=5,
        )
        UnitRepairCount.objects.create(
            tenant=self.shop_b,
            customer=self.customer_b,
            unit_number='UNIT-001',
            repair_count=99,
        )

        response = self._get_api(self.user_a)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['unit_number'], 'UNIT-001')
        self.assertEqual(data[0]['count'], 5, "Shop A customer must see only Shop A's count (5), not Shop B's (99)")

    # ── Test B: Fallback path creates records with tenant set ──

    def test_b_fallback_creates_tenant_scoped_records(self):
        """When no UnitRepairCount exists, the fallback must create records with tenant set."""
        # No UnitRepairCount records — create a completed repair so the fallback has data
        tech = _make_technician(self.shop_a)
        _make_repair(self.shop_a, self.customer_a, 'UNIT-AAA', status='COMPLETED', technician=tech)

        self.client.force_login(self.user_a)
        response = self.client.get(reverse('unit_repair_data_api'))
        self.assertEqual(response.status_code, 200)

        # The fallback should have created a UnitRepairCount for shop_a
        count_record = UnitRepairCount.objects.filter(
            customer=self.customer_a,
            unit_number='UNIT-AAA',
        ).first()
        self.assertIsNotNone(count_record, "Fallback must create a UnitRepairCount row")
        self.assertEqual(
            count_record.tenant_id,
            self.shop_a.id,
            "Fallback-created UnitRepairCount must have tenant set to Shop A, not NULL"
        )

    # ── Test C: NULL-tenant rows are NOT returned by the scoped queryset ──

    def test_c_null_tenant_rows_not_returned(self):
        """Pre-existing NULL-tenant rows must not appear in the API response."""
        # Simulate a legacy NULL-tenant row for this customer
        UnitRepairCount.objects.create(
            tenant=None,          # legacy/broken row
            customer=self.customer_a,
            unit_number='UNIT-LEGACY',
            repair_count=7,
        )
        # Also create a properly-scoped row
        UnitRepairCount.objects.create(
            tenant=self.shop_a,
            customer=self.customer_a,
            unit_number='UNIT-GOOD',
            repair_count=3,
        )

        response = self._get_api(self.user_a)
        self.assertEqual(response.status_code, 200)

        units = {row['unit_number'] for row in response.json()}
        self.assertIn('UNIT-GOOD', units)
        self.assertNotIn('UNIT-LEGACY', units, "NULL-tenant legacy rows must not be returned")

    # ── Test D: Cross-tenant data is not visible ──

    def test_d_cross_tenant_counts_invisible(self):
        """Shop B's UnitRepairCount rows must never appear in Shop A customer's response."""
        # Only create counts for Shop B
        UnitRepairCount.objects.create(
            tenant=self.shop_b,
            customer=self.customer_b,
            unit_number='UNIT-BBB',
            repair_count=42,
        )

        response = self._get_api(self.user_a)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data), 0, "Shop A customer must see 0 rows — Shop B counts must not bleed over")

    # ── Test E: Non-customer user gets appropriate error ──

    def test_e_non_customer_user_gets_error(self):
        """A user with no CustomerUser record should get a 404 or redirect."""
        non_customer = _make_user('tech@example.com')
        self.client.force_login(non_customer)
        response = self.client.get(reverse('unit_repair_data_api'))
        # @customer_required redirects; bare CustomerUser.DoesNotExist returns 404
        self.assertIn(response.status_code, [302, 404])

    # ── Test F: Fallback only counts COMPLETED repairs ──

    def test_f_fallback_counts_only_completed_repairs(self):
        """Fallback creation must only count COMPLETED repairs, not PENDING/REQUESTED."""
        tech = _make_technician(self.shop_a)
        _make_repair(self.shop_a, self.customer_a, 'UNIT-DONE', status='COMPLETED', technician=tech)
        _make_repair(self.shop_a, self.customer_a, 'UNIT-DONE', status='COMPLETED', technician=tech)
        _make_repair(self.shop_a, self.customer_a, 'UNIT-DONE', status='PENDING', technician=tech)  # should not count

        response = self._get_api(self.user_a)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        unit = next((d for d in data if d['unit_number'] == 'UNIT-DONE'), None)
        self.assertIsNotNone(unit)
        self.assertEqual(unit['count'], 2, "Fallback must count only COMPLETED repairs (2), not PENDING (3)")
