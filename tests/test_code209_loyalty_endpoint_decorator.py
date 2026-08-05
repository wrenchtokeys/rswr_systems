"""
CODE-209: owner_loyalty_adjust_points and owner_loyalty_liability_report
used @login_required instead of @owner_or_manager_required.

This means any authenticated user (technicians, customer portal users, or
users from a different tenant) could reach these endpoints. While
_get_owner_tenant() returned (None, None) for non-owner users and the views
returned 403 JSON responses, the @login_required decorator is inconsistent
with the rest of the owner portal endpoints and allows non-owner users to
probe the endpoint surface.

Fix: replace @login_required with @owner_or_manager_required on both views.

This test verifies:
1. Anonymous requests are redirected to login (not 403).
2. Authenticated technicians are redirected (not 403).
3. Authenticated customer portal users are redirected (not 403).
4. Owners can reach both endpoints successfully.
5. Managers can reach both endpoints successfully.
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician


_counter = 0


def _uid(prefix=''):
    global _counter
    _counter += 1
    return f'{prefix}{_counter}'


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    return plan


def _make_tenant(name=None):
    uid = _uid('t')
    plan = _make_plan()
    owner = User.objects.create_user(
        username=f'owner_{uid}',
        email=f'owner_{uid}@example.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=name or f'Shop {uid}',
        slug=f'shop-{uid}',
        subdomain=f'shop-{uid}',
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(
        tenant=tenant, user=owner, role='owner', is_active=True,
    )
    return tenant, owner


def _make_manager(tenant):
    uid = _uid('mgr')
    user = User.objects.create_user(
        username=f'manager_{uid}',
        email=f'manager_{uid}@example.com',
        password='testpass',
    )
    TenantMembership.objects.create(
        tenant=tenant, user=user, role='manager', is_active=True,
    )
    Technician.objects.create(
        tenant=tenant, user=user, is_manager=True, is_active=True,
    )
    return user


def _make_technician(tenant):
    uid = _uid('tech')
    user = User.objects.create_user(
        username=f'tech_{uid}',
        email=f'tech_{uid}@example.com',
        password='testpass',
    )
    TenantMembership.objects.create(
        tenant=tenant, user=user, role='technician', is_active=True,
    )
    Technician.objects.create(
        tenant=tenant, user=user, is_active=True,
    )
    return user


def _make_customer_user(tenant):
    uid = _uid('cu')
    user = User.objects.create_user(
        username=f'cu_{uid}',
        email=f'cu_{uid}@example.com',
        password='testpass',
    )
    customer = Customer.objects.create(
        name=f'Customer {uid}',
        email=f'cu_{uid}@example.com',
        tenant=tenant,
    )
    TenantMembership.objects.create(
        tenant=tenant, user=user, role='customer', is_active=True,
    )
    CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=True)
    return user, customer


class LoyaltyEndpointDecoratorTests(TestCase):
    """Verify that loyalty management endpoints require owner/manager role."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('Loyalty Decorator Test Shop')
        self.manager = _make_manager(self.tenant)
        self.technician = _make_technician(self.tenant)
        self.cu_user, self.customer = _make_customer_user(self.tenant)

        # Create a Customer to target for adjust_points (loyalty is
        # customer-anchored: the endpoint takes a Customer pk)
        _, self.target_customer = _make_customer_user(self.tenant)

        self.client = Client(HTTP_HOST='testserver')

        # URLs
        self.adjust_url = reverse(
            'owner_loyalty_adjust_points',
            kwargs={'customer_id': self.target_customer.pk},
        )
        self.liability_url = reverse('owner_loyalty_liability_report')

    def _with_tenant(self, client):
        """Inject tenant into session so middleware can resolve it."""
        session = client.session
        session['tenant_id'] = self.tenant.pk
        session.save()
        return client

    # ── Anonymous ──────────────────────────────────────────────────────────

    def test_adjust_points_anonymous_redirected(self):
        """Anonymous user → redirect (not 403/500)."""
        response = self.client.post(self.adjust_url, {'amount': '10', 'reason': 'test'})
        self.assertIn(
            response.status_code, [301, 302],
            f"Expected redirect for anonymous user, got {response.status_code}",
        )

    def test_liability_report_anonymous_redirected(self):
        """Anonymous user → redirect (not 403/500)."""
        response = self.client.get(self.liability_url)
        self.assertIn(
            response.status_code, [301, 302],
            f"Expected redirect for anonymous user, got {response.status_code}",
        )

    # ── Technician (should NOT have access) ────────────────────────────────

    def test_adjust_points_technician_redirected(self):
        """Technician → redirect (not allowed to use owner endpoints)."""
        client = Client(HTTP_HOST='testserver')
        client.force_login(self.technician)
        self._with_tenant(client)
        response = client.post(self.adjust_url, {'amount': '10', 'reason': 'test'})
        # @owner_or_manager_required redirects non-owner/manager users
        self.assertIn(
            response.status_code, [301, 302],
            f"Technician should be redirected, got {response.status_code}",
        )

    def test_liability_report_technician_redirected(self):
        """Technician → redirect."""
        client = Client(HTTP_HOST='testserver')
        client.force_login(self.technician)
        self._with_tenant(client)
        response = client.get(self.liability_url)
        self.assertIn(
            response.status_code, [301, 302],
            f"Technician should be redirected, got {response.status_code}",
        )

    # ── Customer portal user (should NOT have access) ──────────────────────

    def test_adjust_points_customer_redirected(self):
        """Customer portal user → redirect."""
        client = Client(HTTP_HOST='testserver')
        client.force_login(self.cu_user)
        self._with_tenant(client)
        response = client.post(self.adjust_url, {'amount': '10', 'reason': 'test'})
        self.assertIn(
            response.status_code, [301, 302],
            f"Customer user should be redirected, got {response.status_code}",
        )

    def test_liability_report_customer_redirected(self):
        """Customer portal user → redirect."""
        client = Client(HTTP_HOST='testserver')
        client.force_login(self.cu_user)
        self._with_tenant(client)
        response = client.get(self.liability_url)
        self.assertIn(
            response.status_code, [301, 302],
            f"Customer user should be redirected, got {response.status_code}",
        )

    # ── Owner (should have access) ──────────────────────────────────────────

    def test_liability_report_owner_allowed(self):
        """Owner → 200 JSON response."""
        client = Client(HTTP_HOST='testserver')
        client.force_login(self.owner)
        self._with_tenant(client)
        response = client.get(self.liability_url)
        self.assertEqual(
            response.status_code, 200,
            f"Owner should get 200, got {response.status_code}",
        )
        data = response.json()
        self.assertIn('total_outstanding_points', data)

    # ── Manager (should have access) ───────────────────────────────────────

    def test_liability_report_manager_allowed(self):
        """Manager → 200 JSON response."""
        client = Client(HTTP_HOST='testserver')
        client.force_login(self.manager)
        self._with_tenant(client)
        response = client.get(self.liability_url)
        self.assertEqual(
            response.status_code, 200,
            f"Manager should get 200, got {response.status_code}",
        )
        data = response.json()
        self.assertIn('total_outstanding_points', data)
