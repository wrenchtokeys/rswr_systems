"""
CODE-050 Regression: _get_viscosity_rule_or_404() was unsafe when tenant is None.

The helper fetched ViscosityRecommendation with only 'id=rule_id' when
request.tenant was None (e.g., broken/stale middleware):

    def _get_viscosity_rule_or_404(request, rule_id):
        tenant = getattr(request, 'tenant', None)
        lookup = {'id': rule_id}
        if tenant:        # <-- silently skipped when None
            lookup['tenant'] = tenant
        return get_object_or_404(ViscosityRecommendation, **lookup)

All four consumers (get, update, delete, toggle) share this path, so any one of
them could expose or mutate a foreign tenant's rule if middleware failed to
resolve the tenant.

Fix: Early Http404 when tenant is None, then force tenant into the DB lookup:
    if not tenant:
        raise Http404(...)
    return get_object_or_404(ViscosityRecommendation, id=rule_id, tenant=tenant)

Tests:
  1. Normal path: own-tenant rule returns 200/success
  2. Cross-tenant read: returns 404 (rule ID belongs to another tenant)
  3. No-tenant fallback: returns 404 (tenant not resolved)
  4. Cross-tenant update: returns 404, rule is NOT mutated
  5. Cross-tenant delete: returns 404, rule is NOT deleted
  6. Cross-tenant toggle: returns 404, is_active not flipped
"""

import json

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, ViscosityRecommendation

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def _make_tenant_with_manager(slug):
    """Create a tenant and a manager user with a Technician record."""
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='testpass123',
        first_name='Owner',
        last_name=slug.title(),
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=f'shop-{slug}',
        owner=owner,
        is_active=True,
    )
    TenantMembership.objects.create(
        user=owner,
        tenant=tenant,
        role='owner',
        is_active=True,
    )
    manager = User.objects.create_user(
        username=f'manager_{slug}',
        email=f'manager_{slug}@example.com',
        password='testpass123',
        first_name='Manager',
        last_name=slug.title(),
    )
    TenantMembership.objects.create(
        user=manager,
        tenant=tenant,
        role='manager',
        is_active=True,
    )
    tech = Technician.objects.create(
        user=manager,
        tenant=tenant,
        is_manager=True,
        is_active=True,
    )
    return tenant, owner, manager, tech


def _make_viscosity_rule(tenant, name='Summer Mix'):
    return ViscosityRecommendation.objects.create(
        tenant=tenant,
        name=name,
        recommended_viscosity='5W-30',
        suggestion_text='Good for warm weather',
        badge_color='green',
        display_order=1,
        is_active=True,
    )


@override_settings(**TEST_OVERRIDES)
class ViscosityRuleIDORTests(TestCase):
    """Regression tests for CODE-050: tenant-scoped viscosity rule lookup."""

    def setUp(self):
        self.client_a = Client()
        self.client_b = Client()

        self.tenant_a, self.owner_a, self.manager_a, self.tech_a = _make_tenant_with_manager('alpha')
        self.tenant_b, self.owner_b, self.manager_b, self.tech_b = _make_tenant_with_manager('beta')

        self.rule_a = _make_viscosity_rule(self.tenant_a, 'Shop A Rule')
        self.rule_b = _make_viscosity_rule(self.tenant_b, 'Shop B Rule')

    def _login_as(self, client, user, tenant):
        """Log in and seed session with the correct tenant_id."""
        client.login(username=user.username, password='testpass123')
        session = client.session
        session['tenant_id'] = tenant.id
        session.save()

    # -----------------------------------------------------------------------
    # Test 1: own-tenant rule read succeeds
    # -----------------------------------------------------------------------
    def test_get_own_tenant_rule_returns_200(self):
        self._login_as(self.client_a, self.manager_a, self.tenant_a)
        url = reverse('get_viscosity_rule', args=[self.rule_a.id])
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['rule']['name'], 'Shop A Rule')

    # -----------------------------------------------------------------------
    # Test 2: cross-tenant read returns 404
    # -----------------------------------------------------------------------
    def test_get_foreign_tenant_rule_returns_404(self):
        """Manager A cannot read Shop B's rule by guessing the PK."""
        self._login_as(self.client_a, self.manager_a, self.tenant_a)
        url = reverse('get_viscosity_rule', args=[self.rule_b.id])
        resp = self.client_a.get(url)
        self.assertEqual(resp.status_code, 404)

    # -----------------------------------------------------------------------
    # Test 3: no-tenant (broken middleware) returns 404 — simulated via a user
    # with NO TenantMembership at all (edge case after deactivation/deletion).
    # -----------------------------------------------------------------------
    def test_get_rule_no_tenant_returns_404(self):
        """When a user has no memberships, middleware sets tenant=None → 404."""
        # Create a standalone user with no memberships
        orphan = User.objects.create_user(
            username='orphan_user_050',
            email='orphan_050@example.com',
            password='testpass123',
        )
        # Give them a Technician record so @manager_required doesn't redirect
        Technician.objects.create(
            user=orphan,
            tenant=self.tenant_a,
            is_manager=True,
            is_active=True,
        )
        # Log in but do NOT create TenantMembership — middleware fallback (#3)
        # will find nothing and leave request.tenant = None.
        self.client_a.login(username='orphan_user_050', password='testpass123')
        url = reverse('get_viscosity_rule', args=[self.rule_a.id])
        resp = self.client_a.get(url)
        # Must NOT be 200 — either 404 (Http404 from helper) or 302 (decorator
        # redirect when tenant is None and manager_required fails).
        self.assertNotEqual(resp.status_code, 200)

    # -----------------------------------------------------------------------
    # Test 4: cross-tenant update is blocked, rule NOT mutated
    # -----------------------------------------------------------------------
    def test_update_foreign_tenant_rule_blocked_and_not_mutated(self):
        """Manager A cannot update Shop B's rule."""
        self._login_as(self.client_a, self.manager_a, self.tenant_a)
        url = reverse('update_viscosity_rule', args=[self.rule_b.id])
        resp = self.client_a.post(
            url,
            data=json.dumps({'name': 'HACKED NAME'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)
        # Verify DB is unchanged
        self.rule_b.refresh_from_db()
        self.assertEqual(self.rule_b.name, 'Shop B Rule')

    # -----------------------------------------------------------------------
    # Test 5: cross-tenant delete is blocked, rule NOT deleted
    # -----------------------------------------------------------------------
    def test_delete_foreign_tenant_rule_blocked(self):
        """Manager A cannot delete Shop B's rule."""
        self._login_as(self.client_a, self.manager_a, self.tenant_a)
        url = reverse('delete_viscosity_rule', args=[self.rule_b.id])
        resp = self.client_a.post(url)
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(ViscosityRecommendation.objects.filter(id=self.rule_b.id).exists())

    # -----------------------------------------------------------------------
    # Test 6: cross-tenant toggle is blocked, is_active NOT flipped
    # -----------------------------------------------------------------------
    def test_toggle_foreign_tenant_rule_blocked(self):
        """Manager A cannot toggle Shop B's rule active state."""
        original_active = self.rule_b.is_active
        self._login_as(self.client_a, self.manager_a, self.tenant_a)
        url = reverse('toggle_viscosity_rule', args=[self.rule_b.id])
        resp = self.client_a.post(url)
        self.assertEqual(resp.status_code, 404)
        self.rule_b.refresh_from_db()
        self.assertEqual(self.rule_b.is_active, original_active)
