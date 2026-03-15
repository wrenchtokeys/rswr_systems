"""
CODE-032 Regression: is_tenant_admin() called multiple times per batch view.

Before fix:
  - technician_batch_detail: 2 calls (permission check + context dict)
  - create_multi_break_repair: 2 calls (POST branch + GET branch)
  - convert_to_batch:
      * 1 call at the top (permission gate)
      * 1 call PER BREAK inside `for i in range(additional_breaks)` — N+1 DB queries
        Converting a 10-break batch fired 11 TenantMembership queries instead of 1.

After fix: every view caches the result in a local `user_is_admin` variable
           computed once at the top of the function. The loop in convert_to_batch
           now reads the cached boolean.

Tests verify:
1. technician_batch_detail works correctly for admin and non-admin users.
2. create_multi_break_repair GET works correctly.
3. convert_to_batch GET works correctly.
4. convert_to_batch POST with multiple breaks calls is_tenant_admin exactly ONCE
   (not N+1 where N = additional_breaks).
5. Cross-tenant and permission isolation still work.
"""
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
}


def _make_tenant_with_owner(name, slug):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        password='pw',
        email=f'owner_{slug}@test.com',
        first_name='Test',
        last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return owner, tenant


def _make_tech(tenant, suffix):
    user = User.objects.create_user(
        username=f'tech_{suffix}',
        password='pw',
        email=f'tech_{suffix}@test.com',
    )
    TenantMembership.objects.create(user=user, tenant=tenant, role='technician', is_active=True)
    tech = Technician.objects.create(user=user, tenant=tenant, is_active=True)
    return user, tech


def _make_customer(tenant, name):
    return Customer.objects.create(name=name, tenant=tenant)


def _make_repair(tenant, customer, technician, queue_status='APPROVED', **kwargs):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='T-001',
        damage_type='chip',
        cost=Decimal('50.00'),
        queue_status=queue_status,
        **kwargs,
    )


@override_settings(**TEST_OVERRIDES)
class BatchDetailCacheTests(TestCase):
    """technician_batch_detail: is_tenant_admin cached, not called twice."""

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('BD Shop', 'bd-shop')
        _, self.tech = _make_tech(self.tenant, 'bd1')
        self.customer = _make_customer(self.tenant, 'BD Customer')
        self.batch_id = uuid.uuid4()
        self.repair = _make_repair(
            self.tenant, self.customer, self.tech,
            queue_status='APPROVED',
            repair_batch_id=self.batch_id,
            break_number=1,
            total_breaks_in_batch=1,
        )

    def test_admin_can_view_batch(self):
        """Owner (admin) should see the batch detail page (200 or redirect handled)."""
        client = Client()
        client.force_login(self.owner)
        resp = client.get(
            reverse('technician_batch_detail', kwargs={'batch_id': self.batch_id}),
            SERVER_NAME='bd-shop.testserver',
        )
        self.assertIn(resp.status_code, [200, 302])

    def test_assigned_tech_can_view_batch(self):
        """Assigned technician should be able to view their own batch."""
        client = Client()
        client.force_login(self.tech.user)
        resp = client.get(
            reverse('technician_batch_detail', kwargs={'batch_id': self.batch_id}),
            SERVER_NAME='bd-shop.testserver',
        )
        self.assertIn(resp.status_code, [200, 302])

    def test_unassigned_tech_redirected(self):
        """Unassigned tech should be redirected — cannot view someone else's batch."""
        _, other_tech = _make_tech(self.tenant, 'bd2')
        client = Client()
        client.force_login(other_tech.user)
        resp = client.get(
            reverse('technician_batch_detail', kwargs={'batch_id': self.batch_id}),
            SERVER_NAME='bd-shop.testserver',
        )
        self.assertEqual(resp.status_code, 302)

    def test_is_tenant_admin_called_once(self):
        """is_tenant_admin should be called exactly once (not twice) for batch_detail."""
        from apps.technician_portal.views import batch as batch_module
        with patch.object(batch_module, 'is_tenant_admin', wraps=batch_module.is_tenant_admin) as mock_fn:
            client = Client()
            client.force_login(self.owner)
            client.get(
                reverse('technician_batch_detail', kwargs={'batch_id': self.batch_id}),
                SERVER_NAME='bd-shop.testserver',
            )
        self.assertEqual(mock_fn.call_count, 1,
            f"is_tenant_admin called {mock_fn.call_count}× — expected 1 (cached fix for CODE-032)")


@override_settings(**TEST_OVERRIDES)
class CreateMultiBreakGetCacheTests(TestCase):
    """create_multi_break_repair GET: is_tenant_admin cached once."""

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('MB Shop', 'mb-shop')

    def test_get_renders_for_admin(self):
        """GET should succeed for an admin user."""
        client = Client()
        client.force_login(self.owner)
        resp = client.get(
            reverse('create_multi_break_repair'),
            SERVER_NAME='mb-shop.testserver',
        )
        self.assertIn(resp.status_code, [200, 302])

    def test_is_tenant_admin_called_once_on_get(self):
        """GET path: is_tenant_admin should be called exactly once."""
        from apps.technician_portal.views import batch as batch_module
        with patch.object(batch_module, 'is_tenant_admin', wraps=batch_module.is_tenant_admin) as mock_fn:
            client = Client()
            client.force_login(self.owner)
            client.get(
                reverse('create_multi_break_repair'),
                SERVER_NAME='mb-shop.testserver',
            )
        self.assertEqual(mock_fn.call_count, 1,
            f"is_tenant_admin called {mock_fn.call_count}× on GET — expected 1 (CODE-032 cache fix)")


@override_settings(**TEST_OVERRIDES)
class ConvertToBatchCacheTests(TestCase):
    """convert_to_batch: is_tenant_admin NOT called inside the per-break loop (N+1 fix)."""

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('CTB Shop', 'ctb-shop')
        _, self.tech = _make_tech(self.tenant, 'ctb1')
        self.customer = _make_customer(self.tenant, 'CTB Customer')
        self.repair = _make_repair(
            self.tenant, self.customer, self.tech, queue_status='APPROVED'
        )

    def test_get_renders_for_admin(self):
        """GET should render the convert-to-batch form for an admin."""
        client = Client()
        client.force_login(self.owner)
        resp = client.get(
            reverse('convert_to_batch', kwargs={'repair_id': self.repair.id}),
            SERVER_NAME='ctb-shop.testserver',
        )
        self.assertIn(resp.status_code, [200, 302])

    def test_is_tenant_admin_called_once_on_get(self):
        """GET path: is_tenant_admin should be called exactly once (not per request check)."""
        from apps.technician_portal.views import batch as batch_module
        with patch.object(batch_module, 'is_tenant_admin', wraps=batch_module.is_tenant_admin) as mock_fn:
            client = Client()
            client.force_login(self.owner)
            client.get(
                reverse('convert_to_batch', kwargs={'repair_id': self.repair.id}),
                SERVER_NAME='ctb-shop.testserver',
            )
        self.assertEqual(mock_fn.call_count, 1,
            f"is_tenant_admin called {mock_fn.call_count}× on GET — expected 1")

    def test_is_tenant_admin_not_n_plus_one_on_post(self):
        """POST with N breaks: is_tenant_admin called ONCE (not N+1 — the key N+1 fix)."""
        from apps.technician_portal.views import batch as batch_module
        additional_breaks = 4  # Before fix: would fire 5 is_tenant_admin calls

        post_data = {'additional_breaks': str(additional_breaks)}
        for i in range(additional_breaks):
            post_data[f'damage_type_{i}'] = 'chip'

        with patch.object(batch_module, 'is_tenant_admin', wraps=batch_module.is_tenant_admin) as mock_fn:
            client = Client()
            client.force_login(self.owner)
            client.post(
                reverse('convert_to_batch', kwargs={'repair_id': self.repair.id}),
                data=post_data,
                SERVER_NAME='ctb-shop.testserver',
            )
        self.assertEqual(mock_fn.call_count, 1,
            f"is_tenant_admin called {mock_fn.call_count}× for {additional_breaks} breaks — "
            f"expected 1 (was N+1: called once at top + once per break before CODE-032 fix)")

    def test_non_admin_cannot_view_others_repair(self):
        """Non-admin tech should be redirected when trying to convert another tech's repair."""
        _, other_tech = _make_tech(self.tenant, 'ctb2')
        other_repair = _make_repair(
            self.tenant, self.customer, other_tech, queue_status='APPROVED'
        )
        client = Client()
        client.force_login(self.tech.user)
        resp = client.get(
            reverse('convert_to_batch', kwargs={'repair_id': other_repair.id}),
            SERVER_NAME='ctb-shop.testserver',
        )
        self.assertEqual(resp.status_code, 302)

    def test_cross_tenant_repair_returns_404(self):
        """A repair from another tenant should 404 (tenant filter in queryset)."""
        other_owner, other_tenant = _make_tenant_with_owner('Other CTB', 'other-ctb')
        _, other_tech = _make_tech(other_tenant, 'ctb_other')
        other_customer = _make_customer(other_tenant, 'Other CTB Cust')
        other_repair = _make_repair(
            other_tenant, other_customer, other_tech, queue_status='APPROVED'
        )

        client = Client()
        client.force_login(self.owner)
        resp = client.get(
            reverse('convert_to_batch', kwargs={'repair_id': other_repair.id}),
            SERVER_NAME='ctb-shop.testserver',
        )
        self.assertEqual(resp.status_code, 404)
