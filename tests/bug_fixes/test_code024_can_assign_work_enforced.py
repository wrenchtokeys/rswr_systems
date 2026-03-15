"""
Regression tests for CODE-024: can_assign_work flag ignored in assign/reassign views.

Bug:
    assign_repair() and reassign_to_self() in apps/technician_portal/views/repairs.py
    checked is_manager but never checked can_assign_work.

    A manager with is_manager=True but can_assign_work=False could:
    - Assign any REQUESTED repair to any technician in their tenant
    - Reassign a managed tech's repair to themselves

    This makes the can_assign_work permission field effectively dead/misleading.
    Shop owners could configure a manager without assign authority and it would
    be silently ignored.

Fix:
    Both views now check `can_assign_work` for non-admin managers and return
    a 403-equivalent redirect with an error message if the flag is False.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name, plan):
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "_")}',
        password='pw',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner,
        plan='trial',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role='owner', is_active=True)
    return tenant, owner


def _make_technician(tenant, username, is_manager=False, can_assign_work=False):
    user = User.objects.create_user(username=username, password='pw')
    TenantMembership.objects.create(user=user, tenant=tenant, role='technician', is_active=True)
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        expertise='chip',
        is_manager=is_manager,
        can_assign_work=can_assign_work,
    )
    return user, tech


def _make_repair(tenant, customer, technician, status='REQUESTED'):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        service_date='2026-03-15',
        queue_status=status,
        damage_type='chip',
    )


def _make_request(factory, user, tenant, method='POST', data=None):
    if method == 'POST':
        req = factory.post('/', data=data or {})
    else:
        req = factory.get('/')
    req.user = user
    req.tenant = tenant
    return req


class AssignRepairCanAssignWorkTest(TestCase):
    """assign_repair() must reject managers with can_assign_work=False."""

    def setUp(self):
        plan = _make_plan()
        self.tenant, self.owner = _make_tenant('Shop A', plan)
        self.customer = Customer.objects.create(
            name='Test Fleet',
            email='fleet@shopatest.com',
            tenant=self.tenant,
        )

    def test_manager_without_can_assign_work_blocked_from_assign(self):
        """Manager with is_manager=True, can_assign_work=False cannot assign repairs."""
        from apps.technician_portal.views.repairs import assign_repair

        manager_user, manager_tech = _make_technician(
            self.tenant, 'mgr_no_assign', is_manager=True, can_assign_work=False
        )
        _, placeholder_tech = _make_technician(self.tenant, 'placeholder_assign')

        repair = _make_repair(self.tenant, self.customer, placeholder_tech, status='REQUESTED')

        factory = RequestFactory()
        request = _make_request(factory, manager_user, self.tenant, method='GET')

        with patch('apps.technician_portal.views.repairs.messages') as mock_messages:
            response = assign_repair(request, repair_id=repair.id)

        # Should redirect (to dashboard URL /tech/)
        self.assertEqual(response.status_code, 302)

        # Should show error message about permission
        mock_messages.error.assert_called_once()
        error_msg = mock_messages.error.call_args[0][1]
        self.assertIn('permission', error_msg.lower())

    def test_manager_with_can_assign_work_allowed_on_get(self):
        """Manager with is_manager=True AND can_assign_work=True can access assign view."""
        from apps.technician_portal.views.repairs import assign_repair

        manager_user, manager_tech = _make_technician(
            self.tenant, 'mgr_yes_assign', is_manager=True, can_assign_work=True
        )
        _, placeholder_tech = _make_technician(self.tenant, 'placeholder_assign2')

        repair = _make_repair(self.tenant, self.customer, placeholder_tech, status='REQUESTED')

        factory = RequestFactory()
        request = _make_request(factory, manager_user, self.tenant, method='GET')

        with patch('apps.technician_portal.views.repairs.render') as mock_render:
            mock_render.return_value = MagicMock(status_code=200)
            response = assign_repair(request, repair_id=repair.id)

        # Render should have been called (view proceeds normally)
        mock_render.assert_called_once()

    def test_non_manager_cannot_assign(self):
        """Regular technician without is_manager cannot assign repairs."""
        from apps.technician_portal.views.repairs import assign_repair

        tech_user, tech = _make_technician(
            self.tenant, 'plain_tech_assign', is_manager=False, can_assign_work=False
        )
        _, placeholder_tech = _make_technician(self.tenant, 'placeholder_assign3')

        repair = _make_repair(self.tenant, self.customer, placeholder_tech, status='REQUESTED')

        factory = RequestFactory()
        request = _make_request(factory, tech_user, self.tenant, method='GET')

        with patch('apps.technician_portal.views.repairs.messages') as mock_messages:
            response = assign_repair(request, repair_id=repair.id)

        self.assertEqual(response.status_code, 302)
        mock_messages.error.assert_called_once()


class ReassignToSelfCanAssignWorkTest(TestCase):
    """reassign_to_self() must reject managers with can_assign_work=False."""

    def setUp(self):
        plan = _make_plan()
        self.tenant, self.owner = _make_tenant('Shop B', plan)
        self.customer = Customer.objects.create(
            name='Fleet Co',
            email='fleet@shopbtest.com',
            tenant=self.tenant,
        )

    def test_manager_without_can_assign_work_blocked_from_reassign(self):
        """Manager with is_manager=True, can_assign_work=False cannot reassign repairs."""
        from apps.technician_portal.views.repairs import reassign_to_self

        manager_user, manager_tech = _make_technician(
            self.tenant, 'mgr_no_reassign', is_manager=True, can_assign_work=False
        )
        _, other_tech = _make_technician(
            self.tenant, 'other_tech_reassign', is_manager=False
        )

        repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=other_tech,
            unit_number='UNIT-002',
            service_date='2026-03-15',
            queue_status='APPROVED',
            damage_type='chip',
        )

        factory = RequestFactory()
        request = _make_request(factory, manager_user, self.tenant, method='GET')

        with patch('apps.technician_portal.views.repairs.messages') as mock_messages:
            response = reassign_to_self(request, repair_id=repair.id)

        # Should redirect (to technician dashboard; URL resolves to /tech/)
        self.assertEqual(response.status_code, 302)

        mock_messages.error.assert_called_once()
        error_msg = mock_messages.error.call_args[0][1]
        self.assertIn('permission', error_msg.lower())

    def test_manager_with_can_assign_work_passes_guard_for_reassign(self):
        """Manager with can_assign_work=True passes the guard check."""
        from apps.technician_portal.views.repairs import reassign_to_self

        manager_user, manager_tech = _make_technician(
            self.tenant, 'mgr_yes_reassign', is_manager=True, can_assign_work=True
        )
        _, other_tech = _make_technician(
            self.tenant, 'other_tech_reassign2', is_manager=False
        )
        manager_tech.managed_technicians.add(other_tech)

        repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=other_tech,
            unit_number='UNIT-003',
            service_date='2026-03-15',
            queue_status='APPROVED',
            damage_type='chip',
        )

        factory = RequestFactory()
        request = _make_request(factory, manager_user, self.tenant, method='GET')

        with patch('apps.technician_portal.views.repairs.render') as mock_render:
            mock_render.return_value = MagicMock(status_code=200)
            response = reassign_to_self(request, repair_id=repair.id)

        # Should reach the render call (i.e., not blocked at guard)
        mock_render.assert_called_once()

    def test_non_manager_cannot_reassign(self):
        """Regular technician without is_manager cannot reassign."""
        from apps.technician_portal.views.repairs import reassign_to_self

        tech_user, tech = _make_technician(
            self.tenant, 'plain_tech_reassign', is_manager=False, can_assign_work=False
        )
        _, other_tech_3 = _make_technician(self.tenant, 'other_tech_reassign3')

        repair = _make_repair(self.tenant, self.customer, other_tech_3, status='APPROVED')

        factory = RequestFactory()
        request = _make_request(factory, tech_user, self.tenant, method='GET')

        with patch('apps.technician_portal.views.repairs.messages') as mock_messages:
            response = reassign_to_self(request, repair_id=repair.id)

        self.assertEqual(response.status_code, 302)
        mock_messages.error.assert_called_once()
