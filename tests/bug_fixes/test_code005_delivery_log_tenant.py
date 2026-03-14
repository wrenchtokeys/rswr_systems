"""
Regression tests for CODE-005 — NotificationDeliveryLog has no tenant FK

Before fix: NotificationDeliveryLog had no way to associate a log entry with a
tenant, making superadmin audit views show all logs mixed together.

After fix:
- NotificationDeliveryLog.tenant is a nullable FK to Tenant
- save() auto-populates tenant from notification.recipient (Technician or CustomerUser)
- Admin list_filter includes 'tenant'
"""
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from unittest.mock import patch

from core.models import Notification
from core.models.notification_delivery_log import NotificationDeliveryLog

User = get_user_model()

_tenant_counter = 0


def _make_tenant(name="Test Shop"):
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


def _make_customer_user(tenant, username="custuser1"):
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
        tenant = _make_tenant("Explicit Tenant")
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
        tenant = _make_tenant("Tech Tenant")
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
        tenant = _make_tenant("Customer Tenant")
        cu = _make_customer_user(tenant, username="auto_cu1")
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
        tenant_a = _make_tenant("Tenant A")
        tenant_b = _make_tenant("Tenant B")
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
        tenant_x = _make_tenant("Shop X")
        tenant_y = _make_tenant("Shop Y")
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
        tenant = _make_tenant("Safe Tenant")
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
