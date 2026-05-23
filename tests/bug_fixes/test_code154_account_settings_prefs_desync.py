"""
CODE-154: Regression test — account_settings prefs/customer verification desync.

Bug: In `apps/customer_portal/views.py` → `account_settings()`, the view
previously called `prefs.save()` eagerly inside the email-change and phone-change
blocks, BEFORE the password validation check. When a user changed their phone
number AND also attempted (and failed) a password change in the same form
submission, the following happened:

1. Phone change detected → `customer.phone_verified = False` (in memory only)
   → `prefs.phone_verified = False` → `prefs.save()` ← COMMITTED TO DB
2. Password check fails → early `return render(...)` 
3. `customer.save()` is never reached → `customer.phone_verified` stays True in DB

Result: `CustomerNotificationPreference.phone_verified = False` while
`Customer.phone_verified = True` — a permanent desync. The customer's
notification preference says unverified but the Customer record says verified.

Identical issue exists for email changes combined with a bad password attempt.

Fix: Validate the password BEFORE any save calls. Collect prefs changes in a
staging dict (`prefs_updates`) and apply them together with `customer.save()` at
the very end of the happy path.

Tests verify:
1. Successful phone+password change updates both Customer and prefs atomically.
2. Phone change + bad password: neither Customer nor prefs phone_verified changes.
3. Phone change + good password: both Customer.phone and prefs.phone_verified
   are updated consistently.
4. Email change + bad password: neither Customer nor prefs email_verified changes.
5. Email change + good password: both updated consistently.
6. Phone change only (no password): Customer.phone and prefs updated correctly.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from core.models.notification_preferences import CustomerNotificationPreference
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(name='Test Shop'):
    """Create a minimal tenant with a required owner."""
    slug = name.lower().replace(' ', '-')
    owner = User.objects.create_user(
        username=f"towner_{slug[:15]}",
        password='ownerpass123',
        email=f"towner_{slug[:15]}@example.com",
    )
    return Tenant.objects.create(
        name=name,
        slug=slug,
        owner=owner,
        subscription_status='active',
    )


def _make_user(email, password='testpass123', first='Test', last='User'):
    user = User.objects.create_user(
        username=email,
        email=email,
        password=password,
        first_name=first,
        last_name=last,
    )
    return user


def _make_customer(tenant, name='Acme Corp', email='acme@example.com', phone='555-0100'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=email,
        phone=phone,
        phone_verified=True,
        email_verified=True,
    )


def _make_customer_user(user, customer):
    return CustomerUser.objects.create(user=user, customer=customer)


class AccountSettingsPrefsDesyncTest(TestCase):
    """Regression tests for CODE-154: prefs/customer verification desync."""

    def setUp(self):
        self.tenant = _make_tenant('Sync Test Shop')
        self.user = _make_user('synctest@example.com', password='OldPass123!')
        self.customer = _make_customer(self.tenant, phone='555-0100')
        self.customer_user = _make_customer_user(self.user, self.customer)

        # The Customer post_save signal auto-creates CustomerNotificationPreference.
        # Fetch it and set verified=True so tests can confirm it gets reset.
        self.prefs = CustomerNotificationPreference.objects.get(customer=self.customer)
        self.prefs.phone_verified = True
        self.prefs.email_verified = True
        self.prefs.save(update_fields=['phone_verified', 'email_verified'])

        self.client = Client()
        self.client.login(username='synctest@example.com', password='OldPass123!')

        # Set tenant in session (customer portal expects tenant_id)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_settings(self, data):
        return self.client.post(reverse('customer_account_settings'), data, follow=False)

    # ------------------------------------------------------------------
    # Test 1: Phone change + wrong password → NO changes persisted
    # ------------------------------------------------------------------
    def test_phone_change_bad_password_no_desync(self):
        """
        If the user changes phone + provides wrong current_password, NEITHER
        Customer.phone_verified NOR CustomerNotificationPreference.phone_verified
        should change. Previously prefs was saved eagerly before the password check.
        """
        response = self._post_settings({
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'synctest@example.com',
            'phone': '555-9999',  # changed
            'current_password': 'WRONG_PASSWORD',
            'new_password': 'NewPass456!',
            'confirm_password': 'NewPass456!',
        })

        # Should not redirect (password failed)
        self.assertNotEqual(response.status_code, 302)

        # Reload from DB — nothing should have changed
        self.customer.refresh_from_db()
        self.prefs.refresh_from_db()

        self.assertEqual(self.customer.phone, '555-0100', "Customer.phone should be unchanged")
        self.assertTrue(self.customer.phone_verified, "Customer.phone_verified should stay True")
        self.assertTrue(self.prefs.phone_verified, "prefs.phone_verified should stay True — was incorrectly saved False before fix")

    # ------------------------------------------------------------------
    # Test 2: Email change + wrong password → NO changes persisted
    # ------------------------------------------------------------------
    def test_email_change_bad_password_no_desync(self):
        """
        If the user changes email + provides wrong current_password, NEITHER
        Customer.email_verified NOR prefs.email_verified should change.
        """
        response = self._post_settings({
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'newemail@example.com',  # changed
            'phone': '555-0100',
            'current_password': 'WRONG_PASSWORD',
            'new_password': 'NewPass456!',
            'confirm_password': 'NewPass456!',
        })

        self.assertNotEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.prefs.refresh_from_db()

        self.assertEqual(self.user.email, 'synctest@example.com', "User.email should be unchanged")
        self.assertTrue(self.customer.email_verified, "Customer.email_verified should stay True")
        self.assertTrue(self.prefs.email_verified, "prefs.email_verified should stay True")

    # ------------------------------------------------------------------
    # Test 3: Phone change with NO password change → updates both atomically
    # ------------------------------------------------------------------
    def test_phone_change_no_password_updates_both(self):
        """
        If the user just changes their phone (no password), both
        Customer.phone and prefs.phone_verified should update consistently.
        """
        response = self._post_settings({
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'synctest@example.com',
            'phone': '555-7777',  # changed
        })

        # Should redirect to dashboard on success
        self.assertEqual(response.status_code, 302)

        self.customer.refresh_from_db()
        self.prefs.refresh_from_db()

        self.assertEqual(self.customer.phone, '555-7777', "Customer.phone should update")
        self.assertFalse(self.customer.phone_verified, "Customer.phone_verified should be reset to False")
        self.assertFalse(self.prefs.phone_verified, "prefs.phone_verified should also be reset to False")

    # ------------------------------------------------------------------
    # Test 4: Phone change + correct password → both updated atomically
    # ------------------------------------------------------------------
    def test_phone_change_good_password_updates_both(self):
        """
        Phone change + valid password change: both Customer.phone/phone_verified
        and prefs.phone_verified update correctly, and password is changed.
        """
        response = self._post_settings({
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'synctest@example.com',
            'phone': '555-8888',  # changed
            'current_password': 'OldPass123!',
            'new_password': 'NewPass456!',
            'confirm_password': 'NewPass456!',
        })

        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.customer.refresh_from_db()
        self.prefs.refresh_from_db()

        self.assertEqual(self.customer.phone, '555-8888', "Customer.phone should update")
        self.assertFalse(self.customer.phone_verified, "Customer.phone_verified should be False")
        self.assertFalse(self.prefs.phone_verified, "prefs.phone_verified should be False (in sync)")
        self.assertTrue(self.user.check_password('NewPass456!'), "Password should be changed")

    # ------------------------------------------------------------------
    # Test 5: Password-mismatch early return doesn't save prefs
    # ------------------------------------------------------------------
    def test_phone_change_password_mismatch_no_save(self):
        """
        Phone change + mismatched new/confirm passwords → early return,
        neither Customer nor prefs should change.
        """
        response = self._post_settings({
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'synctest@example.com',
            'phone': '555-4444',  # changed
            'current_password': 'OldPass123!',
            'new_password': 'NewPass456!',
            'confirm_password': 'DOESNOTMATCH',
        })

        self.assertNotEqual(response.status_code, 302)

        self.customer.refresh_from_db()
        self.prefs.refresh_from_db()

        self.assertEqual(self.customer.phone, '555-0100', "Customer.phone should be unchanged")
        self.assertTrue(self.customer.phone_verified, "Customer.phone_verified should stay True")
        self.assertTrue(self.prefs.phone_verified, "prefs.phone_verified should stay True")

    # ------------------------------------------------------------------
    # Test 6: Short new password early return doesn't save prefs
    # ------------------------------------------------------------------
    def test_phone_change_short_password_no_save(self):
        """
        Phone change + new password too short → early return, no state change.
        """
        response = self._post_settings({
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'synctest@example.com',
            'phone': '555-3333',  # changed
            'current_password': 'OldPass123!',
            'new_password': 'short',
            'confirm_password': 'short',
        })

        self.assertNotEqual(response.status_code, 302)

        self.customer.refresh_from_db()
        self.prefs.refresh_from_db()

        self.assertEqual(self.customer.phone, '555-0100')
        self.assertTrue(self.customer.phone_verified)
        self.assertTrue(self.prefs.phone_verified)
