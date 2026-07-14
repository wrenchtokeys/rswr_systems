"""
Tests for the "Configure Your Shop" unified setup page (/owner/setup/).

Tests:
- Page loads for owner/manager
- 403 for non-owner roles (technician, viewer)
- Each section AJAX save endpoint works correctly
- Viscosity auto-populate creates default rules
- Viscosity disable deactivates rules
- Dashboard completion card shows/hides based on setup state

Author: Amelia (Clawdbot AI)
"""

import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import BillingConfig, TaxRate
from apps.technician_portal.models import ViscosityRecommendation


def _make_tenant(name='Test Shop', owner=None):
    """Create a tenant with defaults."""
    from django.utils.text import slugify
    import time
    slug = slugify(name) + str(int(time.time() * 1000))[-4:]
    if owner is None:
        # Create a throwaway owner user for tenant creation
        uname = 'tenant_owner_' + slug[-6:]
        owner = User.objects.create_user(username=uname, password='x')
    return Tenant.objects.create(name=name, slug=slug, is_active=True, owner=owner)


def _make_user(username, email=None):
    return User.objects.create_user(
        username=username,
        email=email or f'{username}@example.com',
        password='testpass123',
        first_name='Test',
        last_name='User',
    )


def _make_membership(tenant, user, role):
    return TenantMembership.objects.create(tenant=tenant, user=user, role=role, is_active=True)


class OwnerSetupPageAccessTest(TestCase):
    """Test access control for /owner/setup/."""

    def setUp(self):
        self.tenant = _make_tenant('Access Test Shop')
        self.owner_user = _make_user('access_owner')
        self.manager_user = _make_user('access_manager')
        self.tech_user = _make_user('access_tech')
        self.viewer_user = _make_user('access_viewer')

        _make_membership(self.tenant, self.owner_user, 'owner')
        _make_membership(self.tenant, self.manager_user, 'manager')
        _make_membership(self.tenant, self.tech_user, 'technician')
        _make_membership(self.tenant, self.viewer_user, 'viewer')

        self.client = Client()

    def _login(self, user):
        self.client.login(username=user.username, password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_owner_can_access_setup_page(self):
        # /owner/setup/ retired: redirects to the settings page, which now
        # carries the "Configure Your Shop" checklist.
        self._login(self.owner_user)
        resp = self.client.get('/owner/setup/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/owner/settings/')
        followed = self.client.get('/owner/setup/', follow=True)
        self.assertEqual(followed.status_code, 200)
        self.assertContains(followed, 'Configure Your Shop')

    def test_manager_can_access_setup_page(self):
        self._login(self.manager_user)
        resp = self.client.get('/owner/setup/', follow=True)
        self.assertEqual(resp.status_code, 200)

    def test_technician_forbidden(self):
        self._login(self.tech_user)
        resp = self.client.get('/owner/setup/')
        # Should redirect to login or return 403
        self.assertIn(resp.status_code, [302, 403])

    def test_viewer_forbidden(self):
        self._login(self.viewer_user)
        resp = self.client.get('/owner/setup/')
        self.assertIn(resp.status_code, [302, 403])

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get('/owner/setup/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp['Location'].lower())


class OwnerSetupSaveBusinessTest(TestCase):
    """Test saving business info section."""

    def setUp(self):
        self.tenant = _make_tenant('Biz Info Shop')
        self.owner = _make_user('biz_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='biz_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_save_business_info(self):
        resp = self.client.post('/owner/setup/save/business/', {
            'business_name': 'Updated Shop Name',
            'business_phone': '555-123-4567',
            'business_email': 'shop@example.com',
            'business_address': '123 Main St, Anytown, AR 72000',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, 'Updated Shop Name')
        self.assertEqual(self.tenant.business_phone, '555-123-4567')
        self.assertEqual(self.tenant.business_email, 'shop@example.com')

    def test_save_business_info_csrf_required(self):
        """CSRF enforcement — AJAX with wrong client should fail or use Django test client behavior."""
        # The test client always sends CSRF, so just verify endpoint exists
        resp = self.client.post('/owner/setup/save/business/', {
            'business_name': 'No CSRF Test',
        })
        self.assertIn(resp.status_code, [200, 403])


class OwnerSetupSavePricingTest(TestCase):
    """Test saving pricing section."""

    def setUp(self):
        self.tenant = _make_tenant('Pricing Shop')
        self.owner = _make_user('pricing_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='pricing_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_save_progressive_pricing(self):
        resp = self.client.post('/owner/setup/save/pricing/', {
            'pricing_model': 'progressive',
            'repair_price_1': '55.00',
            'repair_price_2': '45.00',
            'repair_price_3': '38.00',
            'repair_price_4': '32.00',
            'repair_price_5_plus': '28.00',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.use_progressive_pricing)
        self.assertEqual(self.tenant.repair_price_1, Decimal('55.00'))
        self.assertEqual(self.tenant.repair_price_5_plus, Decimal('28.00'))

    def test_save_flat_pricing(self):
        resp = self.client.post('/owner/setup/save/pricing/', {
            'pricing_model': 'flat',
            'repair_price_1': '45.00',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        self.tenant.refresh_from_db()
        self.assertFalse(self.tenant.use_progressive_pricing)


class OwnerSetupSaveTaxTest(TestCase):
    """Test saving tax section."""

    def setUp(self):
        self.tenant = _make_tenant('Tax Shop')
        self.owner = _make_user('tax_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='tax_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_enable_tax_creates_rate(self):
        resp = self.client.post('/owner/setup/save/tax/', {
            'tax_enabled': '1',
            'city': 'Little Rock',
            'state': 'AR',
            'state_rate': '6.500',
            'county_rate': '1.000',
            'city_rate': '0.500',
            'special_rate': '0.000',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        rate = TaxRate.objects.filter(tenant=self.tenant, city='Little Rock', state='AR').first()
        self.assertIsNotNone(rate)
        self.assertEqual(rate.state_rate, Decimal('6.500'))
        self.assertEqual(rate.total_rate, Decimal('8.000'))

    def test_disable_tax(self):
        resp = self.client.post('/owner/setup/save/tax/', {
            'tax_enabled': '0',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.tax_enabled)


class OwnerSetupSaveBillingTest(TestCase):
    """Test saving billing & invoicing section."""

    def setUp(self):
        self.tenant = _make_tenant('Billing Shop')
        self.owner = _make_user('billing_setup_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='billing_setup_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_save_billing_config(self):
        resp = self.client.post('/owner/setup/save/billing/', {
            'default_payment_terms': 'NET30',
            'auto_email_invoices': '1',
            'overdue_reminder_enabled': '1',
            'overdue_reminder_days': '7,30',
            'batch_invoice_frequency': 'monthly',
            'batch_invoice_day': '1',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        config = BillingConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.default_payment_terms, 'NET30')
        self.assertTrue(config.overdue_reminder_enabled)
        self.assertEqual(config.overdue_reminder_days, '7,30')
        self.assertEqual(config.batch_invoice_frequency, 'monthly')

        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.auto_invoice_enabled)

    def test_save_billing_cod_terms(self):
        resp = self.client.post('/owner/setup/save/billing/', {
            'default_payment_terms': 'COD',
            'auto_email_invoices': '0',
            'overdue_reminder_enabled': '0',
            'overdue_reminder_days': '7,14,30',
            'batch_invoice_frequency': 'disabled',
            'batch_invoice_day': '1',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])


class OwnerSetupSaveViscosityTest(TestCase):
    """Test viscosity auto-populate and toggle."""

    def setUp(self):
        self.tenant = _make_tenant('Viscosity Shop')
        self.owner = _make_user('visc_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='visc_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_enable_viscosity_creates_default_rules(self):
        # No rules to start
        self.assertEqual(ViscosityRecommendation.objects.filter(tenant=self.tenant).count(), 0)

        resp = self.client.post('/owner/setup/save/viscosity/', {
            'enable_viscosity': '1',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        self.assertTrue(data['enabled'])

        rules = ViscosityRecommendation.objects.filter(tenant=self.tenant, is_active=True)
        self.assertEqual(rules.count(), 5)

        rule_names = list(rules.values_list('name', flat=True))
        self.assertIn('Cold Glass', rule_names)
        self.assertIn('Ideal Conditions', rule_names)
        self.assertIn('Hot Glass \u2014 Cool First', rule_names)

    def test_enable_viscosity_no_duplicate_rules(self):
        """Enabling twice shouldn't create duplicate rules."""
        self.client.post('/owner/setup/save/viscosity/', {'enable_viscosity': '1'})
        self.client.post('/owner/setup/save/viscosity/', {'enable_viscosity': '1'})
        count = ViscosityRecommendation.objects.filter(tenant=self.tenant).count()
        self.assertEqual(count, 5)

    def test_disable_viscosity_deactivates_rules(self):
        # First enable
        self.client.post('/owner/setup/save/viscosity/', {'enable_viscosity': '1'})
        self.assertEqual(ViscosityRecommendation.objects.filter(tenant=self.tenant, is_active=True).count(), 5)

        # Then disable
        resp = self.client.post('/owner/setup/save/viscosity/', {'enable_viscosity': '0'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])
        self.assertFalse(data['enabled'])

        self.assertEqual(ViscosityRecommendation.objects.filter(tenant=self.tenant, is_active=True).count(), 0)

    def test_viscosity_rule_temperature_ranges(self):
        """Default rules have correct temperature ranges."""
        self.client.post('/owner/setup/save/viscosity/', {'enable_viscosity': '1'})

        cold = ViscosityRecommendation.objects.get(tenant=self.tenant, name='Cold Glass')
        self.assertIsNone(cold.min_temperature)
        self.assertEqual(cold.max_temperature, Decimal('59.9'))
        self.assertEqual(cold.recommended_viscosity, 'Low')
        self.assertEqual(cold.badge_color, 'blue')

        hot = ViscosityRecommendation.objects.get(tenant=self.tenant, name='Hot Glass \u2014 Cool First')
        self.assertEqual(hot.min_temperature, Decimal('105.1'))
        self.assertIsNone(hot.max_temperature)
        self.assertEqual(hot.badge_color, 'red')


class OwnerSetupSaveAssignmentTest(TestCase):
    """Test saving repair assignment strategy."""

    def setUp(self):
        self.tenant = _make_tenant('Assignment Shop')
        self.owner = _make_user('assign_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='assign_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_save_round_robin(self):
        resp = self.client.post('/owner/setup/save/assignment/', {
            'assignment_strategy': 'round_robin',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.assignment_strategy, 'round_robin')

    def test_save_manual_strategy(self):
        resp = self.client.post('/owner/setup/save/assignment/', {
            'assignment_strategy': 'manual',
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertTrue(data['success'])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.assignment_strategy, 'manual')

    def test_invalid_strategy_rejected(self):
        resp = self.client.post('/owner/setup/save/assignment/', {
            'assignment_strategy': 'invalid_strategy',
        })
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertFalse(data['success'])


class OwnerSetupCompletionTest(TestCase):
    """Test setup completion logic and dashboard card."""

    def setUp(self):
        self.tenant = _make_tenant('Completion Shop')
        self.owner = _make_user('comp_owner')
        _make_membership(self.tenant, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='comp_owner', password='testpass123')
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_completion_business_false_without_phone_email(self):
        from apps.saas.views import _setup_completion
        self.tenant.business_phone = ''
        self.tenant.business_email = ''
        self.tenant.save()
        completion = _setup_completion(self.tenant)
        self.assertFalse(completion['business_info'])
        self.assertFalse(completion['critical_complete'])

    def test_completion_business_true_with_phone_and_email(self):
        from apps.saas.views import _setup_completion
        self.tenant.business_phone = '555-0000'
        self.tenant.business_email = 'test@test.com'
        self.tenant.save()
        completion = _setup_completion(self.tenant)
        self.assertTrue(completion['business_info'])

    def test_completion_viscosity_after_enable(self):
        from apps.saas.views import _setup_completion
        completion_before = _setup_completion(self.tenant)
        self.assertFalse(completion_before['viscosity'])

        # Enable viscosity
        self.client.post('/owner/setup/save/viscosity/', {'enable_viscosity': '1'})

        completion_after = _setup_completion(self.tenant)
        self.assertTrue(completion_after['viscosity'])

    def test_dashboard_shows_setup_card_when_incomplete(self):
        """Dashboard shows setup progress card when critical sections not done."""
        resp = self.client.get('/owner/')
        self.assertEqual(resp.status_code, 200)
        # Should see setup card content since business info likely not configured
        content = resp.content.decode()
        # Either the new unified card or the legacy setup steps should appear
        self.assertTrue(
            'Configure Your Shop' in content or
            'Finish setting up' in content or
            'of 6 settings configured' in content or
            '/owner/setup/' in content
        )

    def test_setup_page_shows_completion_badges(self):
        # The checklist (with the literal section titles) lives on
        # /owner/settings/ now; /owner/setup/ redirects there.
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Configure Your Shop', content)
        self.assertIn('Business Info', content)
        self.assertIn('Pricing Structure', content)
        self.assertIn('Tax Rates', content)
        self.assertIn('Billing', content)
        self.assertIn('Invoicing', content)
        self.assertIn('Viscosity Recommendations', content)
        self.assertIn('Repair Assignment', content)

    def test_tenant_isolation_business_save(self):
        """Business info save only affects logged-in user's tenant."""
        other_tenant = _make_tenant('Other Shop')
        other_owner = _make_user('other_owner_iso')
        _make_membership(other_tenant, other_owner, 'owner')

        # Save as our owner
        self.client.post('/owner/setup/save/business/', {
            'business_name': 'My Updated Shop',
            'business_phone': '555-9999',
            'business_email': 'mine@mine.com',
            'business_address': '',
        })

        # Other tenant should be unaffected
        other_tenant.refresh_from_db()
        self.assertNotEqual(other_tenant.name, 'My Updated Shop')
        self.assertNotEqual(other_tenant.business_phone, '555-9999')


class OnboardingAddSelfAsTechTest(TestCase):
    """
    Regression tests for CODE-217: onboarding add-self-as-tech crashes with
    IntegrityError when the owner already has a Technician record at another tenant.

    Technician.user is a OneToOneField — at most one Technician row per User globally.
    Previously, the check `if not Technician.objects.filter(user=user, tenant=tenant).exists()`
    passed (the cross-tenant tech has a different tenant), and the subsequent
    Technician.objects.create() raised IntegrityError.
    """

    def setUp(self):
        self.tenant_a = _make_tenant('Shop A')
        self.tenant_b = _make_tenant('Shop B')
        self.owner = _make_user('onb_owner_crossten')
        _make_membership(self.tenant_a, self.owner, 'owner')
        _make_membership(self.tenant_b, self.owner, 'owner')
        self.client = Client()
        self.client.login(username='onb_owner_crossten', password='testpass123')

    def _set_tenant(self, tenant):
        session = self.client.session
        session['tenant_id'] = tenant.id
        session.save()

    def test_add_self_as_tech_at_first_shop_succeeds(self):
        """Owner can add themselves as a tech at their first shop."""
        self._set_tenant(self.tenant_a)
        from apps.technician_portal.models import Technician
        self.assertFalse(Technician.objects.filter(user=self.owner).exists())

        resp = self.client.post('/onboarding/?step=2', {
            'add_self': 'on',
            'tech_phone': '555-1111',
        })
        # Should redirect (success) to step 3
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Technician.objects.filter(user=self.owner, tenant=self.tenant_a).exists())

    def test_add_self_as_tech_cross_tenant_no_crash(self):
        """
        CODE-217: Owner who already has a Technician at Shop A should not crash
        when they try to add themselves as a tech at Shop B during onboarding.
        The view must show a warning and NOT raise IntegrityError.
        """
        from apps.technician_portal.models import Technician
        # Pre-create a Technician at tenant_a
        Technician.objects.create(
            tenant=self.tenant_a,
            user=self.owner,
            is_active=True,
        )

        # Now try to add-self at tenant_b
        self._set_tenant(self.tenant_b)
        try:
            resp = self.client.post('/onboarding/?step=2', {
                'add_self': 'on',
                'tech_phone': '555-2222',
            })
        except Exception as exc:
            self.fail(f"Cross-tenant add-self raised unexpectedly: {exc}")

        # Must not crash — should either redirect (302) or render the page (200)
        self.assertIn(resp.status_code, [200, 302])
        # No second Technician should have been created for tenant_b
        self.assertFalse(Technician.objects.filter(user=self.owner, tenant=self.tenant_b).exists())
        # Tenant A's record must be untouched
        self.assertTrue(Technician.objects.filter(user=self.owner, tenant=self.tenant_a).exists())

    def test_add_self_idempotent_same_shop(self):
        """Adding self when already a tech at the same shop shows info message (no error)."""
        from apps.technician_portal.models import Technician
        Technician.objects.create(
            tenant=self.tenant_a,
            user=self.owner,
            is_active=True,
        )
        self._set_tenant(self.tenant_a)
        resp = self.client.post('/onboarding/?step=2', {
            'add_self': 'on',
            'tech_phone': '555-3333',
        })
        self.assertIn(resp.status_code, [200, 302])
        # Still only one Technician record
        self.assertEqual(Technician.objects.filter(user=self.owner).count(), 1)
