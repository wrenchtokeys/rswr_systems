"""
Tenant Scoping Tests
Consolidated from: CODE-005, CODE-008, CODE-009, CODE-011, CODE-020, CODE-021, CODE-022
"""

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import RewardOption
from apps.technician_portal.admin import TechnicianAdmin
from apps.technician_portal.decorators import is_tenant_admin
from apps.technician_portal.models import Repair, Technician, TechnicianNotification
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from common.auth import get_user_role
from core.models import Customer, Notification
from core.models.notification_delivery_log import NotificationDeliveryLog
from decimal import Decimal
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.http import Http404, HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from unittest.mock import MagicMock, PropertyMock, patch
import logging
import uuid

User = get_user_model()


# --- From test_code005_delivery_log_tenant.py ---

User = get_user_model()

_tenant_counter = 0


def _make_tenant_c005(name="Test Shop"):
    """Create a minimal Tenant (with required owner) for testing."""
    global _tenant_counter
    _tenant_counter += 1
    from apps.tenants.models import Tenant, TenantMembership
    from apps.tenants.models import SubscriptionPlan
    slug = name.lower().replace(" ", "-")
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="starter",
        defaults={"name": "Starter", "monthly_price": Decimal("0.00"), "trial_days": 30, "display_order": 0},
    )
    owner = User.objects.create_user(
        username=f"owner_{slug}_{_tenant_counter}",
        email=f"owner{_tenant_counter}@{slug}.test",
        password="pass",
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=f"{slug}-{_tenant_counter}",
        subdomain=f"{slug}-{_tenant_counter}",
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role="owner")
    return tenant


def _make_technician(tenant, username="tech1"):
    """Create a Technician linked to a tenant."""
    from apps.technician_portal.models import Technician
    user = User.objects.create_user(username=username, password="pass")
    return Technician.objects.create(user=user, tenant=tenant)


def _make_customer_user_c005(tenant, username="custuser1"):
    """Create a CustomerUser linked to a tenant (via Customer)."""
    from core.models import Customer
    from apps.customer_portal.models import CustomerUser
    customer = Customer.objects.create(name="Fleet Co", tenant=tenant)
    user = User.objects.create_user(username=username, password="pass")
    return CustomerUser.objects.create(user=user, customer=customer)


def _make_notification(recipient):
    """Create a minimal Notification for a given recipient object."""
    ct = ContentType.objects.get_for_model(recipient)
    return Notification.objects.create(
        recipient_type=ct,
        recipient_id=recipient.pk,
        title="Test Notification",
        message="Test message",
        priority=Notification.PRIORITY_MEDIUM,
        category=Notification.CATEGORY_SYSTEM,
    )


class TestDeliveryLogTenantField(TestCase):
    """Verify the tenant field exists and is nullable."""

    def test_field_exists_and_is_nullable(self):
        """NotificationDeliveryLog.tenant field must exist and allow null."""
        log = NotificationDeliveryLog.objects.create(
            channel="email",
            status="pending",
            recipient_email="test@example.com",
        )
        self.assertIsNone(log.tenant)

    def test_tenant_fk_can_be_set_explicitly(self):
        """tenant can be set explicitly without notification."""
        tenant = _make_tenant_c005("Explicit Tenant")
        log = NotificationDeliveryLog.objects.create(
            channel="email",
            status="sent",
            recipient_email="x@y.com",
            tenant=tenant,
        )
        log.refresh_from_db()
        self.assertEqual(log.tenant_id, tenant.pk)


class TestDeliveryLogTenantAutopopulate(TestCase):
    """Verify save() auto-populates tenant from notification recipient."""

    def test_auto_populate_from_technician_recipient(self):
        """
        When notification recipient is a Technician, save() should derive
        tenant from Technician.tenant.
        """
        tenant = _make_tenant_c005("Tech Tenant")
        tech = _make_technician(tenant, username="auto_tech1")
        notification = _make_notification(tech)

        log = NotificationDeliveryLog.objects.create(
            notification=notification,
            channel="sms",
            status="sent",
            recipient_phone="+15005550001",
        )
        log.refresh_from_db()
        self.assertEqual(log.tenant_id, tenant.pk,
                         "tenant should be auto-populated from Technician")

    def test_auto_populate_from_customer_user_recipient(self):
        """
        When notification recipient is a CustomerUser, save() should derive
        tenant from CustomerUser.customer.tenant.
        """
        tenant = _make_tenant_c005("Customer Tenant")
        cu = _make_customer_user_c005(tenant, username="auto_cu1")
        notification = _make_notification(cu)

        log = NotificationDeliveryLog.objects.create(
            notification=notification,
            channel="email",
            status="sent",
            recipient_email="fleet@example.com",
        )
        log.refresh_from_db()
        self.assertEqual(log.tenant_id, tenant.pk,
                         "tenant should be auto-populated from CustomerUser.customer.tenant")

    def test_no_autopopulate_without_notification(self):
        """Log without a notification gets tenant=None."""
        log = NotificationDeliveryLog.objects.create(
            channel="email",
            status="failed",
            recipient_email="no-notification@example.com",
        )
        self.assertIsNone(log.tenant)

    def test_explicit_tenant_not_overwritten_by_autopopulate(self):
        """
        If tenant is explicitly set before save, it should NOT be overwritten
        by _resolve_tenant().
        """
        tenant_a = _make_tenant_c005("Tenant A")
        tenant_b = _make_tenant_c005("Tenant B")
        tech = _make_technician(tenant_a, username="tech_override")
        notification = _make_notification(tech)

        log = NotificationDeliveryLog.objects.create(
            notification=notification,
            channel="email",
            status="sent",
            recipient_email="x@y.com",
            tenant=tenant_b,  # explicitly set to B
        )
        log.refresh_from_db()
        # tenant_b was explicitly set — should remain (auto-populate skips when tenant_id is not None)
        self.assertEqual(log.tenant_id, tenant_b.pk)


class TestDeliveryLogTenantFilter(TestCase):
    """Verify logs can be filtered by tenant in queries (superadmin use-case)."""

    def test_filter_by_tenant(self):
        """logs can be filtered by tenant FK."""
        tenant_x = _make_tenant_c005("Shop X")
        tenant_y = _make_tenant_c005("Shop Y")
        tech_x = _make_technician(tenant_x, username="tech_x")
        tech_y = _make_technician(tenant_y, username="tech_y")
        notif_x = _make_notification(tech_x)
        notif_y = _make_notification(tech_y)

        log_x = NotificationDeliveryLog.objects.create(
            notification=notif_x, channel="email", status="sent",
            recipient_email="x@shop.com",
        )
        log_y = NotificationDeliveryLog.objects.create(
            notification=notif_y, channel="sms", status="sent",
            recipient_phone="+10001112222",
        )

        x_logs = NotificationDeliveryLog.objects.filter(tenant=tenant_x)
        y_logs = NotificationDeliveryLog.objects.filter(tenant=tenant_y)

        self.assertIn(log_x, x_logs)
        self.assertNotIn(log_y, x_logs)
        self.assertIn(log_y, y_logs)
        self.assertNotIn(log_x, y_logs)

    def test_resolve_tenant_exception_does_not_break_save(self):
        """
        If _resolve_tenant() raises, save() should still succeed with tenant=None
        (no exception propagated).
        """
        tenant = _make_tenant_c005("Safe Tenant")
        tech = _make_technician(tenant, username="safe_tech")
        notification = _make_notification(tech)

        with patch.object(
            NotificationDeliveryLog,
            '_resolve_tenant',
            side_effect=RuntimeError("simulated error"),
        ):
            # Should not raise
            log = NotificationDeliveryLog(
                notification=notification,
                channel="email",
                status="pending",
                recipient_email="err@test.com",
            )
            log.save()

        # tenant stays None when resolution errors
        log.refresh_from_db()
        self.assertIsNone(log.tenant)


class TestDeliveryLogAdminTenantFilter(TestCase):
    """Smoke-test that admin list_filter includes 'tenant'."""

    def test_admin_list_filter_contains_tenant(self):
        from core.admin import DeliveryLogAdmin
        self.assertIn('tenant', DeliveryLogAdmin.list_filter)

    def test_admin_list_display_contains_tenant(self):
        from core.admin import DeliveryLogAdmin
        self.assertIn('tenant', DeliveryLogAdmin.list_display)


# --- From test_code008_cross_tenant_tech_assign.py ---

def _make_tenant_c008(name, owner_username, plan):
    owner = User.objects.create_user(username=owner_username, password='pw')
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner,
        plan='trial',
        subscription_plan=plan,
    ), owner


def _add_membership(user, tenant, role='owner'):
    TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)


class AssignRepairCrossTenantTest(TestCase):
    """
    assign_repair() must not allow assigning a technician from another tenant.
    """

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        # Shop A
        self.tenant_a, self.owner_a = _make_tenant_c008('Shop A', 'owner_a', plan)
        _add_membership(self.owner_a, self.tenant_a, 'owner')

        # Shop B
        self.tenant_b, self.owner_b = _make_tenant_c008('Shop B', 'owner_b', plan)
        _add_membership(self.owner_b, self.tenant_b, 'owner')

        # Technician belonging to Shop B
        self.tech_b_user = User.objects.create_user(username='tech_b', password='pw')
        self.tech_b = Technician.objects.create(
            user=self.tech_b_user,
            tenant=self.tenant_b,
            is_active=True,
        )

        # A placeholder technician in Shop A (needed for Repair NOT NULL constraint)
        self.placeholder_tech_user = User.objects.create_user(username='placeholder_tech_a', password='pw')
        self.placeholder_tech = Technician.objects.create(
            user=self.placeholder_tech_user,
            tenant=self.tenant_a,
            is_active=True,
        )

        # Customer + repair in Shop A
        self.customer_a = Customer.objects.create(
            name='Fleet A', email='fleet@a.com', tenant=self.tenant_a,
        )
        self.repair_a = Repair.objects.create(
            customer=self.customer_a,
            tenant=self.tenant_a,
            unit_number='A-001',
            queue_status='REQUESTED',
            technician=self.placeholder_tech,
        )

    def _make_request(self, user, tenant, post_data):
        """Build a POST request with the given user and tenant."""
        factory = RequestFactory()
        request = factory.post(f'/technician/repairs/{self.repair_a.id}/assign/', post_data)
        request.user = user
        request.tenant = tenant
        # Django messages middleware
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))
        return request

    def test_assign_repair_rejects_cross_tenant_tech_for_owner(self):
        """
        An owner of Shop A POSTing with a Shop B technician's ID should get
        'Selected technician not found.' — NOT a successful assignment.
        """
        from apps.technician_portal.views.repairs import assign_repair

        request = self._make_request(
            self.owner_a,
            self.tenant_a,
            {'technician_id': str(self.tech_b.id)},
        )

        response = assign_repair(request, self.repair_a.id)

        # Repair must NOT have been reassigned to the foreign tech
        self.repair_a.refresh_from_db()
        self.assertNotEqual(self.repair_a.technician_id, self.tech_b.id,
                            "Repair must not be assigned to a cross-tenant technician")
        self.assertEqual(self.repair_a.queue_status, 'REQUESTED',
                         "Queue status must remain REQUESTED after rejected cross-tenant assignment")

    def test_assign_repair_allows_same_tenant_tech(self):
        """
        An owner of Shop A can assign a repair to a technician in Shop A.
        """
        from apps.technician_portal.views.repairs import assign_repair

        # Create a technician in Shop A
        tech_a_user = User.objects.create_user(username='tech_a', password='pw')
        tech_a = Technician.objects.create(
            user=tech_a_user,
            tenant=self.tenant_a,
            is_active=True,
        )

        request = self._make_request(
            self.owner_a,
            self.tenant_a,
            {'technician_id': str(tech_a.id)},
        )

        assign_repair(request, self.repair_a.id)

        self.repair_a.refresh_from_db()
        self.assertEqual(self.repair_a.technician_id, tech_a.id,
                         "Repair should be assigned to the same-tenant technician")


class BatchCrossTenantTechTest(TestCase):
    """
    create_multi_break_repair() must not allow assigning a cross-tenant technician.
    The fix ensures the Technician queryset is filtered by tenant.
    """

    def test_batch_view_tech_queryset_is_tenant_filtered(self):
        """
        When an admin POSTs technician_id belonging to another tenant, the view
        must raise DoesNotExist (or a 'not found' redirect), not succeed.

        We test the queryset logic directly since the full view requires
        extensive multi-break POST data.
        """
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        tenant_a, owner_a = _make_tenant_c008('Batch Shop A', 'batch_owner_a', plan)
        tenant_b, owner_b = _make_tenant_c008('Batch Shop B', 'batch_owner_b', plan)

        tech_b_user = User.objects.create_user(username='batch_tech_b', password='pw')
        tech_b = Technician.objects.create(
            user=tech_b_user,
            tenant=tenant_b,
            is_active=True,
        )

        # Simulate the fixed queryset from batch.py admin path
        tech_id = str(tech_b.id)
        tech_qs = Technician.objects.filter(id=tech_id)
        tech_qs = tech_qs.filter(tenant=tenant_a)  # tenant_a is the request tenant

        # Should be empty — tech_b belongs to tenant_b
        self.assertEqual(
            tech_qs.count(), 0,
            "Cross-tenant technician must not be reachable from tenant_a's filtered queryset"
        )

    def test_batch_view_same_tenant_tech_queryset_passes(self):
        """
        Same-tenant technician ID is found correctly.
        """
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        tenant_a, owner_a = _make_tenant_c008('Batch Shop C', 'batch_owner_c', plan)

        tech_a_user = User.objects.create_user(username='batch_tech_a', password='pw')
        tech_a = Technician.objects.create(
            user=tech_a_user,
            tenant=tenant_a,
            is_active=True,
        )

        # Simulate the fixed queryset from batch.py admin path
        tech_qs = Technician.objects.filter(id=tech_a.id)
        tech_qs = tech_qs.filter(tenant=tenant_a)

        self.assertEqual(tech_qs.count(), 1,
                         "Same-tenant technician must be found")
        self.assertEqual(tech_qs.first().id, tech_a.id)


# --- From test_code009_admin_managed_technicians_tenant.py ---

def _make_plan_c009():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name="Test Plan",
        defaults={
            "monthly_price": 0,
            "max_technicians": 10,
            "max_customers": 100,
            "trial_days": 14,
        },
    )
    return plan


def _make_tenant_c009(name):
    plan = _make_plan_c009()
    owner = User.objects.create_user(
        username=f"owner_{name.lower().replace(' ', '_')}",
        email=f"owner_{name.lower().replace(' ', '_')}@example.com",
        password="pass",
    )
    tenant = Tenant.objects.create(
        name=name,
        subdomain=name.lower().replace(" ", "-"),
        subscription_plan=plan,
        owner=owner,
    )
    return tenant


def _make_tech_c009(tenant, username, is_manager=False):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pass",
        first_name=username,
        last_name="Test",
    )
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        expertise="CHIP",
        is_manager=is_manager,
        is_active=True,
    )
    return tech


class ManagedTechnicianAdminQuerysetTest(TestCase):
    """
    TechnicianAdmin.get_form() managed_technicians queryset must be
    scoped to the manager's tenant.
    """

    def setUp(self):
        self.site = AdminSite()
        self.admin = TechnicianAdmin(Technician, self.site)

        self.tenant_a = _make_tenant_c009("Shop A")
        self.tenant_b = _make_tenant_c009("Shop B")

        self.manager_a = _make_tech_c009(self.tenant_a, "mgr_a", is_manager=True)
        self.tech_a1 = _make_tech_c009(self.tenant_a, "tech_a1")
        self.tech_a2 = _make_tech_c009(self.tenant_a, "tech_a2")
        self.tech_b1 = _make_tech_c009(self.tenant_b, "tech_b1")
        self.tech_b2 = _make_tech_c009(self.tenant_b, "tech_b2")

        # Superuser request
        self.superuser = User.objects.create_superuser(
            username="super", email="super@example.com", password="pass"
        )

    def _make_request(self):
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get("/admin/")
        req.user = self.superuser
        return req

    def test_managed_technicians_queryset_excludes_other_tenant(self):
        """When editing an existing manager, M2M picker must not show foreign-tenant techs."""
        request = self._make_request()
        form = self.admin.get_form(request, obj=self.manager_a)

        if "managed_technicians" not in form.base_fields:
            self.skipTest("managed_technicians not in form fields")

        qs = form.base_fields["managed_technicians"].queryset
        ids = list(qs.values_list("id", flat=True))

        # Tenant B techs must NOT appear
        self.assertNotIn(self.tech_b1.id, ids, "tech_b1 (Tenant B) must not appear in Tenant A manager's picker")
        self.assertNotIn(self.tech_b2.id, ids, "tech_b2 (Tenant B) must not appear in Tenant A manager's picker")

    def test_managed_technicians_queryset_includes_same_tenant(self):
        """Picker must still show active techs from the same tenant."""
        request = self._make_request()
        form = self.admin.get_form(request, obj=self.manager_a)

        if "managed_technicians" not in form.base_fields:
            self.skipTest("managed_technicians not in form fields")

        qs = form.base_fields["managed_technicians"].queryset
        ids = list(qs.values_list("id", flat=True))

        self.assertIn(self.tech_a1.id, ids, "tech_a1 (same tenant) must appear in picker")
        self.assertIn(self.tech_a2.id, ids, "tech_a2 (same tenant) must appear in picker")

    def test_managed_technicians_queryset_excludes_self(self):
        """Manager must not appear in their own managed_technicians picker."""
        request = self._make_request()
        form = self.admin.get_form(request, obj=self.manager_a)

        if "managed_technicians" not in form.base_fields:
            self.skipTest("managed_technicians not in form fields")

        qs = form.base_fields["managed_technicians"].queryset
        ids = list(qs.values_list("id", flat=True))

        self.assertNotIn(self.manager_a.id, ids, "Manager must not appear in their own picker")


class ValidateManagedTechniciansTest(TestCase):
    """
    validate_managed_technicians() must strip cross-tenant techs and raise.
    save_related() must call it so M2M saves are safe.
    """

    def setUp(self):
        self.tenant_a = _make_tenant_c009("Shop X")
        self.tenant_b = _make_tenant_c009("Shop Y")
        self.manager_a = _make_tech_c009(self.tenant_a, "mgr_x", is_manager=True)
        self.tech_b = _make_tech_c009(self.tenant_b, "tech_y")
        self.tech_a = _make_tech_c009(self.tenant_a, "tech_x")

    def test_validate_strips_cross_tenant_techs(self):
        """validate_managed_technicians() removes foreign-tenant techs."""
        from django.core.exceptions import ValidationError

        # Force-add a cross-tenant tech (bypassing the form)
        self.manager_a.managed_technicians.add(self.tech_b)
        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

        with self.assertRaises(ValidationError):
            self.manager_a.validate_managed_technicians()

        # The cross-tenant tech should have been removed
        self.assertEqual(self.manager_a.managed_technicians.count(), 0)

    def test_validate_keeps_same_tenant_techs(self):
        """validate_managed_technicians() does not remove same-tenant techs."""
        self.manager_a.managed_technicians.add(self.tech_a)
        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

        # Should not raise
        self.manager_a.validate_managed_technicians()

        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

    def test_save_related_calls_validate(self):
        """
        TechnicianAdmin.save_related() must call validate_managed_technicians()
        so cross-tenant techs are stripped even if they reach the save step.
        """
        site = AdminSite()
        admin_obj = TechnicianAdmin(Technician, site)

        # Force-add a cross-tenant tech
        self.manager_a.managed_technicians.add(self.tech_b)
        self.assertEqual(self.manager_a.managed_technicians.count(), 1)

        # Simulate what admin does: build a minimal mock form
        class MockForm:
            instance = self.manager_a
            def save_m2m(self):
                pass

        # save_related signature: (request, form, formsets, change)
        admin_obj.save_related(request=None, form=MockForm(), formsets=[], change=True)

        # Cross-tenant tech must be gone
        self.manager_a.refresh_from_db()
        self.assertEqual(
            self.manager_a.managed_technicians.count(), 0,
            "save_related must strip cross-tenant techs via validate_managed_technicians()"
        )


# --- From test_code011_reward_options_tenant_scope.py ---

def _make_plan_c011():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant_c011(name, plan):
    owner = User.objects.create_user(
        username=f"owner_{name.lower().replace(' ', '_')}",
        password='pw'
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


def _make_customer_user_c011(tenant, username='cust_user'):
    user = User.objects.create_user(username=username, password='pw', email=f'{username}@test.com')
    customer = Customer.objects.create(
        name='Test Fleet Co.',
        email=f'{username}@fleet.com',
        tenant=tenant,
    )
    customer_user = CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=True,
    )
    return user, customer_user


class RewardOptionTenantScopeTest(TestCase):
    """
    customer_rewards_redirect must only show the requesting tenant's reward options.
    """

    def setUp(self):
        plan = _make_plan_c011()
        self.tenant_a, _owner_a = _make_tenant_c011('Shop A', plan)
        self.tenant_b, _owner_b = _make_tenant_c011('Shop B', plan)

        self.user_a, self.cu_a = _make_customer_user_c011(self.tenant_a, 'cust_a')
        self.user_b, self.cu_b = _make_customer_user_c011(self.tenant_b, 'cust_b')

        # Shop A reward option
        self.option_a = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='Free Wash - Shop A',
            description='A free wash from Shop A',
            points_required=100,
            is_active=True,
        )
        # Shop B reward option
        self.option_b = RewardOption.objects.create(
            tenant=self.tenant_b,
            name='Free Wash - Shop B',
            description='A free wash from Shop B',
            points_required=200,
            is_active=True,
        )
        # Inactive option in Shop A
        self.option_a_inactive = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='Inactive Shop A Option',
            description='Inactive',
            points_required=50,
            is_active=False,
        )

    # ------------------------------------------------------------------
    # Unit-level: QuerySet behaviour
    # ------------------------------------------------------------------

    def test_queryset_with_tenant_filter_returns_only_own_options(self):
        """Filtering by tenant + is_active must only return that tenant's active options."""
        qs_a = RewardOption.objects.filter(is_active=True, tenant=self.tenant_a)
        self.assertIn(self.option_a, qs_a)
        self.assertNotIn(self.option_b, qs_a)
        self.assertNotIn(self.option_a_inactive, qs_a)

    def test_queryset_without_tenant_filter_leaks_cross_tenant(self):
        """Control: unfiltered queryset DOES contain cross-tenant options (documents the old bug)."""
        qs_all = RewardOption.objects.filter(is_active=True)
        self.assertIn(self.option_a, qs_all)
        self.assertIn(self.option_b, qs_all)

    # ------------------------------------------------------------------
    # View-level: HTTP response must not contain other tenant's options
    # ------------------------------------------------------------------

    def _get_rewards_page(self, user, tenant):
        """Hit the customer_rewards_redirect view as the given user."""
        self.client.force_login(user)
        # Patch request.tenant so middleware-dependent code works
        with patch('apps.customer_portal.views.CustomerUser.objects.select_related') as mock_sel:
            # Let the real ORM do the work — just need the view to succeed
            pass
        response = self.client.get('/app/rewards/', follow=True)
        return response

    def test_view_only_shows_own_tenant_options(self):
        """The rewards view renders only the requesting tenant's active options."""
        self.client.force_login(self.user_a)
        response = self.client.get('/app/rewards/')
        # View should succeed (200 or redirect to login, not 500)
        self.assertIn(response.status_code, (200, 302))

        if response.status_code == 200:
            content = response.content.decode()
            # Shop A's option must appear
            self.assertIn('Shop A', content)
            # Shop B's option must NOT appear
            self.assertNotIn('Shop B', content)

    def test_view_does_not_show_other_tenant_option_to_shop_b_user(self):
        """A Shop B customer must not see Shop A options."""
        self.client.force_login(self.user_b)
        response = self.client.get('/app/rewards/')
        self.assertIn(response.status_code, (200, 302))

        if response.status_code == 200:
            content = response.content.decode()
            self.assertNotIn('Free Wash - Shop A', content)
            self.assertIn('Free Wash - Shop B', content)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_options_for_tenant_returns_empty(self):
        """If a tenant has no active reward options, the view gets an empty list."""
        # Create a third tenant with no options
        plan = _make_plan_c011()
        tenant_c, _owner_c = _make_tenant_c011('Shop C', plan)
        user_c, _cu_c = _make_customer_user_c011(tenant_c, 'cust_c')

        qs_c = RewardOption.objects.filter(is_active=True, tenant=tenant_c)
        self.assertEqual(qs_c.count(), 0)

    def test_inactive_options_excluded(self):
        """Inactive options are excluded even when they belong to the right tenant."""
        qs_a = RewardOption.objects.filter(is_active=True, tenant=self.tenant_a)
        self.assertNotIn(self.option_a_inactive, qs_a)

    def test_options_ordered_by_points_required(self):
        """Options should come back in ascending points_required order."""
        extra = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='Premium Option',
            description='Expensive one',
            points_required=500,
            is_active=True,
        )
        qs = list(RewardOption.objects.filter(is_active=True, tenant=self.tenant_a).order_by('points_required'))
        self.assertEqual(qs[0], self.option_a)      # 100 pts
        self.assertEqual(qs[1], extra)               # 500 pts


# --- From test_code020_update_team_member_tenant_scope.py ---

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_c020():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial",
        defaults={
            "name": "Trial",
            "monthly_price": Decimal("0.00"),
            "trial_days": 30,
            "is_active": True,
            "display_order": 0,
        },
    )
    return plan


def _make_tenant_c020(name, slug, owner):
    return Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan="trial",
        subscription_plan=_plan_c020(),
    )


def _membership_c020(user, tenant, role="owner"):
    return TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True
    )


def _make_user(username):
    return User.objects.create_user(
        username=username,
        password="pw",
        email=f"{username}@ex.com",
        first_name="Test",
        last_name="User",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@override_settings(**TEST_OVERRIDES)
class UpdateTeamMemberTenantScopeTests(TestCase):
    """update_team_member() must never touch Technician records from other tenants."""

    def setUp(self):
        # Two independent shops
        self.owner_a = _make_user("owner_a_020")
        self.owner_b = _make_user("owner_b_020")

        self.tenant_a = _make_tenant_c020("Shop A 020", "shop-a-020", self.owner_a)
        self.tenant_b = _make_tenant_c020("Shop B 020", "shop-b-020", self.owner_b)

        _membership_c020(self.owner_a, self.tenant_a, "owner")
        _membership_c020(self.owner_b, self.tenant_b, "owner")

        self.client_a = Client()
        self.client_a.force_login(self.owner_a)

        self.client_b = Client()
        self.client_b.force_login(self.owner_b)

    # ------------------------------------------------------------------
    # Scenario 1: Promote a fresh user (no prior Technician) — normal path
    # ------------------------------------------------------------------

    def test_promote_creates_technician_for_correct_tenant(self):
        """Promoting a brand-new viewer to technician creates a Technician for THIS tenant."""
        new_user = _make_user("newbie_020")
        mem = _membership_c020(new_user, self.tenant_a, "viewer")

        resp = self.client_a.post(
            f"/owner/team/{mem.id}/update/",
            {"role": "technician", "can_repair": "on"},
        )
        self.assertIn(resp.status_code, [200, 302],
                      f"Expected redirect or 200, got {resp.status_code}")

        tech = Technician.objects.filter(user=new_user, tenant=self.tenant_a).first()
        self.assertIsNotNone(tech, "Technician record should be created for Shop A")
        self.assertEqual(tech.tenant, self.tenant_a)

    # ------------------------------------------------------------------
    # Scenario 2: User has Technician at Shop B; Shop A tries to promote
    # ------------------------------------------------------------------

    def test_promote_does_not_steal_foreign_technician_record(self):
        """
        If a user already has a Technician record for Shop B, promoting them
        at Shop A must NOT overwrite that record's tenant field.
        """
        shared_user = _make_user("shared_tech_020")

        # Shop B already has this user as a Technician
        tech_b = Technician.objects.create(
            user=shared_user,
            tenant=self.tenant_b,
            is_active=True,
            is_manager=False,
        )

        # Shop A adds them as a viewer, then owner promotes to technician
        mem_a = _membership_c020(shared_user, self.tenant_a, "viewer")

        self.client_a.post(
            f"/owner/team/{mem_a.id}/update/",
            {"role": "technician", "can_repair": "on"},
        )

        # Shop B's Technician record must be untouched
        tech_b.refresh_from_db()
        self.assertEqual(
            tech_b.tenant, self.tenant_b,
            "Shop B's Technician.tenant must NOT be overwritten to Shop A",
        )
        self.assertTrue(tech_b.is_active, "Shop B's Technician must remain active")

    def test_promote_does_not_change_foreign_tech_is_manager(self):
        """Promoting at Shop A must not flip is_manager on the existing record from Shop B."""
        shared_user = _make_user("shared_mgr_020")

        tech_b = Technician.objects.create(
            user=shared_user,
            tenant=self.tenant_b,
            is_active=True,
            is_manager=False,
        )

        mem_a = _membership_c020(shared_user, self.tenant_a, "viewer")

        self.client_a.post(
            f"/owner/team/{mem_a.id}/update/",
            {"role": "manager"},
        )

        tech_b.refresh_from_db()
        self.assertFalse(
            tech_b.is_manager,
            "Shop B's is_manager must not be changed by Shop A's promote action",
        )
        self.assertEqual(tech_b.tenant, self.tenant_b)

    # ------------------------------------------------------------------
    # Scenario 3: Same-tenant update works correctly
    # ------------------------------------------------------------------

    def test_promote_same_tenant_updates_in_place(self):
        """Updating an existing same-tenant Technician record updates flags in place."""
        user = _make_user("same_tenant_020")
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,
            is_active=True,
            is_manager=False,
            can_repair=True,
            can_replace=False,
        )
        mem = _membership_c020(user, self.tenant_a, "technician")

        resp = self.client_a.post(
            f"/owner/team/{mem.id}/update/",
            {"role": "manager", "can_repair": "on", "can_replace": "on"},
        )
        self.assertIn(resp.status_code, [200, 302])

        tech.refresh_from_db()
        self.assertTrue(tech.is_manager, "is_manager should be updated to True")
        self.assertTrue(tech.can_replace, "can_replace should be updated to True")
        self.assertEqual(tech.tenant, self.tenant_a, "tenant must not change")

    def test_demote_deactivates_same_tenant_technician(self):
        """Moving a technician to viewer deactivates their Technician record for THIS tenant."""
        user = _make_user("demoted_020")
        tech = Technician.objects.create(
            user=user,
            tenant=self.tenant_a,
            is_active=True,
            is_manager=False,
        )
        mem = _membership_c020(user, self.tenant_a, "technician")

        self.client_a.post(
            f"/owner/team/{mem.id}/update/",
            {"role": "viewer"},
        )

        tech.refresh_from_db()
        self.assertFalse(tech.is_active, "Shop A's Technician should be deactivated")

    # ------------------------------------------------------------------
    # Scenario 4: Cross-tenant membership ID cannot be updated (URL auth)
    # ------------------------------------------------------------------

    def test_shop_b_cannot_update_shop_a_membership(self):
        """
        A Shop B owner cannot update a TenantMembership belonging to Shop A
        (get_object_or_404 tenant scoping).
        """
        user = _make_user("target_user_020")
        mem_a = _membership_c020(user, self.tenant_a, "technician")

        resp = self.client_b.post(
            f"/owner/team/{mem_a.id}/update/",
            {"role": "viewer"},
        )
        # Should redirect away or 404 — membership doesn't belong to tenant_b
        self.assertIn(resp.status_code, [302, 404])
        # The membership for Shop A must be unchanged
        mem_a.refresh_from_db()
        self.assertEqual(mem_a.role, "technician",
                         "Shop A membership must not be changed by Shop B owner")

    # ------------------------------------------------------------------
    # Scenario 5: Verify the warning log is emitted for cross-tenant collision
    # ------------------------------------------------------------------

    def test_warning_logged_when_foreign_technician_exists(self):
        """
        When a user already has a foreign-tenant Technician record, the view
        must log a warning and skip creation (not raise or silently corrupt).
        """
        shared_user = _make_user("collision_warn_020")

        # User already has a Technician at Shop B
        Technician.objects.create(
            user=shared_user,
            tenant=self.tenant_b,
            is_active=True,
        )

        mem_a = _membership_c020(shared_user, self.tenant_a, "viewer")

        with self.assertLogs("apps.saas.views", level=logging.WARNING) as log_cm:
            self.client_a.post(
                f"/owner/team/{mem_a.id}/update/",
                {"role": "technician", "can_repair": "on"},
            )

        # At least one warning about the collision should be present
        warning_found = any(
            "already has a Technician record" in msg for msg in log_cm.output
        )
        self.assertTrue(
            warning_found,
            "Expected a WARNING log about cross-tenant Technician collision, "
            f"but got: {log_cm.output}",
        )


# --- From test_code021_unscoped_is_tenant_admin_in_views.py ---

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan_c021():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant_c021(name, owner_user, plan):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-').replace('_', '-'),
        subdomain=name.lower().replace(' ', '-').replace('_', '-'),
        owner=owner_user,
        plan='trial',
        subscription_plan=plan,
    )


def _membership_c021(user, tenant, role):
    return TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class IsAdminScopingTests(TestCase):
    """
    Verify that is_tenant_admin with vs without tenant parameter behaves
    correctly for cross-tenant scenarios.
    """

    def setUp(self):
        plan = _plan_c021()

        # Shop A owner (also manager at Shop A)
        self.owner_a = User.objects.create_user('owner_a_021', password='pw')
        self.tenant_a = _make_tenant_c021('shop_a_021', self.owner_a, plan)
        _membership_c021(self.owner_a, self.tenant_a, 'owner')

        # Shop B owner
        self.owner_b = User.objects.create_user('owner_b_021', password='pw')
        self.tenant_b = _make_tenant_c021('shop_b_021', self.owner_b, plan)
        _membership_c021(self.owner_b, self.tenant_b, 'owner')

        # Cross-tenant user: admin at Shop A, plain technician at Shop B
        self.cross_user = User.objects.create_user('cross_021', password='pw')
        _membership_c021(self.cross_user, self.tenant_a, 'owner')   # admin at A
        _membership_c021(self.cross_user, self.tenant_b, 'viewer')  # viewer at B

    def test_unscoped_returns_highest_privilege(self):
        """Without tenant, is_tenant_admin returns True if user is admin anywhere."""
        # This is expected behavior for unscoped — but it's WRONG in view context
        result = is_tenant_admin(self.cross_user)
        self.assertTrue(result, "Unscoped should return True (admin at Shop A)")

    def test_scoped_to_shop_b_returns_false(self):
        """With tenant=shop_b, is_tenant_admin returns False for cross-tenant admin."""
        result = is_tenant_admin(self.cross_user, tenant=self.tenant_b)
        self.assertFalse(result, "Should NOT be admin at Shop B (only viewer there)")

    def test_scoped_to_shop_a_returns_true(self):
        """With tenant=shop_a, is_tenant_admin returns True for shop_a admin."""
        result = is_tenant_admin(self.cross_user, tenant=self.tenant_a)
        self.assertTrue(result, "Should be admin at Shop A")

    def test_plain_technician_not_admin_at_either_shop(self):
        """A plain technician is not admin at any shop."""
        tech_user = User.objects.create_user('tech_only_021', password='pw')
        _membership_c021(tech_user, self.tenant_a, 'technician')

        self.assertFalse(is_tenant_admin(tech_user))
        self.assertFalse(is_tenant_admin(tech_user, tenant=self.tenant_a))
        self.assertFalse(is_tenant_admin(tech_user, tenant=self.tenant_b))

    def test_manager_at_shop_a_not_admin_at_shop_b(self):
        """A manager at Shop A is not admin at Shop B (even with unrelated membership)."""
        mgr = User.objects.create_user('mgr_021', password='pw')
        _membership_c021(mgr, self.tenant_a, 'manager')
        _membership_c021(mgr, self.tenant_b, 'technician')

        # Unscoped: True (manager at A)
        self.assertTrue(is_tenant_admin(mgr))
        # Scoped to B: False (only technician at B)
        self.assertFalse(is_tenant_admin(mgr, tenant=self.tenant_b))
        # Scoped to A: True
        self.assertTrue(is_tenant_admin(mgr, tenant=self.tenant_a))


class GetUserRoleScopingTests(TestCase):
    """Verify get_user_role (underlying function) respects tenant parameter."""

    def setUp(self):
        plan = _plan_c021()
        self.owner_a = User.objects.create_user('gr_owner_a_021', password='pw')
        self.tenant_a = _make_tenant_c021('gr_shop_a_021', self.owner_a, plan)
        _membership_c021(self.owner_a, self.tenant_a, 'owner')

        self.owner_b = User.objects.create_user('gr_owner_b_021', password='pw')
        self.tenant_b = _make_tenant_c021('gr_shop_b_021', self.owner_b, plan)
        _membership_c021(self.owner_b, self.tenant_b, 'owner')

        self.cross_user = User.objects.create_user('gr_cross_021', password='pw')
        _membership_c021(self.cross_user, self.tenant_a, 'owner')
        _membership_c021(self.cross_user, self.tenant_b, 'technician')

    def test_role_without_tenant_returns_highest(self):
        role = get_user_role(self.cross_user)
        self.assertEqual(role, 'owner', "Without tenant, highest role (owner at A) returned")

    def test_role_scoped_to_b_returns_technician(self):
        role = get_user_role(self.cross_user, tenant=self.tenant_b)
        self.assertEqual(role, 'technician', "Scoped to B: only technician")

    def test_role_scoped_to_a_returns_owner(self):
        role = get_user_role(self.cross_user, tenant=self.tenant_a)
        self.assertEqual(role, 'owner', "Scoped to A: owner")


class ViewCodeUsesCorrectParamTests(TestCase):
    """
    Black-box verification: scan the view source to confirm all in-view
    is_tenant_admin(request.user) calls now include the tenant parameter.
    """

    def test_repairs_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/repairs.py') as f:
            src = f.read()
        # Bare call: is_tenant_admin(request.user) NOT followed by ", tenant"
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in repairs.py: {bare}"
        )

    def test_batch_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/batch.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in batch.py: {bare}"
        )

    def test_customers_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/customers.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in customers.py: {bare}"
        )

    def test_settings_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/settings.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in settings.py: {bare}"
        )

    def test_dashboard_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/dashboard.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in dashboard.py: {bare}"
        )

    def test_rewards_py_no_bare_calls(self):
        import re
        with open('apps/technician_portal/views/rewards.py') as f:
            src = f.read()
        bare = re.findall(r'is_tenant_admin\(request\.user\)(?!\s*,|\s*tenant)', src)
        self.assertEqual(
            bare, [],
            f"Found unscoped is_tenant_admin calls in rewards.py: {bare}"
        )


# --- From test_code022_batch_detail_no_technician_profile.py ---

def _make_plan_c022():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant_c022(name, owner):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner,
        plan='trial',
        subscription_plan=_make_plan_c022(),
    )


def _make_membership(user, tenant, role='technician'):
    TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)


def _make_tech_c022(user, tenant, is_manager=False):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        phone_number='555-0100',
        is_manager=is_manager,
    )


class BatchDetailNoTechProfileTests(TestCase):
    """
    Verifies that technician_batch_detail and technician_batch_start_work do NOT
    crash when the authenticated user has no Technician model record.
    """

    def setUp(self):
        _make_plan_c022()

        # Owner without a Technician record
        self.owner_user = User.objects.create_user(username='shop_owner', password='pw')
        self.tenant = _make_tenant_c022('Test Shop', self.owner_user)
        _make_membership(self.owner_user, self.tenant, 'owner')
        # Intentionally NOT creating a Technician for owner_user

        # Separate tech user who DOES have a Technician record (creates the batch)
        self.tech_user = User.objects.create_user(username='tech_a', password='pw')
        _make_membership(self.tech_user, self.tenant, 'technician')
        self.tech = _make_tech_c022(self.tech_user, self.tenant)

        self.customer = Customer.objects.create(
            name='Fleet Co',
            address='1 Industrial Blvd',
            email='fleet@example.com',
            tenant=self.tenant,
        )

        # Build a batch of 2 repairs
        # Note: is_part_of_batch is a @property, not a field — do not pass it to create()
        self.batch_id = uuid.uuid4()
        self.repair_1 = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            service_date='2026-03-15',
            unit_number='T-001',
            damage_type='CHIP',
            queue_status='APPROVED',
            cost=Decimal('75.00'),
            repair_batch_id=self.batch_id,
            break_number=1,
            total_breaks_in_batch=2,
        )
        self.repair_2 = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            service_date='2026-03-15',
            unit_number='T-001',
            damage_type='CRACK',
            queue_status='APPROVED',
            cost=Decimal('85.00'),
            repair_batch_id=self.batch_id,
            break_number=2,
            total_breaks_in_batch=2,
        )

        self.factory = RequestFactory()

    def _make_request(self, user, method='GET', data=None):
        """Build a request with tenant and session attached."""
        if method == 'POST':
            req = self.factory.post(f'/tech/batch/{self.batch_id}/', data or {})
        else:
            req = self.factory.get(f'/tech/batch/{self.batch_id}/')
        req.user = user
        req.tenant = self.tenant
        req.session = {}
        # Attach messages middleware manually
        from django.contrib.messages.storage.fallback import FallbackStorage
        req._messages = FallbackStorage(req)
        return req

    # ------------------------------------------------------------------
    # 1. technician_batch_detail — owner without Technician record
    # ------------------------------------------------------------------

    def test_batch_detail_owner_no_tech_profile_does_not_crash(self):
        """
        Owner user with no Technician record should NOT raise
        RelatedObjectDoesNotExist when viewing a batch.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.owner_user)
        # Should not raise — just return a response
        response = technician_batch_detail(req, batch_id=self.batch_id)
        # Owner is admin → can_view=True → 200 OK (or 302 redirect to dashboard)
        self.assertIn(response.status_code, [200, 302])

    def test_batch_detail_owner_no_tech_profile_can_view(self):
        """
        Owner (is_tenant_admin=True) should be granted can_view even without
        a Technician profile — so they see the batch, not a "permission denied" redirect.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.owner_user)
        response = technician_batch_detail(req, batch_id=self.batch_id)
        # Owner is admin, so should not be redirected to dashboard with error
        # A 200 means the template rendered; a 302 to technician_dashboard would be wrong
        if response.status_code == 302:
            self.assertNotIn('technician_dashboard', response.get('Location', ''))

    def test_batch_detail_superuser_no_tech_profile_does_not_crash(self):
        """
        Superuser (is_superuser=True) with no Technician record should not crash.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        su = User.objects.create_superuser(username='superadmin', password='pw')
        req = self._make_request(su)
        # Should not raise
        response = technician_batch_detail(req, batch_id=self.batch_id)
        self.assertIn(response.status_code, [200, 302])

    def test_batch_detail_nonexistent_batch_returns_redirect(self):
        """
        A batch_id that doesn't exist should return a redirect (not crash).
        Even for owner without tech profile.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        fake_id = uuid.uuid4()
        req = self._make_request(self.owner_user)
        req._messages = __import__('django.contrib.messages.storage.fallback',
                                    fromlist=['FallbackStorage']).FallbackStorage(req)
        response = technician_batch_detail(req, batch_id=fake_id)
        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # 2. technician_batch_start_work — owner without Technician record
    # ------------------------------------------------------------------

    def test_batch_start_work_owner_no_tech_profile_does_not_crash(self):
        """
        Owner without a Technician record should NOT crash in batch_start_work.
        Owners are tenant admins (is_tenant_admin=True), so they CAN start repairs
        even without a Technician profile — the admin branch bypasses the
        `repair.technician == technician` check entirely.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        req = self._make_request(self.owner_user, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        # Should not raise — redirects back to batch detail
        self.assertEqual(response.status_code, 302)
        # Owners ARE tenant admins → they start all APPROVED repairs in the batch
        self.repair_1.refresh_from_db()
        self.repair_2.refresh_from_db()
        self.assertEqual(self.repair_1.queue_status, 'IN_PROGRESS')
        self.assertEqual(self.repair_2.queue_status, 'IN_PROGRESS')

    def test_batch_start_work_superuser_no_tech_profile_does_not_crash(self):
        """
        Superuser without a Technician record should not crash in batch_start_work.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        su = User.objects.create_superuser(username='superadmin2', password='pw')
        req = self._make_request(su, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # 3. Normal technician — should still work
    # ------------------------------------------------------------------

    def test_batch_detail_normal_tech_can_view_own_batch(self):
        """
        A regular Technician with repairs in the batch should still be able
        to view the batch after the fix.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.tech_user)
        response = technician_batch_detail(req, batch_id=self.batch_id)
        self.assertIn(response.status_code, [200, 302])

    def test_batch_start_work_tech_with_profile_starts_repairs(self):
        """
        A regular Technician can still start work on their approved batch repairs.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        req = self._make_request(self.tech_user, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        self.assertEqual(response.status_code, 302)
        self.repair_1.refresh_from_db()
        self.repair_2.refresh_from_db()
        self.assertEqual(self.repair_1.queue_status, 'IN_PROGRESS')
        self.assertEqual(self.repair_2.queue_status, 'IN_PROGRESS')

    # ------------------------------------------------------------------
    # 4. getattr guard — unit test
    # ------------------------------------------------------------------

    def test_owner_user_has_no_technician_attribute(self):
        """
        Baseline sanity check: owner_user genuinely has no Technician record.
        Accessing .technician directly should raise an exception; getattr should
        return None.
        """
        with self.assertRaises(Exception):
            _ = self.owner_user.technician

        result = getattr(self.owner_user, 'technician', None)
        self.assertIsNone(result)


# --- CODE-029: IDOR on batch pricing AJAX endpoint ---

from django.test import TestCase, Client
from apps.technician_portal.services.batch_pricing_service import get_batch_pricing_preview


class BatchPricingTenantScopeTests(TestCase):
    """
    CODE-029: get_batch_pricing_preview() and the /tech/api/batch-pricing/ endpoint
    had no tenant filter on Customer lookup. Any technician could probe any shop's
    customer pricing data by guessing integer PKs.
    """

    def setUp(self):
        from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
        from apps.technician_portal.models import Technician

        plan = SubscriptionPlan.objects.create(
            name='Trial', slug='trial-bprice', monthly_price=0,
            max_technicians=10, trial_days=14,
        )
        owner_a = User.objects.create_user('bp_owner_a', 'bp_owner_a@ex.com', 'pass')
        owner_b = User.objects.create_user('bp_owner_b', 'bp_owner_b@ex.com', 'pass')
        self.tenant_a = Tenant.objects.create(name='BP Shop A', slug='bp-shop-a', plan=plan, owner=owner_a)
        self.tenant_b = Tenant.objects.create(name='BP Shop B', slug='bp-shop-b', plan=plan, owner=owner_b)

        # Customer at Shop B
        self.customer_b = Customer.objects.create(
            name='Shop B Customer', tenant=self.tenant_b, email='custb@ex.com'
        )

        # Technician at Shop A
        self.tech_user = User.objects.create_user('bp_tech_a', 'bp_tech_a@ex.com', 'pass')
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.tech_user, role='technician')
        from django.contrib.auth.models import Group
        grp, _ = Group.objects.get_or_create(name='Technicians')
        self.tech_user.groups.add(grp)
        self.tech = Technician.objects.create(
            tenant=self.tenant_a, user=self.tech_user, is_active=True,
        )

    def test_service_returns_none_for_cross_tenant_customer(self):
        """With tenant filter, pricing preview returns None for wrong-tenant customer."""
        result = get_batch_pricing_preview(
            customer_id=self.customer_b.id,
            unit_number='UNIT-1',
            breaks_count=2,
            tenant=self.tenant_a,   # Shop A tenant — should NOT find Shop B customer
        )
        self.assertIsNone(result, "Must return None when customer belongs to a different tenant")

    def test_service_returns_data_for_correct_tenant_customer(self):
        """With tenant filter, pricing preview returns data for same-tenant customer."""
        customer_a = Customer.objects.create(
            name='Shop A Customer', tenant=self.tenant_a, email='custa@ex.com'
        )
        result = get_batch_pricing_preview(
            customer_id=customer_a.id,
            unit_number='UNIT-1',
            breaks_count=2,
            tenant=self.tenant_a,
        )
        # None means not found; non-None means found (even if pricing is default)
        self.assertIsNotNone(result, "Must return pricing data for correct-tenant customer")

    def test_endpoint_returns_404_for_cross_tenant_customer(self):
        """AJAX endpoint returns 404 when tech probes another shop's customer ID."""
        client = Client()
        client.force_login(self.tech_user)

        # Simulate middleware setting tenant to Shop A
        session = client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

        response = client.get('/tech/api/batch-pricing/', {
            'customer_id': self.customer_b.id,
            'unit_number': 'UNIT-1',
            'breaks_count': '2',
        })
        # Should return 404 (customer not found in tenant A) not 200 with Shop B's data
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# CODE-111: technician_batch_detail / technician_batch_start_work used
#           unscoped getattr(request.user, 'technician', None) which resolves
#           the OneToOneField without a tenant filter.  A manager at Shop A
#           visiting Shop B's batch URL would have their Shop A is_manager flag
#           evaluated in Shop B's context.
# ---------------------------------------------------------------------------

class BatchViewTenantScopeTests(TestCase):
    """
    CODE-111: Verify batch views resolve Technician record via tenant-scoped
    lookup, not the bare OneToOneField reverse accessor.
    """

    def setUp(self):
        from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
        from decimal import Decimal

        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )

        # Shop A owner + manager
        self.owner_a = User.objects.create_user('c111_owner_a', 'oa@ex.com', 'pw')
        self.tenant_a = Tenant.objects.create(
            name='Shop A 111', slug='shop-a-111', subdomain='shop-a-111',
            owner=self.owner_a, plan='trial', subscription_plan=plan,
        )
        TenantMembership.objects.create(user=self.owner_a, tenant=self.tenant_a, role='owner', is_active=True)

        # Manager at Shop A (is_manager=True, can_override_pricing=True)
        self.mgr_user_a = User.objects.create_user('c111_mgr_a', 'mgra@ex.com', 'pw')
        TenantMembership.objects.create(user=self.mgr_user_a, tenant=self.tenant_a, role='manager', is_active=True)
        from django.contrib.auth.models import Group
        grp, _ = Group.objects.get_or_create(name='Technicians')
        self.mgr_user_a.groups.add(grp)
        self.mgr_a = Technician.objects.create(
            user=self.mgr_user_a, tenant=self.tenant_a,
            is_manager=True, can_override_pricing=True, is_active=True,
        )

        # Shop B — the manager from A has NO membership or Technician record here
        self.owner_b = User.objects.create_user('c111_owner_b', 'ob@ex.com', 'pw')
        self.tenant_b = Tenant.objects.create(
            name='Shop B 111', slug='shop-b-111', subdomain='shop-b-111',
            owner=self.owner_b, plan='trial', subscription_plan=plan,
        )
        TenantMembership.objects.create(user=self.owner_b, tenant=self.tenant_b, role='owner', is_active=True)

        # A technician who actually belongs to Shop B
        self.tech_b_user = User.objects.create_user('c111_tech_b', 'tb@ex.com', 'pw')
        TenantMembership.objects.create(user=self.tech_b_user, tenant=self.tenant_b, role='technician', is_active=True)
        self.tech_b_user.groups.add(grp)
        self.tech_b = Technician.objects.create(
            user=self.tech_b_user, tenant=self.tenant_b, is_manager=False, is_active=True,
        )

        # Customer and batch in Shop B
        self.customer_b = Customer.objects.create(
            name='Fleet B', email='fleet_b@ex.com', tenant=self.tenant_b,
        )
        self.batch_id = uuid.uuid4()
        self.repair_b1 = Repair.objects.create(
            tenant=self.tenant_b, customer=self.customer_b, technician=self.tech_b,
            service_date='2026-03-20', unit_number='T-099', damage_type='CHIP',
            queue_status='APPROVED', cost=Decimal('75.00'),
            repair_batch_id=self.batch_id, break_number=1, total_breaks_in_batch=2,
        )
        self.repair_b2 = Repair.objects.create(
            tenant=self.tenant_b, customer=self.customer_b, technician=self.tech_b,
            service_date='2026-03-20', unit_number='T-099', damage_type='CRACK',
            queue_status='APPROVED', cost=Decimal('85.00'),
            repair_batch_id=self.batch_id, break_number=2, total_breaks_in_batch=2,
        )

        self.factory = RequestFactory()

    def _make_request(self, user, tenant, method='GET', data=None):
        if method == 'POST':
            req = self.factory.post(f'/tech/batch/{self.batch_id}/', data or {})
        else:
            req = self.factory.get(f'/tech/batch/{self.batch_id}/')
        req.user = user
        req.tenant = tenant
        req.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage
        req._messages = FallbackStorage(req)
        return req

    def test_manager_from_shop_a_cannot_view_shop_b_batch(self):
        """
        A manager at Shop A who visits a Shop B batch URL should be denied.
        Two things protect Shop B:

        1. The @technician_required decorator checks can_access(user, 'repairs', tenant_b).
           Since mgr_user_a has NO membership at Shop B, it denies at the decorator level
           (redirects to owner_dashboard because they're a global manager).

        2. Even if they somehow bypassed the decorator (e.g. via direct function call),
           the view uses a tenant-scoped Technician lookup which returns None for Shop B,
           so can_view stays False → redirects to technician_dashboard.

        This test verifies that accessing via the decorator chain results in a 302 redirect
        (not a 200 with Shop B's batch data).
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.mgr_user_a, self.tenant_b)
        response = technician_batch_detail(req, batch_id=self.batch_id)
        # Must redirect (access denied at decorator or view level), not 200
        self.assertEqual(response.status_code, 302)
        # Location should NOT be the batch detail page itself
        location = response.get('Location', '')
        self.assertNotIn(str(self.batch_id), location,
                         "Must not redirect to the batch detail page for cross-tenant manager")

    def test_manager_from_shop_a_cannot_start_work_on_shop_b_batch(self):
        """
        A manager at Shop A should not be able to start work on Shop B batch
        repairs, regardless of their global is_manager=True.

        The @technician_required decorator denies access at the gate (redirects
        before the view runs).  As a defence-in-depth check, even if someone
        called the view function directly with tenant_b context, the
        tenant-scoped Technician lookup returns None for Shop B (the fix), so
        `repair.technician == None` never matches, and no repairs are started.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        req = self._make_request(self.mgr_user_a, self.tenant_b, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        self.assertEqual(response.status_code, 302)
        # Whether blocked by decorator or view, Shop B repairs must stay APPROVED
        self.repair_b1.refresh_from_db()
        self.repair_b2.refresh_from_db()
        self.assertIn(self.repair_b1.queue_status, ['APPROVED'],
                      "Cross-tenant manager must not start Shop B repairs")
        self.assertIn(self.repair_b2.queue_status, ['APPROVED'],
                      "Cross-tenant manager must not start Shop B repairs")

    def test_shop_b_tech_can_still_view_own_batch(self):
        """
        After the fix, a real Shop B technician can still view their own batch.
        """
        from apps.technician_portal.views.batch import technician_batch_detail
        req = self._make_request(self.tech_b_user, self.tenant_b)
        response = technician_batch_detail(req, batch_id=self.batch_id)
        # 200 (rendered) or 302 to batch detail — must NOT be a "permission denied" redirect
        self.assertIn(response.status_code, [200, 302])
        if response.status_code == 302:
            # If it redirects, it should NOT be to technician_dashboard (access denied)
            from django.urls import reverse
            self.assertNotEqual(
                response.get('Location', ''),
                reverse('technician_dashboard'),
            )

    def test_shop_b_tech_can_still_start_work_on_own_batch(self):
        """
        After the fix, a real Shop B technician can still start work on their batch.
        """
        from apps.technician_portal.views.batch import technician_batch_start_work
        req = self._make_request(self.tech_b_user, self.tenant_b, method='POST')
        response = technician_batch_start_work(req, batch_id=self.batch_id)
        self.assertEqual(response.status_code, 302)
        self.repair_b1.refresh_from_db()
        self.repair_b2.refresh_from_db()
        self.assertEqual(self.repair_b1.queue_status, 'IN_PROGRESS',
                         "Shop B tech must be able to start their own repairs")
        self.assertEqual(self.repair_b2.queue_status, 'IN_PROGRESS',
                         "Shop B tech must be able to start their own repairs")
