"""
Regression tests for CODE-073:
  delete_customer() used Repair.objects (RepairSoftDeleteManager — excludes
  soft-deleted records) to check whether a customer had repairs.

Root cause:
    GlassService.customer FK uses on_delete=SET_NULL. Repair.objects uses
    RepairSoftDeleteManager which excludes rows where deleted_at IS NOT NULL.
    A customer with ONLY soft-deleted repairs would pass the check (count=0),
    letting the deletion through. After deletion:
      - The customer row is gone.
      - Every archived repair's customer FK is NULLed by Django SET_NULL.
      - Those repairs are now permanently orphaned — the archive/restore page
        can still show them (they have a tenant FK) but they have no customer
        name, no customer context, and cannot be meaningfully restored.

Fix (CODE-073):
    Changed Repair.objects.filter(...) to Repair.all_objects.filter(...) so
    the count includes soft-deleted repairs. Any customer with any repair —
    active OR archived — is protected from deletion.

Tests verify:
    1. Customer with NO repairs at all: deletion allowed (happy path).
    2. Customer with only active (non-deleted) repairs: deletion blocked.
    3. Customer with only soft-deleted repairs: deletion blocked (the bug fix).
    4. Customer with both active and soft-deleted repairs: deletion blocked.
    5. Cross-tenant: cannot delete another tenant's customer (404).
    6. Non-admin user: blocked with permission error.
"""

import datetime
import uuid

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from core.models import Customer
from apps.technician_portal.models import Technician, Repair


# ---------------------------------------------------------------------------
# Shared test helpers (copied from test_code066 pattern)
# ---------------------------------------------------------------------------

def make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
            'max_technicians': 10, 'max_customers': 100, 'max_repairs_per_month': 1000,
        }
    )
    return plan


def make_user(prefix='user'):
    slug = uuid.uuid4().hex[:8]
    return User.objects.create_user(
        username=f'{prefix}_{slug}',
        email=f'{prefix}_{slug}@test.com',
        password='pass',
        first_name='Test',
        last_name='User',
    )


def make_tenant(name=None, owner=None):
    slug = uuid.uuid4().hex[:12]
    _owner = owner or make_user('auto_owner')
    make_plan()
    tenant = Tenant.objects.create(
        name=name or f'Shop {slug}',
        slug=slug,
        owner=_owner,
        plan='trial',
        is_active=True,
    )
    if owner:
        TenantMembership.objects.create(
            user=owner, tenant=tenant, role='owner', is_active=True
        )
    return tenant


def make_technician(user, tenant):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        expertise='windshield',
        is_active=True,
    )


def make_repair(customer, tenant, technician, deleted=False):
    """Create a repair and optionally soft-delete it."""
    repair = Repair.all_objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        queue_status='COMPLETED',
    )
    if deleted:
        repair.deleted_at = timezone.now() - datetime.timedelta(days=1)
        repair.save(update_fields=['deleted_at'])
    return repair


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class DeleteCustomerSoftDeletedRepairsTest(TestCase):
    """CODE-073: delete_customer() must count soft-deleted repairs too."""

    def setUp(self):
        self.admin_user = make_user('admin')
        self.tenant = make_tenant(name='Shop A', owner=self.admin_user)
        self.technician = make_technician(self.admin_user, self.tenant)
        self.client.force_login(self.admin_user)

        # Simulate tenant middleware by storing tenant_id in session
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_delete_customer_with_no_repairs_succeeds(self):
        """Customer with zero repairs should be deletable."""
        customer = Customer.objects.create(
            name='Empty Customer',
            tenant=self.tenant,
        )
        response = self.client.post(
            f'/tech/customers/{customer.id}/delete/',
        )
        # Should redirect to customer list (success)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Customer.objects.filter(id=customer.id).exists())

    def test_delete_customer_with_active_repairs_blocked(self):
        """Customer with active (non-deleted) repairs must not be deleted."""
        customer = Customer.objects.create(
            name='Active Repairs Customer',
            tenant=self.tenant,
        )
        make_repair(customer, self.tenant, self.technician, deleted=False)

        response = self.client.post(
            f'/tech/customers/{customer.id}/delete/',
        )
        self.assertEqual(response.status_code, 302)
        # Customer must still exist
        self.assertTrue(Customer.objects.filter(id=customer.id).exists())

    def test_delete_customer_with_only_soft_deleted_repairs_blocked(self):
        """
        THE BUG: Customer with ONLY soft-deleted repairs used to pass the
        check (Repair.objects excludes deleted rows, returns count=0) and
        the customer was deleted, orphaning archived repairs with NULL customer.
        """
        customer = Customer.objects.create(
            name='Archived Repairs Customer',
            tenant=self.tenant,
        )
        repair = make_repair(customer, self.tenant, self.technician, deleted=True)
        self.assertIsNotNone(repair.deleted_at)  # sanity-check it's soft-deleted

        # Verify the bug condition: Repair.objects returns 0 (the broken path)
        self.assertEqual(
            Repair.objects.filter(customer=customer, tenant=self.tenant).count(),
            0,
            "Repair.objects should exclude soft-deleted repairs (root-cause verification)"
        )
        # Verify Repair.all_objects sees it
        self.assertEqual(
            Repair.all_objects.filter(customer=customer, tenant=self.tenant).count(),
            1,
        )

        response = self.client.post(
            f'/tech/customers/{customer.id}/delete/',
        )
        # Must be BLOCKED — customer still exists
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Customer.objects.filter(id=customer.id).exists(),
            "Customer with soft-deleted repairs must NOT be deletable (CODE-073)"
        )
        # The archived repair must still have its customer FK intact
        repair.refresh_from_db()
        self.assertEqual(
            repair.customer_id, customer.id,
            "Archived repair's customer FK must not be NULLed"
        )

    def test_delete_customer_with_mixed_repairs_blocked(self):
        """Customer with both active and soft-deleted repairs must not be deleted."""
        customer = Customer.objects.create(
            name='Mixed Repairs Customer',
            tenant=self.tenant,
        )
        make_repair(customer, self.tenant, self.technician, deleted=False)
        make_repair(customer, self.tenant, self.technician, deleted=True)

        response = self.client.post(
            f'/tech/customers/{customer.id}/delete/',
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(id=customer.id).exists())

    def test_cross_tenant_delete_returns_404(self):
        """Cannot delete a customer belonging to a different tenant."""
        other_user = make_user('other_owner')
        other_tenant = make_tenant(name='Shop B', owner=other_user)
        other_customer = Customer.objects.create(
            name='Other Tenant Customer',
            tenant=other_tenant,
        )

        response = self.client.post(
            f'/tech/customers/{other_customer.id}/delete/',
        )
        # Tenant-scoped lookup should 404 for cross-tenant requests
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Customer.objects.filter(id=other_customer.id).exists())

    def test_non_admin_cannot_delete_customer(self):
        """Plain technician must be blocked from deletion."""
        plain_user = make_user('tech')
        TenantMembership.objects.create(
            user=plain_user,
            tenant=self.tenant,
            role='technician',
            is_active=True,
        )
        Technician.objects.create(user=plain_user, tenant=self.tenant)

        customer = Customer.objects.create(
            name='Deletable Customer',
            tenant=self.tenant,
        )

        self.client.force_login(plain_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        response = self.client.post(
            f'/tech/customers/{customer.id}/delete/',
        )
        self.assertEqual(response.status_code, 302)
        # Customer still exists — permission denied
        self.assertTrue(Customer.objects.filter(id=customer.id).exists())
