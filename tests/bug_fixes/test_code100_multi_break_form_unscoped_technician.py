"""
CODE-100 Regression Test: multi_break_repair_form.html and base.html use unscoped user.technician

Root cause:
  templates/technician_portal/multi_break_repair_form.html used `user.technician.is_manager`
  and `user.technician.can_override_pricing` (bare OneToOneField) to decide whether to show
  the price-override section and approval limit.

  templates/base.html used `request.user.technician.is_manager` to decide whether to show
  the "Manager Settings" nav link.

  Both templates resolved the Technician record globally — ignoring the current tenant.  A
  user who is a manager (is_manager=True) at Shop A but a plain technician at Shop B would:

  1. See the "Price Override (Manager Only)" section in the multi-break form at Shop B.
  2. See Shop A's approval_limit displayed in the form at Shop B.
  3. See the "Manager Settings" nav link at Shop B (should be hidden).

  The server-side validation in create_multi_break_repair() was already tenant-scoped
  (CODE-091 fixed that), so no actual security bypass was possible — but the UI was
  misleading and could confuse users.

Fix (CODE-100):
  - create_multi_break_repair() now resolves `current_technician` using the tenant-scoped
    lookup Technician.objects.filter(user=request.user, tenant=tenant).first() and passes it
    to the template context.
  - multi_break_repair_form.html now uses `current_technician.is_manager` and
    `current_technician.can_override_pricing` instead of bare `user.technician.*`.
  - base.html now uses `user_role` from the context processor (already tenant-scoped via
    get_user_role()) instead of `request.user.technician.is_manager`.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


class MultiBreakFormUnscopedTechnicianTest(TestCase):
    """Tests that multi_break_repair_form.html uses tenant-scoped technician."""

    def setUp(self):
        # Owner users needed for Tenant.owner FK
        self.owner_a = User.objects.create_user(
            username="ownera", email="ownera@example.com", password="testpass123"
        )
        self.owner_b = User.objects.create_user(
            username="ownerb", email="ownerb@example.com", password="testpass123"
        )

        # Shop A — user is manager here
        self.shop_a = Tenant.objects.create(
            name="Shop A",
            slug="shop-a",
            plan="trial",
            is_active=True,
            owner=self.owner_a,
        )
        # Shop B — user is plain technician here
        self.shop_b = Tenant.objects.create(
            name="Shop B",
            slug="shop-b",
            plan="trial",
            is_active=True,
            owner=self.owner_b,
        )

        # Cross-tenant user: manager at Shop A, technician at Shop B
        self.cross_user = User.objects.create_user(
            username="crossmanager",
            email="cross@example.com",
            password="testpass123",
            first_name="Cross",
            last_name="Manager",
        )

        TenantMembership.objects.create(
            tenant=self.shop_a, user=self.cross_user, role='manager', is_active=True
        )
        TenantMembership.objects.create(
            tenant=self.shop_b, user=self.cross_user, role='technician', is_active=True
        )

        # Technician record at Shop A — is_manager=True, can_override_pricing=True
        self.tech_a = Technician.objects.create(
            tenant=self.shop_a,
            user=self.cross_user,
            is_manager=True,
            can_override_pricing=True,
            approval_limit=500,
            is_active=True,
        )

        # Technician record at Shop B — is_manager=False, can_override_pricing=False
        # NOTE: Technician.user is OneToOneField so a user can only have one Technician
        # record. In this test we verify that when the view resolves via tenant-scope,
        # it returns None (no record at Shop B) rather than Shop A's record.
        # We verify the view passes current_technician=None to the template.

        # Customer at Shop B
        self.customer_b = Customer.objects.create(
            tenant=self.shop_b,
            name="Shop B Customer",
            email="customer@shopb.com",
        )

    def test_view_passes_current_technician_to_context(self):
        """create_multi_break_repair passes tenant-scoped current_technician to template."""
        self.client.login(username="crossmanager", password="testpass123")
        session = self.client.session
        session['tenant_id'] = self.shop_b.id
        session.save()

        response = self.client.get(reverse('create_multi_break_repair'))
        self.assertEqual(response.status_code, 200)

        # current_technician must be in context
        self.assertIn('current_technician', response.context)
        # Since Technician.user is OneToOneField and only one record exists (Shop A),
        # the tenant-scoped lookup for Shop B returns None.
        ct = response.context['current_technician']
        # current_technician should either be None (no Shop B record) or a Technician
        # whose tenant == Shop B. It must NOT be Shop A's Technician.
        if ct is not None:
            self.assertEqual(ct.tenant_id, self.shop_b.id,
                             "current_technician must belong to Shop B, not Shop A")
            self.assertNotEqual(ct.tenant_id, self.shop_a.id,
                                "Must not leak Shop A's manager record to Shop B template")

    def test_template_does_not_show_override_section_for_cross_tenant_manager(self):
        """Price override section must NOT appear for cross-tenant manager at Shop B."""
        self.client.login(username="crossmanager", password="testpass123")
        session = self.client.session
        session['tenant_id'] = self.shop_b.id
        session.save()

        response = self.client.get(reverse('create_multi_break_repair'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()

        # The price override section should NOT appear because:
        # - current_technician is None (no Technician record for this user at Shop B)
        # - Even if we had a record, can_override_pricing would be False at Shop B
        # The section header text is "Price Override (Manager Only)"
        self.assertNotIn("Price Override (Manager Only)", content,
                         "Cross-tenant manager at Shop B must NOT see price override section")

    def test_template_does_not_show_shop_a_approval_limit_at_shop_b(self):
        """Shop A approval_limit ($500) must NOT appear in Shop B's multi-break form."""
        self.client.login(username="crossmanager", password="testpass123")
        session = self.client.session
        session['tenant_id'] = self.shop_b.id
        session.save()

        response = self.client.get(reverse('create_multi_break_repair'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        # The Shop A approval limit ($500) must not leak into the Shop B form
        self.assertNotIn("approval limit", content.lower(),
                         "Shop A approval_limit must not appear in Shop B form")
        self.assertNotIn("$500", content,
                         "Shop A approval_limit $500 must not be visible at Shop B")

    def test_context_processor_user_role_is_tenant_scoped(self):
        """user_role from context processor must reflect Shop B role (technician), not Shop A (manager)."""
        self.client.login(username="crossmanager", password="testpass123")
        session = self.client.session
        session['tenant_id'] = self.shop_b.id
        session.save()

        # Any page that uses the base template will have context processor vars
        response = self.client.get(reverse('create_multi_break_repair'))
        self.assertEqual(response.status_code, 200)

        # user_role must reflect Shop B membership (technician), not Shop A (manager)
        user_role = response.context.get('user_role')
        self.assertEqual(user_role, 'technician',
                         f"user_role must be 'technician' at Shop B, got '{user_role}'")

    def test_template_uses_current_technician_not_user_technician(self):
        """Template must reference current_technician variable, not bare user.technician."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '../../templates/technician_portal/multi_break_repair_form.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()

        # The old unscoped access should be gone
        self.assertNotIn(
            'user.technician.is_manager',
            content,
            "Template must not use bare user.technician.is_manager (cross-tenant leak)"
        )
        self.assertNotIn(
            'user.technician.can_override_pricing',
            content,
            "Template must not use bare user.technician.can_override_pricing (cross-tenant leak)"
        )
        self.assertNotIn(
            'user.technician.approval_limit',
            content,
            "Template must not use bare user.technician.approval_limit (cross-tenant leak)"
        )
        # The fix uses current_technician instead
        self.assertIn(
            'current_technician',
            content,
            "Template must use current_technician context variable"
        )

    def test_base_template_uses_user_role_not_user_technician(self):
        """base.html must reference user_role for Manager Settings link, not user.technician."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '../../templates/base.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()

        # Old unscoped pattern must be gone
        self.assertNotIn(
            'request.user.technician.is_manager',
            content,
            "base.html must not use bare request.user.technician.is_manager (cross-tenant leak)"
        )
        # New pattern uses user_role from context processor
        self.assertIn(
            "user_role == 'manager'",
            content,
            "base.html must use user_role context processor variable for manager check"
        )
