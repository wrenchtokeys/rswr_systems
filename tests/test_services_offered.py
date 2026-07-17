"""
Shop services-offered setting (repair / replacement / both).

Covers: the Tenant.services_offered field and properties, the signup
cascade onto the owner's Technician abilities, the owner-settings change
sync, server-side guards on create/request views for un-offered services,
onboarding step 2 invites, self ability edits, and nav gating.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, Client, override_settings

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan, InviteToken
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Replacement
from core.models import Customer
from apps.customer_portal.models import CustomerUser


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def ensure_trial_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
            'is_active': True,
        },
    )
    return plan


def make_shop(business_name, email, services='both'):
    ensure_trial_plan()
    result = create_tenant_with_owner(
        business_name=business_name,
        email=email,
        password='testpass123!',
        first_name='Test',
        last_name='Owner',
        services_offered=services,
    )
    return result['user'], result['tenant']


def login_owner(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


@override_settings(**TEST_SETTINGS)
class ServicesOfferedModelTests(TestCase):

    def test_default_is_both(self):
        user, tenant = make_shop('Both Shop', 'both@test.com')
        self.assertEqual(tenant.services_offered, 'both')
        self.assertTrue(tenant.offers_repairs)
        self.assertTrue(tenant.offers_replacements)

    def test_repair_only_properties(self):
        user, tenant = make_shop('Repair Shop', 'rep@test.com', services='repair')
        self.assertTrue(tenant.offers_repairs)
        self.assertFalse(tenant.offers_replacements)

    def test_replacement_only_properties(self):
        user, tenant = make_shop('Repl Shop', 'repl@test.com', services='replacement')
        self.assertFalse(tenant.offers_repairs)
        self.assertTrue(tenant.offers_replacements)

    def test_invalid_value_falls_back_to_both(self):
        user, tenant = make_shop('Weird Shop', 'weird@test.com', services='nonsense')
        self.assertEqual(tenant.services_offered, 'both')


@override_settings(**TEST_SETTINGS)
class SignupCascadeTests(TestCase):
    """The owner's auto-created Technician follows what the shop does."""

    def test_both_shop_owner_can_do_everything(self):
        user, tenant = make_shop('Both Shop', 'both2@test.com', services='both')
        tech = Technician.objects.get(user=user, tenant=tenant)
        self.assertTrue(tech.can_repair)
        self.assertTrue(tech.can_replace)
        self.assertTrue(tech.is_manager)

    def test_replacement_shop_owner_can_replace(self):
        user, tenant = make_shop('Repl Shop', 'repl2@test.com', services='replacement')
        tech = Technician.objects.get(user=user, tenant=tenant)
        self.assertFalse(tech.can_repair)
        self.assertTrue(tech.can_replace)

    def test_repair_shop_owner_can_repair(self):
        user, tenant = make_shop('Repair Shop', 'rep2@test.com', services='repair')
        tech = Technician.objects.get(user=user, tenant=tenant)
        self.assertTrue(tech.can_repair)
        self.assertFalse(tech.can_replace)


@override_settings(**TEST_SETTINGS)
class SettingsChangeSyncTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_shop('Sync Shop', 'sync@test.com', services='repair')
        self.client = Client()
        login_owner(self.client, self.user, self.tenant)

    def _post_services(self, value):
        return self.client.post('/owner/settings/', {
            'form_type': 'services_offered',
            'services_offered': value,
        })

    def test_change_to_replacement_only_flips_tech_flags(self):
        resp = self._post_services('replacement')
        self.assertEqual(resp.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.services_offered, 'replacement')
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.assertFalse(tech.can_repair)
        self.assertTrue(tech.can_replace)

    def test_change_to_both_enables_missing_service(self):
        # Repair-only shop: owner tech has can_replace=False. Switching to
        # 'both' must give the shop at least one replacement-capable tech.
        self._post_services('both')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.services_offered, 'both')
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.assertTrue(tech.can_repair)
        self.assertTrue(tech.can_replace)

    def test_invalid_value_rejected(self):
        self._post_services('bogus')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.services_offered, 'repair')


@override_settings(**TEST_SETTINGS)
class StaffCreateGuardTests(TestCase):

    def test_repairs_only_shop_blocks_replacement_create(self):
        user, tenant = make_shop('Guard Shop A', 'guarda@test.com', services='repair')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/tech/replacement/new/')
        self.assertEqual(resp.status_code, 302)
        # Historical list stays reachable
        resp = client.get('/tech/replacements/')
        self.assertEqual(resp.status_code, 200)

    def test_replacement_only_shop_blocks_repair_create(self):
        user, tenant = make_shop('Guard Shop B', 'guardb@test.com', services='replacement')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/tech/repairs/create/')
        self.assertEqual(resp.status_code, 302)
        resp = client.get('/tech/repairs/create-multi-break/')
        self.assertEqual(resp.status_code, 302)

    def test_both_shop_allows_both_creates(self):
        user, tenant = make_shop('Guard Shop C', 'guardc@test.com', services='both')
        client = Client()
        login_owner(client, user, tenant)
        self.assertEqual(client.get('/tech/replacement/new/').status_code, 200)
        self.assertEqual(client.get('/tech/repairs/create/').status_code, 200)


@override_settings(**TEST_SETTINGS)
class CustomerRequestGuardTests(TestCase):

    def _make_customer(self, tenant, username):
        customer = Customer.objects.create(name=f'{username} Co', tenant=tenant)
        cust_user = User.objects.create_user(
            username, f'{username}@fleet.com', 'testpass123',
            first_name='Pat', last_name='Contact',
        )
        CustomerUser.objects.create(
            user=cust_user, customer=customer, is_primary_contact=True,
        )
        return cust_user, customer

    def test_repairs_only_shop_rejects_replacement_request(self):
        owner, tenant = make_shop('Cust Shop A', 'custa@test.com', services='repair')
        cust_user, customer = self._make_customer(tenant, 'fleet_a')
        client = Client()
        client.force_login(cust_user)

        resp = client.post('/app/replacements/request/', {
            'unit_number': 'Truck 1',
            'glass_position': 'WINDSHIELD',
            'description': 'Cracked',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Replacement.objects.filter(tenant=tenant).count(), 0)

    def test_replacement_only_shop_rejects_repair_request(self):
        owner, tenant = make_shop('Cust Shop B', 'custb@test.com', services='replacement')
        cust_user, customer = self._make_customer(tenant, 'fleet_b')
        client = Client()
        client.force_login(cust_user)

        resp = client.get('/app/repairs/request/')
        self.assertEqual(resp.status_code, 302)

    def test_replacement_shop_accepts_replacement_request(self):
        owner, tenant = make_shop('Cust Shop C', 'custc@test.com', services='replacement')
        cust_user, customer = self._make_customer(tenant, 'fleet_c')
        client = Client()
        client.force_login(cust_user)

        resp = client.get('/app/replacements/request/')
        self.assertEqual(resp.status_code, 200)


@override_settings(**TEST_SETTINGS)
class OnboardingTechInviteTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_shop('Onboard Shop', 'onb@test.com', services='both')
        self.client = Client()
        login_owner(self.client, self.user, self.tenant)
        # Owner already has a Technician from signup; step 2 adds another person.
        session = self.client.session
        session['onboarding_step'] = '2'
        session.save()

    def test_adding_tech_sends_invite_email(self):
        resp = self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'Randy',
            'tech_last_name': 'Glass',
            'tech_email': 'randy@shop.com',
            'tech_phone': '',
            'tech_can_repair': 'on',
            'tech_can_replace': 'on',
        })
        self.assertEqual(resp.status_code, 302)

        randy = User.objects.get(email='randy@shop.com')
        self.assertFalse(randy.has_usable_password())
        self.assertTrue(
            InviteToken.objects.filter(tenant=self.tenant, user=randy, used_at__isnull=True).exists()
        )
        tech = Technician.objects.get(user=randy, tenant=self.tenant)
        self.assertTrue(tech.is_active)
        self.assertTrue(tech.can_repair)
        self.assertTrue(tech.can_replace)
        self.assertTrue(
            TenantMembership.objects.filter(tenant=self.tenant, user=randy, role='technician', is_active=True).exists()
        )
        invite_mails = [m for m in mail.outbox if 'randy@shop.com' in m.to]
        self.assertEqual(len(invite_mails), 1)
        self.assertIn('/invite/', invite_mails[0].body)

    def test_adding_tech_without_email_is_rejected(self):
        resp = self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'NoEmail',
            'tech_last_name': 'Person',
            'tech_email': '',
        })
        # Invalid form stays on step 2 and creates nothing
        self.assertEqual(User.objects.filter(first_name='NoEmail').count(), 0)

    def test_single_service_shop_forces_flags_on_invite(self):
        # Repairs-only shop: even if the POST claims can_replace, the server
        # derives flags from the shop's services.
        self.tenant.services_offered = 'repair'
        self.tenant.save(update_fields=['services_offered'])
        self.client.post('/onboarding/?step=2', {
            'add_self': '',
            'tech_first_name': 'Forced',
            'tech_last_name': 'Flags',
            'tech_email': 'forced@shop.com',
            'tech_can_repair': '',
            'tech_can_replace': 'on',
        })
        tech = Technician.objects.get(user__email='forced@shop.com', tenant=self.tenant)
        self.assertTrue(tech.can_repair)
        self.assertFalse(tech.can_replace)


@override_settings(**TEST_SETTINGS)
class SelfAbilityEditTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_shop('Self Shop', 'self@test.com', services='both')
        self.client = Client()
        login_owner(self.client, self.user, self.tenant)
        self.membership = TenantMembership.objects.get(tenant=self.tenant, user=self.user)

    def test_owner_can_edit_own_abilities(self):
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        tech.can_replace = False
        tech.save(update_fields=['can_replace'])

        resp = self.client.post(f'/owner/team/{self.membership.id}/update/', {
            'can_repair': 'on',
            'can_replace': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        tech.refresh_from_db()
        self.assertTrue(tech.can_replace)

    def test_owner_cannot_change_own_role(self):
        resp = self.client.post(f'/owner/team/{self.membership.id}/update/', {
            'role': 'technician',
            'can_repair': 'on',
            'can_replace': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.role, 'owner')


@override_settings(**TEST_SETTINGS)
class TeamAddSelfTests(TestCase):
    """Owners can make themselves an assignable technician from the Team tab."""

    def setUp(self):
        self.user, self.tenant = make_shop('AddSelf Shop', 'addself@test.com', services='both')
        self.client = Client()
        login_owner(self.client, self.user, self.tenant)

    def test_owner_without_tech_record_can_add_self(self):
        # Simulate an older shop where signup didn't create the record
        Technician.objects.filter(user=self.user, tenant=self.tenant).delete()

        resp = self.client.get('/owner/settings/?tab=team')
        self.assertContains(resp, 'Add myself as a technician')

        resp = self.client.post('/owner/team/add-self/')
        self.assertEqual(resp.status_code, 302)
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.assertTrue(tech.is_active)
        self.assertTrue(tech.is_manager)
        self.assertTrue(tech.can_repair)
        self.assertTrue(tech.can_replace)

    def test_add_self_reactivates_deactivated_record(self):
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        tech.is_active = False
        tech.save(update_fields=['is_active'])

        self.client.post('/owner/team/add-self/')
        tech.refresh_from_db()
        self.assertTrue(tech.is_active)

    def test_add_self_follows_shop_services(self):
        Technician.objects.filter(user=self.user, tenant=self.tenant).delete()
        self.tenant.services_offered = 'replacement'
        self.tenant.save(update_fields=['services_offered'])

        self.client.post('/owner/team/add-self/')
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.assertFalse(tech.can_repair)
        self.assertTrue(tech.can_replace)

    def test_callout_hidden_when_already_technician(self):
        resp = self.client.get('/owner/settings/?tab=team')
        self.assertNotContains(resp, 'Add myself as a technician')

    def test_add_self_is_idempotent(self):
        resp = self.client.post('/owner/team/add-self/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            Technician.objects.filter(user=self.user, tenant=self.tenant).count(), 1
        )


@override_settings(**TEST_SETTINGS)
class NavGatingTests(TestCase):

    def test_repairs_only_hides_replacement_nav(self):
        user, tenant = make_shop('Nav Shop A', 'nava@test.com', services='repair')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/owner/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'New Replacement')
        self.assertContains(resp, 'New Repair')

    def test_replacement_only_hides_repair_nav(self):
        user, tenant = make_shop('Nav Shop B', 'navb@test.com', services='replacement')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/owner/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'New Repair')
        self.assertContains(resp, 'New Replacement')

    def test_both_shows_everything(self):
        user, tenant = make_shop('Nav Shop C', 'navc@test.com', services='both')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/owner/')
        self.assertContains(resp, 'New Repair')
        self.assertContains(resp, 'New Replacement')

    def test_settings_hides_resin_card_for_replacement_shop(self):
        user, tenant = make_shop('Nav Shop D', 'navd@test.com', services='replacement')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Repair Resin Rules')
        self.assertNotContains(resp, 'Repair Pricing')

    def test_tech_dashboard_shows_replacements_when_offered(self):
        user, tenant = make_shop('Nav Shop E', 'nave@test.com', services='replacement')
        customer = Customer.objects.create(name='Fleet E', tenant=tenant)
        tech = Technician.objects.get(user=user, tenant=tenant)
        Replacement.objects.create(
            tenant=tenant, customer=customer, technician=tech,
            queue_status='APPROVED', glass_position='WINDSHIELD',
        )
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/tech/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'My Replacements')

    def test_tech_dashboard_hides_replacements_for_repair_shop(self):
        user, tenant = make_shop('Nav Shop F', 'navf@test.com', services='repair')
        client = Client()
        login_owner(client, user, tenant)
        resp = client.get('/tech/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'My Replacements')
