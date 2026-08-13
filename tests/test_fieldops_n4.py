"""
Field ops N4 — SMS opt-in compliance (toll-free registration v2).

The v1 registration was denied for "Unclear Opt-in Language": the consent
surface (shop-side checkbox) named no message types, frequency, rates line,
or STOP/HELP. These tests lock down the fix:

1. Shop-side customer forms carry carrier-compliant disclosure beside the
   consent checkbox (message types, frequency, "Msg & data rates", STOP/HELP,
   link to /sms/).
2. The public invoice page offers a FIRST-PARTY opt-in when the customer has
   a usable mobile and isn't opted in; records CUSTOMER-source consent.
3. Customer.record_sms_consent source semantics: first-party consent
   upgrades shop-attested consent, never the reverse.
"""

import uuid
from decimal import Decimal

from django.test import Client, TestCase

from apps.billing.models import BillingConfig, Invoice
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer
from rs_systems.views import generate_payment_token

BROWSER_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)

# Phrases the carrier reviewer flagged as missing. Every consent surface
# must carry all of them.
REQUIRED_DISCLOSURE = [
    'invoice links and review',      # message types
    'per completed job',             # frequency
    'data rates may apply',          # rates
    'STOP',                          # opt-out keyword
    'HELP',                          # help keyword
    '/sms/',                         # program terms link
]


def make_tenant(business_name='N4 Test Shop', email='n4-owner@test.com'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name='NFour', last_name='Owner',
    )


def make_invoice(tenant, customer):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-N4-{uuid.uuid4().hex[:8]}',
        status='SENT',
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        amount_paid=Decimal('0.00'),
    )


class RecordSmsConsentSourceTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.tenant = result['tenant']
        self.customer = Customer.objects.create(
            name='Consent Co', tenant=self.tenant, phone='501-555-0100',
        )

    def test_default_source_is_shop(self):
        self.customer.record_sms_consent()
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.sms_opt_in)
        self.assertIsNotNone(self.customer.sms_opt_in_at)
        self.assertEqual(self.customer.sms_opt_in_source, Customer.SMS_CONSENT_SHOP)

    def test_customer_source_recorded(self):
        self.customer.record_sms_consent(source=Customer.SMS_CONSENT_CUSTOMER)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.sms_opt_in_source, Customer.SMS_CONSENT_CUSTOMER)

    def test_first_party_upgrades_shop_attested(self):
        self.customer.record_sms_consent()  # shop
        first_at = Customer.objects.get(pk=self.customer.pk).sms_opt_in_at
        self.customer.record_sms_consent(source=Customer.SMS_CONSENT_CUSTOMER)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.sms_opt_in_source, Customer.SMS_CONSENT_CUSTOMER)
        # Upgrade is a new consent event — timestamp refreshed
        self.assertGreaterEqual(self.customer.sms_opt_in_at, first_at)

    def test_shop_attestation_never_downgrades_first_party(self):
        self.customer.record_sms_consent(source=Customer.SMS_CONSENT_CUSTOMER)
        at = Customer.objects.get(pk=self.customer.pk).sms_opt_in_at
        self.customer.record_sms_consent()  # shop, e.g. invoice-text send
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.sms_opt_in_source, Customer.SMS_CONSENT_CUSTOMER)
        self.assertEqual(self.customer.sms_opt_in_at, at)

    def test_form_save_stamps_shop_source(self):
        # Shop-side customer form sets the boolean directly, then save()
        self.customer.sms_opt_in = True
        self.customer.save()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.sms_opt_in_source, Customer.SMS_CONSENT_SHOP)
        self.assertIsNotNone(self.customer.sms_opt_in_at)


class ShopSideDisclosureTests(TestCase):
    """The shop-facing consent checkbox must carry the full disclosure."""

    def setUp(self):
        result = make_tenant(email='n4-shop@test.com')
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        self.customer = Customer.objects.create(
            name='Disclosure Fleet', tenant=self.tenant, phone='501-555-0111',
        )

    def assert_disclosure(self, response):
        content = response.content.decode()
        for phrase in REQUIRED_DISCLOSURE:
            self.assertIn(phrase, content, f"Consent disclosure missing: {phrase!r}")

    def test_customer_create_form_has_disclosure(self):
        response = self.client.get('/tech/customers/create/')
        self.assertEqual(response.status_code, 200)
        self.assert_disclosure(response)

    def test_customer_edit_form_has_disclosure(self):
        response = self.client.get(f'/tech/customers/{self.customer.id}/edit/')
        self.assertEqual(response.status_code, 200)
        self.assert_disclosure(response)


class PublicInvoiceOptInPageTests(TestCase):
    """The first-party opt-in widget on the public invoice page."""

    def setUp(self):
        self.client = Client(HTTP_USER_AGENT=BROWSER_UA)
        result = make_tenant(email='n4-public@test.com')
        self.tenant = result['tenant']
        BillingConfig.objects.get_or_create(tenant=self.tenant)
        self.customer = Customer.objects.create(
            name='Optin Customer', tenant=self.tenant, phone='(501) 555-0123',
        )
        self.invoice = make_invoice(self.tenant, self.customer)
        self.token = generate_payment_token(self.invoice.id)
        self.url = f'/invoice/{self.invoice.id}/{self.token}/'

    def test_widget_offered_with_full_disclosure(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('sms_agree', content)
        self.assertIn('Sign up for texts', content)
        self.assertIn('0123', content)  # masked number: last 4 only
        self.assertNotIn('555-0123', content)  # never the full number
        for phrase in REQUIRED_DISCLOSURE:
            self.assertIn(phrase, content, f"Opt-in disclosure missing: {phrase!r}")
        self.assertIn('not a condition of purchase', content)

    def test_no_widget_without_usable_phone(self):
        self.customer.phone = ''
        self.customer.save()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('sms_agree', response.content.decode())

    def test_confirmation_instead_of_form_when_opted_in(self):
        self.customer.record_sms_consent()
        response = self.client.get(self.url)
        content = response.content.decode()
        self.assertNotIn('sms_agree', content)
        self.assertIn('signed up for text updates', content)
        self.assertIn('STOP', content)


class PublicInvoiceOptInPostTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_USER_AGENT=BROWSER_UA)
        result = make_tenant(email='n4-post@test.com')
        self.tenant = result['tenant']
        BillingConfig.objects.get_or_create(tenant=self.tenant)
        self.customer = Customer.objects.create(
            name='Optin Poster', tenant=self.tenant, phone='501-555-0155',
        )
        self.invoice = make_invoice(self.tenant, self.customer)
        self.token = generate_payment_token(self.invoice.id)
        self.optin_url = f'/invoice/{self.invoice.id}/{self.token}/sms-opt-in/'

    def test_opt_in_records_customer_source_consent(self):
        response = self.client.post(self.optin_url, {'sms_agree': '1'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('sms=thanks', response['Location'])
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.sms_opt_in)
        self.assertEqual(self.customer.sms_opt_in_source, Customer.SMS_CONSENT_CUSTOMER)
        self.assertIsNotNone(self.customer.sms_opt_in_at)

    def test_unchecked_box_records_nothing(self):
        response = self.client.post(self.optin_url, {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('sms=missing', response['Location'])
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.sms_opt_in)
        self.assertEqual(self.customer.sms_opt_in_source, '')

    def test_bad_token_404s_and_records_nothing(self):
        response = self.client.post(
            f'/invoice/{self.invoice.id}/not-the-token/sms-opt-in/', {'sms_agree': '1'},
        )
        self.assertEqual(response.status_code, 404)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.sms_opt_in)

    def test_get_not_allowed(self):
        response = self.client.get(self.optin_url)
        self.assertEqual(response.status_code, 405)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.sms_opt_in)

    def test_no_phone_redirects_without_consent(self):
        self.customer.phone = ''
        self.customer.save()
        response = self.client.post(self.optin_url, {'sms_agree': '1'})
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.sms_opt_in)
