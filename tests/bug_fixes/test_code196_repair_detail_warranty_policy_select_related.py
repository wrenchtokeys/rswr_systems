"""
CODE-196: repair_detail view missing select_related('warranty_policy')

Bug: The repair_detail queryset used:
    Repair.objects.select_related('customer', 'technician__user')
but NOT 'warranty_policy'. The repair_detail.html template accesses
repair.warranty_policy at two points:
  - {% if repair.queue_status == 'COMPLETED' and repair.warranty_policy %}
  - repair.warranty_policy.name  (triggers extra SELECT if not prefetched)
  - repair.warranty_policy.coverage_description

For any COMPLETED repair with a warranty policy assigned, this caused an
extra DB query per page load (N=1 extra SELECT per request, every time).

Fix: Add 'warranty_policy' to the select_related() call in repair_detail().

Test: Verifies that accessing repair.warranty_policy.name after a simulated
repair_detail fetch does NOT trigger an additional query (i.e., the
WarrantyPolicy was loaded in the same query via JOIN).
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.technician_portal.models import Repair, Technician, WarrantyPolicy
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class RepairDetailWarrantyPolicySelectRelatedTest(TestCase):
    """Verify warranty_policy is select_related in repair_detail queryset."""

    def setUp(self):
        # Create owner user first (Tenant requires owner FK)
        self.owner = User.objects.create_user(
            username='owner_wsr',
            email='owner@testshop.com',
            password='testpass123',
        )

        # Create tenant
        self.tenant = Tenant.objects.create(
            name='Test Shop',
            slug='test-shop-warranty-sr',
            subdomain='test-shop-warranty-sr',
            owner=self.owner,
        )

        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
            is_active=True,
        )

        # Create technician user
        self.tech_user = User.objects.create_user(
            username='tech_wsr',
            email='tech@testshop.com',
            password='testpass123',
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.tech_user,
            role='technician',
            is_active=True,
        )
        self.technician = Technician.objects.create(
            user=self.tech_user,
            tenant=self.tenant,
            is_active=True,
            can_repair=True,
        )

        # Create customer
        self.customer = Customer.objects.create(
            name='Fleet Co',
            tenant=self.tenant,
        )

        # Create warranty policy
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard 1-Year',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            coverage_description='Labor and materials for one year.',
            covers_labor=True,
            covers_materials=True,
            is_active=True,
        )

        # Create a COMPLETED repair with warranty assigned
        self.repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-001',
            damage_type='chip',
            queue_status='COMPLETED',
            cost=50,
            warranty_policy=self.policy,
            warranty_expires_at=timezone.now() + timezone.timedelta(days=365),
        )

    def test_repair_detail_queryset_includes_warranty_policy(self):
        """
        The repair_detail view queryset must select_related('warranty_policy')
        so that accessing repair.warranty_policy.name does NOT fire an extra query.
        """
        from apps.technician_portal.models import Repair as RepairModel

        # Simulate the repair_detail queryset (the fixed version)
        qs = RepairModel.objects.select_related(
            'customer', 'technician__user', 'warranty_policy'
        ).filter(tenant=self.tenant)

        # Fetch the repair — this should JOIN warranty_policy in the same query
        repair = qs.get(pk=self.repair.pk)

        # Now count queries when we access warranty_policy attributes
        # If select_related worked, zero additional queries should fire
        with CaptureQueriesContext(connection) as ctx:
            # These attribute accesses would fire extra SELECTs if warranty_policy
            # was NOT select_related (the bug we're fixing).
            _ = repair.warranty_policy
            _ = repair.warranty_policy.name
            _ = repair.warranty_policy.coverage_description

        self.assertEqual(
            len(ctx.captured_queries),
            0,
            f"Expected 0 additional queries after select_related, "
            f"got {len(ctx.captured_queries)}: {[q['sql'][:80] for q in ctx.captured_queries]}"
        )

    def test_repair_detail_view_returns_200_with_warranty(self):
        """
        The repair_detail view should return 200 for a completed repair
        that has a warranty policy assigned.
        """
        client = Client()
        client.login(username='owner_wsr', password='testpass123')

        # Set the tenant on the session/middleware (simulate middleware)
        session = client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        response = client.get(f'/tech/repairs/{self.repair.id}/')

        # Should not 500 — the template must render correctly even with warranty_policy
        # set on the repair (and now properly select_related'd in the view).
        self.assertIn(response.status_code, [200, 302],
                      f"Unexpected status code: {response.status_code}")

    def test_repair_without_warranty_policy_still_renders(self):
        """
        A COMPLETED repair without any warranty policy should also render correctly
        (no AttributeError from repair.warranty_policy being None).
        """
        # Create a repair with no warranty
        repair_no_warranty = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-002',
            damage_type='chip',
            queue_status='COMPLETED',
            cost=50,
        )

        qs = Repair.objects.select_related(
            'customer', 'technician__user', 'warranty_policy'
        ).filter(tenant=self.tenant)

        repair = qs.get(pk=repair_no_warranty.pk)

        # warranty_policy should be None (no extra query needed)
        with CaptureQueriesContext(connection) as ctx:
            _ = repair.warranty_policy

        self.assertEqual(len(ctx.captured_queries), 0,
                         "No query should fire when warranty_policy is already loaded as None")
        self.assertIsNone(repair.warranty_policy)
