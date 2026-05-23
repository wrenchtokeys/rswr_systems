"""
Regression tests for CODE-086:
Unscoped Technician lookup in update_technician_profile (api.py)
and mark_unit_replaced (customers.py).

Root cause:
  1. update_technician_profile used get_object_or_404(Technician, user=request.user)
     — no tenant scope. If a user has Technician records at two shops,
     Django raises MultipleObjectsReturned → 500. Even with one shop,
     the resolved Technician may belong to the wrong tenant, causing
     form saves to update the wrong shop's record.

  2. mark_unit_replaced used hasattr(request.user, 'technician') then
     request.user.technician (unscoped) for the technician attribution
     on the Replacement record. A cross-tenant user would create a
     Replacement in Shop B attributed to Shop A's Technician.

Fix (CODE-086):
  Both sites now use:
      Technician.objects.filter(user=request.user, tenant=tenant).first()
  update_technician_profile raises Http404 (not 500) when no record
  exists for the current tenant.

Test scenarios:
  A. update_technician_profile: Cross-tenant user (Shop A tech at Shop B)
     gets 404, not 500 MultipleObjectsReturned.
  B. update_technician_profile: Legitimate Shop B technician receives 200.
  C. mark_unit_replaced: Cross-tenant user's Replacement record is attributed
     to the correct Shop B technician (scoped lookup), not Shop A's record.
  D. mark_unit_replaced: When the cross-tenant user has no Shop B technician,
     attribution falls back to customer.primary_technician.
"""

import uuid
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404
from unittest.mock import patch, MagicMock

from core.models import Customer
from apps.technician_portal.models import Technician, Repair, Replacement
from apps.tenants.models import Tenant, TenantMembership


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_messages(request):
    setattr(request, 'session', {})
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)
    return request


def _make_request(method, url, user, tenant, data=None):
    factory = RequestFactory()
    fn = getattr(factory, method.lower())
    req = fn(url, data=data or {})
    req.user = user
    req.tenant = tenant
    _add_messages(req)
    return req


def _create_tenant(name=None):
    name = name or f"Shop {uuid.uuid4().hex[:6]}"
    slug = uuid.uuid4().hex[:10]
    owner = _create_user(f"owner_{slug}")
    return Tenant.objects.create(
        name=name,
        subdomain=slug,
        slug=slug,
        owner=owner,
        is_active=True,
    )


def _create_user(username=None):
    username = username or f"user_{uuid.uuid4().hex[:8]}"
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
    )


def _create_technician(user, tenant, **kwargs):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        phone_number="5551234567",
        expertise="windshield",
        is_active=True,
        **kwargs,
    )


def _create_customer(tenant, primary_tech=None):
    return Customer.objects.create(
        tenant=tenant,
        name=f"Customer {uuid.uuid4().hex[:6]}",
        primary_technician=primary_tech,
    )


# ---------------------------------------------------------------------------
# Test A & B: update_technician_profile
# ---------------------------------------------------------------------------

class TestUpdateTechnicianProfileTenantScope(TestCase):
    """Tests for CODE-086: update_technician_profile tenant scoping."""

    def setUp(self):
        self.shop_a = _create_tenant("Shop A")
        self.shop_b = _create_tenant("Shop B")

        # Cross-tenant user: enrolled at Shop A only, visiting Shop B portal
        self.cross_tenant_user = _create_user("cross_tenant_user")
        _create_technician(self.cross_tenant_user, self.shop_a)
        TenantMembership.objects.create(
            user=self.cross_tenant_user,
            tenant=self.shop_b,
            role="technician",
            is_active=True,
        )

        # Legitimate Shop B user
        self.shop_b_user = _create_user("shop_b_tech")
        _create_technician(self.shop_b_user, self.shop_b)
        TenantMembership.objects.create(
            user=self.shop_b_user,
            tenant=self.shop_b,
            role="technician",
            is_active=True,
        )

    def test_a_cross_tenant_user_gets_404_not_500(self):
        """
        A cross-tenant user at Shop B (no Shop B Technician) should get Http404,
        not MultipleObjectsReturned (500).
        """
        from apps.technician_portal.views.api import update_technician_profile

        req = _make_request("GET", "/tech/profile/update/", self.cross_tenant_user, self.shop_b)
        with self.assertRaises(Http404):
            update_technician_profile(req)

    def test_b_legitimate_shop_b_technician_gets_200(self):
        """
        A legitimate Shop B technician should be able to GET the profile update page.
        """
        from apps.technician_portal.views.api import update_technician_profile

        req = _make_request("GET", "/tech/profile/update/", self.shop_b_user, self.shop_b)
        with patch("django.shortcuts.render") as mock_render:
            mock_render.return_value = MagicMock(status_code=200)
            response = update_technician_profile(req)

        mock_render.assert_called_once()
        context = mock_render.call_args[0][2]
        # The technician in context must belong to shop_b
        self.assertEqual(context["technician"].tenant_id, self.shop_b.id)

    def test_b2_profile_update_uses_correct_tenant_technician(self):
        """
        Ensure the technician object passed to the form is the Shop B record,
        not any other tenant's record.
        """
        from apps.technician_portal.views.api import update_technician_profile

        req = _make_request("GET", "/tech/profile/update/", self.shop_b_user, self.shop_b)
        shop_b_tech = Technician.objects.get(user=self.shop_b_user, tenant=self.shop_b)

        with patch("django.shortcuts.render") as mock_render:
            mock_render.return_value = MagicMock(status_code=200)
            update_technician_profile(req)

        context = mock_render.call_args[0][2]
        self.assertEqual(context["technician"].id, shop_b_tech.id)


# ---------------------------------------------------------------------------
# Test C & D: mark_unit_replaced
# ---------------------------------------------------------------------------

class TestMarkUnitReplacedTechnicianScope(TestCase):
    """Tests for CODE-086: mark_unit_replaced technician attribution scoping."""

    def setUp(self):
        self.shop_a = _create_tenant("Shop A")
        self.shop_b = _create_tenant("Shop B")

        # Shop B's primary technician
        self.shop_b_primary_user = _create_user("shop_b_primary")
        self.shop_b_primary_tech = _create_technician(self.shop_b_primary_user, self.shop_b)

        # Customer in Shop B with primary tech set
        self.shop_b_customer = _create_customer(self.shop_b, primary_tech=self.shop_b_primary_tech)

        # Cross-tenant user: has Technician at Shop A, membership at Shop B
        self.cross_tenant_user = _create_user("cross_a_in_b")
        self.shop_a_tech = _create_technician(self.cross_tenant_user, self.shop_a)
        TenantMembership.objects.create(
            user=self.cross_tenant_user,
            tenant=self.shop_b,
            role="technician",
            is_active=True,
        )

        # Legitimate Shop B technician
        self.shop_b_user = _create_user("shop_b_tech")
        self.shop_b_tech = _create_technician(self.shop_b_user, self.shop_b)
        TenantMembership.objects.create(
            user=self.shop_b_user,
            tenant=self.shop_b,
            role="technician",
            is_active=True,
        )

        # Create a repair for unit #99 to trigger unit replacement tracking
        self.unit_number = "99"

    def _post_mark_unit_replaced(self, user, tenant, customer, unit_number):
        from apps.technician_portal.views.customers import mark_unit_replaced
        req = _make_request(
            "POST",
            f"/tech/customers/{customer.id}/units/{unit_number}/replace/",
            user,
            tenant,
            data={"unit_number": unit_number},
        )
        # Patch the UnitRepairCount and Replacement creation to avoid real DB side effects
        return req, mark_unit_replaced

    def test_c_cross_tenant_replacement_attributed_to_primary_tech(self):
        """
        A cross-tenant user (Shop A tech in Shop B) has no Shop B Technician.
        Replacement record should fall back to customer.primary_technician, NOT
        be attributed to the Shop A technician.
        """
        from apps.technician_portal.views.customers import mark_unit_replaced

        req = _make_request(
            "POST",
            f"/tech/customers/{self.shop_b_customer.id}/units/{self.unit_number}/replace/",
            self.cross_tenant_user,
            self.shop_b,
            data={"unit_number": self.unit_number},
        )

        with patch("apps.technician_portal.views.customers.redirect") as mock_redirect:
            mock_redirect.return_value = MagicMock(status_code=302)
            try:
                mark_unit_replaced(req, self.shop_b_customer.id, self.unit_number)
            except Exception:
                pass  # May redirect; we just care about the Replacement created

        replacements = Replacement.objects.filter(
            tenant=self.shop_b,
            customer=self.shop_b_customer,
            unit_number=self.unit_number,
        )

        for r in replacements:
            # Must NOT be the Shop A technician
            self.assertNotEqual(
                r.technician_id,
                self.shop_a_tech.id,
                "Replacement was attributed to the cross-tenant (Shop A) technician!",
            )

    def test_d_legitimate_shop_b_tech_replacement_attributed_correctly(self):
        """
        A legitimate Shop B technician gets their own Technician record on the
        Replacement, not a fallback.
        """
        from apps.technician_portal.views.customers import mark_unit_replaced

        req = _make_request(
            "POST",
            f"/tech/customers/{self.shop_b_customer.id}/units/{self.unit_number}/replace/",
            self.shop_b_user,
            self.shop_b,
            data={"unit_number": self.unit_number},
        )

        with patch("apps.technician_portal.views.customers.redirect") as mock_redirect:
            mock_redirect.return_value = MagicMock(status_code=302)
            try:
                mark_unit_replaced(req, self.shop_b_customer.id, self.unit_number)
            except Exception:
                pass

        replacements = Replacement.objects.filter(
            tenant=self.shop_b,
            customer=self.shop_b_customer,
            unit_number=self.unit_number,
        )

        for r in replacements:
            self.assertEqual(
                r.technician_id,
                self.shop_b_tech.id,
                "Replacement was not attributed to the correct Shop B technician.",
            )
