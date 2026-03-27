"""
CODE-206 Regression: invite_member() allowed managers to invite other managers.

A user with role='manager' could POST role=manager to /owner/settings/invite/
and create a new manager without the shop owner's knowledge.  The role
whitelist check only prevented 'owner' from being invited (role not in
('manager', 'technician', 'viewer') was the gate), but it did not prevent
a manager from granting peer-level manager access.

Impact: A malicious or confused manager could escalate another user to manager
        rights, giving them access to settings, pricing overrides, team
        management, and financial reports — without the owner approving it.

Fix (CODE-206): Added a privilege escalation guard in invite_member():

    if membership.role == 'manager' and role == 'manager':
        messages.error(request, 'Only the shop owner can invite managers.')
        return redirect('owner_settings')

This mirrors the guard already present in update_team_member() which requires
my_membership.role == 'owner' to change a member's role.

Tests verify:
  1. A manager CANNOT invite a new manager (blocked with error message).
  2. A manager CAN invite a technician (allowed).
  3. A manager CAN invite a viewer (allowed).
  4. The shop owner CAN still invite managers (unchanged behaviour).
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
}


def _make_shop_with_manager(slug):
    """
    Create a tenant, an owner, and a manager for it.
    Returns (tenant, owner, manager_user).
    """
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=f'unlimited-206-{slug}',
        defaults={
            'name': 'Unlimited',
            'monthly_price': 0,
            'annual_price': 0,
            'max_technicians': None,
        },
    )

    owner = User.objects.create_user(
        username=f'owner_206_{slug}',
        email=f'owner_206_{slug}@example.com',
        password='ownerpass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop 206 {slug}',
        slug=f'shop-206-{slug}',
        owner=owner,
        plan='pro',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)

    manager_user = User.objects.create_user(
        username=f'manager_206_{slug}',
        email=f'manager_206_{slug}@example.com',
        password='managerpass',
    )
    TenantMembership.objects.create(tenant=tenant, user=manager_user, role='manager', is_active=True)
    Technician.objects.create(
        tenant=tenant,
        user=manager_user,
        is_active=True,
        is_manager=True,
    )

    return tenant, owner, manager_user


def _post_invite(client, role, email, tenant):
    """Helper: POST to invite_member with the given role/email."""
    return client.post(
        reverse('owner_invite_member'),
        {
            'email': email,
            'first_name': 'New',
            'last_name': 'Person',
            'role': role,
        },
        follow=True,
    )


@override_settings(**TEST_OVERRIDES)
class ManagerCannotInviteManagerTests(TestCase):

    def setUp(self):
        self.tenant, self.owner, self.manager_user = _make_shop_with_manager('main')

    def _login_as_manager(self):
        c = Client()
        c.force_login(self.manager_user)
        session = c.session
        session['tenant_slug'] = self.tenant.slug
        session.save()
        return c

    def _login_as_owner(self):
        c = Client()
        c.force_login(self.owner)
        session = c.session
        session['tenant_slug'] = self.tenant.slug
        session.save()
        return c

    def test_manager_cannot_invite_manager(self):
        """
        A manager should be blocked from inviting a new manager (CODE-206).
        No User record should be created for the invite target.
        """
        c = self._login_as_manager()
        email = 'new_mgr_206@example.com'

        resp = _post_invite(c, 'manager', email, self.tenant)

        # The invite must be blocked: no user record created
        self.assertFalse(
            User.objects.filter(email=email).exists(),
            'Manager was able to create a new manager — privilege escalation not blocked.',
        )
        # No new TenantMembership with role=manager for target
        self.assertFalse(
            TenantMembership.objects.filter(
                tenant=self.tenant,
                user__email=email,
                role='manager',
            ).exists(),
        )

    def test_manager_can_invite_technician(self):
        """A manager should still be allowed to invite a technician."""
        c = self._login_as_manager()
        email = 'new_tech_206@example.com'

        resp = _post_invite(c, 'technician', email, self.tenant)

        self.assertTrue(
            User.objects.filter(email=email).exists(),
            'Manager was incorrectly blocked from inviting a technician.',
        )

    def test_manager_can_invite_viewer(self):
        """A manager should still be allowed to invite a viewer."""
        c = self._login_as_manager()
        email = 'new_viewer_206@example.com'

        resp = _post_invite(c, 'viewer', email, self.tenant)

        self.assertTrue(
            User.objects.filter(email=email).exists(),
            'Manager was incorrectly blocked from inviting a viewer.',
        )

    def test_owner_can_invite_manager(self):
        """
        The shop owner must still be able to invite managers (behaviour unchanged).
        """
        c = self._login_as_owner()
        email = 'new_mgr_by_owner_206@example.com'

        resp = _post_invite(c, 'manager', email, self.tenant)

        self.assertTrue(
            User.objects.filter(email=email).exists(),
            'Owner was incorrectly blocked from inviting a manager.',
        )
        self.assertTrue(
            TenantMembership.objects.filter(
                tenant=self.tenant,
                user__email=email,
                role='manager',
            ).exists(),
            'Manager TenantMembership was not created for owner-initiated invite.',
        )
