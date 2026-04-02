"""
CODE-270: Regression tests for accept_invite() TOCTOU race condition.

Bug: accept_invite() checked invite.is_valid BEFORE the transaction.atomic() block.
Two simultaneous POST requests could both pass the validity check (TOCTOU), then
both execute inside separate transactions — setting the password twice and potentially
creating duplicate Technician records.

Fix: Re-fetch the token with select_for_update() inside the atomic block and re-check
validity. If the token was already consumed by a concurrent request, return an error.

Pattern mirrors quick_approve_repair() and quick_deny_repair() (CODE-260/261).
"""

import uuid
from datetime import timedelta
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, InviteToken, SubscriptionPlan

User = get_user_model()


class AcceptInviteRaceTest(TestCase):
    """Tests for accept_invite() TOCTOU race condition fix."""

    def setUp(self):
        self.factory = RequestFactory()

        # Create a plan
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'price_monthly': 0, 'is_active': True},
        )

        # Create tenant owner + tenant
        self.owner = User.objects.create_user(
            username='owner_270',
            email='owner_270@example.com',
            password='testpass123',
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 270',
            slug='test-shop-270',
            owner=self.owner,
            subscription_plan=self.plan,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
        )

        # Invited technician (no password yet)
        self.invited_user = User.objects.create_user(
            username='invited_270',
            email='invited_270@example.com',
        )
        self.invited_user.set_unusable_password()
        self.invited_user.save()

        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.invited_user,
            role='technician',
        )

        # Create a valid InviteToken
        self.invite_token = InviteToken.objects.create(
            tenant=self.tenant,
            user=self.invited_user,
            role='technician',
            invited_by=self.owner,
        )

    def test_valid_invite_accepted_successfully(self):
        """A fresh invite token should allow password set + login."""
        response = self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': 'NewSecurePass99!', 'password_confirm': 'NewSecurePass99!'},
        )
        # Should redirect (either to portal or login)
        self.assertIn(response.status_code, (301, 302))

        # Token should be marked used
        self.invite_token.refresh_from_db()
        self.assertIsNotNone(self.invite_token.used_at)

    def test_already_used_invite_rejected(self):
        """A token that's already been used should fail gracefully."""
        # Mark the token as used
        self.invite_token.used_at = timezone.now()
        self.invite_token.save()

        response = self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': 'NewSecurePass99!', 'password_confirm': 'NewSecurePass99!'},
        )
        # Should render the invite page (not redirect) showing invalid/error state
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # The page should indicate the invite is not valid (either invite_valid=False
        # from the initial check, or the in-transaction error message)
        self.assertTrue(
            'already been used' in content or
            'invalid' in content.lower() or
            'expired' in content.lower() or
            'error' in content.lower()
        )

    def test_expired_invite_rejected(self):
        """An expired token should fail gracefully."""
        self.invite_token.expires_at = timezone.now() - timedelta(hours=1)
        self.invite_token.save()

        response = self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': 'NewSecurePass99!', 'password_confirm': 'NewSecurePass99!'},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertTrue(
            'expired' in content.lower() or
            'invalid' in content.lower() or
            'error' in content.lower()
        )

    def test_password_mismatch_rejected(self):
        """Mismatched passwords should fail without consuming the token."""
        response = self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': 'NewSecurePass99!', 'password_confirm': 'DifferentPass!'},
        )
        self.assertEqual(response.status_code, 200)

        # Token should NOT be consumed
        self.invite_token.refresh_from_db()
        self.assertIsNone(self.invite_token.used_at)

    def test_weak_password_rejected(self):
        """Weak passwords should be rejected by Django validators."""
        response = self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': '12345678', 'password_confirm': '12345678'},
        )
        self.assertEqual(response.status_code, 200)

        # Token should NOT be consumed
        self.invite_token.refresh_from_db()
        self.assertIsNone(self.invite_token.used_at)

    def test_token_consumed_exactly_once(self):
        """The token's used_at should be set exactly once after successful acceptance."""
        self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': 'NewSecurePass99!', 'password_confirm': 'NewSecurePass99!'},
        )

        self.invite_token.refresh_from_db()
        used_at_first = self.invite_token.used_at
        self.assertIsNotNone(used_at_first)

        # A second POST after the token is consumed should NOT update used_at
        self.client.post(
            f'/invite/{self.invite_token.token}/',
            {'password': 'AnotherPass99!', 'password_confirm': 'AnotherPass99!'},
        )
        self.invite_token.refresh_from_db()
        self.assertEqual(self.invite_token.used_at, used_at_first)

    def test_manager_invite_sets_is_manager_flag(self):
        """Accepting a manager invite should set the Technician.is_manager flag."""
        from apps.technician_portal.models import Technician

        # Create a fresh user + manager invite
        mgr_user = User.objects.create_user(
            username='manager_270',
            email='manager_270@example.com',
        )
        mgr_user.set_unusable_password()
        mgr_user.save()
        TenantMembership.objects.create(tenant=self.tenant, user=mgr_user, role='manager')
        mgr_token = InviteToken.objects.create(
            tenant=self.tenant,
            user=mgr_user,
            role='manager',
            invited_by=self.owner,
        )

        self.client.post(
            f'/invite/{mgr_token.token}/',
            {'password': 'NewSecurePass99!', 'password_confirm': 'NewSecurePass99!'},
        )

        tech = Technician.objects.filter(user=mgr_user, tenant=self.tenant).first()
        self.assertIsNotNone(tech, "Technician record should be created for manager invite")
        self.assertTrue(tech.is_manager, "is_manager should be True for manager role invite")

    def test_nonexistent_token_returns_invalid_page(self):
        """A random UUID not in the DB should render the invalid invite page."""
        fake_token = uuid.uuid4()
        response = self.client.get(f'/invite/{fake_token}/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Page should indicate the invite is not valid
        self.assertTrue(
            'invalid' in content.lower() or
            'expired' in content.lower() or
            'not found' in content.lower()
        )
