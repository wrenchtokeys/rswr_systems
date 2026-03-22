"""
CODE-145: Regression test — Missing admin registrations for PlatformConfig,
PlatformFeeRecord, and TechnicianNotification.

Bug: Three models had no Django admin registration:
  1. PlatformConfig (billing) — global singleton for Stripe Connect fee settings
  2. PlatformFeeRecord (billing) — per-tenant audit log of collected fees, has tenant FK
  3. TechnicianNotification (technician_portal) — in-app notifications, reachable via technician → tenant

Impact:
  - Superusers could not view or audit fee collection records from admin
  - PlatformConfig fee rate was not editable without a Django shell
  - Technician notification delivery could not be debugged from admin
  - PlatformFeeRecord had a tenant FK but no tenant-scoped admin filtering

Fix: Added PlatformConfigAdmin (singleton, superuser-only),
     PlatformFeeRecordAdmin (TenantFilterMixin, read-only),
     and TechnicianNotificationAdmin (TechnicianTenantFilterMixin, read-only with read/unread actions).

Tests verify:
1. All three models are registered in Django admin.
2. PlatformConfig is accessible as singleton — has_add_permission blocked when record exists.
3. PlatformFeeRecord is read-only (no add/change permission).
4. TechnicianNotification is read-only with mark_as_read / mark_as_unread actions.
5. TechnicianNotification queryset filters to tenant for non-superusers.
6. PlatformFeeRecord queryset filters to tenant for non-superusers.
"""

from django.test import TestCase, RequestFactory, Client
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth.models import User

from apps.billing.models import PlatformConfig, PlatformFeeRecord, Invoice
from apps.technician_portal.models import TechnicianNotification, Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


# =============================================================================
# Helpers
# =============================================================================

def make_superuser(username):
    return User.objects.create_superuser(
        username=username, email=f'{username}@test.com', password='pass'
    )


def make_regular_user(username):
    return User.objects.create_user(
        username=username, email=f'{username}@test.com', password='pass'
    )


def make_tenant(name, owner):
    slug = name.lower().replace(' ', '-')
    return Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        plan='trial',
        owner=owner,
    )


# =============================================================================
# Admin registration tests
# =============================================================================

class AdminRegistrationTest(TestCase):
    """Verify that all three previously-unregistered models now appear in admin."""

    def test_platform_config_is_registered(self):
        self.assertIn(PlatformConfig, admin_site._registry,
                      "PlatformConfig must be registered in Django admin")

    def test_platform_fee_record_is_registered(self):
        self.assertIn(PlatformFeeRecord, admin_site._registry,
                      "PlatformFeeRecord must be registered in Django admin")

    def test_technician_notification_is_registered(self):
        self.assertIn(TechnicianNotification, admin_site._registry,
                      "TechnicianNotification must be registered in Django admin")


# =============================================================================
# PlatformConfig admin permissions
# =============================================================================

class PlatformConfigAdminPermissionsTest(TestCase):
    """PlatformConfig is a superuser-only singleton."""

    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = make_superuser('su_code145_cfg')
        self.regular = make_regular_user('reg_code145_cfg')
        self.model_admin = admin_site._registry[PlatformConfig]

    def _make_request(self, user):
        req = self.factory.get('/')
        req.user = user
        return req

    def test_superuser_can_change(self):
        self.assertTrue(
            self.model_admin.has_change_permission(self._make_request(self.superuser)),
            "Superuser must be able to change PlatformConfig"
        )

    def test_regular_user_cannot_change(self):
        self.assertFalse(
            self.model_admin.has_change_permission(self._make_request(self.regular)),
            "Non-superuser must not be able to change PlatformConfig"
        )

    def test_no_delete_permission(self):
        cfg = PlatformConfig.get()
        self.assertFalse(
            self.model_admin.has_delete_permission(self._make_request(self.superuser), cfg),
            "PlatformConfig must not be deletable — it's a singleton"
        )

    def test_add_blocked_when_record_exists(self):
        PlatformConfig.get()  # ensure singleton exists
        self.assertFalse(
            self.model_admin.has_add_permission(self._make_request(self.superuser)),
            "has_add_permission must be False when PlatformConfig already exists"
        )

    def test_add_allowed_when_no_record(self):
        PlatformConfig.objects.all().delete()
        self.assertTrue(
            self.model_admin.has_add_permission(self._make_request(self.superuser)),
            "has_add_permission must be True when no PlatformConfig record exists"
        )


# =============================================================================
# PlatformFeeRecord admin permissions and tenant filtering
# =============================================================================

class PlatformFeeRecordAdminTest(TestCase):
    """PlatformFeeRecord is read-only; non-superusers see only their tenant's records."""

    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = make_superuser('su_code145_fee')

        owner_a = make_regular_user('owner_a_145')
        owner_b = make_regular_user('owner_b_145')
        self.tenant_a = make_tenant('Shop A 145', owner_a)
        self.tenant_b = make_tenant('Shop B 145', owner_b)

        self.user_a = make_regular_user('user_a_145')
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.user_a, is_active=True)

        # Create a minimal invoice for each tenant so PlatformFeeRecord FK is valid.
        # We need a Customer for invoice.
        self.customer_a = Customer.objects.create(
            name='Cust A 145', tenant=self.tenant_a
        )
        self.customer_b = Customer.objects.create(
            name='Cust B 145', tenant=self.tenant_b
        )
        self.invoice_a = Invoice.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            invoice_number='INV-A-145',
            subtotal='100.00',
            total='100.00',
        )
        self.invoice_b = Invoice.objects.create(
            tenant=self.tenant_b,
            customer=self.customer_b,
            invoice_number='INV-B-145',
            subtotal='200.00',
            total='200.00',
        )

        self.fee_a = PlatformFeeRecord.objects.create(
            tenant=self.tenant_a,
            invoice=self.invoice_a,
            payment_intent_id='pi_test_a',
            gross_amount='100.00',
            fee_amount='2.50',
            fee_percent='2.50',
            stripe_account_id='acct_a',
        )
        self.fee_b = PlatformFeeRecord.objects.create(
            tenant=self.tenant_b,
            invoice=self.invoice_b,
            payment_intent_id='pi_test_b',
            gross_amount='200.00',
            fee_amount='5.00',
            fee_percent='2.50',
            stripe_account_id='acct_b',
        )

        self.model_admin = admin_site._registry[PlatformFeeRecord]

    def _make_request(self, user):
        req = self.factory.get('/')
        req.user = user
        return req

    def test_no_add_permission(self):
        req = self._make_request(self.superuser)
        self.assertFalse(
            self.model_admin.has_add_permission(req),
            "PlatformFeeRecord must not be manually addable"
        )

    def test_no_change_permission(self):
        req = self._make_request(self.superuser)
        self.assertFalse(
            self.model_admin.has_change_permission(req, self.fee_a),
            "PlatformFeeRecord must not be editable"
        )

    def test_superuser_sees_all_tenants(self):
        req = self._make_request(self.superuser)
        qs = self.model_admin.get_queryset(req)
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.fee_a.pk, pks)
        self.assertIn(self.fee_b.pk, pks)

    def test_non_superuser_sees_own_tenant_only(self):
        req = self._make_request(self.user_a)
        qs = self.model_admin.get_queryset(req)
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.fee_a.pk, pks,
                      "user_a should see tenant_a's fee records")
        self.assertNotIn(self.fee_b.pk, pks,
                         "user_a must not see tenant_b's fee records")


# =============================================================================
# TechnicianNotification admin permissions and tenant filtering
# =============================================================================

class TechnicianNotificationAdminTest(TestCase):
    """TechnicianNotification is read-only; non-superusers see only their tenant's notifications."""

    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = make_superuser('su_code145_notif')

        owner_x_user = make_regular_user('owner_x_145')
        owner_y_user = make_regular_user('owner_y_145')
        self.tenant_x = make_tenant('Shop X 145', owner_x_user)
        self.tenant_y = make_tenant('Shop Y 145', owner_y_user)

        self.owner_x = owner_x_user
        TenantMembership.objects.create(tenant=self.tenant_x, user=self.owner_x, is_active=True)

        tech_user_x = make_regular_user('tech_x_145')
        self.tech_x = Technician.objects.create(
            user=tech_user_x, tenant=self.tenant_x, phone_number='555-1001'
        )

        tech_user_y = make_regular_user('tech_y_145')
        self.tech_y = Technician.objects.create(
            user=tech_user_y, tenant=self.tenant_y, phone_number='555-1002'
        )

        self.notif_x = TechnicianNotification.objects.create(
            technician=self.tech_x,
            message='Repair approved for unit ABC',
        )
        self.notif_y = TechnicianNotification.objects.create(
            technician=self.tech_y,
            message='Repair approved for unit XYZ',
        )

        self.model_admin = admin_site._registry[TechnicianNotification]

    def _make_request(self, user):
        req = self.factory.get('/')
        req.user = user
        return req

    def test_no_add_permission(self):
        req = self._make_request(self.superuser)
        self.assertFalse(
            self.model_admin.has_add_permission(req),
            "TechnicianNotification must not be manually addable"
        )

    def test_no_change_permission(self):
        req = self._make_request(self.superuser)
        self.assertFalse(
            self.model_admin.has_change_permission(req, self.notif_x),
            "TechnicianNotification must not be editable"
        )

    def test_superuser_sees_all_tenants(self):
        req = self._make_request(self.superuser)
        qs = self.model_admin.get_queryset(req)
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.notif_x.pk, pks)
        self.assertIn(self.notif_y.pk, pks)

    def test_non_superuser_sees_own_tenant_only(self):
        req = self._make_request(self.owner_x)
        qs = self.model_admin.get_queryset(req)
        pks = list(qs.values_list('pk', flat=True))
        self.assertIn(self.notif_x.pk, pks,
                      "owner_x should see tenant_x's notifications")
        self.assertNotIn(self.notif_y.pk, pks,
                         "owner_x must not see tenant_y's notifications")

    def test_mark_as_read_action(self):
        """mark_as_read action should flip read=False → True.

        Use the Django test Client (which includes message middleware) rather
        than RequestFactory, so self.message_user() doesn't raise
        MessageFailure about missing middleware.
        """
        self.assertFalse(self.notif_x.read)
        client = Client()
        client.force_login(self.superuser)
        # POST to the admin changelist with the action + selected IDs
        response = client.post(
            f'/admin/technician_portal/techniciannotification/',
            {
                'action': 'mark_as_read',
                '_selected_action': [str(self.notif_x.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.notif_x.refresh_from_db()
        self.assertTrue(self.notif_x.read)

    def test_mark_as_unread_action(self):
        """mark_as_unread action should flip read=True → False."""
        self.notif_x.read = True
        self.notif_x.save()
        client = Client()
        client.force_login(self.superuser)
        response = client.post(
            f'/admin/technician_portal/techniciannotification/',
            {
                'action': 'mark_as_unread',
                '_selected_action': [str(self.notif_x.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.notif_x.refresh_from_db()
        self.assertFalse(self.notif_x.read)

    def test_message_preview_truncates_long_messages(self):
        """message_preview should truncate messages over 80 chars."""
        long_msg = 'A' * 90
        notif = TechnicianNotification(
            technician=self.tech_x,
            message=long_msg,
        )
        preview = self.model_admin.message_preview(notif)
        self.assertLessEqual(len(preview), 84,  # 80 + '…' (1 char) + some buffer
                             "message_preview should truncate to 80 chars + ellipsis")
        self.assertTrue(preview.endswith('…'))

    def test_message_preview_short_message_unchanged(self):
        """Short messages should pass through unchanged."""
        notif = TechnicianNotification(
            technician=self.tech_x,
            message='Short message.',
        )
        preview = self.model_admin.message_preview(notif)
        self.assertEqual(preview, 'Short message.')

    def test_get_notification_type_repair(self):
        """Notification with repair_id should show 🔧 Repair type."""
        customer = Customer.objects.create(name='Cust Notif 145', tenant=self.tenant_x)
        repair = Repair.objects.create(
            technician=self.tech_x,
            customer=customer,
            tenant=self.tenant_x,
            unit_number='U1',
            damage_type='chip',
            queue_status='PENDING',
            cost='0.00',
        )
        notif = TechnicianNotification(
            technician=self.tech_x,
            message='Test',
            repair=repair,
        )
        type_label = self.model_admin.get_notification_type(notif)
        self.assertIn('Repair', type_label)

    def test_get_notification_type_batch(self):
        """Notification with repair_batch_id should show 📦 Batch type."""
        import uuid
        notif = TechnicianNotification(
            technician=self.tech_x,
            message='Test',
            repair_batch_id=uuid.uuid4(),
        )
        type_label = self.model_admin.get_notification_type(notif)
        self.assertIn('Batch', type_label)

    def test_get_notification_type_general(self):
        """Notification with no FK links should show 📣 General type."""
        notif = TechnicianNotification(
            technician=self.tech_x,
            message='General announcement.',
        )
        type_label = self.model_admin.get_notification_type(notif)
        self.assertIn('General', type_label)
