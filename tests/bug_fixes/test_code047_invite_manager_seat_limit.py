"""
CODE-047 Regression: invite_member() seat limit check only applied to
role='technician', not role='manager'.

Both technicians and managers create a Technician record and consume a
technician seat. The seat check was:

    if role == 'technician' and tenant:
        can_add, limit_msg = UsageService(tenant).can_add_technician()

This meant a shop owner at the seat limit could bypass the cap by choosing
'Manager' as the role for a new invite. The Technician record is created for
both roles (role in ('technician', 'manager') branch) so they do consume a seat.

Impact: shops on a plan with max_technicians could silently exceed their seat
limit by inviting managers instead of technicians.

Fix: Changed the check condition from:
    role == 'technician'
to:
    role in ('technician', 'manager')

Tests verify:
  1. At seat limit, inviting a TECHNICIAN is blocked (existing behaviour preserved)
  2. At seat limit, inviting a MANAGER is also blocked (new behaviour)
  3. Below seat limit, inviting a MANAGER is allowed
  4. Inviting a VIEWER never checks seats (viewers have no Technician record)
  5. Inviting on an unlimited plan (max_technicians=None) is always allowed
"""

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def _make_tenant_at_limit(slug, max_techs):
    """Create a tenant with a capped plan and fill it to the seat limit."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=f'capped-{max_techs}-{slug}',
        defaults={
            'name': f'Capped {max_techs}',
            'monthly_price': 0,
            'annual_price': 0,
            'max_technicians': max_techs,
        },
    )
    plan.max_technicians = max_techs
    plan.save()

    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='pass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        owner=owner,
        plan='starter',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)

    # Fill seats to the limit
    for i in range(max_techs):
        tech_user = User.objects.create_user(
            username=f'tech_{slug}_{i}',
            email=f'tech_{slug}_{i}@example.com',
            password='pass',
        )
        TenantMembership.objects.create(tenant=tenant, user=tech_user, role='technician', is_active=True)
        Technician.objects.create(
            tenant=tenant,
            user=tech_user,
            is_active=True,
            is_manager=False,
        )

    return tenant, owner


def _make_unlimited_tenant(slug):
    """Create a tenant on an unlimited plan."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=f'unlimited-{slug}',
        defaults={
            'name': 'Unlimited',
            'monthly_price': 0,
            'annual_price': 0,
            'max_technicians': None,
        },
    )
    plan.max_technicians = None
    plan.save()

    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='pass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        owner=owner,
        plan='pro',
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return tenant, owner


@override_settings(**TEST_OVERRIDES)
class InviteManagerSeatLimitTests(TestCase):

    def _post_invite(self, client, role, email):
        """Helper: POST to invite_member with the given role/email."""
        return client.post(
            reverse('owner_invite_member'),
            {
                'email': email,
                'first_name': 'New',
                'last_name': 'Person',
                'role': role,
                'can_repair': 'on',
                'can_replace': 'on',
            },
            follow=True,
        )

    def test_at_limit_technician_invite_blocked(self):
        """Existing behaviour: inviting technician at limit is blocked."""
        tenant, owner = _make_tenant_at_limit('t47a', max_techs=2)
        c = Client()
        c.force_login(owner)
        # Manually attach tenant to the request via session approach
        session = c.session
        session['tenant_slug'] = tenant.slug
        session.save()

        resp = self._post_invite(c, 'technician', 'newtech@example.com')
        # No new technician should be created
        self.assertFalse(User.objects.filter(email='newtech@example.com').exists())

    def test_at_limit_manager_invite_blocked(self):
        """New behaviour: inviting manager at limit is also blocked (CODE-047 fix)."""
        tenant, owner = _make_tenant_at_limit('t47b', max_techs=2)
        c = Client()
        c.force_login(owner)
        session = c.session
        session['tenant_slug'] = tenant.slug
        session.save()

        resp = self._post_invite(c, 'manager', 'newmgr@example.com')
        # No new manager should be created (seat limit enforced)
        self.assertFalse(User.objects.filter(email='newmgr@example.com').exists())

    def test_below_limit_manager_invite_allowed(self):
        """Inviting a manager when below the seat limit is still allowed."""
        tenant, owner = _make_tenant_at_limit('t47c', max_techs=3)
        # Remove one tech to free up a slot
        extra_tech = Technician.objects.filter(tenant=tenant).first()
        extra_tech.is_active = False
        extra_tech.save()

        c = Client()
        c.force_login(owner)
        session = c.session
        session['tenant_slug'] = tenant.slug
        session.save()

        resp = self._post_invite(c, 'manager', 'newmgr2@example.com')
        # Manager invite should succeed (slot is available)
        self.assertTrue(User.objects.filter(email='newmgr2@example.com').exists())

    def test_viewer_invite_never_blocked_by_seat_limit(self):
        """Viewer role has no Technician record and should not be blocked by seat limit."""
        tenant, owner = _make_tenant_at_limit('t47d', max_techs=2)
        c = Client()
        c.force_login(owner)
        session = c.session
        session['tenant_slug'] = tenant.slug
        session.save()

        resp = self._post_invite(c, 'viewer', 'newviewer@example.com')
        # Viewer invite should succeed even at seat limit
        self.assertTrue(User.objects.filter(email='newviewer@example.com').exists())

    def test_unlimited_plan_manager_invite_always_allowed(self):
        """On an unlimited plan, manager invite should never be blocked."""
        tenant, owner = _make_unlimited_tenant('t47e')
        # Add many techs
        for i in range(20):
            u = User.objects.create_user(
                username=f'tech_unlim_{i}',
                email=f'tech_unlim_{i}@example.com',
                password='pass',
            )
            TenantMembership.objects.create(tenant=tenant, user=u, role='technician', is_active=True)
            Technician.objects.create(tenant=tenant, user=u, is_active=True, is_manager=False)

        c = Client()
        c.force_login(owner)
        session = c.session
        session['tenant_slug'] = tenant.slug
        session.save()

        resp = self._post_invite(c, 'manager', 'newmgr3@example.com')
        # Should be allowed (unlimited plan)
        self.assertTrue(User.objects.filter(email='newmgr3@example.com').exists())

    def test_seat_check_uses_active_technicians_only(self):
        """
        Seat count excludes deactivated technicians.
        At limit with one deactivated tech => inviting manager should succeed.
        """
        tenant, owner = _make_tenant_at_limit('t47f', max_techs=2)
        # Deactivate one seat
        tech = Technician.objects.filter(tenant=tenant).last()
        tech.is_active = False
        tech.save()

        c = Client()
        c.force_login(owner)
        session = c.session
        session['tenant_slug'] = tenant.slug
        session.save()

        resp = self._post_invite(c, 'manager', 'newmgr4@example.com')
        # One slot freed by deactivation → invite allowed
        self.assertTrue(User.objects.filter(email='newmgr4@example.com').exists())
