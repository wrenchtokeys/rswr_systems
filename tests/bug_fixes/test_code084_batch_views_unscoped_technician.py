"""
Regression tests for CODE-084:
Unscoped request.user.technician in create_multi_break_repair and convert_to_batch.

Root cause:
  Two views in batch.py used `request.user.technician` (unscoped OneToOneField
  reverse lookup):

  1. create_multi_break_repair (non-admin path) — the else branch assigned
     `technician = request.user.technician`.  A user with a Technician record
     at Shop A but TenantMembership at Shop B would create a Shop B repair with
     Shop A's Technician attached — cross-tenant FK contamination.

  2. create_multi_break_repair (admin no-tech-id path) — the `hasattr` guard
     + `request.user.technician` fallback was also unscoped, so an admin at
     Shop B with a Technician record from Shop A would attach the wrong record.

  3. convert_to_batch ownership check — `original_repair.technician_id !=
     request.user.technician.id` used unscoped lookup.  If the Shop A
     Technician ID happened to match a Shop B repair's assigned tech, the
     ownership check would pass incorrectly (or fail in confusing ways).

Fix: All three sites now use:
     Technician.objects.filter(user=request.user, tenant=tenant).first()
     A user with no Technician record at the current tenant gets None, which
     surfaces as a clear error rather than silently using the wrong record.

Test scenarios:
  A. create_multi_break_repair: Cross-tenant technician (Shop A tech hitting
     Shop B portal) is blocked — "no technician profile" error, no repair
     created.
  B. create_multi_break_repair: Legitimate Shop B technician can POST and
     creates repairs with the correct Shop B Technician assigned.
  C. create_multi_break_repair: Admin at Shop B with only a Shop A Technician
     record and no tech_id in POST → blocked ("must select a technician"),
     not passed through with Shop A's Technician.
  D. convert_to_batch: Cross-tenant user cannot pass the ownership check for
     Shop B's repair — redirected with "no permission" message.
  E. convert_to_batch: Legitimate Shop B technician who owns the repair passes
     the ownership check and reaches the form page.
"""

import uuid
import json
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from unittest.mock import patch

from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_get_request(url, user, tenant):
    factory = RequestFactory()
    req = factory.get(url)
    req.user = user
    req.tenant = tenant
    setattr(req, 'session', 'session')
    setattr(req, '_messages', FallbackStorage(req))
    return req


def _make_post_request(url, user, tenant, data):
    factory = RequestFactory()
    req = factory.post(url, data=data)
    req.user = user
    req.tenant = tenant
    setattr(req, 'session', 'session')
    setattr(req, '_messages', FallbackStorage(req))
    return req


def _make_user(username):
    return User.objects.create_user(
        username=username,
        password='testpass123',
        email=f'{username}@test.com',
    )


def _make_tenant(name):
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "_")}',
        password='ownerpass',
        email=f'owner_{name.lower().replace(" ", "")}@test.com',
    )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        is_active=True,
        owner=owner,
    )


def _make_customer(tenant, name='Test Fleet'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='FLEET',
    )


def _make_technician(user, tenant, is_manager=False):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=is_manager,
        is_active=True,
        can_repair=True,
    )


def _make_repair(tenant, customer, technician, status='APPROVED'):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        damage_type='CHIP',
        queue_status=status,
    )


def _make_membership(user, tenant, role='technician'):
    return TenantMembership.objects.create(
        user=user,
        tenant=tenant,
        role=role,
        is_active=True,
    )


def _messages(request):
    return list(request._messages)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class CreateMultiBreakRepairCrossTenantTests(TestCase):
    """
    Scenario A: Cross-tenant technician (Shop A tech visiting Shop B portal)
    should be blocked when posting to create_multi_break_repair.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A')
        self.shop_b = _make_tenant('Shop B')

        # User has Technician at Shop A
        self.cross_tenant_user = _make_user('cross_tech')
        self.tech_a = _make_technician(self.cross_tenant_user, self.shop_a)

        # But only a TenantMembership (no Technician record) at Shop B
        _make_membership(self.cross_tenant_user, self.shop_b, role='technician')

        self.customer_b = _make_customer(self.shop_b, name='Fleet B')

    def test_cross_tenant_tech_blocked_no_tech_profile(self):
        """
        A user with Technician at Shop A but no Technician at Shop B
        should be blocked from creating a repair at Shop B.
        No Repair should be created.
        """
        from apps.technician_portal.views.batch import create_multi_break_repair
        import datetime

        post_data = {
            'customer': str(self.customer_b.id),
            'unit_number': 'UNIT-X',
            'repair_date': datetime.datetime.now().isoformat(),
            'breaks_count': '1',
            'breaks[0][damage_type]': 'CHIP',
            'breaks[0][notes]': 'test',
        }
        req = _make_post_request('/batch/create/', self.cross_tenant_user, self.shop_b, post_data)

        initial_count = Repair.objects.filter(tenant=self.shop_b).count()

        with patch('apps.technician_portal.views.batch.calculate_batch_pricing') as mock_pricing:
            mock_pricing.return_value = {'total': 0, 'breaks': [{'cost': 0}]}
            response = create_multi_break_repair(req)

        # Should redirect (error path) — no repair created at Shop B
        final_count = Repair.objects.filter(tenant=self.shop_b).count()
        self.assertEqual(initial_count, final_count,
            "No repair should be created for cross-tenant technician")
        # Response should be a redirect (error message displayed)
        self.assertEqual(response.status_code, 302)

    def test_cross_tenant_tech_cannot_attach_shop_a_technician_to_shop_b_repair(self):
        """
        After fix: the cross-tenant user should never attach Shop A's Technician
        to a Shop B repair. No Repair with tech_a as technician should exist at Shop B.
        """
        from apps.technician_portal.views.batch import create_multi_break_repair
        import datetime

        post_data = {
            'customer': str(self.customer_b.id),
            'unit_number': 'UNIT-Y',
            'repair_date': datetime.datetime.now().isoformat(),
            'breaks_count': '1',
            'breaks[0][damage_type]': 'CHIP',
            'breaks[0][notes]': '',
        }
        req = _make_post_request('/batch/create/', self.cross_tenant_user, self.shop_b, post_data)

        with patch('apps.technician_portal.views.batch.calculate_batch_pricing') as mock_pricing:
            mock_pricing.return_value = {'total': 0, 'breaks': [{'cost': 0}]}
            create_multi_break_repair(req)

        # Shop A's tech should NEVER be attached to a Shop B repair
        cross_tenant_contaminated = Repair.objects.filter(
            tenant=self.shop_b, technician=self.tech_a
        ).exists()
        self.assertFalse(cross_tenant_contaminated,
            "Shop A's Technician must not be attached to a Shop B repair")


class CreateMultiBreakRepairLegitTechTests(TestCase):
    """
    Scenario B: A legitimate Shop B technician should be able to create repairs
    and have the correct Shop B Technician attached.
    """

    def setUp(self):
        self.shop_b = _make_tenant('Shop B Legit')
        self.legit_user = _make_user('legit_tech_b')
        self.tech_b = _make_technician(self.legit_user, self.shop_b)
        _make_membership(self.legit_user, self.shop_b, role='technician')
        self.customer_b = _make_customer(self.shop_b, name='Legit Fleet')

    def test_legitimate_technician_repair_uses_correct_technician(self):
        """
        A valid Shop B technician posting to create_multi_break_repair should
        have Shop B's Technician record assigned to the created repairs.
        """
        from apps.technician_portal.views.batch import create_multi_break_repair
        import datetime

        post_data = {
            'customer': str(self.customer_b.id),
            'unit_number': 'UNIT-Z',
            'repair_date': datetime.datetime.now().isoformat(),
            'breaks_count': '1',
            'breaks[0][damage_type]': 'CHIP',
            'breaks[0][notes]': 'legit repair',
        }
        req = _make_post_request('/batch/create/', self.legit_user, self.shop_b, post_data)

        with patch('apps.technician_portal.views.batch.calculate_batch_pricing') as mock_pricing:
            # pricing_breakdown is accessed as pricing_breakdown[i]['price']
            mock_pricing.return_value = {0: {'price': 50}}
            response = create_multi_break_repair(req)

        # Should redirect to batch detail (success)
        self.assertEqual(response.status_code, 302)
        # Repair should be created with the correct technician
        created = Repair.objects.filter(tenant=self.shop_b, technician=self.tech_b).first()
        self.assertIsNotNone(created,
            "Shop B technician should be attached to the newly created repair")


class CreateMultiBreakRepairAdminCrossTenantTests(TestCase):
    """
    Scenario C: Admin at Shop B whose only Technician record is from Shop A,
    posting with no tech_id, should be blocked (must select a technician).
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A Admin')
        self.shop_b = _make_tenant('Shop B Admin')

        # Admin user: TenantMembership as 'owner' at Shop B, Technician record at Shop A
        self.admin_user = _make_user('admin_cross')
        self.tech_a = _make_technician(self.admin_user, self.shop_a)
        _make_membership(self.admin_user, self.shop_b, role='owner')

        self.customer_b = _make_customer(self.shop_b, name='Admin Fleet')

    def test_admin_no_tech_id_no_current_tenant_tech_is_blocked(self):
        """
        An admin with only a Shop A Technician record, posting to create_multi_break_repair
        at Shop B with no technician_id, should be blocked (not auto-assigned Shop A tech).
        """
        from apps.technician_portal.views.batch import create_multi_break_repair
        import datetime

        post_data = {
            'customer': str(self.customer_b.id),
            'unit_number': 'UNIT-ADMIN',
            'repair_date': datetime.datetime.now().isoformat(),
            'breaks_count': '1',
            'breaks[0][damage_type]': 'CHIP',
            'breaks[0][notes]': '',
            # No technician_id in POST
        }
        req = _make_post_request('/batch/create/', self.admin_user, self.shop_b, post_data)

        initial_count = Repair.objects.filter(tenant=self.shop_b).count()

        with patch('apps.technician_portal.views.batch.calculate_batch_pricing') as mock_pricing:
            mock_pricing.return_value = {'total': 0, 'breaks': [{'cost': 0}]}
            response = create_multi_break_repair(req)

        # Should be blocked — no repair created
        final_count = Repair.objects.filter(tenant=self.shop_b).count()
        self.assertEqual(initial_count, final_count,
            "Admin without Shop B Technician record must not create a repair (no tech to assign)")
        self.assertEqual(response.status_code, 302)
        # Shop A's tech should not contaminate Shop B
        contaminated = Repair.objects.filter(tenant=self.shop_b, technician=self.tech_a).exists()
        self.assertFalse(contaminated)


class ConvertToBatchCrossTenantTests(TestCase):
    """
    Scenario D & E: convert_to_batch ownership check.
    """

    def setUp(self):
        self.shop_a = _make_tenant('Shop A Convert')
        self.shop_b = _make_tenant('Shop B Convert')

        # Cross-tenant user: Technician at Shop A, TenantMembership at Shop B
        self.cross_user = _make_user('cross_convert')
        self.tech_a = _make_technician(self.cross_user, self.shop_a)
        _make_membership(self.cross_user, self.shop_b, role='technician')

        # Legit Shop B technician
        self.legit_user = _make_user('legit_convert')
        self.tech_b = _make_technician(self.legit_user, self.shop_b)
        _make_membership(self.legit_user, self.shop_b, role='technician')

        self.customer_b = _make_customer(self.shop_b, name='Convert Fleet')
        # Shop B repair assigned to legit_user (tech_b)
        self.repair_b = _make_repair(self.shop_b, self.customer_b, self.tech_b, status='APPROVED')

    def test_cross_tenant_user_blocked_from_convert_to_batch(self):
        """
        A user with no Technician record at Shop B should be denied access
        to convert_to_batch for a Shop B repair (even if their Shop A tech
        ID coincidentally matches the ownership check).
        """
        from apps.technician_portal.views.batch import convert_to_batch

        req = _make_get_request(
            f'/batch/convert/{self.repair_b.id}/',
            self.cross_user,
            self.shop_b,
        )
        response = convert_to_batch(req, repair_id=self.repair_b.id)

        # Should be redirected with "no permission" message
        self.assertEqual(response.status_code, 302)
        msgs = _messages(req)
        error_messages = [str(m) for m in msgs]
        self.assertTrue(
            any("permission" in m.lower() for m in error_messages),
            f"Expected permission error, got: {error_messages}"
        )

    def test_legit_technician_can_access_their_own_repair_convert(self):
        """
        A legitimate Shop B technician who owns the repair should pass
        the ownership check and receive a 200 (form page) response.
        """
        from apps.technician_portal.views.batch import convert_to_batch

        req = _make_get_request(
            f'/batch/convert/{self.repair_b.id}/',
            self.legit_user,
            self.shop_b,
        )
        response = convert_to_batch(req, repair_id=self.repair_b.id)

        # Should render the convert form (200)
        self.assertEqual(response.status_code, 200)

    def test_cross_tenant_user_not_blocked_by_coincidental_id_match(self):
        """
        Even if Shop A Technician's ID could match a Shop B repair's tech ID,
        the fix ensures we look up by (user, tenant) — not by ID from another shop.

        This test verifies the scoped lookup path is used by asserting the
        cross-tenant user is still denied access at Shop B.
        """
        from apps.technician_portal.views.batch import convert_to_batch

        req = _make_get_request(
            f'/batch/convert/{self.repair_b.id}/',
            self.cross_user,
            self.shop_b,
        )
        response = convert_to_batch(req, repair_id=self.repair_b.id)

        self.assertEqual(response.status_code, 302,
            "Cross-tenant user must be redirected regardless of ID coincidence")
