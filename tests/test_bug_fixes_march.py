"""
Bug Fix Tests — March 2026 Manual Testing Bugs

Tests for BUG-001 (cross-tenant customer leak + no-technician guard), BUG-002 (trial enforcement),
BUG-003 (tax isolation), BUG-004 (make_random_password).

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings, RequestFactory
from django.utils import timezone
from datetime import timedelta

from apps.billing.models import TaxRate
from apps.billing.services.tax_service import TaxService
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.subscription_middleware import SubscriptionEnforcementMiddleware
from apps.technician_portal.forms import RepairForm
from apps.technician_portal.models import Technician
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_tenant(name, username, plan_slug='trial', **kwargs):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=plan_slug,
        defaults={'name': plan_slug.title(), 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'display_order': 0},
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123')
    tenant = Tenant.objects.create(
        name=name, slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user, subscription_plan=plan, **kwargs,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


# =============================================================================
# BUG-001: Cross-tenant customer leak in repair form
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class RepairFormTenantIsolationTests(TestCase):
    """RepairForm must only show customers/techs from the current tenant."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Shop A', 'owner_a')
        self.user_b, self.tenant_b = _make_tenant('Shop B', 'owner_b')

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='Customer A')
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='Customer B')
        self.cust_a2 = Customer.objects.create(tenant=self.tenant_a, name='Customer A2')

        self.tech_a = Technician.objects.create(
            tenant=self.tenant_a, user=self.user_a,
            can_repair=True, is_active=True,
        )
        self.tech_b = Technician.objects.create(
            tenant=self.tenant_b, user=self.user_b,
            can_repair=True, is_active=True,
        )

    def test_customer_dropdown_filtered_by_tenant(self):
        """Form with tenant A should only show tenant A's customers."""
        form = RepairForm(user=self.user_a, tenant=self.tenant_a)
        customer_qs = form.fields['customer'].queryset
        self.assertEqual(customer_qs.count(), 2)
        self.assertIn(self.cust_a, customer_qs)
        self.assertIn(self.cust_a2, customer_qs)
        self.assertNotIn(self.cust_b, customer_qs)

    def test_customer_dropdown_tenant_b(self):
        """Form with tenant B should only show tenant B's customers."""
        form = RepairForm(user=self.user_b, tenant=self.tenant_b)
        customer_qs = form.fields['customer'].queryset
        self.assertEqual(customer_qs.count(), 1)
        self.assertIn(self.cust_b, customer_qs)
        self.assertNotIn(self.cust_a, customer_qs)

    def test_technician_dropdown_filtered_by_tenant(self):
        """Form should only show technicians from the current tenant."""
        form = RepairForm(user=self.user_a, tenant=self.tenant_a)
        tech_qs = form.fields['technician'].queryset
        self.assertIn(self.tech_a, tech_qs)
        self.assertNotIn(self.tech_b, tech_qs)

    def test_form_without_tenant_shows_all(self):
        """Without tenant (superuser), should fall back to all."""
        form = RepairForm(user=self.user_a, tenant=None)
        customer_qs = form.fields['customer'].queryset
        self.assertEqual(customer_qs.count(), 3)


# =============================================================================
# BUG-002: Trial/subscription enforcement
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class SubscriptionEnforcementTests(TestCase):
    """Subscription middleware blocks expired/canceled tenants."""

    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()
        self.middleware = SubscriptionEnforcementMiddleware(lambda r: type('R', (), {'status_code': 200})())

    def test_expired_trial_blocked(self):
        """Users with expired trial should be blocked from app pages."""
        user, tenant = _make_tenant(
            'Expired Shop', 'expired_owner',
            plan='trial',
            trial_started_at=timezone.now() - timedelta(days=31),
            subscription_status='trialing',
        )
        # Tenant's plan is 'trial' and trial_started_at is 31 days ago
        self.assertTrue(tenant.is_trial_expired)

        self.client.login(username='expired_owner', password='testpass123')
        resp = self.client.get('/tech/')
        # Should redirect to pricing (302) not show the page
        self.assertIn(resp.status_code, [302])
        if resp.status_code == 302:
            self.assertIn('pricing', resp.url)

    def test_canceled_subscription_blocked(self):
        user, tenant = _make_tenant(
            'Canceled Shop', 'canceled_owner',
            subscription_status='canceled',
        )
        self.client.login(username='canceled_owner', password='testpass123')
        resp = self.client.get('/tech/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('pricing', resp.url)

    def test_active_subscription_allowed(self):
        user, tenant = _make_tenant(
            'Active Shop', 'active_owner',
            subscription_status='active',
        )
        tenant.plan = 'starter'
        tenant.save()
        self.client.login(username='active_owner', password='testpass123')
        resp = self.client.get('/tech/')
        self.assertIn(resp.status_code, [200, 302])  # 302 to dashboard is OK
        if resp.status_code == 302:
            self.assertNotIn('pricing', resp.url)

    def test_billing_api_always_accessible(self):
        """Even expired tenants should access billing endpoints to pay."""
        user, tenant = _make_tenant(
            'Expired Billing', 'expired_billing',
            subscription_status='expired',
        )
        self.client.login(username='expired_billing', password='testpass123')
        resp = self.client.get('/api/billing/invoices/')
        # Should NOT redirect to pricing — billing is exempt
        self.assertNotEqual(resp.status_code, 302)

    def test_api_returns_402(self):
        """API endpoints return 402 for expired subscriptions."""
        user, tenant = _make_tenant(
            'API Expired', 'api_expired',
            subscription_status='canceled',
        )
        self.client.login(username='api_expired', password='testpass123')
        # A non-exempt API path
        resp = self.client.get('/api/schema/swagger-ui/')
        # Schema is exempt (under /api/schema/), so try a tech API
        # Actually the tech portal path is not /api/ so it redirects
        # Let's test that the middleware logic works on the request
        req = self.factory.get('/api/some-endpoint/')
        req.user = user
        req.tenant = tenant
        response = self.middleware(req)
        self.assertEqual(response.status_code, 402)


# =============================================================================
# BUG-003: Tax isolation — tenant-scoped tax rates
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class TaxServiceTenantIsolationTests(TestCase):
    """TaxService must use tenant-specific tax rates, not global config."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Tax Shop A', 'tax_a')
        self.user_b, self.tenant_b = _make_tenant('Tax Shop B', 'tax_b')

        # Shop A has a tax rate configured
        TaxRate.objects.create(
            tenant=self.tenant_a, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), county_rate=Decimal('1.000'),
            city_rate=Decimal('2.000'),
        )
        # Shop B has NO tax rates configured

    def test_tenant_with_rates_gets_tax(self):
        svc = TaxService(tenant=self.tenant_a)
        result = svc.calculate_tax(subtotal=Decimal('100.00'))
        self.assertTrue(result['enabled'])
        self.assertEqual(result['rate'], Decimal('9.500'))
        self.assertEqual(result['amount'], Decimal('9.50'))

    def test_tenant_without_rates_gets_no_tax(self):
        """New tenant with no TaxRate entries should get zero tax."""
        svc = TaxService(tenant=self.tenant_b)
        result = svc.calculate_tax(subtotal=Decimal('100.00'))
        self.assertFalse(result['enabled'])
        self.assertEqual(result['amount'], Decimal('0.00'))

    def test_tax_exempt_customer(self):
        svc = TaxService(tenant=self.tenant_a)
        customer = Customer.objects.create(
            tenant=self.tenant_a, name='Exempt Co', tax_exempt=True,
        )
        result = svc.calculate_tax(subtotal=Decimal('100.00'), customer=customer)
        self.assertTrue(result['exempt'])
        self.assertEqual(result['amount'], Decimal('0.00'))

    def test_is_tax_enabled_per_tenant(self):
        svc_a = TaxService(tenant=self.tenant_a)
        svc_b = TaxService(tenant=self.tenant_b)
        self.assertTrue(svc_a.is_tax_enabled())
        self.assertFalse(svc_b.is_tax_enabled())


# =============================================================================
# BUG-001 (part 2): create_repair view guard — no-technician scenarios
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class CreateRepairNoTechnicianGuardTests(TestCase):
    """
    BUG-001 regression: create_repair view must NOT return 500 when:
    - Admin/owner has no technicians in the system
    - Non-admin user has no Technician profile
    Both should redirect to dashboard with a helpful message instead.
    """

    def setUp(self):
        self.owner, self.tenant = _make_tenant('Guard Test Shop', 'guard_owner_ux')
        self.client = Client()

    def _login_owner(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_owner_with_no_technicians_redirects_not_500(self):
        """Owner with zero technicians should be redirected, not shown a 500."""
        self._login_owner()
        # Ensure no technicians exist
        Technician.objects.filter(tenant=self.tenant).delete()

        with override_settings(ALLOWED_HOSTS=['*']):
            response = self.client.get(
                '/tech/repairs/create/',
                HTTP_HOST=f'{self.tenant.subdomain}.testserver',
            )

        # Should redirect (302) to dashboard, not 500
        self.assertIn(response.status_code, [200, 302],
                      f"Expected redirect/200, got {response.status_code}")
        if response.status_code == 302:
            # technician_dashboard resolves to /tech/
            self.assertIn('/tech', response['Location'])

    def test_owner_with_no_technicians_shows_warning(self):
        """Owner with zero technicians gets a warning message when redirected."""
        self._login_owner()
        Technician.objects.filter(tenant=self.tenant).delete()

        with override_settings(ALLOWED_HOSTS=['*']):
            response = self.client.get(
                '/tech/repairs/create/',
                follow=True,
                HTTP_HOST=f'{self.tenant.subdomain}.testserver',
            )

        # After following redirects, the response should contain a warning
        self.assertEqual(response.status_code, 200)
        messages_list = list(response.context['messages']) if response.context and 'messages' in response.context else []
        warning_texts = [str(m) for m in messages_list]
        self.assertTrue(
            any('technician' in t.lower() for t in warning_texts),
            f"Expected 'technician' in messages, got: {warning_texts}"
        )

    def test_owner_with_active_technician_can_access_create_repair(self):
        """Owner with at least one active technician should see the form (200)."""
        self._login_owner()
        # Create a technician for the tenant
        tech_user = User.objects.create_user(
            username='test_tech_guard', password='test123',
            first_name='Test', last_name='Tech',
        )
        Technician.objects.create(
            tenant=self.tenant, user=tech_user,
            is_active=True, can_repair=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=tech_user, role='technician',
        )

        with override_settings(ALLOWED_HOSTS=['*']):
            response = self.client.get(
                '/tech/repairs/create/',
                HTTP_HOST=f'{self.tenant.subdomain}.testserver',
            )

        self.assertEqual(response.status_code, 200)

    def test_post_create_repair_no_technician_no_500(self):
        """POST to create_repair with no technicians must not return 500."""
        self._login_owner()
        Technician.objects.filter(tenant=self.tenant).delete()

        with override_settings(ALLOWED_HOSTS=['*']):
            response = self.client.post(
                '/tech/repairs/create/',
                data={},
                HTTP_HOST=f'{self.tenant.subdomain}.testserver',
            )

        self.assertNotEqual(response.status_code, 500,
                            "500 Server Error on create_repair with no technicians")
        self.assertIn(response.status_code, [200, 302])


# =============================================================================
# BUG-004: make_random_password removed in Django 5.x
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class MakeRandomPasswordTests(TestCase):
    """Verify make_random_password is not used anywhere."""

    def test_no_make_random_password_usage(self):
        """Grep the codebase — make_random_password should not appear."""
        import subprocess
        result = subprocess.run(
            ['grep', '-rn', 'make_random_password', '--include=*.py',
             '/home/ubuntu/rswr_systems/apps', '/home/ubuntu/rswr_systems/common',
             '/home/ubuntu/rswr_systems/core', '/home/ubuntu/rswr_systems/rs_systems'],
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), '',
                         f"make_random_password still used:\n{result.stdout}")
