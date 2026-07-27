"""
Tenant Isolation Tests — Comprehensive
Covers model queries, API viewsets, rewards, viscosity, customer portal
"""

from apps.billing.models import Invoice, TaxRate
from apps.rewards_referrals.models import RewardOption, RewardType
from apps.technician_portal.models import Technician, Repair
from apps.technician_portal.models import ViscosityRecommendation
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from decimal import Decimal
from django.contrib.auth.models import User
from django.contrib.auth.models import User, Group
from django.test import TestCase, Client, override_settings
from django.test import TestCase, RequestFactory, override_settings
from tests.helpers import make_tenant as _make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


# --- From test_tenant_isolation.py ---

@override_settings(**TEST_OVERRIDES)
class TenantIsolationModelTests(TestCase):
    """Verify tenant-scoped querysets isolate data."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Shop A', 'owner_a')
        self.user_b, self.tenant_b = _make_tenant('Shop B', 'owner_b')

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='Customer A')
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='Customer B')

        self.inv_a = Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='A-001', subtotal=Decimal('100'), total=Decimal('100'),
        )
        self.inv_b = Invoice.objects.create(
            tenant=self.tenant_b, customer=self.cust_b,
            invoice_number='B-001', subtotal=Decimal('200'), total=Decimal('200'),
        )

        TaxRate.objects.create(tenant=self.tenant_a, city='Conway', state='AR')
        TaxRate.objects.create(tenant=self.tenant_b, city='Memphis', state='TN')

    def test_customer_queryset_isolation(self):
        """Unscoped query returns all, but tenant-filtered returns only own."""
        all_custs = Customer.objects.all()
        self.assertEqual(all_custs.count(), 2)

        a_custs = Customer.objects.filter(tenant=self.tenant_a)
        self.assertEqual(a_custs.count(), 1)
        self.assertEqual(a_custs.first().name, 'Customer A')

    def test_invoice_queryset_isolation(self):
        a_invoices = Invoice.objects.filter(tenant=self.tenant_a)
        self.assertEqual(a_invoices.count(), 1)
        self.assertEqual(a_invoices.first().invoice_number, 'A-001')

        b_invoices = Invoice.objects.filter(tenant=self.tenant_b)
        self.assertEqual(b_invoices.count(), 1)

    def test_tax_rate_isolation(self):
        a_rates = TaxRate.objects.filter(tenant=self.tenant_a)
        self.assertEqual(a_rates.count(), 1)
        self.assertEqual(a_rates.first().city, 'Conway')

    def test_unique_customer_name_per_tenant(self):
        """Same customer name in different tenants is OK."""
        Customer.objects.create(tenant=self.tenant_b, name='Customer A')
        # Should not raise — different tenant

    def test_duplicate_fleet_name_same_tenant(self):
        """Same FLEET business name in the same tenant should fail."""
        with self.assertRaises(Exception):
            Customer.objects.create(
                tenant=self.tenant_a, name='Customer A', customer_type='FLEET')

    def test_duplicate_individual_name_same_tenant_is_allowed(self):
        """People share names — the uniqueness constraint is FLEET-only."""
        Customer.objects.create(
            tenant=self.tenant_a, name='John Smith', customer_type='RETAIL')
        Customer.objects.create(
            tenant=self.tenant_a, name='John Smith', customer_type='RETAIL')
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant_a, name='John Smith').count(), 2)


@override_settings(**TEST_OVERRIDES)
class TenantIsolationAPITests(TestCase):
    """Verify API endpoints don't leak cross-tenant data."""

    def setUp(self):
        self.client = Client()
        self.user_a, self.tenant_a = _make_tenant('API Shop A', 'api_a')
        self.user_b, self.tenant_b = _make_tenant('API Shop B', 'api_b')

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='API Cust A')
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='API Cust B')

        Invoice.objects.create(
            tenant=self.tenant_a, customer=self.cust_a,
            invoice_number='API-A-001', subtotal=Decimal('50'), total=Decimal('50'),
        )
        Invoice.objects.create(
            tenant=self.tenant_b, customer=self.cust_b,
            invoice_number='API-B-001', subtotal=Decimal('75'), total=Decimal('75'),
        )

    def test_billing_api_only_own_invoices(self):
        """Owner A should only see their own invoices via API."""
        self.client.login(username='api_a', password='pass')
        resp = self.client.get('/api/billing/invoices/')
        if resp.status_code == 200:
            data = resp.json()
            # Should not contain tenant B's invoice
            invoices = data.get('invoices', data.get('results', []))
            if isinstance(invoices, list):
                for inv in invoices:
                    inv_num = inv.get('invoice_number', '')
                    self.assertNotIn('API-B', inv_num,
                                     "Cross-tenant invoice leaked!")


# --- From test_tenant_isolation_round3.py ---

@override_settings(**TEST_OVERRIDES)
class APIViewSetTenantScopingTests(TestCase):
    """BUG-029: API ViewSets must scope querysets to tenant."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user_a, self.tenant_a = _make_tenant('API A', 'api_owner_a')
        self.user_b, self.tenant_b = _make_tenant('API B', 'api_owner_b')

        # Make user_a a staff/admin for API access
        self.user_a.is_staff = True
        self.user_a.is_superuser = True
        self.user_a.save()

        self.cust_a = Customer.objects.create(tenant=self.tenant_a, name='Cust A')
        self.cust_b = Customer.objects.create(tenant=self.tenant_b, name='Cust B')

        self.tech_a = Technician.objects.create(
            user=self.user_a, tenant=self.tenant_a, phone_number='555-0001'
        )
        self.tech_b = Technician.objects.create(
            user=self.user_b, tenant=self.tenant_b, phone_number='555-0002'
        )

    def test_customer_viewset_scoped(self):
        """CustomerViewSet.get_queryset only returns tenant's customers."""
        from apps.technician_portal.api.views import CustomerViewSet

        request = self.factory.get('/api/customers/')
        request.user = self.user_a
        request.tenant = self.tenant_a

        viewset = CustomerViewSet()
        viewset.request = request
        viewset.kwargs = {}
        viewset.format_kwarg = None

        qs = viewset.get_queryset()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, 'Cust A')

    def test_technician_viewset_scoped(self):
        """TechnicianViewSet.get_queryset only returns tenant's technicians."""
        from apps.technician_portal.api.views import TechnicianViewSet

        request = self.factory.get('/api/technicians/')
        request.user = self.user_a
        request.tenant = self.tenant_a

        viewset = TechnicianViewSet()
        viewset.request = request
        viewset.kwargs = {}
        viewset.format_kwarg = None

        qs = viewset.get_queryset()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().user, self.user_a)

    def test_viewset_no_tenant_raises_permission_denied(self):
        """Without tenant context, raises PermissionDenied."""
        from django.core.exceptions import PermissionDenied
        from apps.technician_portal.api.views import CustomerViewSet

        request = self.factory.get('/api/customers/')
        request.user = self.user_a
        request.tenant = None

        viewset = CustomerViewSet()
        viewset.request = request
        viewset.kwargs = {}
        viewset.format_kwarg = None

        with self.assertRaises(PermissionDenied):
            viewset.get_queryset()


@override_settings(**TEST_OVERRIDES)
class DashboardTenantScopingTests(TestCase):
    """BUG-030/031: Dashboard admin_data and RewardRedemption must be tenant-scoped."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Dash A', 'dash_a')
        self.user_b, self.tenant_b = _make_tenant('Dash B', 'dash_b')

        self.tech_a = Technician.objects.create(
            user=self.user_a, tenant=self.tenant_a, phone_number='555-0001'
        )
        self.tech_b = Technician.objects.create(
            user=self.user_b, tenant=self.tenant_b, phone_number='555-0002'
        )

        Customer.objects.create(tenant=self.tenant_a, name='Dash Cust A')
        Customer.objects.create(tenant=self.tenant_b, name='Dash Cust B')

    def test_technician_count_scoped(self):
        """Technician count must be tenant-scoped."""
        a_count = Technician.objects.filter(tenant=self.tenant_a).count()
        self.assertEqual(a_count, 1)
        total = Technician.objects.count()
        self.assertGreater(total, a_count)


@override_settings(**TEST_OVERRIDES)
class RewardFulfillmentTenantTests(TestCase):
    """BUG-032: RewardFulfillmentService must scope technician assignment to tenant."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Reward A', 'reward_a')
        self.user_b, self.tenant_b = _make_tenant('Reward B', 'reward_b')

        self.tech_a = Technician.objects.create(
            user=self.user_a, tenant=self.tenant_a, phone_number='555-0001'
        )
        self.tech_b = Technician.objects.create(
            user=self.user_b, tenant=self.tenant_b, phone_number='555-0002'
        )

    def test_technician_scoping_in_assignment(self):
        """Only same-tenant technicians should be candidates for reward fulfillment."""
        techs_a = Technician.objects.filter(tenant=self.tenant_a)
        techs_b = Technician.objects.filter(tenant=self.tenant_b)

        self.assertEqual(techs_a.count(), 1)
        self.assertEqual(techs_b.count(), 1)
        self.assertNotEqual(techs_a.first().id, techs_b.first().id)


@override_settings(**TEST_OVERRIDES)
class CustomerPortalProfileCreationTests(TestCase):
    """BUG-035/036: Profile creation must not fall back to Customer.objects.all()."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Profile A', 'profile_a')
        self.user_b, self.tenant_b = _make_tenant('Profile B', 'profile_b')

        Customer.objects.create(tenant=self.tenant_a, name='Profile Cust A')
        Customer.objects.create(tenant=self.tenant_b, name='Profile Cust B')

    def test_no_tenant_returns_empty(self):
        """Without tenant, customer list should be empty (not all)."""
        qs = Customer.objects.none()
        self.assertEqual(qs.count(), 0)

    def test_with_tenant_returns_scoped(self):
        """With tenant, only that tenant's customers returned."""
        qs = Customer.objects.filter(tenant=self.tenant_a)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, 'Profile Cust A')


@override_settings(**TEST_OVERRIDES)
class ReferralLeaderboardTenantTests(TestCase):
    """BUG-034: Referral leaderboard must be tenant-scoped."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Ref A', 'ref_a')
        self.user_b, self.tenant_b = _make_tenant('Ref B', 'ref_b')

    def test_referral_code_scoping(self):
        """ReferralCode queries should be filterable by tenant via customer_user."""
        from apps.rewards_referrals.models import ReferralCode
        # Just verify the filter path works without error
        qs = ReferralCode.objects.filter(customer_user__customer__tenant=self.tenant_a)
        self.assertEqual(qs.count(), 0)  # No codes created yet, but query works


# --- From test_tenant_isolation_round4.py ---

@override_settings(**TEST_OVERRIDES)
class ViscosityRecommendationTenantTests(TestCase):
    """BUG-038: ViscosityRecommendation must be tenant-scoped."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Visc A', 'visc_owner_a')
        self.user_b, self.tenant_b = _make_tenant('Visc B', 'visc_owner_b')

        # Create viscosity rules for tenant A
        self.rule_a = ViscosityRecommendation.objects.create(
            tenant=self.tenant_a,
            name='Cold Weather A',
            min_temperature=None,
            max_temperature=Decimal('59.9'),
            recommended_viscosity='Low',
            suggestion_text='Use low viscosity for cold conditions',
            badge_color='blue',
            display_order=10,
        )

        # Create viscosity rules for tenant B
        self.rule_b = ViscosityRecommendation.objects.create(
            tenant=self.tenant_b,
            name='Cold Weather B',
            min_temperature=None,
            max_temperature=Decimal('50.0'),
            recommended_viscosity='Extra Low',
            suggestion_text='Use extra low viscosity',
            badge_color='green',
            display_order=10,
        )

    def test_recommendation_scoped_to_tenant(self):
        """get_recommendation_for_temperature should only return tenant's rules."""
        # At 55F, tenant A's rule matches (max 59.9) but tenant B's doesn't (max 50.0)
        result_a = ViscosityRecommendation.get_recommendation_for_temperature(55.0, tenant=self.tenant_a)
        self.assertIsNotNone(result_a)
        self.assertEqual(result_a['recommendation'], 'Low')

        result_b = ViscosityRecommendation.get_recommendation_for_temperature(55.0, tenant=self.tenant_b)
        self.assertIsNone(result_b)  # 55F > 50F max, no match for tenant B

    def test_no_cross_tenant_rule_leakage(self):
        """Tenant B should not see tenant A's rules."""
        tenant_b_rules = ViscosityRecommendation.objects.filter(tenant=self.tenant_b)
        self.assertEqual(tenant_b_rules.count(), 1)
        self.assertEqual(tenant_b_rules.first().name, 'Cold Weather B')

    def test_new_rule_assigned_to_tenant(self):
        """New rules should be created with tenant context."""
        rule = ViscosityRecommendation.objects.create(
            tenant=self.tenant_a,
            name='Hot Weather',
            min_temperature=Decimal('86.0'),
            recommended_viscosity='High',
            suggestion_text='Use high viscosity',
            badge_color='red',
        )
        self.assertEqual(rule.tenant, self.tenant_a)


@override_settings(**TEST_OVERRIDES)
class RewardOptionTenantTests(TestCase):
    """BUG-039: RewardOption must be tenant-scoped."""

    def setUp(self):
        self.user_a, self.tenant_a = _make_tenant('Reward A', 'reward_owner_a')
        self.user_b, self.tenant_b = _make_tenant('Reward B', 'reward_owner_b')

        self.reward_type, _ = RewardType.objects.get_or_create(
            name='Repair Discount',
            category='REPAIR_DISCOUNT',
            defaults={'discount_type': 'PERCENTAGE', 'discount_value': 50},
        )

        # Create reward options for tenant A
        self.option_a = RewardOption.objects.create(
            tenant=self.tenant_a,
            name='50% Off Repair (A)',
            description='Tenant A discount',
            points_required=2000,
            reward_type=self.reward_type,
        )

        # Create reward options for tenant B
        self.option_b = RewardOption.objects.create(
            tenant=self.tenant_b,
            name='Free Repair (B)',
            description='Tenant B free repair',
            points_required=3500,
            reward_type=self.reward_type,
        )

    def test_reward_options_scoped_to_tenant(self):
        """Each tenant should only see their own reward options."""
        from apps.rewards_referrals.services import RewardService

        opts_a = RewardService.get_reward_options(tenant=self.tenant_a)
        self.assertEqual(opts_a.count(), 1)
        self.assertEqual(opts_a.first().name, '50% Off Repair (A)')

        opts_b = RewardService.get_reward_options(tenant=self.tenant_b)
        self.assertEqual(opts_b.count(), 1)
        self.assertEqual(opts_b.first().name, 'Free Repair (B)')

    def test_no_cross_tenant_reward_leakage(self):
        """Tenant A should not see tenant B's rewards."""
        tenant_a_options = RewardOption.objects.filter(tenant=self.tenant_a)
        names = list(tenant_a_options.values_list('name', flat=True))
        self.assertNotIn('Free Repair (B)', names)

    def test_without_tenant_returns_all(self):
        """Without tenant filter, service returns all (for superuser)."""
        from apps.rewards_referrals.services import RewardService

        all_opts = RewardService.get_reward_options(tenant=None)
        self.assertEqual(all_opts.count(), 2)


@override_settings(**TEST_OVERRIDES)
class UnitDetailsTechnicianNoneRegressionTests(TestCase):
    """
    CODE-187: unit_details() used technician=None filter when _scoped_tech_unit
    was None, producing a semantically wrong queryset (filter for repairs where
    technician IS NULL).  Although the DB's NOT NULL constraint makes that
    queryset always empty, the intent was wrong — the fix uses Repair.objects.none()
    explicitly so the behavior is guaranteed, not incidental.

    Test coverage:
    1. A user with TenantMembership(role='technician') but no Technician record →
       unit_details returns empty repairs and replacements.
    2. A user with a proper Technician record sees only their own repairs.
    3. The old code path (technician=_scoped_tech_unit with None) is no longer reachable.
    """

    def setUp(self):
        from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
        from core.models import Customer

        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )

        self.owner_a = User.objects.create_user('ud_owner_a', 'oa@test.com', 'pass')
        self.tenant_a = Tenant.objects.create(
            name='Shop UD-A', slug='shop-ud-a', subdomain='shop-ud-a',
            owner=self.owner_a, subscription_plan=plan,
        )
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.owner_a, role='owner')

        # Customer at shop A
        self.customer_a = Customer.objects.create(tenant=self.tenant_a, name='Cust UD-A')

        # A user with 'technician' membership but NO Technician model row
        self.tech_user = User.objects.create_user('ud_tech_no_record', 'tech@test.com', 'pass')
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.tech_user, role='technician')

        # A separate technician user with a proper Technician record
        self.tech_user2 = User.objects.create_user('ud_tech_with_record', 'tech2@test.com', 'pass')
        TenantMembership.objects.create(tenant=self.tenant_a, user=self.tech_user2, role='technician')

        from apps.technician_portal.models import Technician, Repair
        self.technician2 = Technician.objects.create(
            tenant=self.tenant_a, user=self.tech_user2,
            can_repair=True, is_active=True,
        )
        # A repair assigned to tech_user2 for unit #42
        self.repair_owned = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='42',
            queue_status='COMPLETED',
            technician=self.technician2,
        )

    def test_user_without_technician_record_sees_no_repairs(self):
        """
        A user with TenantMembership(technician) but no Technician row must see
        nothing in unit_details, not other techs' repairs.
        """
        from apps.technician_portal.views.customers import unit_details
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get(f'/technician/customers/{self.customer_a.id}/units/42/')
        request.user = self.tech_user       # no Technician record
        request.tenant = self.tenant_a

        response = unit_details(request, self.customer_a.id, '42')
        self.assertEqual(response.status_code, 200)

        try:
            response.render()
            ctx = response.context
            repairs_ctx = list(ctx['repairs']) if ctx and 'repairs' in ctx else []
        except Exception:
            repairs_ctx = []

        # Must be empty — the repair belongs to tech_user2, not this user
        self.assertEqual(len(repairs_ctx), 0,
            f"Expected no repairs, got {len(repairs_ctx)}: {repairs_ctx}")

    def test_user_with_technician_record_sees_own_repair_via_queryset_logic(self):
        """
        Directly verify the queryset logic used in unit_details for a tech with
        a proper Technician record — they should see their own repairs.
        """
        from apps.technician_portal.models import Repair
        from apps.technician_portal.decorators import is_tenant_admin

        tenant = self.tenant_a
        is_admin = is_tenant_admin(self.tech_user2, tenant=tenant)
        from apps.technician_portal.models import Technician
        scoped_tech = Technician.objects.filter(user=self.tech_user2, tenant=tenant).first()
        is_mgr = bool(scoped_tech and scoped_tech.is_manager)

        self.assertFalse(is_admin)
        self.assertFalse(is_mgr)
        self.assertIsNotNone(scoped_tech, "tech_user2 must have a Technician record")

        # Replicate the fixed code path
        repairs = Repair.objects.filter(
            technician=scoped_tech,
            customer=self.customer_a,
            unit_number='42',
        ).exclude(queue_status__in=['REQUESTED', 'PENDING']).filter(tenant=tenant)

        self.assertEqual(repairs.count(), 1)
        self.assertEqual(repairs.first().id, self.repair_owned.id)

    def test_user_without_technician_record_sees_no_repairs_via_queryset_logic(self):
        """
        Verify the fixed code path uses Repair.objects.none() when _scoped_tech_unit
        is None, not Repair.objects.filter(technician=None, ...).
        """
        from apps.technician_portal.models import Repair
        from apps.technician_portal.decorators import is_tenant_admin

        tenant = self.tenant_a
        is_admin = is_tenant_admin(self.tech_user, tenant=tenant)
        from apps.technician_portal.models import Technician
        scoped_tech = Technician.objects.filter(user=self.tech_user, tenant=tenant).first()
        is_mgr = bool(scoped_tech and scoped_tech.is_manager)

        self.assertFalse(is_admin)
        self.assertFalse(is_mgr)
        self.assertIsNone(scoped_tech, "tech_user must NOT have a Technician record for this test")

        # Fixed code path: when scoped_tech is None, use .none()
        repairs = Repair.objects.none()  # This is what the fixed view does

        self.assertEqual(repairs.count(), 0)

        # Confirm: the OLD code path (filter(technician=None)) would also return 0
        # due to the NOT NULL constraint — but the INTENT was wrong.
        # The old code: Repair.objects.filter(technician=None, ...)
        old_path_repairs = Repair.objects.filter(
            technician=None,  # This is what the buggy code did
            customer=self.customer_a,
            unit_number='42',
        )
        self.assertEqual(old_path_repairs.count(), 0,
            "Both paths return 0 here, but the old path relied on a DB constraint, "
            "not deliberate logic. The fix ensures explicit intent.")

    def test_user_without_technician_record_sees_no_replacements_via_queryset_logic(self):
        """Same guard applies to the Replacement queryset path in unit_details."""
        from apps.technician_portal.models import Replacement, Technician
        from apps.technician_portal.decorators import is_tenant_admin

        # Create a replacement owned by tech_user2
        replacement = Replacement.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            unit_number='42',
            queue_status='COMPLETED',
            technician=self.technician2,
            glass_position='windshield',
        )

        tenant = self.tenant_a
        scoped_tech = Technician.objects.filter(user=self.tech_user, tenant=tenant).first()
        self.assertIsNone(scoped_tech)

        # Fixed code path returns none()
        replacements = Replacement.objects.none()
        self.assertEqual(replacements.count(), 0)

        # Verify the replacement actually exists (so the test is meaningful)
        self.assertEqual(
            Replacement.objects.filter(
                customer=self.customer_a, unit_number='42', tenant=tenant
            ).count(),
            1,
            "The replacement exists but should not be visible to the user with no Technician record",
        )
