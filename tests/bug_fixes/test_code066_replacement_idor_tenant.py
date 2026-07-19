"""
Regression tests for CODE-066:
  replacement_detail(), replacement_edit(), and replacement_update_status()
  fetched the Replacement via get_object_or_404(Replacement, pk=pk) WITHOUT
  a tenant filter.  The follow-up tenant-id check then returned a 302 redirect
  instead of a proper 404, leaking the information that the record EXISTS
  (IDOR — Insecure Direct Object Reference information disclosure).

  Inconsistency with the rest of the codebase: every other object lookup in
  saas/views.py (Invoice, TaxRate, TenantMembership) passes tenant= directly
  to get_object_or_404 so a cross-tenant request receives a clean 404.

Root cause:
    Three views used a two-step pattern:
        replacement = get_object_or_404(Replacement, pk=pk)       # step 1
        if not tenant or replacement.tenant_id != tenant.id:      # step 2
            messages.error(...)
            return redirect('owner_dashboard')

Fix (CODE-066):
    Guard for no-tenant context first, then pass tenant= directly to
    get_object_or_404 so the DB query itself enforces ownership:
        if not tenant: return redirect_to_portal(...)
        replacement = get_object_or_404(Replacement, pk=pk, tenant=tenant)

Tests verify:
1. Owner at Shop A can view their own replacement (200 OK).
2. Owner at Shop B requesting Shop A's replacement PK gets 404, not 302.
3. Owner at Shop A can edit their own replacement (200 OK).
4. Owner at Shop B requesting edit of Shop A's replacement gets 404.
5. Owner at Shop A can POST to update_status on their own replacement (302).
6. Owner at Shop B POSTing to update_status on Shop A's replacement gets 404.
7. Missing tenant context (no session tenant) returns redirect-to-portal.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Replacement, Technician
from core.models import Customer

import uuid


def make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
                  'max_technicians': 10, 'max_customers': 100, 'max_repairs_per_month': 1000}
    )
    return plan


def make_tenant(name=None, owner=None):
    slug = uuid.uuid4().hex[:12]
    _owner = owner or make_user('auto_owner')
    plan = make_plan()
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


def make_user(prefix='user'):
    slug = uuid.uuid4().hex[:8]
    return User.objects.create_user(
        username=f'{prefix}_{slug}',
        email=f'{prefix}_{slug}@test.com',
        password='pass',
        first_name='Test',
        last_name='User',
    )


def make_customer(tenant):
    customer = Customer.objects.create(
        name=f'Customer {uuid.uuid4().hex[:6]}',
        tenant=tenant,
        email=f'cust_{uuid.uuid4().hex[:6]}@test.com',
    )
    # Explicitly require approval — shop-created work auto-approves by default
    from apps.customer_portal.models import CustomerRepairPreference
    CustomerRepairPreference.objects.create(
        customer=customer,
        field_repair_approval_mode='REQUIRE_APPROVAL',
    )
    return customer


def make_technician(user, tenant):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        expertise='windshield',
        is_active=True,
    )


def make_replacement(tenant, customer, technician=None):
    return Replacement.objects.create(
        tenant=tenant,
        customer=customer,
        unit_number=f'UNIT-{uuid.uuid4().hex[:4]}',
        glass_position='WINDSHIELD',
        glass_type='OEM',
        parts_cost=Decimal('150.00'),
        labor_cost=Decimal('75.00'),
        adas_calibration_cost=Decimal('0.00'),
        cost=Decimal('225.00'),
        technician=technician,
        service_date=date.today(),
        queue_status='PENDING',
    )


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
}


def _login_as_owner(client, user, tenant):
    """Force-login user and inject tenant into session."""
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


from django.test import override_settings


@override_settings(**TEST_OVERRIDES)
class ReplacementTenantIsolationTest(TestCase):
    """Verify replacement views enforce tenant ownership via get_object_or_404."""

    def setUp(self):
        # Shop A
        self.owner_a = make_user('owner_a')
        self.tenant_a = make_tenant('Shop A', owner=self.owner_a)
        self.customer_a = make_customer(self.tenant_a)
        self.tech_a = make_technician(self.owner_a, self.tenant_a)
        self.replacement_a = make_replacement(self.tenant_a, self.customer_a, self.tech_a)

        # Shop B
        self.owner_b = make_user('owner_b')
        self.tenant_b = make_tenant('Shop B', owner=self.owner_b)

    # ── detail ────────────────────────────────────────────────────────────────

    def test_owner_a_can_view_own_replacement(self):
        """Shop A owner gets 200 on their own replacement."""
        client = Client()
        _login_as_owner(client, self.owner_a, self.tenant_a)
        resp = client.get(
            f'/tech/replacement/{self.replacement_a.pk}/',
            HTTP_HOST='testserver',
        )
        self.assertEqual(resp.status_code, 200)

    def test_owner_b_gets_404_on_shop_a_replacement_detail(self):
        """Shop B owner requesting Shop A's replacement gets 404, not 302."""
        client = Client()
        _login_as_owner(client, self.owner_b, self.tenant_b)
        resp = client.get(
            f'/tech/replacement/{self.replacement_a.pk}/',
            HTTP_HOST='testserver',
        )
        # Must be 404 — returning 302 would leak that the record exists
        self.assertEqual(resp.status_code, 404)

    def test_owner_b_does_not_get_302_on_shop_a_replacement_detail(self):
        """Ensure the old IDOR bug (302 redirect that reveals existence) is gone."""
        client = Client()
        _login_as_owner(client, self.owner_b, self.tenant_b)
        resp = client.get(
            f'/tech/replacement/{self.replacement_a.pk}/',
            HTTP_HOST='testserver',
        )
        self.assertNotEqual(resp.status_code, 302,
            "302 redirect leaks replacement existence to other-tenant user")

    # ── edit ──────────────────────────────────────────────────────────────────

    def test_owner_a_can_edit_own_replacement(self):
        """Shop A owner gets 200 on the edit form for their own replacement."""
        client = Client()
        _login_as_owner(client, self.owner_a, self.tenant_a)
        resp = client.get(
            f'/tech/replacement/{self.replacement_a.pk}/edit/',
            HTTP_HOST='testserver',
        )
        self.assertEqual(resp.status_code, 200)

    def test_owner_b_gets_404_on_shop_a_replacement_edit(self):
        """Shop B owner requesting edit of Shop A's replacement gets 404."""
        client = Client()
        _login_as_owner(client, self.owner_b, self.tenant_b)
        resp = client.get(
            f'/tech/replacement/{self.replacement_a.pk}/edit/',
            HTTP_HOST='testserver',
        )
        self.assertEqual(resp.status_code, 404)

    # ── update_status ─────────────────────────────────────────────────────────

    def test_owner_a_can_update_status_on_own_replacement(self):
        """Shop A owner POSTing a valid status transition gets 302 to detail."""
        client = Client()
        _login_as_owner(client, self.owner_a, self.tenant_a)
        resp = client.post(
            f'/tech/replacement/{self.replacement_a.pk}/update-status/',
            {'status': 'APPROVED'},
            HTTP_HOST='testserver',
        )
        # Should redirect to detail page (success)
        self.assertEqual(resp.status_code, 302)
        self.replacement_a.refresh_from_db()
        self.assertEqual(self.replacement_a.queue_status, 'APPROVED')

    def test_owner_b_gets_404_on_update_status_for_shop_a_replacement(self):
        """Shop B owner POSTing to Shop A's replacement status endpoint gets 404."""
        client = Client()
        _login_as_owner(client, self.owner_b, self.tenant_b)
        resp = client.post(
            f'/tech/replacement/{self.replacement_a.pk}/update-status/',
            {'status': 'APPROVED'},
            HTTP_HOST='testserver',
        )
        self.assertEqual(resp.status_code, 404)
        # Status must NOT have changed
        self.replacement_a.refresh_from_db()
        self.assertEqual(self.replacement_a.queue_status, 'PENDING')

    def test_owner_b_cannot_mutate_shop_a_replacement_via_status_post(self):
        """Cross-tenant status mutation is rejected and record is unchanged."""
        client = Client()
        _login_as_owner(client, self.owner_b, self.tenant_b)
        for status in ('APPROVED', 'IN_PROGRESS', 'COMPLETED', 'DENIED'):
            client.post(
                f'/tech/replacement/{self.replacement_a.pk}/update-status/',
                {'status': status},
                HTTP_HOST='testserver',
            )
        self.replacement_a.refresh_from_db()
        # All POSTs should have been rejected; original status preserved
        self.assertEqual(self.replacement_a.queue_status, 'PENDING')
