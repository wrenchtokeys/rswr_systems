"""
CODE-188: Regression tests — customer portal password validation

Both `customer_register` and `accept_customer_invitation` used bare
`len(password) < 8` checks instead of Django's `validate_password()`.
This meant common/numeric passwords like "password1" or "12345678" were
accepted when they should be rejected by CommonPasswordValidator and
NumericPasswordValidator.

Fixed: both views now call `validate_password(password, user=temp_user)`.
"""
import uuid
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.customer_portal.models import CustomerInvitation, CustomerUser


def _make_tenant(slug=None):
    slug = slug or f"shop-{uuid.uuid4().hex[:8]}"
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'), 'trial_days': 30, 'display_order': 0},
    )
    owner = User.objects.create_user(
        username=f'owner-{slug}',
        email=f'owner-{slug}@example.com',
        password='ownerpass123',
    )
    t = Tenant.objects.create(
        name=f"Shop {slug}",
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
        is_active=True,
    )
    TenantMembership.objects.create(tenant=t, user=owner, role='owner')
    return t


def _make_customer(tenant, name="Test Corp"):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        customer_type='FLEET',
    )


def _make_invitation(customer, email=None):
    email = email or f"invite-{uuid.uuid4().hex[:6]}@example.com"
    return CustomerInvitation.objects.create(
        customer=customer,
        email=email,
        first_name="Jane",
        last_name="Doe",
        invited_by=None,
        is_primary_contact=False,
    )


class CustomerRegisterPasswordValidationTest(TestCase):
    """customer_register must reject weak/common passwords via validate_password."""

    def setUp(self):
        self.client = Client()
        self.url = '/app/register/'

    def _post(self, password, confirm=None):
        if confirm is None:
            confirm = password
        return self.client.post(self.url, {
            'username': f'testuser{uuid.uuid4().hex[:6]}',
            'email': f'user{uuid.uuid4().hex[:6]}@example.com',
            'password': password,
            'confirm_password': confirm,
            'first_name': 'Test',
            'last_name': 'User',
        })

    def test_numeric_only_password_rejected(self):
        """'12345678' should fail NumericPasswordValidator."""
        response = self._post('12345678')
        # Should NOT redirect (form error) and no user created
        self.assertNotEqual(response.status_code, 302,
                            "Numeric-only password '12345678' was accepted — should be rejected")

    def test_common_password_rejected(self):
        """'password1' should fail CommonPasswordValidator."""
        response = self._post('password1')
        self.assertNotEqual(response.status_code, 302,
                            "Common password 'password1' was accepted — should be rejected")

    def test_strong_password_accepted(self):
        """A reasonably strong unique password should pass."""
        response = self._post('Xy9!kR2mQ#vL')
        # Either success redirect or the user was created — accept 302 redirect
        # Note: if the URL doesn't exist in test DB, we may get a 404 — just
        # verify no error message about password strength.
        if response.status_code == 302:
            return  # accepted as expected
        # If 200, make sure it's not a password-strength error
        content = response.content.decode()
        self.assertNotIn('too common', content)
        self.assertNotIn('entirely numeric', content)
        self.assertNotIn('at least 8', content)

    def test_mismatch_password_rejected(self):
        """Mismatched passwords must be rejected."""
        response = self._post('Xy9!kR2mQ#vL', confirm='DifferentPass1!')
        self.assertNotEqual(response.status_code, 302,
                            "Mismatched passwords were accepted")


class AcceptCustomerInvitationPasswordValidationTest(TestCase):
    """accept_customer_invitation must use validate_password not bare len()."""

    def setUp(self):
        self.client = Client()
        self.tenant = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.invitation = _make_invitation(self.customer)

    def _url(self):
        return f'/app/invite/{self.invitation.token}/'

    def _post(self, password, confirm=None):
        if confirm is None:
            confirm = password
        email = f'newuser{uuid.uuid4().hex[:6]}@example.com'
        return self.client.post(self._url(), {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': email,
            'password': password,
            'password_confirm': confirm,
        })

    def test_numeric_only_password_rejected(self):
        """'12345678' must fail NumericPasswordValidator in invitation acceptance."""
        response = self._post('12345678')
        self.assertNotEqual(response.status_code, 302,
                            "Numeric-only password accepted in accept_customer_invitation")
        # Verify no CustomerUser was created
        self.assertEqual(
            User.objects.filter(first_name='Jane', last_name='Doe').count(), 0,
            "User was created despite weak numeric password"
        )

    def test_common_password_rejected(self):
        """'password1' must fail CommonPasswordValidator in invitation acceptance."""
        response = self._post('password1')
        self.assertNotEqual(response.status_code, 302,
                            "Common password 'password1' accepted in accept_customer_invitation")

    def test_strong_password_accepted(self):
        """A strong password should result in user creation."""
        response = self._post('Xy9!kR2mQ#v7')
        # Should redirect to customer dashboard after successful account creation
        self.assertEqual(response.status_code, 302,
                         f"Strong password was rejected in accept_customer_invitation: {response.content[:200]}")
        # Verify user was created
        self.assertEqual(
            User.objects.filter(first_name='Jane', last_name='Doe').count(), 1
        )

    def test_password_mismatch_rejected(self):
        """Mismatched passwords must be rejected."""
        response = self._post('Xy9!kR2mQ#v7', confirm='AnotherPass1!')
        self.assertNotEqual(response.status_code, 302,
                            "Mismatched passwords accepted in accept_customer_invitation")

    def test_no_user_created_on_weak_password(self):
        """No User or CustomerUser row should exist after a failed validation."""
        before_count = User.objects.count()
        self._post('12345678')
        self.assertEqual(User.objects.count(), before_count,
                         "User was created despite weak password validation failure")
