"""
Tests for P1 step 5 — Mygrant quote-only flow.

Service layer (NAGS parsing, Inquiry → SKU list) plus the quote/apply
endpoints on the Replacement, all against a mocked Mygrant response.
"""
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.technician_portal import mygrant_service
from apps.technician_portal.models import Replacement, Technician
from apps.technician_portal.parts_models import MygrantConfig
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


def make_tenant(business_name='Glass Shop', email='owner@test.com'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name='Test', last_name='Owner',
    )


def sku_xml(part='DW01658 GTY FYG', brand='FYG', qty='57', list_price='921.13',
            customer_price='69.08', branch='MGC Hayward, CA', notes='Success',
            code='0', desc='07-14 Chevy Silverado'):
    return (
        '<Response>'
        '<ResponseItemNo>1</ResponseItemNo>'
        '<ResponseProductType>GL</ResponseProductType>'
        f'<ResponseBrand>{brand}</ResponseBrand>'
        f'<QtyAvailable>{qty}</QtyAvailable>'
        '<TruckRun>NIGHT RUN</TruckRun>'
        '<ResponseNextDepartingDate>3/12/2025 12:30:00 PM</ResponseNextDepartingDate>'
        '<ResponseShipFromBranchID>B001</ResponseShipFromBranchID>'
        f'<ResponseShipFromBranchName>{branch}</ResponseShipFromBranchName>'
        f'<ListUnitPrice>{list_price}</ListUnitPrice>'
        f'<CustomerUnitPrice>{customer_price}</CustomerUnitPrice>'
        f'<ResponsePart>{part}</ResponsePart>'
        f'<ResponsePartDesc>{desc}</ResponsePartDesc>'
        f'<ResponseNotes>{notes}</ResponseNotes>'
        f'<ResponseCode>{code}</ResponseCode>'
        '</Response>'
    )


def soap_quote_response(sku_elements='', status_code='0', status_text='Success'):
    inner = (
        '<MygrantXMLOrderingSystemRequest>'
        '<RequestHeader><RequestType>Inquiry</RequestType></RequestHeader>'
        '<RequestSet><RequestItem>'
        '<RequestItemNo>1</RequestItemNo>'
        f'{sku_elements}'
        '</RequestItem></RequestSet>'
        f'<RequestStatusCode>{status_code}</RequestStatusCode>'
        f'<RequestStatusText>{status_text}</RequestStatusText>'
        '</MygrantXMLOrderingSystemRequest>'
    )
    return (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">'
        '<soap:Body>'
        '<InboundTrafficResponse xmlns="http://tempuri.org/">'
        f'<InboundTrafficResult><![CDATA[{inner}]]></InboundTrafficResult>'
        '</InboundTrafficResponse>'
        '</soap:Body>'
        '</soap:Envelope>'
    )


class ParseNagsNumberTests(TestCase):
    def test_accepted_shapes(self):
        for raw, expected in [
            ('DW01658', ('DW', '01658')),
            ('dw 1658', ('DW', '1658')),
            ('FW-2000', ('FW', '2000')),
            ('DW01658 GBY', ('DW', '01658')),
            ('  fw 02000  ', ('FW', '02000')),
        ]:
            self.assertEqual(mygrant_service.parse_nags_number(raw), expected)

    def test_rejected_shapes(self):
        for raw in ('', None, '01658', 'windshield', 'D1658', 'DWX'):
            with self.assertRaises(mygrant_service.MygrantError):
                mygrant_service.parse_nags_number(raw)


class QuoteNagsTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()['tenant']
        self.config = MygrantConfig.get_for_tenant(self.tenant)
        self.config.customer_id = 'C027180-001'
        self.config.web_user_id = 'glassguy'
        self.config.password = 'hunter2!'
        self.config.api_key = 'key-abc-123'
        self.config.save()

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_quote_parses_skus(self, post):
        post.return_value = mock.Mock(
            status_code=200,
            text=soap_quote_response(
                sku_xml() + sku_xml(part='DW01658 GBY FYG', customer_price='69.58',
                                    qty='116', notes='Success'),
            ),
        )
        skus = mygrant_service.quote_nags(self.config, 'DW01658')
        self.assertEqual(len(skus), 2)
        first = skus[0]
        self.assertEqual(first['part'], 'DW01658 GTY FYG')
        self.assertEqual(first['customer_price'], Decimal('69.08'))
        self.assertEqual(first['list_price'], Decimal('921.13'))
        self.assertEqual(first['qty_available'], '57')
        self.assertEqual(first['branch'], 'MGC Hayward, CA')
        self.assertEqual(first['notes'], 'Success')
        # Production environment by default
        self.assertEqual(post.call_args[0][0], mygrant_service.PRODUCTION_URL)
        self.assertIn('<EnvironmentID>PROD</EnvironmentID>', post.call_args[1]['data'].decode())

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_staging_environment_routes_to_staging(self, post):
        post.return_value = mock.Mock(status_code=200, text=soap_quote_response(sku_xml()))
        mygrant_service.quote_nags(self.config, 'DW01658', environment='TEST')
        self.assertEqual(post.call_args[0][0], mygrant_service.STAGING_URL)
        self.assertIn('<EnvironmentID>TEST</EnvironmentID>', post.call_args[1]['data'].decode())

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_no_product_found_is_empty_not_error(self, post):
        post.return_value = mock.Mock(
            status_code=200,
            text=soap_quote_response('', status_code='1', status_text='NoProductFound'),
        )
        self.assertEqual(mygrant_service.quote_nags(self.config, 'DW99999'), [])

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_item_level_errors_surface_in_notes(self, post):
        post.return_value = mock.Mock(
            status_code=200,
            text=soap_quote_response(sku_xml(notes='NoStock', code='5', qty='0')),
        )
        skus = mygrant_service.quote_nags(self.config, 'DW01658')
        self.assertEqual(skus[0]['notes'], 'NoStock')
        self.assertEqual(skus[0]['response_code'], '5')

    def test_disabled_config_refuses(self):
        self.config.api_key = ''
        with self.assertRaises(mygrant_service.MygrantError):
            mygrant_service.quote_nags(self.config, 'DW01658')

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_auth_rejection_is_auth_error(self, post):
        post.return_value = mock.Mock(
            status_code=200,
            text=soap_quote_response('', status_code='E600', status_text='NotAuthenticated'),
        )
        with self.assertRaises(mygrant_service.MygrantAuthError):
            mygrant_service.quote_nags(self.config, 'DW01658')


class QuoteEndpointTestBase(TestCase):
    def setUp(self):
        cache.clear()
        result = make_tenant()
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        self.customer = Customer.objects.create(tenant=self.tenant, name='Penske')
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.technician,
            unit_number='R-100', glass_position='WINDSHIELD',
            nags_number='DW01658', queue_status='APPROVED',
            labor_cost=Decimal('150.00'),
        )
        self.config = MygrantConfig.get_for_tenant(self.tenant)
        self.config.customer_id = 'C027180-001'
        self.config.web_user_id = 'glassguy'
        self.config.password = 'hunter2!'
        self.config.api_key = 'key-abc-123'
        self.config.save()

        self.quote_url = reverse('replacement_mygrant_quote', kwargs={'pk': self.replacement.pk})
        self.apply_url = reverse('replacement_mygrant_apply', kwargs={'pk': self.replacement.pk})


class QuoteEndpointTests(QuoteEndpointTestBase):
    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_quote_returns_skus(self, post):
        post.return_value = mock.Mock(status_code=200, text=soap_quote_response(sku_xml()))
        response = self.client.post(self.quote_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['skus']), 1)
        sku = data['skus'][0]
        self.assertEqual(sku['part'], 'DW01658 GTY FYG')
        self.assertEqual(sku['customer_price'], '69.08')
        self.assertTrue(sku['ok'])

    def test_quote_without_connection_is_400(self):
        self.config.api_key = ''
        self.config.save()
        response = self.client.post(self.quote_url)
        self.assertEqual(response.status_code, 400)

    def test_cross_tenant_is_404(self):
        other = make_tenant(business_name='Other Shop', email='other@test.com')
        self.client.force_login(other['user'])
        session = self.client.session
        session['tenant_id'] = other['tenant'].id
        session.save()
        response = self.client.post(self.quote_url)
        self.assertEqual(response.status_code, 404)

    def test_get_not_allowed(self):
        response = self.client.get(self.quote_url)
        self.assertEqual(response.status_code, 405)


class ApplyEndpointTests(QuoteEndpointTestBase):
    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def _run_quote(self, post):
        post.return_value = mock.Mock(
            status_code=200,
            text=soap_quote_response(
                sku_xml() + sku_xml(part='DW01658 GBY FYG', customer_price='69.58'),
            ),
        )
        return self.client.post(self.quote_url)

    def test_apply_sets_parts_cost_and_recomputes_total(self):
        self._run_quote()
        response = self.client.post(self.apply_url, {'sku_index': 1})
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('DW01658 GBY FYG', data['message'])
        self.replacement.refresh_from_db()
        self.assertEqual(self.replacement.parts_cost, Decimal('69.58'))
        # save() recomputed cost from parts + labor
        self.assertEqual(self.replacement.cost, Decimal('219.58'))

    def test_apply_uses_cached_price_not_client_input(self):
        self._run_quote()
        # Client can only pick an index; a forged price field is ignored
        response = self.client.post(self.apply_url, {'sku_index': 0, 'price': '0.01'})
        self.assertTrue(response.json()['success'])
        self.replacement.refresh_from_db()
        self.assertEqual(self.replacement.parts_cost, Decimal('69.08'))

    def test_apply_without_quote_says_expired(self):
        response = self.client.post(self.apply_url, {'sku_index': 0})
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('expired', data['error'])

    def test_apply_bad_index_is_friendly(self):
        self._run_quote()
        response = self.client.post(self.apply_url, {'sku_index': '99'})
        self.assertFalse(response.json()['success'])

    def test_apply_mentions_cost_override(self):
        self.replacement.cost_override = Decimal('500.00')
        self.replacement.save()
        self._run_quote()
        response = self.client.post(self.apply_url, {'sku_index': 0})
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('override', data['message'])
        self.replacement.refresh_from_db()
        self.assertEqual(self.replacement.parts_cost, Decimal('69.08'))
        self.assertEqual(self.replacement.cost, Decimal('500.00'))


class DetailPageTests(QuoteEndpointTestBase):
    def test_card_renders_when_connected(self):
        response = self.client.get(
            reverse('replacement_detail', kwargs={'pk': self.replacement.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Get Mygrant Quote')

    def test_card_hidden_without_connection(self):
        self.config.api_key = ''
        self.config.save()
        response = self.client.get(
            reverse('replacement_detail', kwargs={'pk': self.replacement.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Get Mygrant Quote')

    def test_card_hidden_without_nags_number(self):
        self.replacement.nags_number = ''
        self.replacement.save()
        response = self.client.get(
            reverse('replacement_detail', kwargs={'pk': self.replacement.pk})
        )
        self.assertNotContains(response, 'Get Mygrant Quote')

    def test_margin_line_shows_after_parts_cost(self):
        self.replacement.parts_cost = Decimal('69.08')
        self.replacement.save()
        response = self.client.get(
            reverse('replacement_detail', kwargs={'pk': self.replacement.pk})
        )
        self.assertContains(response, 'Profit on this job')
        # 219.08 charged - 69.08 parts = 150.00
        self.assertContains(response, '$150.00')
