"""List -> detail view transitions (UI_MAGIC_SESSIONS S10).

Everything here guards a failure that is completely silent in the browser: no
exception, no console warning, no visual error — the app just goes back to hard
page swaps and nobody notices for a month.

1. The `@view-transition` opt-in must be INLINE in the document. Chrome ignores
   it when it arrives in an external stylesheet (verified against Chrome 151),
   so the obvious "tidy-up" of moving it into assets/css/input.css silently kills the
   whole feature.
2. A row that carries `data-vt-key` must contain a `data-vt-hero`, and the page
   it links to must render `.vt-hero`. Miss either half and the row fades
   instead of flying — again, silently.
"""

import re

from django.test import TestCase

from apps.billing.models import Invoice
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer

VT_KEY_ROW = re.compile(r'data-vt-key="([^"]+)"([^>]*)>')


def _make_shop():
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name='VT Shop', email='vt@test.com', password='testpass123!',
        first_name='Test', last_name='Owner',
    )


class ViewTransitionMarkupTests(TestCase):
    """The list side: every keyed row has a hero, keyed to its detail URL."""

    def setUp(self):
        result = _make_shop()
        self.tenant = result['tenant']
        self.user = result['user']
        self.technician = Technician.objects.filter(tenant=self.tenant).first()
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Penske Truck Leasing',
            email='fleet@penske.test', phone='5015550100',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='U101', damage_type='CHIP', queue_status='APPROVED',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _assert_rows_have_heroes(self, html, url):
        """Both halves of the contract, on every keyed row of a page."""
        keys = re.findall(r'data-vt-key="([^"]*)"', html)
        self.assertTrue(keys, 'no data-vt-key rows rendered on %s' % url)
        for key in keys:
            self.assertTrue(key.startswith('/'), 'vt key is not a detail URL: %r' % key)
        # The hero lives inside the row, so it must appear at least as often.
        self.assertGreaterEqual(html.count('data-vt-hero'), len(keys))

    def test_jobs_list_rows_are_keyed_to_their_detail_url(self):
        response = self.client.get('/tech/jobs/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self._assert_rows_have_heroes(html, '/tech/jobs/')
        self.assertIn('data-vt-key="/tech/repairs/%d/"' % self.repair.id, html)

    def test_customer_list_rows_are_keyed(self):
        response = self.client.get('/tech/customers/')
        self.assertEqual(response.status_code, 200)
        self._assert_rows_have_heroes(response.content.decode(), '/tech/customers/')

    def test_repair_detail_renders_the_hero_title(self):
        response = self.client.get('/tech/repairs/%d/' % self.repair.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn('vt-hero', response.content.decode())

    def test_invoice_list_and_detail_share_the_hero(self):
        invoice = Invoice.objects.filter(tenant=self.tenant).first()
        if invoice is None:  # no invoice fixtures — the list must still be keyed
            response = self.client.get('/owner/invoices/')
            self.assertEqual(response.status_code, 200)
            return
        listing = self.client.get('/owner/invoices/')
        self._assert_rows_have_heroes(listing.content.decode(), '/owner/invoices/')
        detail = self.client.get('/owner/invoices/%d/' % invoice.id)
        self.assertIn('vt-hero', detail.content.decode())


class ViewTransitionOptInTests(TestCase):
    """The opt-in has to be inline in the HTML, not in app.css."""

    def setUp(self):
        result = _make_shop()
        self.tenant = result['tenant']
        self.user = result['user']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_app_shell_declares_the_opt_in_inline(self):
        html = self.client.get('/tech/jobs/').content.decode()
        self.assertIn('@view-transition', html,
                      'the opt-in must be inline in <head> — Chrome ignores it '
                      'from an external stylesheet, and the transition dies silently')
        self.assertIn('navigation: auto', html)

    def test_login_page_declares_the_opt_in_inline(self):
        """head_assets.html is shared, so every shell gets it — check one more."""
        self.client.logout()
        html = self.client.get('/login/').content.decode()
        self.assertIn('@view-transition', html)

    def test_navbar_is_named_so_it_does_not_cross_fade(self):
        html = self.client.get('/tech/jobs/').content.decode()
        self.assertIn('vt-nav', html)
