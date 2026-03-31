"""
CODE-255: create_viscosity_rule missing tenant guard — creates orphaned NULL-tenant records.

Bug: `create_viscosity_rule` did not check `tenant is None` before creating a
ViscosityRecommendation. All other CRUD views (update, delete, toggle) used the
tenant-scoped `_get_viscosity_rule_or_404` helper, but create skipped the check.
Since ViscosityRecommendation.tenant is nullable (null=True for migration compat),
the record would be silently created with tenant=NULL — orphaned and invisible
to any tenant-scoped query.

Fix: Added early `if not tenant` guard in `create_viscosity_rule`, returning a
400 JSON error (matching `create_warranty_policy`'s existing pattern).
"""

import json
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, ViscosityRecommendation
from apps.technician_portal.views.settings import create_viscosity_rule


class TestCreateViscosityRuleTenantGuard(TestCase):
    """Regression tests for CODE-255: tenant guard on viscosity rule creation."""

    def setUp(self):
        self.factory = RequestFactory()

        # Create tenant + owner + technician
        self.user = User.objects.create_user(
            username='shopowner', email='owner@test.com', password='testpass123'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop', slug='test-shop', owner=self.user
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='owner'
        )
        self.tech = Technician.objects.create(
            tenant=self.tenant, user=self.user, is_manager=True, is_active=True
        )

        self.valid_payload = {
            'name': 'Cold Weather Rule',
            'recommended_viscosity': 'Low',
            'suggestion_text': 'Use low viscosity in cold weather',
            'badge_color': 'blue',
            'min_temperature': 0,
            'max_temperature': 40,
        }

    def _make_request(self, tenant=None):
        """Build a POST request with the valid payload."""
        request = self.factory.post(
            '/tech/settings/viscosity/create/',
            data=json.dumps(self.valid_payload),
            content_type='application/json',
        )
        request.user = self.user
        request.tenant = tenant
        request.session = SessionStore()
        return request

    def test_no_tenant_returns_400(self):
        """When request.tenant is None, should return 400 — not create an orphan."""
        request = self._make_request(tenant=None)
        response = create_viscosity_rule(request)

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('Tenant', data['error'])

        # No orphaned records
        self.assertEqual(
            ViscosityRecommendation.objects.filter(tenant__isnull=True).count(), 0
        )

    def test_with_tenant_creates_rule(self):
        """With a valid tenant, rule is created and tenant-scoped."""
        request = self._make_request(tenant=self.tenant)
        response = create_viscosity_rule(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])

        rule = ViscosityRecommendation.objects.get(name='Cold Weather Rule')
        self.assertEqual(rule.tenant_id, self.tenant.id)

    def test_cross_tenant_isolation(self):
        """Rules created for tenant A are not visible to tenant B queries."""
        # Create rule for tenant A
        request = self._make_request(tenant=self.tenant)
        create_viscosity_rule(request)

        # Create tenant B
        other_user = User.objects.create_user(
            username='other', email='other@test.com', password='testpass123'
        )
        tenant_b = Tenant.objects.create(
            name='Other Shop', slug='other-shop', owner=other_user
        )

        # Tenant B should see zero rules
        self.assertEqual(
            ViscosityRecommendation.objects.filter(tenant=tenant_b).count(), 0
        )
        # Tenant A should see one
        self.assertEqual(
            ViscosityRecommendation.objects.filter(tenant=self.tenant).count(), 1
        )
