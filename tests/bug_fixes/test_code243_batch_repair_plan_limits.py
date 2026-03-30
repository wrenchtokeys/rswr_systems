"""
Regression tests for CODE-243: Batch repair creation bypasses plan limits.

Before this fix, four repair creation paths did NOT check the tenant's
subscription plan's `max_repairs_per_month` limit:
  1. technician portal — create_multi_break_repair (batch.py)
  2. technician portal — convert_to_batch (batch.py)
  3. customer portal — handle_single_repair_request (views.py)
  4. customer portal — handle_batch_repair_request (views.py)

A tenant on a Starter plan with a 200-repair/month limit could exceed it
by routing work through these paths instead of the single-repair form.

Author: Amelia (Bug Hunter)
"""

from decimal import Decimal
from datetime import date
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


def _make_plan(slug, name, max_repairs):
    """Create a plan with a repair limit."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=slug,
        defaults={
            'name': name,
            'monthly_price': Decimal('49.00'),
            'trial_days': 0,
            'display_order': 1,
            'max_repairs_per_month': max_repairs,
        },
    )
    # Ensure limit is set even if plan existed
    if plan.max_repairs_per_month != max_repairs:
        plan.max_repairs_per_month = max_repairs
        plan.save()
    return plan


def _setup_tenant_at_limit():
    """Create a tenant on a plan with max_repairs_per_month=5, already at 5 repairs."""
    plan = _make_plan('starter-test', 'Starter Test', 5)
    owner = User.objects.create_user('limit_owner', 'lo@test.com', 'pass')
    tenant = Tenant.objects.create(
        name='Limit Shop', slug='limit-shop', subdomain='limit-shop',
        owner=owner, subscription_plan=plan,
        subscription_status='active',
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')

    tech_user = User.objects.create_user('limit_tech', 'lt@test.com', 'pass')
    tech = Technician.objects.create(
        user=tech_user, tenant=tenant, is_active=True,
    )
    TenantMembership.objects.create(tenant=tenant, user=tech_user, role='technician')

    customer = Customer.objects.create(
        name='Test Customer', tenant=tenant,
    )

    # Create 5 repairs to hit the limit
    for i in range(5):
        Repair.objects.create(
            tenant=tenant, technician=tech, customer=customer,
            unit_number=f'UNIT-{i}', service_date=date.today(),
            damage_type='Star Break', queue_status='COMPLETED',
        )

    return tenant, owner, tech_user, tech, customer


def _make_request(factory, user, tenant, path='/', method='GET', data=None):
    """Build a request with session, messages, and tenant."""
    if method == 'POST':
        request = factory.post(path, data=data or {})
    else:
        request = factory.get(path)
    request.user = user
    request.tenant = tenant
    # Session + messages middleware
    request.session = SessionStore()
    request.session.save()
    setattr(request, '_messages', FallbackStorage(request))
    return request


class CreateMultiBreakPlanLimitTests(TestCase):
    """Test that create_multi_break_repair respects plan limits."""

    def setUp(self):
        self.tenant, self.owner, self.tech_user, self.tech, self.customer = _setup_tenant_at_limit()
        self.factory = RequestFactory()

    def test_get_request_blocked_at_limit(self):
        """GET request to multi-break form should redirect when at limit."""
        from apps.technician_portal.views.batch import create_multi_break_repair

        request = _make_request(self.factory, self.tech_user, self.tenant)
        response = create_multi_break_repair(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/tech/', response.url)

    def test_post_request_blocked_at_limit(self):
        """POST to create multi-break repair should redirect when at limit."""
        from apps.technician_portal.views.batch import create_multi_break_repair

        data = {
            'customer': str(self.customer.id),
            'unit_number': 'OVER-LIMIT',
            'repair_date': '2026-03-30',
            'breaks_count': '2',
        }
        request = _make_request(
            self.factory, self.tech_user, self.tenant,
            method='POST', data=data,
        )
        response = create_multi_break_repair(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/tech/', response.url)
        # No new repairs created
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 5)

    def test_allowed_when_under_limit(self):
        """When under limit, the view should proceed normally (not redirect to dashboard)."""
        from apps.tenants.services.usage_service import UsageService

        # Delete one repair to go under limit
        Repair.objects.filter(tenant=self.tenant).first().delete()
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 4)

        svc = UsageService(self.tenant)
        can_create, msg = svc.can_create_repair()
        self.assertTrue(can_create)


class ConvertToBatchPlanLimitTests(TestCase):
    """Test that convert_to_batch respects plan limits."""

    def setUp(self):
        self.tenant, self.owner, self.tech_user, self.tech, self.customer = _setup_tenant_at_limit()
        self.factory = RequestFactory()
        # Mark last repair as APPROVED so it qualifies for conversion
        self.target_repair = Repair.objects.filter(tenant=self.tenant).last()
        self.target_repair.queue_status = 'APPROVED'
        self.target_repair.save()

    def test_get_request_blocked_at_limit(self):
        """GET request to convert-to-batch should redirect when at limit."""
        from apps.technician_portal.views.batch import convert_to_batch

        request = _make_request(self.factory, self.owner, self.tenant)
        response = convert_to_batch(request, self.target_repair.id)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/tech/repairs/', response.url)

    def test_post_request_blocked_at_limit(self):
        """POST to convert to batch should redirect when at limit."""
        from apps.technician_portal.views.batch import convert_to_batch

        data = {'additional_breaks': '3'}
        request = _make_request(
            self.factory, self.owner, self.tenant,
            method='POST', data=data,
        )
        response = convert_to_batch(request, self.target_repair.id)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/tech/repairs/', response.url)
        # No new repairs created
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 5)


class CustomerPortalSingleRepairPlanLimitTests(TestCase):
    """Test that handle_single_repair_request respects plan limits."""

    def setUp(self):
        self.tenant, self.owner, self.tech_user, self.tech, self.customer = _setup_tenant_at_limit()
        self.factory = RequestFactory()

    def test_single_repair_blocked_at_limit(self):
        """Customer single repair request should show warning when at limit."""
        from apps.customer_portal.views import handle_single_repair_request

        data = {
            'unit_number': 'CUST-OVER',
            'description': 'Test',
            'damage_type': 'Star Break',
        }
        request = _make_request(
            self.factory, self.tech_user, self.tenant,
            path='/customer/request-repair/',
            method='POST', data=data,
        )
        response = handle_single_repair_request(request, self.customer)

        # Should render the form with a warning, not create the repair
        self.assertEqual(response.status_code, 200)
        # No new repairs
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 5)


class CustomerPortalBatchRepairPlanLimitTests(TestCase):
    """Test that handle_batch_repair_request respects plan limits."""

    def setUp(self):
        self.tenant, self.owner, self.tech_user, self.tech, self.customer = _setup_tenant_at_limit()
        self.factory = RequestFactory()

    def test_batch_repair_blocked_at_limit(self):
        """Customer batch repair request should show warning when at limit."""
        from apps.customer_portal.views import handle_batch_repair_request
        import json

        units_data = json.dumps([
            {'unitNumber': 'BATCH-1', 'damageType': 'Star Break'},
        ])
        data = {
            'units_data': units_data,
        }
        request = _make_request(
            self.factory, self.tech_user, self.tenant,
            path='/customer/request-repair/',
            method='POST', data=data,
        )
        request.content_type = 'application/x-www-form-urlencoded'

        response = handle_batch_repair_request(request, self.customer)

        # Should render the form with a warning, not create repairs
        self.assertEqual(response.status_code, 200)
        # No new repairs
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 5)


class UnlimitedPlanBypassTests(TestCase):
    """Verify that tenants on unlimited plans (max_repairs_per_month=None) are not blocked."""

    def test_unlimited_plan_allows_batch(self):
        """Tenant with null max_repairs_per_month should never be blocked."""
        from apps.tenants.services.usage_service import UsageService

        plan = _make_plan('pro-test', 'Pro Test', None)  # None = unlimited
        owner = User.objects.create_user('pro_owner', 'po@test.com', 'pass')
        tenant = Tenant.objects.create(
            name='Pro Shop', slug='pro-shop', subdomain='pro-shop',
            owner=owner, subscription_plan=plan,
            subscription_status='active',
        )

        tech_user = User.objects.create_user('pro_tech', 'pt@test.com', 'pass')
        tech = Technician.objects.create(user=tech_user, tenant=tenant, is_active=True)
        customer = Customer.objects.create(name='Pro Cust', tenant=tenant)

        # Create 1000 repairs
        repairs = [
            Repair(
                tenant=tenant, technician=tech, customer=customer,
                unit_number=f'U-{i}', service_date=date.today(),
                damage_type='Star Break', queue_status='COMPLETED',
            )
            for i in range(1000)
        ]
        Repair.objects.bulk_create(repairs)

        svc = UsageService(tenant)
        can_create, msg = svc.can_create_repair()
        self.assertTrue(can_create)
        self.assertEqual(msg, "")
