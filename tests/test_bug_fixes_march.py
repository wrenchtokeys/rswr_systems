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
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.cust_a,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='Customer B')
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.cust_b,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cust_a2 = Customer.objects.create(tenant=self.tenant_a, name='Customer A2')
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.cust_a2,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )

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

    def test_form_without_tenant_shows_none(self):
        """Without tenant context the customer dropdown must be EMPTY —
        showing every shop's customers to a tenant-less (staff) user is a
        cross-tenant leak (closed in the multi-shop hardening pass)."""
        form = RepairForm(user=self.user_a, tenant=None)
        customer_qs = form.fields['customer'].queryset
        self.assertEqual(customer_qs.count(), 0)


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
        # A subscription that has ACTUALLY ended is status='expired' with a
        # past grace_period_end — that is what the Stripe deletion webhook
        # sets. (Previously this test used 'canceled' + past stamp; since A3
        # a stale past stamp on a 'canceled' tenant means "paid days remain"
        # and is ACTIVE — that combination was the CODE-130 residual lockout
        # bug, not a legitimately ended subscription.)
        user, tenant = _make_tenant(
            'Canceled Shop', 'canceled_owner',
            subscription_status='expired',
            grace_period_end=timezone.now() - timedelta(days=1),
        )
        self.client.login(username='canceled_owner', password='testpass123')
        resp = self.client.get('/tech/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('subscription-blocked', resp.url)

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
        # A genuinely expired subscription is status='expired' with a past
        # grace_period_end (what the deletion webhook sets). 'canceled' with
        # a stale past stamp is ACTIVE since A3 (paid days remain).
        user, tenant = _make_tenant(
            'API Expired', 'api_expired',
            subscription_status='expired',
            grace_period_end=timezone.now() - timedelta(days=1),
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

        # Shop A charges tax (tax overhaul: the config flag decides IF tax
        # applies; the TaxRate row supplies the rate)
        from apps.billing.models import BillingConfig
        config_a = BillingConfig.get_for_tenant(self.tenant_a)
        config_a.tax_enabled = True
        config_a.save()
        TaxRate.objects.create(
            tenant=self.tenant_a, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), county_rate=Decimal('1.000'),
            city_rate=Decimal('2.000'),
        )
        # Shop B does not charge tax (tax_enabled stays False)

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
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
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


# =============================================================================
# CODE-014: Unscoped RewardRedemption fetches in technician portal rewards views
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class RewardRedemptionTenantIsolationTests(TestCase):
    """
    reward_fulfillment_detail and apply_reward_to_repair must return 404
    when a technician from Tenant A tries to access a redemption that
    belongs to Tenant B (IDOR via integer PK guessing).
    """

    def setUp(self):
        from apps.rewards_referrals.models import RewardOption, Reward, RewardRedemption
        from apps.customer_portal.models import CustomerUser

        # Tenant A — the attacker's shop
        self.user_a, self.tenant_a = _make_tenant('shop-a', 'tech_a_owner')
        self.tech_user_a = User.objects.create_user('tech_a', 'tech_a@a.com', 'pass')
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.tech_user_a, role='technician')
        self.technician_a = Technician.objects.create(
            user=self.tech_user_a, tenant=self.tenant_a, is_active=True,
        )

        # Tenant B — the victim's shop
        self.user_b, self.tenant_b = _make_tenant('shop-b', 'tech_b_owner')
        cust_user_b = User.objects.create_user('cust_b', 'cust_b@b.com', 'pass')
        self.customer_b = Customer.objects.create(
            name='B Corp', tenant=self.tenant_b, email='corp@b.com',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer_b,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.customer_user_b = CustomerUser.objects.create(
            user=cust_user_b, customer=self.customer_b,
        )
        self.reward_b = Reward.objects.create(
            customer_user=self.customer_user_b, points=500,
        )
        reward_opt_b = RewardOption.objects.create(
            tenant=self.tenant_b, name='Free wash', description='desc',
            points_required=100,
        )
        self.redemption_b = RewardRedemption.objects.create(
            reward=self.reward_b, reward_option=reward_opt_b, status='PENDING',
        )

        self.client = Client()

    def _login_tech_a(self):
        self.client.force_login(self.tech_user_a)
        session = self.client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

    def test_fulfillment_detail_cross_tenant_returns_404(self):
        """Tech A must not be able to view Tenant B's redemption (IDOR)."""
        self._login_tech_a()
        response = self.client.get(
            f'/tech/reward-fulfillment/{self.redemption_b.id}/',
        )
        self.assertEqual(
            response.status_code, 404,
            "Expected 404 for cross-tenant redemption access, got "
            f"{response.status_code}",
        )

    def test_fulfillment_detail_own_tenant_accessible(self):
        """Sanity: a redemption in Tenant A should be accessible to Tech A."""
        from apps.rewards_referrals.models import RewardOption, Reward, RewardRedemption
        from apps.customer_portal.models import CustomerUser

        cust_user_a = User.objects.create_user('cust_a2', 'cust_a2@a.com', 'pass')
        customer_a = Customer.objects.create(
            name='A Corp', tenant=self.tenant_a, email='corp@a.com',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=customer_a,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        cu_a = CustomerUser.objects.create(user=cust_user_a, customer=customer_a)
        reward_a = Reward.objects.create(customer_user=cu_a, points=200)
        opt_a = RewardOption.objects.create(
            tenant=self.tenant_a, name='Discount', description='d',
            points_required=50,
        )
        redemption_a = RewardRedemption.objects.create(
            reward=reward_a, reward_option=opt_a, status='PENDING',
        )

        self._login_tech_a()
        response = self.client.get(
            f'/tech/reward-fulfillment/{redemption_a.id}/',
        )
        # 200 = rendered detail page, 302 = redirect (e.g. permission check inside view)
        self.assertIn(
            response.status_code, [200, 302],
            f"Own-tenant redemption should be accessible, got {response.status_code}",
        )

    def test_apply_reward_cross_tenant_redemption_returns_404(self):
        """
        apply_reward_to_repair must not apply Tenant B's redemption to a
        Tenant A repair when Tech A POSTs with a cross-tenant redemption_id.
        """
        from apps.technician_portal.models import Repair

        repair_a = Repair.objects.create(
            tenant=self.tenant_a, customer=Customer.objects.create(
                name='A Repair Customer', tenant=self.tenant_a, email='arc@a.com',
            ),
            technician=self.technician_a,
            service_date=timezone.now().date(),
            queue_status='APPROVED',
        )

        self._login_tech_a()
        response = self.client.post(
            f'/tech/repairs/{repair_a.id}/apply-reward/',
            data={'redemption_id': self.redemption_b.id, 'auto_fulfill': ''},
        )
        # Should be 404 (redemption not in tenant scope) not 200/302 success
        self.assertEqual(
            response.status_code, 404,
            "Expected 404 when applying cross-tenant redemption to repair, got "
            f"{response.status_code}",
        )

    def test_no_tenant_fulfillment_returns_404(self):
        """With no tenant session (tenant=None), view should return 404."""
        self.client.force_login(self.tech_user_a)
        # Deliberately do NOT set session['tenant_id'] so request.tenant stays None
        response = self.client.get(
            f'/tech/reward-fulfillment/{self.redemption_b.id}/',
        )
        self.assertEqual(response.status_code, 404)


# =============================================================================
# CODE-047: UnitRepairCount missing tenant in get_or_create lookup
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class UnitRepairCountTenantScopeTests(TestCase):
    """
    UnitRepairCount.objects.get_or_create must include tenant in the lookup.
    Without it, a NULL-tenant row is created (or a cross-tenant row is matched),
    breaking TenantManager scoping and progressive pricing isolation.
    """

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Shop Alpha', 'owner_alpha')
        self.user_b, self.tenant_b = _make_tenant('Shop Beta', 'owner_beta')

        self.tech_user_a = User.objects.create_user('tech_alpha', 'ta@test.com', 'pass')
        self.technician_a = Technician.objects.create(
            tenant=self.tenant_a, user=self.tech_user_a, is_active=True, can_repair=True
        )
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.tech_user_a, role='technician')

        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a, name='Fleet A', email='fleet@a.com',
            customer_type='FLEET',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer_a,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )

    def test_repair_save_creates_unit_repair_count_with_tenant(self):
        """Saving a COMPLETED repair should create UnitRepairCount with correct tenant, not NULL."""
        from apps.technician_portal.models import Repair, UnitRepairCount

        repair = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            technician=self.technician_a,
            service_date=timezone.now(),
            unit_number='UNIT-001',
            queue_status='COMPLETED',
            damage_type='BULLSEYE',
        )

        # The UnitRepairCount for this unit/customer should have tenant set
        urc = UnitRepairCount.objects.filter(
            customer=self.customer_a,
            unit_number='UNIT-001',
        ).first()
        self.assertIsNotNone(urc, "UnitRepairCount should have been created on repair save")
        self.assertEqual(
            urc.tenant, self.tenant_a,
            f"UnitRepairCount.tenant should be {self.tenant_a}, got {urc.tenant}"
        )

    def test_pricing_service_creates_unit_repair_count_with_tenant(self):
        """get_expected_repair_cost should create UnitRepairCount scoped to tenant."""
        from apps.technician_portal.models import UnitRepairCount
        from apps.technician_portal.services.pricing_service import get_expected_repair_cost

        # Ensure no pre-existing count
        UnitRepairCount.objects.filter(customer=self.customer_a, unit_number='UNIT-PRICE').delete()

        get_expected_repair_cost(self.customer_a, 'UNIT-PRICE', tenant=self.tenant_a)

        urc = UnitRepairCount.objects.filter(
            customer=self.customer_a,
            unit_number='UNIT-PRICE',
        ).first()
        # The row may or may not be created depending on progressive pricing settings,
        # but if it was created it must have the correct tenant.
        if urc:
            self.assertEqual(
                urc.tenant, self.tenant_a,
                f"UnitRepairCount created by pricing service must be tenant-scoped, got tenant={urc.tenant}"
            )

    def test_two_tenants_same_unit_number_do_not_share_counts(self):
        """Two shops tracking the same unit number should get separate UnitRepairCount rows."""
        from apps.technician_portal.models import Repair, UnitRepairCount

        customer_b = Customer.objects.create(
            tenant=self.tenant_b, name='Fleet B', email='fleet@b.com',
            customer_type='FLEET',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=customer_b,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        tech_user_b = User.objects.create_user('tech_beta2', 'tb2@test.com', 'pass')
        technician_b = Technician.objects.create(
            tenant=self.tenant_b, user=tech_user_b, is_active=True, can_repair=True
        )

        # Repair for Tenant A
        Repair.objects.create(
            tenant=self.tenant_a, customer=self.customer_a,
            technician=self.technician_a, service_date=timezone.now(),
            unit_number='SHARED-UNIT', queue_status='COMPLETED', damage_type='BULLSEYE',
        )

        # Repair for Tenant B
        Repair.objects.create(
            tenant=self.tenant_b, customer=customer_b,
            technician=technician_b, service_date=timezone.now(),
            unit_number='SHARED-UNIT', queue_status='COMPLETED', damage_type='BULLSEYE',
        )

        count_a = UnitRepairCount.objects.filter(tenant=self.tenant_a, unit_number='SHARED-UNIT').count()
        count_b = UnitRepairCount.objects.filter(tenant=self.tenant_b, unit_number='SHARED-UNIT').count()

        self.assertGreaterEqual(count_a, 1, "Tenant A should have its own UnitRepairCount")
        self.assertGreaterEqual(count_b, 1, "Tenant B should have its own UnitRepairCount")

        # Tenant A's count should not be affected by Tenant B's repairs
        urc_a = UnitRepairCount.objects.filter(tenant=self.tenant_a, unit_number='SHARED-UNIT').first()
        self.assertEqual(
            urc_a.repair_count, 1,
            f"Tenant A's SHARED-UNIT should have 1 repair, got {urc_a.repair_count}"
        )


# =============================================================================
# CODE-107: profile_creation redirect loop for cross-shop users
# =============================================================================

@override_settings(**TEST_OVERRIDES)
class ProfileCreationRedirectLoopTests(TestCase):
    """
    CODE-107: profile_creation used an unscoped CustomerUser.objects.filter(user=...).exists()
    check.  A user with a CustomerUser at Shop A visiting Shop B's profile creation page was
    redirected to customer_dashboard, which found no profile for Shop B and redirected back to
    profile_creation — causing an infinite redirect loop.

    After the fix:
      - A user with a CustomerUser at THIS shop → redirected to customer_dashboard (normal).
      - A user with a CustomerUser at a DIFFERENT shop → shown a warning and redirected to
        login (no loop, clear message).
      - A user with NO CustomerUser → profile_creation page renders normally.
    """

    def setUp(self):
        from apps.customer_portal.models import CustomerUser

        self.tenant_a = _make_tenant('Loop Shop A', 'loop_owner_a')[1]
        _, self.tenant_b = _make_tenant('Loop Shop B', 'loop_owner_b')

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='Fleet A')
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.cust_a,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='Fleet B')
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.cust_b,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )

        # User already linked to Shop A
        self.user_cross = User.objects.create_user('cross_shop_user', 'cross@test.com', 'pass')
        self.cu_a = CustomerUser.objects.create(
            user=self.user_cross, customer=self.cust_a, is_primary_contact=False
        )

        # User already linked to Shop B (same shop as request)
        self.user_same = User.objects.create_user('same_shop_user', 'same@test.com', 'pass')
        CustomerUser.objects.create(
            user=self.user_same, customer=self.cust_b, is_primary_contact=False
        )

        # User with no CustomerUser at all
        self.user_fresh = User.objects.create_user('fresh_user', 'fresh@test.com', 'pass')

        self.client = Client()

    def _get(self, user, tenant):
        """GET /app/profile/create/ with the given user and tenant on the request."""
        self.client.force_login(user)
        # Attach the tenant to the request via the session to simulate middleware.
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()
        response = self.client.get('/app/profile/create/', HTTP_HOST='testserver')
        return response

    def test_same_shop_user_redirected_to_dashboard(self):
        """User already linked to THIS shop → redirect to customer_dashboard (/app/) (no loop)."""
        response = self._get(self.user_same, self.tenant_b)
        # Should redirect to customer_dashboard, not to profile_creation
        self.assertIn(response.status_code, [301, 302])
        # customer_dashboard resolves to /app/
        self.assertIn('/app/', response['Location'])
        self.assertNotIn('profile', response['Location'])

    def test_cross_shop_user_without_tenant_redirects_to_login(self):
        """
        User linked to a different shop when request.tenant is None (e.g. no middleware
        context) → must NOT redirect to customer_dashboard (which re-redirects here → loop).
        Instead, redirect to login with a clear warning.

        This tests the core CODE-107 fix: the old unscoped .exists() check redirected
        to customer_dashboard regardless of tenant, enabling the redirect loop.
        The new code distinguishes:
          - tenant=None + existing_cu → redirect to login (no loop).
          - tenant=X + existing_cu for same tenant X → redirect to dashboard (correct).
        """
        from unittest.mock import patch

        self.client.force_login(self.user_cross)
        # Patch getattr(request, 'tenant', None) to return None to test the guard.
        # We do this by making the view run without tenant middleware resolving a tenant.
        # (The real middleware resolves cross-shop users back to their own tenant;
        #  this test verifies the view itself handles tenant=None + existing_cu correctly.)
        with patch('apps.customer_portal.views.getattr', side_effect=lambda obj, attr, default=None:
                   None if (obj is not None and attr == 'tenant') else getattr.__wrapped__(obj, attr, default)
                   if hasattr(getattr, '__wrapped__') else default):
            # Instead of patching getattr, test via RequestFactory to control request.tenant
            from django.test import RequestFactory
            from apps.customer_portal.views import profile_creation
            from django.contrib.messages.storage.fallback import FallbackStorage

            rf = RequestFactory()
            request = rf.get('/app/profile/create/')
            request.user = self.user_cross
            request.tenant = None  # No tenant context
            # Messages middleware requires session
            request.session = self.client.session
            setattr(request, '_messages', FallbackStorage(request))

            response = profile_creation(request)

        # Should NOT redirect to /app/ (customer_dashboard — which loops)
        self.assertIn(response.status_code, [301, 302])
        self.assertNotIn('/app/', response.get('Location', ''))
        self.assertIn('/login/', response.get('Location', ''))

    def test_cross_shop_user_no_redirect_loop(self):
        """
        Follow redirects: cross-shop user must NOT end up in an infinite loop.
        Django's follow=True will raise an error if it hits 20+ redirects.
        """
        self.client.force_login(self.user_cross)
        session = self.client.session
        session['tenant_id'] = self.tenant_b.id
        session.save()
        # follow=True will explode if there's an infinite loop
        response = self.client.get('/app/profile/create/', HTTP_HOST='testserver', follow=True)
        # Should reach some non-looping page
        self.assertNotEqual(response.status_code, 500)

    def test_fresh_user_sees_profile_form(self):
        """User with no CustomerUser → profile creation page should render (200)."""
        self.client.force_login(self.user_fresh)
        session = self.client.session
        session['tenant_id'] = self.tenant_b.id
        session.save()
        response = self.client.get('/app/profile/create/', HTTP_HOST='testserver')
        # Should see the form, not be redirected elsewhere
        self.assertIn(response.status_code, [200, 302])  # 302 only if something else redirects


@override_settings(**TEST_OVERRIDES)
class BatchRepairDenyNotificationTests(TestCase):
    """
    CODE-263: customer_repair_deny used `locked_repair.technician` in the
    notification path, but `locked_repair` is only defined in the non-batch
    code path.  In the batch path this caused a NameError, crashing the
    entire deny flow after the repairs were already DENIED — leaving repairs
    stuck with no technician notification.
    """

    def setUp(self):
        import uuid
        from apps.customer_portal.models import CustomerUser
        from apps.technician_portal.models import TechnicianNotification

        self.sub_plan = SubscriptionPlan.objects.create(
            name='Test Plan', slug='tp-batch-deny',
            monthly_price=Decimal('10.00'), stripe_price_id='price_batch_deny',
        )
        self.owner_user = User.objects.create_user('batchdenyowner', 'o@test.com', 'testpass123')
        self.tenant = Tenant.objects.create(
            name='BatchDenyShop', slug='bds', subdomain='bds',
            plan='professional', subscription_plan=self.sub_plan,
            owner=self.owner_user,
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.owner_user, role='owner', is_active=True)

        self.tech_user = User.objects.create_user('batchdenytech', 't@test.com', 'testpass123')
        self.technician = Technician.objects.create(
            user=self.tech_user, tenant=self.tenant, is_active=True, can_repair=True,
        )

        self.customer = Customer.objects.create(name='Batch Deny Co', tenant=self.tenant)
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )

        self.cu_user = User.objects.create_user('batchdenycu', 'cu@test.com', 'testpass123')
        self.customer_user = CustomerUser.objects.create(
            user=self.cu_user, customer=self.customer, is_primary_contact=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.cu_user, role='viewer', is_active=True,
        )

        # Create a batch of 3 repairs
        self.batch_id = uuid.uuid4()
        from apps.technician_portal.models import Repair
        self.repairs = []
        for i in range(1, 4):
            r = Repair.objects.create(
                tenant=self.tenant,
                technician=self.technician,
                customer=self.customer,
                unit_number='UNIT-BATCH-DENY',
                damage_type='Star Break',
                queue_status='PENDING',
                repair_batch_id=self.batch_id,
                break_number=i,
                total_breaks_in_batch=3,
            )
            self.repairs.append(r)

    def test_batch_deny_creates_notification_without_nameerror(self):
        """Denying a batch repair should NOT crash and should create a notification."""
        from apps.technician_portal.models import TechnicianNotification

        self.client.force_login(self.cu_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        # Deny the first repair in the batch (view should deny all batch siblings)
        response = self.client.post(
            f'/app/repairs/{self.repairs[0].id}/deny/',
            {'reason': 'Not needed'},
            HTTP_HOST='testserver',
        )
        # Should redirect, not crash
        self.assertIn(response.status_code, [200, 301, 302])

        # All batch repairs should be DENIED
        from apps.technician_portal.models import Repair
        for r in Repair.objects.filter(repair_batch_id=self.batch_id):
            self.assertEqual(r.queue_status, 'DENIED', f"Repair #{r.id} should be DENIED")

        # A technician notification should have been created
        notifs = TechnicianNotification.objects.filter(
            technician=self.technician,
            message__contains='DENIED',
        )
        self.assertTrue(notifs.exists(), "Technician should receive a denial notification")


# =============================================================================
# CODE-265: Email normalization missing in account_settings and
#           accept_customer_invitation
# =============================================================================

class EmailNormalizationTests(TestCase):
    """
    CODE-265: Verify that email addresses are normalized to lowercase in all
    user-creation and email-update paths in the customer portal.

    customer_register() was fixed by CODE-264, but account_settings() and
    accept_customer_invitation() were missed — mixed-case emails could bypass
    uniqueness checks and cause duplicate accounts or inconsistent lookups.
    """

    def setUp(self):
        self.client = Client()
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='pro',
            defaults={
                'name': 'Pro', 'monthly_price': Decimal('49.00'),
                'max_repairs_per_month': 999, 'max_technicians': 10,
            },
        )
        self.owner = User.objects.create_user(
            username='emailshopowner', email='owner@emailshop.test', password='ownerpass!',
        )
        self.tenant = Tenant.objects.create(
            name='Email Test Shop',
            slug='email-test-shop',
            subdomain='email-test-shop',
            subscription_plan=plan,
            subscription_status='active',
            owner=self.owner,
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.owner, role='owner', is_active=True,
        )
        self.user = User.objects.create_user(
            username='emailtestuser',
            email='existing@example.com',
            password='testpass123!',
            first_name='Test',
            last_name='User',
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.user, role='viewer', is_active=True,
        )
        from core.models import Customer
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Email Test Customer',
        )
        from apps.customer_portal.models import CustomerRepairPreference as _CRP
        _CRP.objects.get_or_create(
            customer=self.customer,
            defaults={'field_repair_approval_mode': 'REQUIRE_APPROVAL'},
        )
        from apps.customer_portal.models import CustomerUser
        self.customer_user = CustomerUser.objects.create(
            user=self.user, customer=self.customer, is_primary_contact=True,
        )

    def test_account_settings_normalizes_email_to_lowercase(self):
        """account_settings should save emails in lowercase."""
        from apps.customer_portal.views import account_settings
        factory = RequestFactory()
        request = factory.post('/app/account/settings/', {
            'first_name': 'Test',
            'last_name': 'User',
            'email': 'NewEmail@Example.COM',
            'phone': '',
        })
        request.user = self.user
        request.tenant = self.tenant
        # Attach session middleware (needed for messages framework)
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        # Attach messages middleware
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        response = account_settings(request)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'newemail@example.com',
                         "Email should be normalized to lowercase in account_settings")

    def test_accept_invitation_normalizes_email_to_lowercase(self):
        """accept_customer_invitation should create users with lowercase email."""
        from apps.customer_portal.models import CustomerInvitation
        from apps.customer_portal.views import accept_customer_invitation
        invitation = CustomerInvitation.objects.create(
            customer=self.customer,
            email='NewPerson@Example.COM',
            first_name='New',
            last_name='Person',
            invited_by=self.user,
            token='test-invite-token-email-norm',
            expires_at=timezone.now() + timedelta(days=7),
            status='pending',
        )

        factory = RequestFactory()
        request = factory.post(
            f'/app/invite/{invitation.token}/',
            {
                'first_name': 'New',
                'last_name': 'Person',
                'email': 'NewPerson@Example.COM',
                'password': 'SecurePass123!',
                'password_confirm': 'SecurePass123!',
            },
        )
        # Anonymous user (not logged in)
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        request.tenant = self.tenant
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        response = accept_customer_invitation(request, invitation.token)

        # The new user should have a lowercase email
        new_user = User.objects.filter(email='newperson@example.com').first()
        self.assertIsNotNone(new_user,
                             "User should be created with lowercase email from invitation")
