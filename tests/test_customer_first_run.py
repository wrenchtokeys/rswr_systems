"""
Customer-portal first-run walkthrough.

An invited fleet contact accepting their invitation landed on the dashboard
with no orientation at all — the shop side had tours since Phase 2, the portal
had none. These cover the per-portal-user tour state (a company's second
contact still gets their own walkthrough), the completion endpoint's allow-list
and auth, and the ?tour=1 replay linked from Help.

Also pins the notification dropdown's width: it was `w-full` inside the bell's
inline-block wrapper, which resolved to bell width (~40px) and spilled every
line of text outside the panel on mobile.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings

from apps.customer_portal.models import CustomerUser
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.technician_portal.models import Technician
from core.models import Customer

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
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
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    Technician.objects.create(
        user=user, tenant=tenant, is_active=True, is_manager=True,
    )
    return user, tenant


@override_settings(**TEST_SETTINGS)
class CustomerTourTests(TestCase):

    def setUp(self):
        self.owner, self.tenant = make_tenant('Tour Glass', 'ctour_owner')
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        self.cust_user = User.objects.create_user(
            'ctour_contact', 'contact@fleetco.com', 'testpass123', first_name='Pat',
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer, is_primary_contact=True,
        )
        self.client = Client()
        self.client.force_login(self.cust_user)

    def test_first_dashboard_visit_offers_the_tour(self):
        r = self.client.get('/app/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['tour_slug'], 'customer-dashboard')
        self.assertContains(r, 'data-tour="customer-dashboard"')
        # The host must carry the portal's own endpoint — the shop-side default
        # in tours.js is owner-only and would 302 a customer to the login page.
        self.assertContains(
            r, 'data-tour-complete-url="/app/tours/customer-dashboard/complete/"'
        )

    def test_dashboard_loads_the_tour_scripts(self):
        r = self.client.get('/app/')
        self.assertContains(r, 'driver.iife.js')
        self.assertContains(r, 'js/tours.js')

    def test_completion_is_recorded_and_stops_the_nag(self):
        r = self.client.post('/app/tours/customer-dashboard/complete/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])

        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.has_completed_tour('customer-dashboard'))

        r = self.client.get('/app/')
        self.assertEqual(r.context['tour_slug'], '')
        self.assertNotContains(r, 'data-tour="customer-dashboard"')

    def test_replay_via_query_param(self):
        """?tour=1 (linked from Help) forces a replay after completion."""
        self.client.post('/app/tours/customer-dashboard/complete/')
        r = self.client.get('/app/?tour=1')
        self.assertEqual(r.context['tour_slug'], 'customer-dashboard')
        self.assertContains(r, 'data-tour="customer-dashboard"')

    def test_unknown_slug_404s(self):
        r = self.client.post('/app/tours/not-a-tour/complete/')
        self.assertEqual(r.status_code, 404)

    def test_get_is_not_allowed(self):
        r = self.client.get('/app/tours/customer-dashboard/complete/')
        self.assertEqual(r.status_code, 405)

    def test_anonymous_cannot_complete(self):
        self.client.logout()
        r = self.client.post('/app/tours/customer-dashboard/complete/')
        self.assertIn(r.status_code, (302, 403))
        self.customer_user.refresh_from_db()
        self.assertFalse(self.customer_user.has_completed_tour('customer-dashboard'))

    def test_tour_state_is_per_user_not_per_company(self):
        """A coworker invited later still gets their own walkthrough."""
        self.client.post('/app/tours/customer-dashboard/complete/')

        coworker = User.objects.create_user(
            'ctour_coworker', 'coworker@fleetco.com', 'testpass123', first_name='Sam',
        )
        CustomerUser.objects.create(user=coworker, customer=self.customer)
        other = Client()
        other.force_login(coworker)

        r = other.get('/app/')
        self.assertEqual(r.context['tour_slug'], 'customer-dashboard')

    def test_help_page_links_the_replay(self):
        r = self.client.get('/app/help/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '/app/?tour=1')


@override_settings(**TEST_SETTINGS)
class NotificationBellLayoutTests(TestCase):
    """The dropdown panel must never be sized off its inline-block wrapper."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Bell Glass', 'bell_owner')
        self.customer = Customer.objects.create(name='Bell Fleet', tenant=self.tenant)
        self.cust_user = User.objects.create_user(
            'bell_contact', 'bell@fleetco.com', 'testpass123', first_name='Alex',
        )
        CustomerUser.objects.create(user=self.cust_user, customer=self.customer)
        self.client = Client()
        self.client.force_login(self.cust_user)

    def _menu_attrs(self):
        html = self.client.get('/app/').content.decode()
        return html.split('id="notification-menu"', 1)[1].split('>', 1)[0]

    def test_mobile_panel_is_fixed_to_the_viewport(self):
        """Anchoring to the bell put the panel partly off-screen: the avatar
        menu sits to the bell's right, so `absolute right-0` left ~58px of a
        readable panel past the left edge."""
        menu = self._menu_attrs()
        self.assertIn('fixed', menu)
        self.assertIn('inset-x-3', menu)

    def test_desktop_keeps_the_anchored_dropdown(self):
        menu = self._menu_attrs()
        self.assertIn('sm:absolute', menu)
        self.assertIn('sm:right-0', menu)
        self.assertIn('sm:w-96', menu)

    def test_panel_is_never_sized_off_its_wrapper(self):
        """`w-full` = 100% of the ~40px bell wrapper, not of the screen."""
        self.assertNotIn('w-full', self._menu_attrs())
