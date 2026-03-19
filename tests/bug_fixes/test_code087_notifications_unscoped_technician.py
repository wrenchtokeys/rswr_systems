"""
Regression tests for CODE-087:
Unscoped request.user.technician in notification views.

Root cause:
  All notification views (notification_preferences, notification_history,
  mark_notification_read, mark_all_read, get_unread_count, verify_email,
  verify_phone, confirm_phone_verification) used the bare
  `request.user.technician` (OneToOneField reverse accessor).

  Since Technician is a OneToOneField → User, Django resolves whichever
  Technician record exists for the user globally. A user who is a Technician
  at Shop A with a TenantMembership at Shop B would have ALL their
  notification views in Shop B's portal operate against Shop A's Technician
  record:
    - get_unread_count: returns Shop A tech's unread notifications on Shop B's bell
    - mark_all_read: marks Shop A's notifications read while in Shop B
    - notification_preferences: loads Shop A's notification pref form in Shop B
    - verify_email/phone: marks email/phone_verified on Shop A's record
    - confirm_phone_verification: updates phone_verified on wrong tenant's record

Fix (CODE-087):
  Extracted _get_technician_for_tenant(request) helper that uses
  Technician.objects.filter(user=request.user, tenant=tenant).first()
  when request.tenant is present. Falls back to request.user.technician
  only when no tenant context. All 8 views now call this helper.

  Also: get_unread_count cache key now includes tenant PK to prevent
  cross-tenant cache collisions.

Test scenarios:
  A. Cross-tenant user: _get_technician_for_tenant returns None at Shop B
  B. Same-tenant user: _get_technician_for_tenant returns correct record
  C. notification_preferences with cross-tenant user → redirects (no 500)
  D. notification_preferences with correct tenant → 200
  E. mark_notification_read: scoped user can mark their own notification read
  F. mark_notification_read: cross-tenant user cannot mark other shop's notification
  G. mark_all_read: returns 0 count for user with no notifications at current tenant
  H. get_unread_count: cross-tenant user gets 0 count (not another shop's count)
  I. get_unread_count: cache key includes tenant pk to prevent collisions
"""

import json
import uuid
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.contenttypes.models import ContentType
from unittest.mock import patch

from core.models import Notification
from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.views.notifications import _get_technician_for_tenant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_messages(request):
    setattr(request, 'session', {})
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)
    return request


def _make_user(username):
    return User.objects.create_user(username=username, password='test', email=f'{username}@test.com')


def _make_tenant(name):
    import uuid
    slug = uuid.uuid4().hex[:10]
    owner = _make_user(f'owner_{slug}')
    return Tenant.objects.create(name=name, slug=slug, subdomain=slug, owner=owner, is_active=True)


def _make_technician(user, tenant):
    return Technician.objects.create(user=user, tenant=tenant)


def _add_membership(user, tenant, role='technician'):
    TenantMembership.objects.get_or_create(
        user=user, tenant=tenant,
        defaults={'role': role, 'is_active': True}
    )


def _make_notification(tech):
    """Create a test notification for a technician."""
    technician_ct = ContentType.objects.get_for_model(Technician)
    return Notification.objects.create(
        title='Test Notification',
        message='Test message',
        recipient_type=technician_ct,
        recipient_id=tech.id,
        read=False,
    )


# ---------------------------------------------------------------------------
# Unit tests: _get_technician_for_tenant helper
# ---------------------------------------------------------------------------

class GetTechnicianForTenantHelperTests(TestCase):
    """Test the _get_technician_for_tenant helper directly."""

    def setUp(self):
        self.factory = RequestFactory()
        self.shop_a = _make_tenant('Shop A')
        self.shop_b = _make_tenant('Shop B')
        self.user = _make_user('tech_user')
        # User is a Technician at Shop A only
        self.tech_a = _make_technician(self.user, self.shop_a)
        _add_membership(self.user, self.shop_a, 'technician')
        # User has membership at Shop B but NO Technician record there
        _add_membership(self.user, self.shop_b, 'technician')

    def _request(self, tenant=None):
        req = self.factory.get('/')
        req.user = self.user
        req.tenant = tenant
        return req

    def test_returns_correct_tech_at_home_tenant(self):
        """Scoped lookup returns Shop A's Technician when tenant=Shop A."""
        req = self._request(tenant=self.shop_a)
        result = _get_technician_for_tenant(req)
        self.assertEqual(result, self.tech_a)

    def test_returns_none_at_foreign_tenant(self):
        """Cross-tenant user gets None at Shop B (no Technician record there)."""
        req = self._request(tenant=self.shop_b)
        result = _get_technician_for_tenant(req)
        self.assertIsNone(result)

    def test_fallback_when_no_tenant(self):
        """No tenant context → falls back to user.technician (Shop A's record)."""
        req = self._request(tenant=None)
        result = _get_technician_for_tenant(req)
        self.assertEqual(result, self.tech_a)

    def test_none_when_no_tenant_and_no_tech_record(self):
        """User with no Technician record at all → returns None (no AttributeError)."""
        plain_user = _make_user('plain_user')
        req = self._request(tenant=None)
        req.user = plain_user
        result = _get_technician_for_tenant(req)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# View tests: notification_preferences
# ---------------------------------------------------------------------------

class NotificationPreferencesTenantScopeTests(TestCase):
    """notification_preferences view uses tenant-scoped technician lookup."""

    def setUp(self):
        self.factory = RequestFactory()
        self.shop_a = _make_tenant('NP Shop A')
        self.shop_b = _make_tenant('NP Shop B')
        self.user = _make_user('np_user')
        self.tech_a = _make_technician(self.user, self.shop_a)
        _add_membership(self.user, self.shop_a, 'technician')
        _add_membership(self.user, self.shop_b, 'technician')

    def _make_request(self, tenant, method='GET', data=None):
        from apps.technician_portal.views.notifications import notification_preferences
        factory_method = getattr(self.factory, method.lower())
        req = factory_method('/', data=data or {})
        req.user = self.user
        req.tenant = tenant
        _add_messages(req)
        return req, notification_preferences

    def test_cross_tenant_user_redirects_not_500(self):
        """Cross-tenant user (no Technician at Shop B) → redirect, not 500."""
        req, view = self._make_request(self.shop_b)
        response = view(req)
        self.assertEqual(response.status_code, 302)

    def test_correct_tenant_user_gets_200(self):
        """Same-tenant user with Technician record → 200 response."""
        from core.models import TechnicianNotificationPreference
        req, view = self._make_request(self.shop_a)
        response = view(req)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# View tests: mark_notification_read
# ---------------------------------------------------------------------------

class MarkNotificationReadTenantScopeTests(TestCase):
    """mark_notification_read only marks notifications belonging to the current-tenant tech."""

    def setUp(self):
        self.factory = RequestFactory()
        self.shop_a = _make_tenant('MR Shop A')
        self.shop_b = _make_tenant('MR Shop B')
        self.user_a = _make_user('mr_user_a')
        self.user_b = _make_user('mr_user_b')
        self.tech_a = _make_technician(self.user_a, self.shop_a)
        self.tech_b = _make_technician(self.user_b, self.shop_b)
        _add_membership(self.user_a, self.shop_a)
        _add_membership(self.user_b, self.shop_b)
        # Create notifications for each tech
        self.notif_a = _make_notification(self.tech_a)
        self.notif_b = _make_notification(self.tech_b)

    def _make_request(self, user, tenant, notification_id):
        from apps.technician_portal.views.notifications import mark_notification_read
        req = self.factory.post(f'/', {})
        req.user = user
        req.tenant = tenant
        _add_messages(req)
        return mark_notification_read(req, notification_id)

    def test_user_can_mark_own_notification_read(self):
        """Tech A can mark their own notification read at Shop A."""
        response = self._make_request(self.user_a, self.shop_a, self.notif_a.id)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.notif_a.refresh_from_db()
        self.assertTrue(self.notif_a.read)

    def test_cross_tenant_user_cannot_mark_other_shop_notification(self):
        """User A at Shop B (no Technician there) cannot mark Shop B's notifications."""
        # user_a has no technician record at shop_b
        response = self._make_request(self.user_a, self.shop_b, self.notif_b.id)
        # Should get 404 (technician not found at shop_b)
        self.assertEqual(response.status_code, 404)
        # Notification should remain unread
        self.notif_b.refresh_from_db()
        self.assertFalse(self.notif_b.read)


# ---------------------------------------------------------------------------
# View tests: mark_all_read
# ---------------------------------------------------------------------------

class MarkAllReadTenantScopeTests(TestCase):
    """mark_all_read scopes to current tenant's Technician record."""

    def setUp(self):
        self.factory = RequestFactory()
        self.shop_a = _make_tenant('MAR Shop A')
        self.shop_b = _make_tenant('MAR Shop B')
        self.user = _make_user('mar_user')
        self.tech_a = _make_technician(self.user, self.shop_a)
        _add_membership(self.user, self.shop_a)
        _add_membership(self.user, self.shop_b)
        # Create unread notifications for tech_a
        self.notif1 = _make_notification(self.tech_a)
        self.notif2 = _make_notification(self.tech_a)

    def _mark_all(self, tenant):
        from apps.technician_portal.views.notifications import mark_all_read
        req = self.factory.post('/')
        req.user = self.user
        req.tenant = tenant
        _add_messages(req)
        return mark_all_read(req)

    def test_mark_all_at_home_tenant_marks_notifications(self):
        """mark_all_read at Shop A marks Shop A's tech's notifications."""
        response = self._mark_all(self.shop_a)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 2)
        self.notif1.refresh_from_db()
        self.notif2.refresh_from_db()
        self.assertTrue(self.notif1.read)
        self.assertTrue(self.notif2.read)

    def test_mark_all_at_foreign_tenant_returns_error(self):
        """mark_all_read at Shop B (no Technician there) returns 404."""
        response = self._mark_all(self.shop_b)
        self.assertEqual(response.status_code, 404)
        # Notifications should NOT be marked read
        self.notif1.refresh_from_db()
        self.assertFalse(self.notif1.read)


# ---------------------------------------------------------------------------
# View tests: get_unread_count
# ---------------------------------------------------------------------------

class GetUnreadCountTenantScopeTests(TestCase):
    """get_unread_count returns correct count scoped to current tenant."""

    def setUp(self):
        self.factory = RequestFactory()
        self.shop_a = _make_tenant('GUC Shop A')
        self.shop_b = _make_tenant('GUC Shop B')
        self.user = _make_user('guc_user')
        self.tech_a = _make_technician(self.user, self.shop_a)
        _add_membership(self.user, self.shop_a)
        _add_membership(self.user, self.shop_b)
        # 3 unread notifications for tech_a
        for _ in range(3):
            _make_notification(self.tech_a)

    def _get_count(self, tenant):
        from apps.technician_portal.views.notifications import get_unread_count
        from django.core.cache import cache
        cache.clear()
        req = self.factory.get('/')
        req.user = self.user
        req.tenant = tenant
        _add_messages(req)
        return get_unread_count(req)

    def test_count_at_home_tenant_returns_correct_number(self):
        """Tech A at Shop A sees their 3 unread notifications."""
        response = self._get_count(self.shop_a)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 3)

    def test_cross_tenant_user_sees_zero_count(self):
        """User at Shop B (no Technician there) sees 0, not Shop A's 3."""
        response = self._get_count(self.shop_b)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['count'], 0)

    def test_cache_key_includes_tenant(self):
        """Cache key includes tenant PK to prevent cross-tenant collisions."""
        from apps.technician_portal.views.notifications import get_unread_count
        from django.core.cache import cache
        cache.clear()

        # Call at Shop A — caches with shop_a pk
        req_a = self.factory.get('/')
        req_a.user = self.user
        req_a.tenant = self.shop_a
        _add_messages(req_a)
        get_unread_count(req_a)

        # Call at Shop B — different tenant, should NOT get cached Shop A value
        req_b = self.factory.get('/')
        req_b.user = self.user
        req_b.tenant = self.shop_b
        _add_messages(req_b)
        response_b = get_unread_count(req_b)
        data_b = json.loads(response_b.content)
        # Should be 0 (no tech at shop_b), not 3 (from shop_a cache)
        self.assertEqual(data_b['count'], 0)
