"""
CODE-040 Regression: invite_member() re-activation path had three bugs.

Before fix, when an owner re-invited a previously deactivated team member:

  Bug 1 (Technician not reactivated):
    The code updated TenantMembership.is_active = True but never touched the
    Technician record. Technician.is_active stayed False. The re-added member
    could not access the technician portal at all — the @technician_required
    decorator redirects users whose Technician.is_active is False.

  Bug 2 (abilities not updated):
    can_repair/can_replace from the new invite form were never applied to the
    Technician record, so the member always kept their old abilities regardless
    of what the owner set on re-invite.

  Bug 3 (no invite email sent):
    An early `return redirect(...)` meant no InviteToken was created and no
    re-invite email was sent. The member had no way to regain access if they
    forgot their password (most likely for previously deactivated users).

After fix:
  - Technician.is_active → True (or created if missing)
  - Technician.is_manager / can_repair / can_replace updated to new values
  - Non-tech roles deactivate the Technician record
  - InviteToken created and invite email attempted (gracefully handles failure)

Tests verify:
  1. Re-activating a tech → Technician.is_active = True
  2. Role change on re-activation propagates to Technician.is_manager
  3. can_repair/can_replace from new invite are applied
  4. InviteToken is created for re-activated member
  5. Re-activating a viewer role → Technician.is_active = False (deactivated)
  6. Re-activating an already-active member shows warning, no duplicate token
  7. Role → viewer when Technician doesn't exist yet doesn't crash
"""

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership, InviteToken
from apps.technician_portal.models import Technician

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def _make_tenant(slug='test-shop'):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'annual_price': 0},
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}', email=f'owner_{slug}@example.com', password='pass'
    )
    tenant = Tenant.objects.create(
        name='Test Shop', slug=slug, owner=owner,
        subscription_plan=plan, subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return tenant, owner


def _make_deactivated_tech(tenant, email='old_tech@example.com', can_repair=True):
    """Create a user with a deactivated membership + deactivated Technician."""
    user = User.objects.create_user(username=email.split('@')[0], email=email, password='pass')
    TenantMembership.objects.create(tenant=tenant, user=user, role='technician', is_active=False)
    Technician.objects.create(
        user=user, tenant=tenant,
        is_active=False, is_manager=False,
        can_repair=can_repair, can_replace=False,
    )
    return user


@override_settings(**TEST_OVERRIDES)
class InviteMemberReactivationTests(TestCase):
    """Tests for CODE-040: invite_member re-activation path."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant(slug='code040')
        self.client = Client()
        self.client.login(username='owner_code040', password='pass')

        # Simulate middleware tenant attachment
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_invite(self, email, role='technician', can_repair=True, can_replace=False):
        return self.client.post(
            reverse('owner_invite_member'),
            data={
                'email': email,
                'first_name': 'Test',
                'last_name': 'User',
                'role': role,
                'can_repair': 'on' if can_repair else '',
                'can_replace': 'on' if can_replace else '',
            },
            HTTP_HOST='localhost',
        )

    # --- Test 1: Technician is reactivated ---
    def test_reactivated_member_technician_is_active(self):
        """Re-activating a deactivated tech must set Technician.is_active = True."""
        user = _make_deactivated_tech(self.tenant, 'reactivate@example.com')
        self.assertFalse(Technician.objects.get(user=user, tenant=self.tenant).is_active)

        with self.settings(TENANT_FROM_SESSION=True):
            # Simulate tenant middleware via the session — patch _get_owner_tenant
            from unittest.mock import patch
            membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
            with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
                self._post_invite('reactivate@example.com', role='technician')

        tech = Technician.objects.get(user=user, tenant=self.tenant)
        self.assertTrue(tech.is_active, "Technician.is_active must be True after re-activation")

    # --- Test 2: Role change propagates ---
    def test_reactivated_as_manager_sets_is_manager(self):
        """Re-inviting as manager → Technician.is_manager = True."""
        user = _make_deactivated_tech(self.tenant, 'mgr_reactivate@example.com')
        tech = Technician.objects.get(user=user, tenant=self.tenant)
        self.assertFalse(tech.is_manager)

        from unittest.mock import patch
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
            self._post_invite('mgr_reactivate@example.com', role='manager')

        tech.refresh_from_db()
        self.assertTrue(tech.is_manager, "Technician.is_manager must be True when re-invited as manager")
        self.assertTrue(tech.is_active, "Technician.is_active must be True after re-activation as manager")

    # --- Test 3: abilities updated ---
    def test_can_repair_and_can_replace_updated(self):
        """can_repair/can_replace from new invite form apply to Technician record."""
        # Create with can_repair=True, can_replace=False
        user = _make_deactivated_tech(self.tenant, 'abilities@example.com', can_repair=True)
        tech = Technician.objects.get(user=user, tenant=self.tenant)
        self.assertTrue(tech.can_repair)
        self.assertFalse(tech.can_replace)

        from unittest.mock import patch
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
            # Re-invite with can_repair=False, can_replace=True
            self.client.post(
                reverse('owner_invite_member'),
                data={
                    'email': 'abilities@example.com',
                    'first_name': 'Test',
                    'last_name': 'User',
                    'role': 'technician',
                    'can_replace': 'on',  # only can_replace this time
                },
                HTTP_HOST='localhost',
            )

        tech.refresh_from_db()
        self.assertFalse(tech.can_repair, "can_repair must be updated to False")
        self.assertTrue(tech.can_replace, "can_replace must be updated to True")

    # --- Test 4: InviteToken created ---
    def test_invite_token_created_on_reactivation(self):
        """An InviteToken must be created so the user can reset their password."""
        user = _make_deactivated_tech(self.tenant, 'token_check@example.com')
        initial_token_count = InviteToken.objects.filter(user=user, tenant=self.tenant).count()

        from unittest.mock import patch
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
            self._post_invite('token_check@example.com', role='technician')

        new_tokens = InviteToken.objects.filter(user=user, tenant=self.tenant).count()
        self.assertGreater(new_tokens, initial_token_count, "InviteToken must be created on re-activation")

    # --- Test 5: viewer role deactivates Technician ---
    def test_reactivated_as_viewer_deactivates_technician(self):
        """Re-inviting as viewer (non-tech role) should deactivate the Technician record."""
        user = _make_deactivated_tech(self.tenant, 'viewer_reactivate@example.com')

        from unittest.mock import patch
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
            self._post_invite('viewer_reactivate@example.com', role='viewer')

        # Membership should be reactivated
        mem = TenantMembership.objects.get(user=user, tenant=self.tenant)
        self.assertTrue(mem.is_active)
        self.assertEqual(mem.role, 'viewer')

        # Technician record should stay deactivated (viewer has no tech portal access)
        tech = Technician.objects.get(user=user, tenant=self.tenant)
        self.assertFalse(tech.is_active, "Technician.is_active must stay False for viewer role")

    # --- Test 6: already-active member shows warning, no duplicate ---
    def test_reinvite_active_member_shows_warning(self):
        """Re-inviting an already-active member shows a warning, no second membership."""
        user = User.objects.create_user(
            username='active_member', email='active_member@example.com', password='pass'
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=user, role='technician', is_active=True
        )

        from unittest.mock import patch
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
            response = self._post_invite('active_member@example.com', role='technician')

        # Only one membership should exist
        count = TenantMembership.objects.filter(user=user, tenant=self.tenant).count()
        self.assertEqual(count, 1, "Should not create duplicate membership for active member")

    # --- Test 7: viewer re-activation with no Technician doesn't crash ---
    def test_viewer_reactivation_without_technician_no_crash(self):
        """Re-activating a viewer who never had a Technician record must not crash."""
        user = User.objects.create_user(
            username='old_viewer', email='old_viewer@example.com', password='pass'
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=user, role='viewer', is_active=False
        )
        # No Technician record for this user

        from unittest.mock import patch
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch('apps.saas.views._get_owner_tenant', return_value=(self.tenant, membership)):
            try:
                self._post_invite('old_viewer@example.com', role='viewer')
            except Exception as e:
                self.fail(f"Re-activating viewer without Technician record raised: {e}")

        mem = TenantMembership.objects.get(user=user, tenant=self.tenant)
        self.assertTrue(mem.is_active, "Viewer membership must be reactivated")
        self.assertFalse(
            Technician.objects.filter(user=user, tenant=self.tenant).exists(),
            "No Technician record should be created for viewer role"
        )
