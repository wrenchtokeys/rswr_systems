"""
CODE-215 Regression Tests: repair_cost_data_api missing completed filter

Bug: repair_cost_data_api counted ALL repairs regardless of queue_status,
inflating the monthly frequency chart with PENDING, DENIED, IN_PROGRESS, etc.

Fix: Added queue_status='COMPLETED' filter, consistent with unit_repair_data_api.

These tests verify:
1. Only COMPLETED repairs appear in the monthly count data.
2. PENDING/DENIED/IN_PROGRESS repairs are excluded.
3. Empty data pads to 3 placeholder months (existing behaviour preserved).
4. Tenant scoping: only repairs for the authenticated customer's tenant.
"""

import json
from datetime import date, timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser


def _create_tenant(name, slug):
    owner = User.objects.create_user(
        username=f'owner_{slug.replace("-", "_")}',
        email=f'owner_{slug.replace("-", "_")}@test.com',
        password='ownerpass123',
    )
    return Tenant.objects.create(
        name=name,
        slug=slug,
        owner=owner,
        plan='trial',
        is_active=True,
    )


def _create_customer_user(tenant, username, email):
    user = User.objects.create_user(
        username=username,
        email=email,
        password='testpass123',
        first_name='Test',
        last_name='User',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='viewer')
    customer = Customer.objects.create(
        tenant=tenant,
        name=f'Customer for {username}',
        customer_type='FLEET',
        email=email,
    )
    cu = CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=True,
    )
    return user, customer, cu


def _create_tech(tenant, username):
    tech_user = User.objects.create_user(
        username=username,
        password='techpass123',
        first_name='Tech',
        last_name='User',
    )
    TenantMembership.objects.create(tenant=tenant, user=tech_user, role='technician')
    return Technician.objects.create(
        tenant=tenant,
        user=tech_user,
        is_active=True,
    )


def _create_repair(tenant, customer, technician, status, days_ago=0):
    svc_date = timezone.now() - timedelta(days=days_ago)
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-1',
        damage_type='CHIP',
        queue_status=status,
        cost=50,
        service_date=svc_date,
    )


class RepairCostDataApiStatusFilterTests(TestCase):
    """CODE-215: Only COMPLETED repairs should appear in monthly count."""

    def setUp(self):
        self.tenant = _create_tenant('Test Shop', 'test-shop-215')
        self.user, self.customer, self.cu = _create_customer_user(
            self.tenant, 'custuser215', 'cu215@example.com'
        )
        self.tech = _create_tech(self.tenant, 'techuser215')
        self.client = Client()
        # Log in and set tenant session
        self.client.login(username='custuser215', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_only_completed_repairs_counted(self):
        """COMPLETED repairs appear; others do not."""
        # Create one of each status
        _create_repair(self.tenant, self.customer, self.tech, 'COMPLETED', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'PENDING', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'DENIED', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'IN_PROGRESS', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'APPROVED', days_ago=10)

        response = self.client.get('/app/api/repair-cost-data/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        # Should be a list of {date, count} dicts
        self.assertIsInstance(data, list)

        # Sum all counts — should be 1 (only COMPLETED)
        total_count = sum(entry['count'] for entry in data if entry['count'] > 0)
        self.assertEqual(total_count, 1,
            f"Expected 1 completed repair in count, got {total_count}. Data: {data}")

    def test_multiple_completed_repairs_counted(self):
        """All COMPLETED repairs are counted."""
        _create_repair(self.tenant, self.customer, self.tech, 'COMPLETED', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'COMPLETED', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'COMPLETED', days_ago=10)
        _create_repair(self.tenant, self.customer, self.tech, 'PENDING', days_ago=10)

        response = self.client.get('/app/api/repair-cost-data/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        total_count = sum(entry['count'] for entry in data if entry['count'] > 0)
        self.assertEqual(total_count, 3,
            f"Expected 3 completed repairs, got {total_count}. Data: {data}")

    def test_no_completed_repairs_returns_placeholder_months(self):
        """When no completed repairs exist, response pads to ≥3 placeholder months."""
        # Only PENDING — no COMPLETED
        _create_repair(self.tenant, self.customer, self.tech, 'PENDING', days_ago=10)

        response = self.client.get('/app/api/repair-cost-data/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        # The view pads to at least 3 months when data is sparse
        self.assertGreaterEqual(len(data), 3,
            f"Expected ≥3 placeholder months, got {len(data)}")
        total_count = sum(entry['count'] for entry in data)
        self.assertEqual(total_count, 0,
            f"Expected 0 total count with no completed repairs, got {total_count}")

    def test_empty_customer_returns_placeholder_months(self):
        """Customer with no repairs at all still returns ≥3 placeholder months."""
        response = self.client.get('/app/api/repair-cost-data/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertGreaterEqual(len(data), 3)
        total_count = sum(entry['count'] for entry in data)
        self.assertEqual(total_count, 0)

    def test_response_format(self):
        """Each entry has 'date' and 'count' keys."""
        _create_repair(self.tenant, self.customer, self.tech, 'COMPLETED', days_ago=5)

        response = self.client.get('/app/api/repair-cost-data/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        for entry in data:
            self.assertIn('date', entry, f"Missing 'date' key in {entry}")
            self.assertIn('count', entry, f"Missing 'count' key in {entry}")
            # Date should be in YYYY-MM-DD format
            parts = entry['date'].split('-')
            self.assertEqual(len(parts), 3, f"Date not in YYYY-MM-DD format: {entry['date']}")


class RepairCostDataApiTenantScopingTests(TestCase):
    """CODE-215: Tenant scoping — only repairs for the authenticated customer."""

    def setUp(self):
        self.tenant_a = _create_tenant('Shop A', 'shop-a-215')
        self.tenant_b = _create_tenant('Shop B', 'shop-b-215')

        self.user_a, self.customer_a, self.cu_a = _create_customer_user(
            self.tenant_a, 'cust215a', 'cust215a@example.com'
        )
        self.user_b, self.customer_b, self.cu_b = _create_customer_user(
            self.tenant_b, 'cust215b', 'cust215b@example.com'
        )
        self.tech_a = _create_tech(self.tenant_a, 'tech215a')
        self.tech_b = _create_tech(self.tenant_b, 'tech215b')

        self.client_a = Client()
        self.client_a.login(username='cust215a', password='testpass123')
        session = self.client_a.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

    def test_only_own_customer_repairs_counted(self):
        """Customer A does not see Customer B's repairs."""
        # 3 completed repairs for customer A
        for _ in range(3):
            _create_repair(self.tenant_a, self.customer_a, self.tech_a, 'COMPLETED', days_ago=10)
        # 5 completed repairs for customer B
        for _ in range(5):
            _create_repair(self.tenant_b, self.customer_b, self.tech_b, 'COMPLETED', days_ago=10)

        response = self.client_a.get('/app/api/repair-cost-data/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)

        total_count = sum(entry['count'] for entry in data if entry['count'] > 0)
        self.assertEqual(total_count, 3,
            f"Expected 3 (only customer A's repairs), got {total_count}. Data: {data}")
