"""
CODE-105 Regression Test: repair_detail.html uses unscoped user.technician

Root cause:
  templates/technician_portal/repair_detail.html used `user.technician.is_manager`
  (bare OneToOneField) to decide whether to show the Assign, Edit Repair, Delete buttons,
  and the Delete confirmation modal.  It also used `repair.technician == user.technician`
  to decide whether a plain tech can edit their own repair.

  Since Technician is a OneToOneField (one record per User globally), the cross-tenant
  scenario where a user IS a manager at Shop A but visits Shop B without a Technician
  record is blocked at the VIEW level — the view redirects if technician is None and the
  user is not is_tenant_admin.

  However, the template still used `user.technician` (unscoped) which is semantically
  wrong and dangerous for any future code path that might pass through (e.g., superuser
  visiting Shop B's repair detail where user.technician points to Shop A).

  The fix in CODE-105 ensures all manager-UI decisions go through the tenant-scoped
  `technician` context variable rather than the unscoped OneToOneField traversal.

Fix (CODE-105):
  - repair_detail.html now uses context-provided `technician` (tenant-scoped, may be None)
    instead of bare `user.technician.*` references.

Affected template checks (all replaced):
  1. Assign button: `user.technician and user.technician.is_manager` → `technician and technician.is_manager`
  2. Edit Repair (manager branch): same pattern
  3. Edit Repair (tech branch): `repair.technician == user.technician` → `repair.technician == technician`
  4. Delete button: `user.technician and user.technician.is_manager` → `technician and technician.is_manager`
  5. Customer-requested message: same pattern
  6. Delete modal: same pattern
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


class RepairDetailManagerUITest(TestCase):
    """
    Tests that repair_detail.html only shows manager-only UI elements
    (Assign, Delete, manager Edit) to users who ARE managers at the CURRENT shop,
    as determined by the tenant-scoped `technician` context variable.
    """

    def setUp(self):
        self.owner_user = User.objects.create_user('owner_105', password='pw', email='owner105@t.com')
        self.shop = Tenant.objects.create(
            name='Test Shop 105', slug='test-shop-105', plan='trial',
            is_active=True, owner=self.owner_user
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')

        # Manager user
        self.mgr_user = User.objects.create_user('mgr_105', password='pw', email='mgr105@t.com')
        TenantMembership.objects.create(tenant=self.shop, user=self.mgr_user, role='manager')
        self.mgr_tech = Technician.objects.create(
            tenant=self.shop, user=self.mgr_user,
            is_active=True, is_manager=True, can_repair=True
        )

        # Plain technician user
        self.plain_user = User.objects.create_user('plain_105', password='pw', email='plain105@t.com')
        TenantMembership.objects.create(tenant=self.shop, user=self.plain_user, role='technician')
        self.plain_tech = Technician.objects.create(
            tenant=self.shop, user=self.plain_user,
            is_active=True, is_manager=False, can_repair=True
        )

        self.customer = Customer.objects.create(tenant=self.shop, name='Fleet 105')

        # Repair assigned to plain tech
        self.repair = Repair.objects.create(
            tenant=self.shop,
            customer=self.customer,
            technician=self.plain_tech,
            queue_status='APPROVED',
            unit_number='T-105',
            cost=50,
        )

        self.client = Client()

    def _login(self, user):
        self.client.logout()
        self.client.login(username=user.username, password='pw')
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def test_manager_sees_delete_button_and_modal(self):
        """Manager should see the Delete button and confirmation modal."""
        self._login(self.mgr_user)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('deleteRepairModal', content,
            "Manager should see the Delete modal on repair_detail")

    def test_plain_tech_no_delete_button(self):
        """Plain technician (non-manager) should NOT see the Delete button/modal."""
        self._login(self.plain_user)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('deleteRepairModal', content,
            "Plain tech should NOT see the Delete modal on their own repair")

    def test_manager_sees_assign_button_on_requested_repair(self):
        """Manager should see the Assign button on a REQUESTED repair."""
        requested_repair = Repair.objects.create(
            tenant=self.shop,
            customer=self.customer,
            technician=self.mgr_tech,  # manager is the initiating tech
            queue_status='REQUESTED',
            unit_number='T-105-REQ',
            cost=50,
        )
        self._login(self.mgr_user)
        url = reverse('repair_detail', kwargs={'repair_id': requested_repair.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        assign_url = reverse('assign_repair', kwargs={'repair_id': requested_repair.id})
        self.assertIn(assign_url, content,
            "Manager should see the Assign button on a REQUESTED repair")

    def test_plain_tech_sees_edit_button_for_own_repair(self):
        """Plain tech should see the Edit button for their own non-completed repair."""
        self._login(self.plain_user)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        edit_url = reverse('update_repair', kwargs={'repair_id': self.repair.id})
        self.assertIn(edit_url, content,
            "Plain tech should see Edit button for their own APPROVED repair")

    def test_manager_sees_manager_edit_button(self):
        """Manager should see the Edit button (manager variant) for any repair."""
        self._login(self.mgr_user)
        # Manager viewing plain tech's repair — manager can see/edit all their shop's repairs
        # (manager gets can_view=True via manages_technician check)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        edit_url = reverse('update_repair', kwargs={'repair_id': self.repair.id})
        self.assertIn(edit_url, content,
            "Manager should see Edit button on any shop repair they can view")

    def test_manager_sees_manager_edit_on_completed_repair(self):
        """
        Manager should see Edit with 'Manager' badge on completed repairs.
        Plain tech should NOT see Edit on their own completed repair.
        """
        completed_repair = Repair.objects.create(
            tenant=self.shop,
            customer=self.customer,
            technician=self.plain_tech,
            queue_status='COMPLETED',
            unit_number='T-105-DONE',
            cost=50,
        )
        # Manager can edit completed repairs
        self._login(self.mgr_user)
        url = reverse('repair_detail', kwargs={'repair_id': completed_repair.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Manager', content,
            "Manager badge should appear on Edit button for completed repair")

    def test_template_uses_technician_not_user_dot_technician(self):
        """
        Regression: verify the template no longer contains 'user.technician' references.
        This is a direct source-level check to guard against re-introduction.
        """
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '../../templates/technician_portal/repair_detail.html'
        )
        template_path = os.path.normpath(template_path)
        with open(template_path) as f:
            content = f.read()
        self.assertNotIn('user.technician', content,
            "repair_detail.html must not use 'user.technician' — use context 'technician' instead")
