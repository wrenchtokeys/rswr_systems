"""
CODE-190 regression tests: account_settings() password change must use
Django's validate_password() instead of a bare len() < 8 check.

Bug: `account_settings()` in `apps/customer_portal/views.py` only checked
`len(new_password) < 8`, so common weak passwords like "password1" or
"12345678" were accepted. The fix uses `validate_password(new_password, user=user)`
which enforces the full AUTH_PASSWORD_VALIDATORS chain (min length, common
password list, all-numeric guard).

This mirrors CODE-188 which fixed the same pattern in `customer_register()`
and `accept_customer_invitation()`.
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(name='TestShop190'):
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "")}',
        email=f'owner_{name.lower().replace(" ", "")}@example.com',
        password='OwnerPass123!',
    )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-') + '-190',
        owner=owner,
        subscription_status='active',
    )


def _make_customer(tenant, name='Fleet Co 190'):
    return Customer.objects.create(tenant=tenant, name=name)


def _make_customer_user(tenant, customer, username='cu190', email='cu190@example.com', password='ValidPass999!'):
    user = User.objects.create_user(username=username, email=email, password=password,
                                    first_name='Test', last_name='User')
    TenantMembership.objects.create(user=user, tenant=tenant, role='viewer', is_active=True)
    cu = CustomerUser.objects.create(user=user, customer=customer)
    return cu, user


class AccountSettingsPasswordValidationTests(TestCase):
    """account_settings() must reject weak new passwords via validate_password."""

    def setUp(self):
        self.client = Client()
        self.tenant = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.cu, self.user = _make_customer_user(self.tenant, self.customer)
        self.client.login(username='cu190', password='ValidPass999!')

        # Set tenant in session so middleware resolves it correctly
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_password_change(self, new_password, confirm=None):
        if confirm is None:
            confirm = new_password
        return self.client.post(
            reverse('customer_account_settings'),
            {
                'current_password': 'ValidPass999!',
                'new_password': new_password,
                'confirm_password': confirm,
                # required fields for account_settings — provide defaults
                'first_name': 'Test',
                'last_name': 'User',
                'email': self.user.email,
            },
            follow=False,
        )

    def test_common_password_rejected(self):
        """'password1' is too common — validate_password should block it."""
        self._post_password_change('password1')
        # Should not change the password — user should still authenticate with old pass
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ValidPass999!'),
                        "Common weak password 'password1' should have been rejected")

    def test_numeric_only_password_rejected(self):
        """All-numeric passwords are rejected by Django's validators."""
        self._post_password_change('12345678')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ValidPass999!'),
                        "All-numeric password '12345678' should have been rejected")

    def test_too_short_password_rejected(self):
        """Passwords under the minimum length should be rejected."""
        self._post_password_change('Ab1!')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ValidPass999!'),
                        "Too-short password 'Ab1!' should have been rejected")

    def test_strong_password_accepted(self):
        """A genuinely strong password should be accepted and take effect."""
        self._post_password_change('Zx7$Correct!Horse99')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Zx7$Correct!Horse99'),
                        "Strong password should have been accepted")

    def test_mismatched_passwords_rejected(self):
        """Mismatched confirm password should be rejected before validation."""
        self._post_password_change('Zx7$Correct!Horse99', confirm='different99!')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('ValidPass999!'),
                        "Mismatched passwords should not change the password")

    def test_validate_password_used_not_bare_len_check(self):
        """
        Source inspection: account_settings view must use validate_password,
        not a bare len() check.
        """
        import inspect
        from apps.customer_portal import views
        src = inspect.getsource(views.account_settings)
        self.assertIn('validate_password', src,
                      "account_settings() must use validate_password() for new password validation")
        # The old bare check should be gone
        self.assertNotIn("Password must be at least 8 characters", src,
                         "Old bare length error message should be removed")
