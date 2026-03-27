"""
CODE-212 Regression: update_team_member() allowed managers to modify peer managers.

A user with role='manager' could POST to /owner/settings/update-member/<id>/
targeting another manager (same role) and update their can_repair/can_replace
abilities.  The existing role-change guard only blocked changing the *role*
field (new_role != target.role), so a manager POSTing role=manager (matching
the target's current role) bypassed the guard entirely and could silently
alter a peer manager's Technician record.

Impact: A malicious manager could disable a peer manager's repair abilities
        or elevate their own team member's abilities without owner approval.
        Any manager should only be able to edit *technician*-role members.

Fix (CODE-212): Added an explicit guard in update_team_member():

    if my_membership.role == 'manager' and target.role in ('manager', 'owner'):
        messages.error(request, 'Managers can only update technician team members.')
        return redirect('owner_settings')

This prevents managers from touching peers or higher-privilege members.

Tests verify:
  1. A manager CANNOT update another manager's abilities (403-equivalent redirect).
  2. A manager CANNOT update the shop owner's abilities.
  3. A manager CAN update a technician's abilities (allowed).
  4. The shop owner CAN update anyone (unchanged behaviour).
"""

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'DEFAULT_AUTO_FIELD': 'django.db.models.BigAutoField',
}


def _make_tenant():
    import uuid
    slug = uuid.uuid4().hex[:8]
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=f'unlimited-212-{slug}',
        defaults={
            'name': 'Unlimited',
            'monthly_price': 0,
            'annual_price': 0,
            'max_technicians': None,
        },
    )
    owner = User.objects.create_user(
        username=f'shop_owner_{slug}',
        email=f'shop_owner_{slug}@example.com',
        password='ownerpass',
    )
    return Tenant.objects.create(
        name=f'Test Shop {slug}',
        slug=f'shop-{slug}',
        owner=owner,
        plan='pro',
        subscription_plan=plan,
    )


def _make_user(email, first='Test', last='User'):
    import uuid
    username = f'user_{uuid.uuid4().hex[:8]}'
    return User.objects.create_user(username=username, email=email, password='testpass123',
                                    first_name=first, last_name=last)


def _add_member(tenant, user, role, can_repair=True, can_replace=False):
    membership = TenantMembership.objects.create(
        tenant=tenant, user=user, role=role, is_active=True
    )
    if role in ('technician', 'manager'):
        Technician.objects.create(
            user=user, tenant=tenant, is_manager=(role == 'manager'),
            is_active=True, can_repair=can_repair, can_replace=can_replace,
        )
    return membership


@override_settings(**TEST_OVERRIDES)
class ManagerCannotUpdatePeerManagerTest(TestCase):
    """CODE-212: managers can only edit technician-role members."""

    def setUp(self):
        self.client = Client(HTTP_HOST='testserver')
        self.tenant = _make_tenant()

        self.owner_user = _make_user('owner@example.com', 'Owner', 'User')
        self.owner_membership = _add_member(self.tenant, self.owner_user, 'owner')

        self.manager_user = _make_user('manager@example.com', 'Manager', 'User')
        self.manager_membership = _add_member(self.tenant, self.manager_user, 'manager')

        self.peer_manager_user = _make_user('peer@example.com', 'Peer', 'Manager')
        self.peer_manager_membership = _add_member(self.tenant, self.peer_manager_user, 'manager',
                                                    can_repair=True, can_replace=False)

        self.tech_user = _make_user('tech@example.com', 'Tech', 'User')
        self.tech_membership = _add_member(self.tenant, self.tech_user, 'technician',
                                           can_repair=True, can_replace=False)

    def _login_as(self, user):
        self.client.force_login(user)

    def _post_update(self, membership_id, role, can_repair=True, can_replace=False):
        return self.client.post(
            reverse('update_team_member', args=[membership_id]),
            {
                'role': role,
                'can_repair': 'on' if can_repair else '',
                'can_replace': 'on' if can_replace else '',
            },
            HTTP_HOST='testserver',
            SERVER_NAME='testserver',
        )

    # ── Test 1: manager cannot update a peer manager ──────────────────────────

    def test_manager_cannot_update_peer_manager(self):
        """A manager should be blocked from editing another manager's abilities."""
        self._login_as(self.manager_user)

        # Try to update peer manager (same role, no role change — old guard misses this)
        response = self._post_update(
            self.peer_manager_membership.id,
            role='manager',  # same as target.role — old code let this through
            can_repair=False,  # trying to remove peer's repair ability
        )

        # Should redirect (not succeed silently)
        self.assertIn(response.status_code, [302, 403])

        # Peer manager's Technician record must be unchanged
        peer_tech = Technician.objects.get(user=self.peer_manager_user, tenant=self.tenant)
        self.assertTrue(peer_tech.can_repair, 'Peer manager can_repair should NOT have been changed')

    # ── Test 2: manager cannot update the owner ───────────────────────────────

    def test_manager_cannot_update_owner(self):
        """A manager should be blocked from editing the owner's abilities."""
        self._login_as(self.manager_user)

        response = self._post_update(
            self.owner_membership.id,
            role='owner',
        )

        self.assertIn(response.status_code, [302, 403])

    # ── Test 3: manager CAN update a technician ───────────────────────────────

    def test_manager_can_update_technician(self):
        """A manager should be able to update a technician's can_repair/can_replace."""
        self._login_as(self.manager_user)

        # Toggle tech's can_replace on
        response = self._post_update(
            self.tech_membership.id,
            role='technician',
            can_repair=True,
            can_replace=True,
        )

        # Should redirect back to owner_settings (success)
        self.assertEqual(response.status_code, 302)

        tech = Technician.objects.get(user=self.tech_user, tenant=self.tenant)
        self.assertTrue(tech.can_replace, 'Manager should be able to enable can_replace for a technician')

    # ── Test 4: owner CAN update anyone ──────────────────────────────────────

    def test_owner_can_update_peer_manager(self):
        """The shop owner should still be able to edit manager records."""
        self._login_as(self.owner_user)

        # Remove peer manager's can_repair
        response = self._post_update(
            self.peer_manager_membership.id,
            role='manager',
            can_repair=False,
        )

        self.assertEqual(response.status_code, 302)

        peer_tech = Technician.objects.get(user=self.peer_manager_user, tenant=self.tenant)
        self.assertFalse(peer_tech.can_repair, 'Owner should be able to remove manager can_repair')

    def test_owner_can_change_tech_role(self):
        """The shop owner should be able to change a technician's role."""
        self._login_as(self.owner_user)

        response = self._post_update(
            self.tech_membership.id,
            role='manager',
            can_repair=True,
        )

        self.assertEqual(response.status_code, 302)

        self.tech_membership.refresh_from_db()
        self.assertEqual(self.tech_membership.role, 'manager')
