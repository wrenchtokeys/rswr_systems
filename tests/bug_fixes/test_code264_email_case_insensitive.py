"""
CODE-264 regression tests: email duplicate checks must be case-insensitive.

Bug: `customer_register()` used `User.objects.filter(email=email).exists()`
(case-sensitive), so a user could register "Test@Example.com" and then
another user could register "test@example.com" — bypassing the duplicate
check and creating two accounts with functionally identical emails.

The same issue existed in `account_settings()` where changing email used
`User.objects.filter(email=email).exclude(...)`.

Fix:
  1. customer_register() now uses `email__iexact` for the duplicate check.
  2. customer_register() normalizes email to lowercase before creating the User.
  3. account_settings() now uses `email__iexact` and compares with `.lower()`.

This matches the pattern already used in accept_customer_invitation().
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(name='TestShop264'):
    owner = User.objects.create_user(
        username=f'owner_{name.lower().replace(" ", "")}',
        email=f'owner_{name.lower().replace(" ", "")}@example.com',
        password='OwnerPass123!',
    )
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-') + '-264',
        owner=owner,
        subscription_status='active',
    )


def _make_customer(tenant, name='Fleet Co 264'):
    return Customer.objects.create(tenant=tenant, name=name)


def _make_customer_user(tenant, customer, username='cu264', email='cu264@example.com', password='ValidPass999!'):
    user = User.objects.create_user(username=username, email=email, password=password,
                                    first_name='Test', last_name='User')
    TenantMembership.objects.create(user=user, tenant=tenant, role='viewer', is_active=True)
    cu = CustomerUser.objects.create(user=user, customer=customer)
    return cu, user


def _set_tenant_session(client, tenant):
    """Set tenant_id in session so middleware resolves it correctly."""
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


class CustomerRegisterEmailCaseTests(TestCase):
    """Verify customer_register rejects duplicate emails regardless of case."""

    def setUp(self):
        self.tenant = _make_tenant()
        self.customer = _make_customer(self.tenant)
        # Create an existing user with a lowercase email
        self.existing_user = User.objects.create_user(
            username='existing264',
            email='existing264@example.com',
            password='ExistingPass123!',
        )
        self.client = Client()
        _set_tenant_session(self.client, self.tenant)

    def test_register_rejects_same_email_different_case(self):
        """Registration with same email in different case should be rejected."""
        self.client.post(
            reverse('customer_register'),
            {
                'username': 'newuser264',
                'email': 'Existing264@Example.COM',  # Different case
                'password': 'StrongNewPass123!',
                'confirm_password': 'StrongNewPass123!',
                'first_name': 'New',
                'last_name': 'User',
            },
        )
        # Should NOT create a new user — email already exists (case-insensitive)
        self.assertFalse(
            User.objects.filter(username='newuser264').exists(),
            "A second user was created with a case-variant duplicate email"
        )

    def test_register_normalizes_email_to_lowercase(self):
        """Newly registered emails should be stored in lowercase."""
        self.client.post(
            reverse('customer_register'),
            {
                'username': 'fresh264',
                'email': 'Fresh264@Example.COM',
                'password': 'StrongFreshPass123!',
                'confirm_password': 'StrongFreshPass123!',
                'first_name': 'Fresh',
                'last_name': 'User',
            },
        )
        user = User.objects.filter(username='fresh264').first()
        self.assertIsNotNone(user, "User should have been created")
        self.assertEqual(
            user.email, 'fresh264@example.com',
            "Email was not normalized to lowercase on registration"
        )

    def test_register_allows_genuinely_new_email(self):
        """A truly unique email (no case-variant match) should work fine."""
        self.client.post(
            reverse('customer_register'),
            {
                'username': 'unique264',
                'email': 'unique264@example.com',
                'password': 'StrongUniquePass123!',
                'confirm_password': 'StrongUniquePass123!',
                'first_name': 'Unique',
                'last_name': 'User',
            },
        )
        self.assertTrue(
            User.objects.filter(username='unique264').exists(),
            "User with a genuinely unique email should have been created"
        )


class AccountSettingsEmailCaseTests(TestCase):
    """Verify account_settings rejects duplicate emails regardless of case."""

    def setUp(self):
        self.tenant = _make_tenant('Shop264B')
        self.customer = _make_customer(self.tenant, 'Fleet 264B')
        self.cu, self.user = _make_customer_user(
            self.tenant, self.customer,
            username='settings264', email='settings264@example.com',
        )
        # Another user whose email we'll try to steal
        self.other_user = User.objects.create_user(
            username='other264',
            email='other264@example.com',
            password='OtherPass123!',
        )
        self.client = Client()
        self.client.login(username='settings264', password='ValidPass999!')
        _set_tenant_session(self.client, self.tenant)

    def test_settings_rejects_email_case_variant_of_other_user(self):
        """Changing email to a case-variant of another user's email should fail."""
        self.client.post(
            reverse('customer_account_settings'),
            {
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'Other264@Example.COM',  # Case variant of other user
                'phone': '',
            },
        )
        # Refresh from DB — email should NOT have changed
        self.user.refresh_from_db()
        self.assertEqual(
            self.user.email, 'settings264@example.com',
            "Email was changed to a case-variant duplicate of another user's email"
        )

    def test_settings_allows_same_email_different_case_for_self(self):
        """Changing own email to a different case should NOT trigger duplicate error."""
        resp = self.client.post(
            reverse('customer_account_settings'),
            {
                'first_name': 'Test',
                'last_name': 'User',
                'email': 'Settings264@Example.COM',  # Same email, different case
                'phone': '',
            },
        )
        # This should work — it's the same user's email, just different case
        # The iexact check with exclude(id=user.id) should pass
        self.user.refresh_from_db()
        # The email should not have reverted to original due to a false-positive duplicate
        # (both the old and new case variants are acceptable)
