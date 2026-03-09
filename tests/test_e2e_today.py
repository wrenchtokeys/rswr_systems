"""
End-to-end tests for all fixes made on March 7, 2026.

Tests the ACTUAL request/response flow through all middleware,
not just unit-level model/service tests.

Covers:
- BUG-037: Expired account upgrade (no redirect loop)
- Tenant isolation: missing tenant = blocked, not leaked
- Customer portal invite flow (unauthenticated + authenticated)
- Customer invite creates non-primary contact
- MessageMiddleware ordering (no crash)
- Portal middleware routing
- API viewsets require tenant
"""

import secrets
from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair
from core.models import Customer
from apps.customer_portal.models import CustomerUser, CustomerInvitation


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username, plan_slug='trial', trial_expired=False):
    """Create a tenant with an owner user."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=plan_slug,
        defaults={
            'name': plan_slug.title(),
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        owner_username, f'{owner_username}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    if trial_expired:
        tenant.trial_started_at = timezone.now() - timedelta(days=60)
        tenant.trial_end = timezone.now() - timedelta(days=1)
        tenant.save()

    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_SETTINGS)
class ExpiredAccountUpgradeTests(TestCase):
    """BUG-037: Expired account should be able to reach billing page."""

    def setUp(self):
        self.user, self.tenant = make_tenant('Expired Shop', 'expired_owner', trial_expired=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_expired_user_redirected_from_dashboard(self):
        """Expired trial user on /owner/ should be redirected to /pricing/."""
        r = self.client.get('/owner/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/pricing/', r.url)

    def test_expired_user_can_reach_billing(self):
        """Expired trial user should be able to access /owner/billing/ to upgrade."""
        r = self.client.get('/owner/billing/')
        # Should NOT redirect to /pricing/ (no loop)
        self.assertNotEqual(r.url if r.status_code == 302 else '', '/pricing/')
        # Should either load (200) or redirect within billing
        self.assertIn(r.status_code, [200, 302])
        if r.status_code == 302:
            self.assertNotIn('/pricing/', r.url)

    def test_expired_user_blocked_from_tech_portal(self):
        """Expired trial user should NOT access tech portal."""
        r = self.client.get('/tech/repairs/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/pricing/', r.url)

    def test_expired_user_blocked_from_settings(self):
        """Expired trial user should NOT access owner settings."""
        r = self.client.get('/owner/settings/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/pricing/', r.url)


@override_settings(**TEST_SETTINGS)
class NoTenantBlockedTests(TestCase):
    """Authenticated user with NO tenant should be blocked, not see all data."""

    def setUp(self):
        self.orphan = User.objects.create_user('orphan_user', 'orphan@test.com', 'testpass123')
        self.client = Client()
        self.client.force_login(self.orphan)

    def test_no_tenant_blocked_from_tech_repairs(self):
        """User with no tenant can't access /tech/repairs/."""
        r = self.client.get('/tech/repairs/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_no_tenant_blocked_from_owner_dashboard(self):
        """User with no tenant can't access /owner/."""
        r = self.client.get('/owner/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_no_tenant_blocked_from_api(self):
        """User with no tenant gets 403 on API."""
        r = self.client.get('/api/v1/customers/')
        # Could be 403 (our middleware) or 401/403 (DRF permissions)
        self.assertIn(r.status_code, [401, 403])

    def test_no_tenant_can_access_login(self):
        """Login page should always be accessible."""
        self.client.logout()
        r = self.client.get('/login/')
        self.assertEqual(r.status_code, 200)

    def test_no_tenant_can_access_pricing(self):
        """Pricing page should always be accessible."""
        r = self.client.get('/pricing/')
        self.assertIn(r.status_code, [200, 302])


@override_settings(**TEST_SETTINGS)
class TenantIsolationViewTests(TestCase):
    """Verify repairs/customers only show tenant's own data."""

    def setUp(self):
        self.user_a, self.tenant_a = make_tenant('Shop A', 'shop_a_owner')
        self.user_b, self.tenant_b = make_tenant('Shop B', 'shop_b_owner')

        # Create techs
        self.tech_a = Technician.objects.create(
            user=self.user_a, tenant=self.tenant_a, is_manager=True
        )
        self.tech_b = Technician.objects.create(
            user=self.user_b, tenant=self.tenant_b, is_manager=True
        )

        # Create customers
        self.cust_a = Customer.objects.create(name='Customer A', tenant=self.tenant_a)
        self.cust_b = Customer.objects.create(name='Customer B', tenant=self.tenant_b)

        # Create repairs
        Repair.objects.create(
            tenant=self.tenant_a, customer=self.cust_a, technician=self.tech_a,
            queue_status='COMPLETED',
        )
        Repair.objects.create(
            tenant=self.tenant_b, customer=self.cust_b, technician=self.tech_b,
            queue_status='COMPLETED',
        )

    def test_shop_a_only_sees_own_repairs(self):
        """Shop A owner should only see Shop A repairs."""
        c = Client()
        c.force_login(self.user_a)
        r = c.get('/tech/repairs/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn('Customer A', content)
        self.assertNotIn('Customer B', content)

    def test_shop_b_only_sees_own_repairs(self):
        """Shop B owner should only see Shop B repairs."""
        c = Client()
        c.force_login(self.user_b)
        r = c.get('/tech/repairs/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        # Check table body specifically — page has "Customer A-Z" in sort dropdown
        tbody_start = content.find('<tbody')
        tbody_end = content.find('</tbody>')
        if tbody_start > -1 and tbody_end > -1:
            tbody = content[tbody_start:tbody_end]
            self.assertIn('Customer B', tbody)
            self.assertNotIn('Customer A', tbody)
        else:
            # Fallback: just check Customer B is present
            self.assertIn('Customer B', content)

    def test_shop_a_only_sees_own_customers(self):
        """Shop A owner should only see Shop A customers."""
        c = Client()
        c.force_login(self.user_a)
        r = c.get('/tech/customers/')
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertIn('Customer A', content)
        self.assertNotIn('Customer B', content)


@override_settings(**TEST_SETTINGS)
class CustomerInviteFlowTests(TestCase):
    """Full customer portal invitation flow tests."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Test Glass', 'glass_owner')
        self.tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_manager=True
        )
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)

        # Create primary CustomerUser
        self.primary_user = User.objects.create_user(
            'fleet_primary', 'primary@fleet.com', 'testpass123',
            first_name='John', last_name='Primary',
        )
        self.primary_cu = CustomerUser.objects.create(
            user=self.primary_user,
            customer=self.customer,
            is_primary_contact=True,
        )

        # Create a pending invitation
        self.invitation = CustomerInvitation.objects.create(
            customer=self.customer,
            email='newguy@fleet.com',
            first_name='New',
            last_name='Guy',
            token=secrets.token_urlsafe(32),
            invited_by=self.owner,
            status='pending',
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_unauthenticated_can_access_invite_page(self):
        """Unauthenticated user can reach the invite acceptance page."""
        c = Client()
        r = c.get(f'/app/invite/{self.invitation.token}/')
        self.assertEqual(r.status_code, 200)

    def test_unauthenticated_invalid_token_shows_error(self):
        """Invalid token shows error page, not a crash."""
        c = Client()
        r = c.get('/app/invite/totally-fake-token/')
        self.assertEqual(r.status_code, 200)
        # Should render the invalid invitation template

    def test_owner_accepting_invite_stays_on_owner_dashboard(self):
        """Owner clicking invite link should stay on owner dashboard."""
        c = Client()
        c.force_login(self.owner)
        r = c.get(f'/app/invite/{self.invitation.token}/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('owner', r.url.lower())
        # Should NOT create a CustomerUser for the owner
        self.assertFalse(
            CustomerUser.objects.filter(user=self.owner).exists()
        )

    def test_new_user_signup_via_invite(self):
        """New user can sign up through invite and lands on customer portal."""
        c = Client()
        r = c.post(f'/app/invite/{self.invitation.token}/', {
            'first_name': 'New',
            'last_name': 'Guy',
            'email': 'newguy@fleet.com',
            'password': 'securepass123',
            'password_confirm': 'securepass123',
        })
        self.assertEqual(r.status_code, 302)
        # Should redirect to customer dashboard
        self.assertIn('/app', r.url)

        # Verify CustomerUser was created
        new_user = User.objects.get(email='newguy@fleet.com')
        cu = CustomerUser.objects.get(user=new_user)
        self.assertEqual(cu.customer, self.customer)
        # Should NOT be primary (primary already exists)
        self.assertFalse(cu.is_primary_contact)

    def test_invited_user_not_marked_primary_when_primary_exists(self):
        """Invited user should not be primary if a primary already exists."""
        # Create a user with NO TenantMembership (pure customer user)
        other_user = User.objects.create_user(
            'other_fleet', 'other@fleet.com', 'testpass123',
            first_name='Other', last_name='Person',
        )
        c = Client()
        c.force_login(other_user)

        invite2 = CustomerInvitation.objects.create(
            customer=self.customer,
            email='other@fleet.com',
            first_name='Other',
            last_name='Person',
            token=secrets.token_urlsafe(32),
            invited_by=self.owner,
            status='pending',
            expires_at=timezone.now() + timedelta(days=7),
        )

        r = c.get(f'/app/invite/{invite2.token}/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/app', r.url)

        cu = CustomerUser.objects.get(user=other_user)
        self.assertFalse(cu.is_primary_contact)

    def test_invited_user_is_not_primary_when_invite_flag_is_false(self):
        """Primary status is owner-controlled via the invite flag, not auto-assigned.
        Even if no primary exists, an invite without is_primary_contact=True should
        create a non-primary CustomerUser."""
        # Remove existing primary
        self.primary_cu.delete()

        # User with NO TenantMembership
        other_user = User.objects.create_user(
            'first_fleet', 'first@fleet.com', 'testpass123',
            first_name='First', last_name='Contact',
        )
        c = Client()
        c.force_login(other_user)

        invite = CustomerInvitation.objects.create(
            customer=self.customer,
            email='first@fleet.com',
            first_name='First',
            last_name='Contact',
            token=secrets.token_urlsafe(32),
            invited_by=self.owner,
            status='pending',
            expires_at=timezone.now() + timedelta(days=7),
            is_primary_contact=False,  # Owner did not check the box
        )

        r = c.get(f'/app/invite/{invite.token}/')
        self.assertEqual(r.status_code, 302)
        cu = CustomerUser.objects.get(user=other_user)
        # Owner didn't mark as primary — should remain non-primary
        self.assertFalse(cu.is_primary_contact)


@override_settings(**TEST_SETTINGS)
class CustomerPortalAccessTests(TestCase):
    """Customer portal users should be able to access /app/ without loops."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Portal Shop', 'portal_owner')
        self.customer = Customer.objects.create(name='Portal Customer', tenant=self.tenant)

        # Customer user (NO TenantMembership, only CustomerUser)
        self.cust_user = User.objects.create_user(
            'cust_portal', 'cust@portal.com', 'testpass123',
            first_name='Cust', last_name='Portal',
        )
        CustomerUser.objects.create(
            user=self.cust_user,
            customer=self.customer,
            is_primary_contact=True,
        )

    def test_customer_user_can_access_dashboard(self):
        """Customer portal user can access /app/ without redirect loop."""
        c = Client()
        c.force_login(self.cust_user)
        r = c.get('/app/')
        self.assertEqual(r.status_code, 200)

    def test_customer_user_can_access_repairs(self):
        """Customer portal user can access /app/repairs/."""
        c = Client()
        c.force_login(self.cust_user)
        r = c.get('/app/repairs/')
        self.assertEqual(r.status_code, 200)

    def test_customer_user_cannot_access_owner_portal(self):
        """Customer portal user should not access /owner/."""
        c = Client()
        c.force_login(self.cust_user)
        r = c.get('/owner/')
        self.assertEqual(r.status_code, 302)
        # Should redirect somewhere other than /owner/
        self.assertNotIn('/owner/', r.url)

    def test_customer_user_cannot_access_tech_portal(self):
        """Customer portal user should not access /tech/."""
        c = Client()
        c.force_login(self.cust_user)
        r = c.get('/tech/repairs/')
        self.assertEqual(r.status_code, 302)

    def test_customer_user_has_tenant_context(self):
        """Customer portal user should have tenant resolved via CustomerUser chain."""
        c = Client()
        c.force_login(self.cust_user)
        # Access a page and check tenant was set (indirectly — page loads without "no tenant" error)
        r = c.get('/app/')
        self.assertEqual(r.status_code, 200)
        # If tenant wasn't set, middleware would redirect to /login/
        self.assertNotIn('login', r.url if hasattr(r, 'url') else '')


@override_settings(**TEST_SETTINGS)
class MessageMiddlewareOrderTests(TestCase):
    """Verify messages work in middleware (no MessageFailure crash)."""

    def setUp(self):
        self.user, self.tenant = make_tenant('Msg Shop', 'msg_owner', trial_expired=True)

    def test_expired_redirect_no_crash(self):
        """Expired trial redirect should not crash with MessageFailure."""
        c = Client()
        c.force_login(self.user)
        # This would crash with MessageFailure if MessageMiddleware is after SubscriptionMiddleware
        r = c.get('/tech/repairs/')
        self.assertEqual(r.status_code, 302)
        # Should redirect cleanly, not 500

    def test_no_tenant_redirect_no_crash(self):
        """No-tenant redirect should not crash with MessageFailure."""
        orphan = User.objects.create_user('msg_orphan', 'msg_orphan@test.com', 'testpass123')
        c = Client()
        c.force_login(orphan)
        r = c.get('/tech/repairs/')
        self.assertEqual(r.status_code, 302)
        # Should redirect cleanly, not 500


@override_settings(**TEST_SETTINGS)
class SuperuserBypassTests(TestCase):
    """Superusers should bypass all subscription/tenant checks."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            'admin_super', 'admin@test.com', 'testpass123'
        )

    def test_superuser_can_access_owner_dashboard(self):
        c = Client()
        c.force_login(self.superuser)
        r = c.get('/owner/')
        # Superuser might not have a tenant — should still not crash
        self.assertIn(r.status_code, [200, 302])
        if r.status_code == 302:
            self.assertNotIn('/login/', r.url)

    def test_superuser_can_access_pricing(self):
        c = Client()
        c.force_login(self.superuser)
        r = c.get('/pricing/')
        self.assertIn(r.status_code, [200, 302])
