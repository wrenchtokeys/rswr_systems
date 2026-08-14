"""
Tests for the Mygrant "Connect your account" plumbing (P1 step 4).

Covers: encryption at rest (common/encryption.py), the MygrantConfig model,
the owner Settings card wiring, and the Test-connection endpoint against a
mocked Mygrant SOAP service.
"""
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from cryptography.fernet import Fernet

from common import encryption
from apps.technician_portal import mygrant_service
from apps.technician_portal.parts_models import MygrantConfig
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner


def make_tenant(business_name='Glass Shop', email='owner@test.com', first_name='Test'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name=first_name, last_name='Owner',
    )


def soap_response(status_code='0', status_text='Success'):
    inner = (
        '<MygrantXMLOrderingSystemRequest>'
        '<RequestHeader><RequestType>Inquiry</RequestType></RequestHeader>'
        '<RequestSet />'
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


class EncryptionTests(TestCase):
    def test_dev_key_is_configured_in_tests(self):
        # development.py derives a key from SECRET_KEY, so the suite runs
        # without FIELD_ENCRYPTION_KEY being set in the environment.
        self.assertTrue(encryption.is_configured())

    def test_round_trip(self):
        token = encryption.encrypt_str('hunter2!')
        self.assertNotEqual(token, 'hunter2!')
        self.assertEqual(encryption.decrypt_str(token), 'hunter2!')

    def test_empty_stays_empty(self):
        self.assertEqual(encryption.encrypt_str(''), '')
        self.assertEqual(encryption.decrypt_str(''), '')

    @override_settings(FIELD_ENCRYPTION_KEY='')
    def test_missing_key_refuses_to_encrypt(self):
        with self.assertRaises(ImproperlyConfigured):
            encryption.encrypt_str('secret')
        self.assertFalse(encryption.is_configured())

    @override_settings(FIELD_ENCRYPTION_KEY='not-a-fernet-key')
    def test_invalid_key_is_a_config_error(self):
        with self.assertRaises(ImproperlyConfigured):
            encryption.encrypt_str('secret')

    def test_wrong_key_raises_decryption_error(self):
        token = encryption.encrypt_str('secret')
        with override_settings(FIELD_ENCRYPTION_KEY=Fernet.generate_key().decode()):
            with self.assertRaises(encryption.DecryptionError):
                encryption.decrypt_str(token)


class MygrantConfigModelTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()['tenant']

    def test_secrets_are_ciphertext_in_the_database(self):
        config = MygrantConfig.get_for_tenant(self.tenant)
        config.customer_id = 'C027180-001'
        config.web_user_id = 'glassguy'
        config.password = 'hunter2!'
        config.api_key = 'key-abc-123'
        config.save()

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT password, api_key FROM technician_portal_mygrantconfig WHERE id = %s',
                [config.id],
            )
            raw_password, raw_api_key = cursor.fetchone()
        self.assertNotIn('hunter2', raw_password)
        self.assertNotIn('key-abc-123', raw_api_key)

        reloaded = MygrantConfig.objects.get(id=config.id)
        self.assertEqual(reloaded.password, 'hunter2!')
        self.assertEqual(reloaded.api_key, 'key-abc-123')

    def test_gates(self):
        config = MygrantConfig.get_for_tenant(self.tenant)
        self.assertFalse(config.has_credentials)
        self.assertFalse(config.is_enabled())

        config.customer_id = 'C027180-001'
        config.web_user_id = 'glassguy'
        config.password = 'hunter2!'
        config.save()
        self.assertTrue(config.has_credentials)
        self.assertFalse(config.is_enabled())  # no API key yet

        config.api_key = 'key-abc-123'
        config.save()
        self.assertTrue(config.is_enabled())


class MygrantServiceTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()['tenant']
        self.config = MygrantConfig.get_for_tenant(self.tenant)
        self.config.customer_id = 'C027180-001'
        self.config.web_user_id = 'glassguy'
        self.config.password = 'hunter2!'
        self.config.api_key = 'key-abc-123'
        self.config.save()

    def test_inquiry_document_escapes_xml(self):
        self.config.password = 'a<b&c>'
        doc = mygrant_service._build_inquiry_document(self.config, 'DW', '01658', environment='TEST')
        self.assertIn('<Password>a&lt;b&amp;c&gt;</Password>', doc)
        self.assertIn('<EnvironmentID>TEST</EnvironmentID>', doc)
        self.assertIn('<RequestType>Inquiry</RequestType>', doc)

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_test_connection_success_hits_staging(self, post):
        post.return_value = mock.Mock(status_code=200, text=soap_response())
        detail = mygrant_service.test_connection(self.config)
        self.assertIn('Connected', detail)
        url = post.call_args[0][0]
        self.assertEqual(url, mygrant_service.STAGING_URL)
        headers = post.call_args[1]['headers']
        self.assertEqual(headers['AuthToken'], 'key-abc-123')
        body = post.call_args[1]['data'].decode()
        self.assertIn('<EnvironmentID>TEST</EnvironmentID>', body)

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_test_connection_bad_credentials(self, post):
        post.return_value = mock.Mock(
            status_code=200, text=soap_response('E600', 'NotAuthenticated'),
        )
        with self.assertRaises(mygrant_service.MygrantAuthError):
            mygrant_service.test_connection(self.config)

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_test_connection_network_failure(self, post):
        import requests as requests_lib
        post.side_effect = requests_lib.ConnectionError('boom')
        with self.assertRaises(mygrant_service.MygrantUnavailableError):
            mygrant_service.test_connection(self.config)

    def test_test_connection_requires_api_key(self):
        self.config.api_key = ''
        with self.assertRaises(mygrant_service.MygrantError) as ctx:
            mygrant_service.test_connection(self.config)
        self.assertIn('API key', str(ctx.exception))


class OwnerSettingsCardTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_parts_tab_renders(self):
        response = self.client.get('/owner/settings/?tab=parts')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Connect Your Mygrant Account')

    def test_save_and_keep_secrets_on_blank_resubmit(self):
        response = self.client.post('/owner/settings/', {
            'form_type': 'mygrant_settings',
            'mygrant_customer_id': 'C027180-001',
            'mygrant_web_user_id': 'glassguy',
            'mygrant_password': 'hunter2!',
            'mygrant_api_key': 'key-abc-123',
        })
        self.assertRedirects(response, '/owner/settings/?tab=parts')
        config = MygrantConfig.get_for_tenant(self.tenant)
        self.assertEqual(config.customer_id, 'C027180-001')
        self.assertEqual(config.password, 'hunter2!')
        self.assertEqual(config.api_key, 'key-abc-123')

        # Blank secret fields mean "keep what's stored", not "clear it"
        self.client.post('/owner/settings/', {
            'form_type': 'mygrant_settings',
            'mygrant_customer_id': 'C027180-002',
            'mygrant_web_user_id': 'glassguy',
            'mygrant_password': '',
            'mygrant_api_key': '',
        })
        config = MygrantConfig.objects.get(tenant=self.tenant)
        self.assertEqual(config.customer_id, 'C027180-002')
        self.assertEqual(config.password, 'hunter2!')
        self.assertEqual(config.api_key, 'key-abc-123')

    def test_saving_resets_verification(self):
        config = MygrantConfig.get_for_tenant(self.tenant)
        config.customer_id = 'C027180-001'
        config.web_user_id = 'glassguy'
        config.password = 'hunter2!'
        config.save()
        config.mark_verified()

        self.client.post('/owner/settings/', {
            'form_type': 'mygrant_settings',
            'mygrant_customer_id': 'C027180-001',
            'mygrant_web_user_id': 'glassguy',
            'mygrant_password': 'newpass!',
            'mygrant_api_key': '',
        })
        config.refresh_from_db()
        self.assertIsNone(config.last_verified_at)
        self.assertEqual(config.password, 'newpass!')

    def test_disconnect_deletes_credentials(self):
        config = MygrantConfig.get_for_tenant(self.tenant)
        config.customer_id = 'C027180-001'
        config.web_user_id = 'glassguy'
        config.password = 'hunter2!'
        config.api_key = 'key-abc-123'
        config.save()

        response = self.client.post('/owner/settings/', {'form_type': 'mygrant_disconnect'})
        self.assertRedirects(response, '/owner/settings/?tab=parts')
        config.refresh_from_db()
        self.assertEqual(config.customer_id, '')
        self.assertEqual(config.web_user_id, '')
        self.assertEqual(config.password, '')
        self.assertEqual(config.api_key, '')


class TestConnectionEndpointTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        self.config = MygrantConfig.get_for_tenant(self.tenant)
        self.config.customer_id = 'C027180-001'
        self.config.web_user_id = 'glassguy'
        self.config.password = 'hunter2!'
        self.config.api_key = 'key-abc-123'
        self.config.save()
        self.url = reverse('mygrant_test_connection')

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_success_marks_verified(self, post):
        post.return_value = mock.Mock(status_code=200, text=soap_response())
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.config.refresh_from_db()
        self.assertIsNotNone(self.config.last_verified_at)
        self.assertEqual(self.config.last_verify_error, '')

    @mock.patch('apps.technician_portal.mygrant_service.requests.post')
    def test_auth_failure_records_error(self, post):
        post.return_value = mock.Mock(
            status_code=200, text=soap_response('E600', 'NotAuthenticated'),
        )
        response = self.client.post(self.url)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('rejected the login', data['error'])
        self.config.refresh_from_db()
        self.assertIsNone(self.config.last_verified_at)
        self.assertIn('rejected the login', self.config.last_verify_error)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
