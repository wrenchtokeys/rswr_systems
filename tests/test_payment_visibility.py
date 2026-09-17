"""
A shop that hasn't finished Stripe Connect must never be made to look like it
can take a card — and its owner must be told.

Two halves of one bug, which is why they are one module:

  * The portal invoice LIST offered "Pay Now" on "is money owed" alone, while
    the DETAIL page it linked to gated the actual form on `can_pay_online`.
    On the day-one state of every shop that is a button leading to a page
    whose only control is Download PDF, with nothing said.
  * The owner setup checklist had no payments row at all, so a shop could
    reach "fully configured", invoice for a month, and never learn the money
    leg was never connected.

Both now read `Tenant.can_accept_payments`, which the public emailed invoice
has always gated on correctly.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from apps.billing.models import Invoice
from apps.customer_portal.models import CustomerUser
from core.models import Customer
from tests.test_e2e_today import make_tenant

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def connect_shop(tenant):
    """Put a tenant in the only state that satisfies can_accept_payments."""
    tenant.stripe_connect_account_id = 'acct_test123'
    tenant.stripe_onboarding_status = 'active'
    tenant.stripe_connect_charges_enabled = True
    tenant.save(update_fields=[
        'stripe_connect_account_id',
        'stripe_onboarding_status',
        'stripe_connect_charges_enabled',
    ])
    return tenant


@override_settings(**TEST_SETTINGS)
class PortalPayNowVisibilityTests(TestCase):
    """The customer half: no Pay Now the next page won't honour."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Pay Shop', 'pay_owner')
        self.tenant.business_phone = '555-0142'
        self.tenant.business_email = 'shop@payshop.test'
        self.tenant.save(update_fields=['business_phone', 'business_email'])

        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, customer_type='FLEET',
        )
        self.cust_user = User.objects.create_user(
            'pay_contact', 'c@fleetco.test', 'pw', first_name='Pat', last_name='Contact',
        )
        CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer, is_primary_contact=True,
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer, invoice_number='INV-9001',
            status='SENT', subtotal=Decimal('250'), total=Decimal('250'),
        )
        self.client = Client()
        self.client.force_login(self.cust_user)

    def test_list_hides_pay_now_when_the_shop_cannot_take_a_card(self):
        resp = self.client.get('/app/invoices/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['can_pay_online'])
        self.assertNotContains(resp, 'Pay Now')

    def test_list_shows_pay_now_once_connect_is_live(self):
        connect_shop(self.tenant)
        resp = self.client.get('/app/invoices/')
        self.assertTrue(resp.context['can_pay_online'])
        self.assertContains(resp, 'Pay Now')

    def test_detail_explains_itself_instead_of_showing_nothing(self):
        resp = self.client.get(f'/app/invoices/{self.invoice.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['can_pay_online'])
        # The customer is told who to pay and how to reach them, not left with
        # a Download PDF button and no explanation.
        self.assertContains(resp, 'payable directly to')
        self.assertContains(resp, self.tenant.name)
        self.assertContains(resp, '555-0142')
        self.assertContains(resp, 'shop@payshop.test')
        self.assertNotContains(resp, 'Pay Now')

    def test_detail_shows_the_card_form_once_connect_is_live(self):
        connect_shop(self.tenant)
        resp = self.client.get(f'/app/invoices/{self.invoice.id}/')
        self.assertContains(resp, 'Pay Now')
        self.assertNotContains(resp, 'payable directly to')

    def test_a_paid_invoice_offers_neither(self):
        self.invoice.status = 'PAID'
        self.invoice.amount_paid = Decimal('250')
        self.invoice.save()
        resp = self.client.get(f'/app/invoices/{self.invoice.id}/')
        self.assertNotContains(resp, 'Pay Now')
        self.assertNotContains(resp, 'payable directly to')

    def test_the_two_pages_agree_in_both_directions(self):
        """The regression itself: list and detail must never disagree."""
        for connected in (False, True):
            if connected:
                connect_shop(self.tenant)
            listing = self.client.get('/app/invoices/')
            detail = self.client.get(f'/app/invoices/{self.invoice.id}/')
            self.assertEqual(
                listing.context['can_pay_online'],
                detail.context['can_pay_online'],
                f'list and detail disagree when connected={connected}',
            )


@override_settings(**TEST_SETTINGS)
class OwnerPaymentsChecklistTests(TestCase):
    """The owner half: nothing used to say the money leg wasn't connected."""

    def setUp(self):
        self.owner, self.tenant = make_tenant('Checklist Shop', 'checklist_owner')
        self.client = Client()
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _items(self):
        from apps.saas.views import _setup_checklist_items, _setup_completion
        completion = _setup_completion(self.tenant)
        return completion, _setup_checklist_items(self.tenant, completion)

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    def test_checklist_carries_a_payments_row_that_is_todo_until_connect_is_done(self):
        completion, items = self._items()
        row = next((i for i in items if i['label'] == 'Get Paid by Card'), None)
        self.assertIsNotNone(row, 'setup checklist has no card-payments item')
        self.assertEqual(row['status'], 'todo')
        self.assertEqual(row['todo_label'], "Customers can't pay online yet")
        self.assertIn('tab=payments', row['url'])
        self.assertFalse(completion['all_complete'])

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    def test_the_row_turns_done_when_the_shop_can_actually_take_a_card(self):
        connect_shop(self.tenant)
        completion, items = self._items()
        row = next(i for i in items if i['label'] == 'Get Paid by Card')
        self.assertEqual(row['status'], 'done')
        self.assertTrue(completion['payments'])

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    def test_an_unconnected_shop_can_no_longer_reach_a_full_score(self):
        """8/8 configured while unable to take money is the bug."""
        completion, _ = self._items()
        self.assertLess(completion['configured_count'], completion['total_count'])

    @override_settings(STRIPE_SECRET_KEY=None)
    def test_the_row_is_absent_when_the_platform_has_no_stripe_at_all(self):
        """An uncompletable row would hold every shop below 100% forever."""
        completion, items = self._items()
        self.assertFalse(completion['payments_offered'])
        self.assertNotIn('Get Paid by Card', [i['label'] for i in items])

    @override_settings(STRIPE_SECRET_KEY='sk_test_dummy')
    def test_the_dashboard_renders_the_row(self):
        resp = self.client.get('/owner/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Get Paid by Card')
