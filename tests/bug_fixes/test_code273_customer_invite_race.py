"""
CODE-273: Regression tests for accept_customer_invitation() TOCTOU race condition.

Bug: accept_customer_invitation() checked invitation.is_valid BEFORE transaction.atomic().
Two simultaneous POST requests (double-click, browser retry) could both pass the
validity check, then BOTH create a User + CustomerUser linked to the same invitation —
leaving the customer with two ghost portal accounts.

Fix: Inside transaction.atomic(), re-fetch the invitation with select_for_update()
and re-check is_valid. If already consumed by a concurrent request, render the
invalid invitation page instead of creating a duplicate account.

Pattern mirrors accept_invite() fix in CODE-270.
"""

import secrets
from datetime import timedelta
from django.test import TestCase, RequestFactory, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from unittest.mock import patch, MagicMock

from apps.customer_portal.models import CustomerUser, CustomerInvitation
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer

User = get_user_model()


class CustomerInviteRaceTest(TestCase):
    """Tests for accept_customer_invitation() TOCTOU race condition fix."""

    def setUp(self):
        # Create plan + tenant + owner
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'is_active': True},
        )
        self.owner = User.objects.create_user(
            username='owner_273',
            email='owner_273@example.com',
            password='testpass123',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 273',
            slug='test-shop-273',
            owner=self.owner,
            subscription_plan=self.plan,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
        )
        # Fleet customer that will have portal users
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Acme Trucking 273',
            customer_type='FLEET',
        )

    def _make_invite(self, email='newfleet273@example.com', status='pending'):
        """Helper to create a CustomerInvitation."""
        invite = CustomerInvitation.objects.create(
            customer=self.customer,
            email=email,
            first_name='New',
            last_name='User',
            status=status,
            expires_at=timezone.now() + timedelta(days=7),
            invited_by=self.owner,
        )
        return invite

    # ──────────────────────────────────────────────────────────────────
    # 1. Happy path: valid invite creates a user and CustomerUser
    # ──────────────────────────────────────────────────────────────────
    def test_valid_invite_creates_user_and_customer_user(self):
        invite = self._make_invite()
        client = Client()
        url = f'/app/invite/{invite.token}/'

        response = client.post(url, {
            'first_name': 'New',
            'last_name': 'User',
            'email': 'newfleet273@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
        })

        # Should redirect to customer_dashboard on success
        self.assertIn(response.status_code, [302, 200])
        # User should have been created
        self.assertTrue(User.objects.filter(email='newfleet273@example.com').exists())
        # CustomerUser should be linked to the customer
        user = User.objects.get(email='newfleet273@example.com')
        self.assertTrue(CustomerUser.objects.filter(user=user, customer=self.customer).exists())
        # Invitation should be marked accepted
        invite.refresh_from_db()
        self.assertEqual(invite.status, 'accepted')

    # ──────────────────────────────────────────────────────────────────
    # 2. Already-accepted invite returns invalid page (not another user)
    # ──────────────────────────────────────────────────────────────────
    def test_already_accepted_invite_renders_invalid_page(self):
        invite = self._make_invite(email='already273@example.com', status='accepted')
        client = Client()
        url = f'/app/invite/{invite.token}/'

        response = client.post(url, {
            'first_name': 'Duplicate',
            'last_name': 'User',
            'email': 'already273@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
        })

        # Should render invalid page, NOT redirect to dashboard
        self.assertEqual(response.status_code, 200)
        # No user should have been created for this email
        self.assertFalse(User.objects.filter(email='already273@example.com').exists())

    # ──────────────────────────────────────────────────────────────────
    # 3. Expired invite renders invalid page
    # ──────────────────────────────────────────────────────────────────
    def test_expired_invite_renders_invalid_page(self):
        invite = CustomerInvitation.objects.create(
            customer=self.customer,
            email='expired273@example.com',
            first_name='Expired',
            last_name='User',
            status='pending',
            expires_at=timezone.now() - timedelta(hours=1),  # already expired
            invited_by=self.owner,
        )
        client = Client()
        url = f'/app/invite/{invite.token}/'

        response = client.post(url, {
            'first_name': 'Expired',
            'last_name': 'User',
            'email': 'expired273@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!',
        })

        # Should NOT create a user
        self.assertFalse(User.objects.filter(email='expired273@example.com').exists())

    # ──────────────────────────────────────────────────────────────────
    # 4. Race simulation: lock consumed by first request blocks second
    # ──────────────────────────────────────────────────────────────────
    def test_select_for_update_prevents_duplicate_user_on_race(self):
        """
        Simulate the TOCTOU race by mocking select_for_update() to return
        an already-accepted invitation for the second call, verifying that
        the locked re-check aborts the second request cleanly.
        """
        invite = self._make_invite(email='race273@example.com')

        # Simulate: by the time the second request reaches the select_for_update,
        # the first request has already marked it accepted.
        accepted_invite = CustomerInvitation(
            id=invite.id,
            customer=self.customer,
            email=invite.email,
            first_name=invite.first_name,
            last_name=invite.last_name,
            status='accepted',  # already consumed
            expires_at=invite.expires_at,
            invited_by=self.owner,
        )

        # We patch select_for_update at the queryset level so the locked re-fetch
        # returns the already-accepted invitation.
        from django.db.models.query import QuerySet

        original_get = QuerySet.get

        call_count = [0]

        def patched_get(self_qs, **kwargs):
            # Only intercept the select_for_update().get(pk=invite.pk) call
            if call_count[0] == 0 and kwargs.get('pk') == invite.pk:
                call_count[0] += 1
                return accepted_invite
            return original_get(self_qs, **kwargs)

        with patch.object(QuerySet, 'get', patched_get):
            client = Client()
            url = f'/app/invite/{invite.token}/'
            response = client.post(url, {
                'first_name': 'Race',
                'last_name': 'User',
                'email': 'race273@example.com',
                'password': 'SecurePass123!',
                'password_confirm': 'SecurePass123!',
            })

        # With the fix, the re-check sees status='accepted' and renders invalid page
        # Without the fix, a user would have been created.
        # We verify the response isn't a successful redirect (which would imply creation).
        # The exact behavior depends on how the view handles the locked invite's is_valid.
        # Key assertion: no user was created for this email.
        self.assertFalse(
            User.objects.filter(email='race273@example.com').exists(),
            "Race condition allowed duplicate user creation — TOCTOU fix not effective",
        )

    # ──────────────────────────────────────────────────────────────────
    # 5. GET request shows form for a valid invite
    # ──────────────────────────────────────────────────────────────────
    def test_get_request_shows_form(self):
        invite = self._make_invite(email='getform273@example.com')
        client = Client()
        url = f'/app/invite/{invite.token}/'
        response = client.get(url)
        self.assertIn(response.status_code, [200])
        # Invitation should still be pending (GET doesn't consume it)
        invite.refresh_from_db()
        self.assertEqual(invite.status, 'pending')

    # ──────────────────────────────────────────────────────────────────
    # 6. Non-existent token renders invalid page
    # ──────────────────────────────────────────────────────────────────
    def test_invalid_token_renders_invalid_page(self):
        client = Client()
        url = '/app/invite/nonexistent-token-xyz/'
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        # Should not crash — just render invalid

    # ──────────────────────────────────────────────────────────────────
    # 7. Locked invite is_valid check — unit test
    # ──────────────────────────────────────────────────────────────────
    def test_customer_invitation_is_valid_returns_false_for_accepted(self):
        """CustomerInvitation.is_valid must return False once accepted."""
        invite = self._make_invite(email='isvalid273@example.com')
        self.assertTrue(invite.is_valid, "Fresh invite should be valid")
        invite.status = 'accepted'
        invite.save(update_fields=['status'])
        invite.refresh_from_db()
        self.assertFalse(invite.is_valid, "Accepted invite should not be valid")

    def test_customer_invitation_is_valid_returns_false_for_expired(self):
        """CustomerInvitation.is_valid must return False for expired invites."""
        invite = CustomerInvitation.objects.create(
            customer=self.customer,
            email='expiredvalid273@example.com',
            first_name='E',
            last_name='X',
            status='pending',
            expires_at=timezone.now() - timedelta(minutes=1),
            invited_by=self.owner,
        )
        self.assertFalse(invite.is_valid, "Expired invite should not be valid")
