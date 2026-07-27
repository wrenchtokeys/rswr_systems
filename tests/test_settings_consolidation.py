"""
Settings has one home.

Shop configuration used to be reachable through two parallel homes:
/owner/settings/ (tabbed) and /settings/ (a second hub with its own navigation
tiles for team, viscosity and warranty). Nothing in the main nav pointed at the
second one — the only way in was from its own sub-pages — so an owner who
landed there could not get back to the settings they knew.

Naming made it worse: the nav item "Billing" was the shop's own subscription
while the "Billing & Tax" tab one click away was what they charge customers.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant, TenantMembership


class SettingsHasOneHomeTests(TestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user('owner_sc', password='pw', email='owner@sc.test')
        self.shop = Tenant.objects.create(
            name='Consolidated Shop', slug='consolidated-shop', plan='trial',
            is_active=True, owner=self.owner_user, services_offered='both',
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')
        Technician.objects.create(
            tenant=self.shop, user=self.owner_user,
            is_active=True, is_manager=True, can_repair=True,
        )
        self.client = Client()
        self.client.force_login(self.owner_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def test_legacy_settings_hub_redirects_into_the_real_one(self):
        response = self.client.get(reverse('manager_settings_dashboard'))
        self.assertRedirects(response, reverse('owner_settings'))

    def test_setup_page_redirects_into_settings(self):
        response = self.client.get(reverse('owner_setup'))
        self.assertRedirects(response, reverse('owner_settings'))

    def test_tax_rates_page_is_gone(self):
        """The per-city tax-rate CRUD was removed in the tax overhaul —
        tax lives in Settings → Billing (tax_settings form) now."""
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('owner_tax_rates')
        response = self.client.get('/owner/tax-rates/')
        self.assertEqual(response.status_code, 404)

    def test_settings_opens_on_the_requested_tab(self):
        response = self.client.get(reverse('owner_settings'), {'tab': 'warranty'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'warranty')

    def test_sub_page_editors_return_to_their_tab(self):
        """A round trip out to an editor should close where it started."""
        for url_name, tab in (
            ('team_overview', 'team'),
            ('manage_warranty_policies', 'warranty'),
            ('manage_viscosity_rules', 'general'),
        ):
            with self.subTest(url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'/owner/settings/?tab={tab}')

    # --- plain language ----------------------------------------------------

    def test_nav_calls_the_subscription_my_plan_not_billing(self):
        """"Billing" in the nav and "Billing & Tax" in settings meant two
        different things one click apart."""
        response = self.client.get(reverse('owner_settings'))
        content = response.content.decode()
        self.assertIn('My Plan', content)
        self.assertNotIn('>Billing</a>', content)

    def test_tabs_use_plain_language(self):
        response = self.client.get(reverse('owner_settings'))
        content = response.content.decode()
        for label in ('My Shop', 'My Team', 'Pricing &amp; Invoicing', 'Card Payments'):
            self.assertIn(label, content)
        self.assertNotIn('Payment Processing', content)
