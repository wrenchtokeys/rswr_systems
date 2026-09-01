"""
Optional SMS invoice delivery tests (PR: feature/sms-invoices).

Covers:
- The Owner Settings "Text Invoices" toggle
- InvoiceSendService.send_sms: body building, consent recording, stamps
- The owner_send_invoice send_sms=1 path (email first, text second)
- Gating: shop toggle off / no phone / platform disabled
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.billing.models import BillingConfig, Invoice
from apps.billing.services.invoice_send_service import InvoiceSendService
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


SMS_SETTINGS = dict(SMS_ENABLED=True, SMS_ORIGINATION_IDENTITY='+18885550100')


def make_tenant(client):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name='Test Shop', email='owner@test.com',
        password='testpass123!', first_name='Test', last_name='Owner',
    )
    client.force_login(result['user'])
    session = client.session
    session['tenant_id'] = result['tenant'].id
    session.save()
    return result


class SmsInvoicingBase(TestCase):
    def setUp(self):
        result = make_tenant(self.client)
        self.user = result['user']
        self.tenant = result['tenant']
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Penske', email='ap@penske.test',
            phone='(501) 282-7129',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-1001', subtotal=Decimal('100.00'),
            total=Decimal('106.50'), status='DRAFT',
        )
        config = BillingConfig.get_for_tenant(self.tenant)
        config.sms_invoicing_enabled = True
        config.save(update_fields=['sms_invoicing_enabled'])


@override_settings(**SMS_SETTINGS)
class SettingsToggleTests(TestCase):
    def test_toggle_sms_invoicing(self):
        result = make_tenant(self.client)
        tenant = result['tenant']
        self.assertFalse(BillingConfig.get_for_tenant(tenant).sms_invoicing_enabled)

        response = self.client.post('/owner/settings/', {'form_type': 'toggle_sms_invoicing'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BillingConfig.get_for_tenant(tenant).sms_invoicing_enabled)

        self.client.post('/owner/settings/', {'form_type': 'toggle_sms_invoicing'})
        self.assertFalse(BillingConfig.get_for_tenant(tenant).sms_invoicing_enabled)


class PlatformDarkMessagingTests(TestCase):
    """While the platform's toll-free number is pending, the settings UI must
    not claim texting works — the toggle-on message and the pending banner
    both say the option will appear once the number is live."""

    def setUp(self):
        result = make_tenant(self.client)
        self.tenant = result['tenant']

    def _toggle_on(self):
        return self.client.post(
            '/owner/settings/', {'form_type': 'toggle_sms_invoicing'}, follow=True)

    @override_settings(SMS_ENABLED=True, SMS_ORIGINATION_IDENTITY='')
    def test_toggle_on_message_is_honest_while_platform_dark(self):
        response = self._toggle_on()
        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn("isn't live yet", text)
        self.assertNotIn('now offers', text)

    @override_settings(**SMS_SETTINGS)
    def test_toggle_on_message_when_platform_ready(self):
        response = self._toggle_on()
        text = ' '.join(str(m) for m in response.context['messages'])
        self.assertIn('now offers', text)

    @override_settings(SMS_ENABLED=True, SMS_ORIGINATION_IDENTITY='')
    def test_pending_banner_shows_even_with_toggle_off(self):
        response = self.client.get('/owner/settings/?tab=billing')
        self.assertContains(response, "texting number isn't live yet")

    @override_settings(**SMS_SETTINGS)
    def test_no_pending_banner_when_platform_ready(self):
        response = self.client.get('/owner/settings/?tab=billing')
        self.assertNotContains(response, "texting number isn't live yet")


@override_settings(**SMS_SETTINGS)
class SendSmsServiceTests(SmsInvoicingBase):
    @patch('core.services.sms_service.SMSService._send_via_aws')
    def test_send_sms_success_stamps_and_consent(self, mock_send):
        mock_send.return_value = 'msg-1'

        ok, msg = InvoiceSendService.send_sms(self.invoice, self.tenant)

        self.assertTrue(ok)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.last_sms_to, '+15012827129')
        self.assertIsNotNone(self.invoice.last_sms_at)
        # Text never changes status — email is the status-driving channel
        self.assertEqual(self.invoice.status, 'DRAFT')

        self.customer.refresh_from_db()
        self.assertTrue(self.customer.sms_opt_in)
        self.assertIsNotNone(self.customer.sms_opt_in_at)

        body = mock_send.call_args[0][1]
        self.assertIn('INV-1001', body)
        self.assertIn('/invoice/', body)
        self.assertIn('Reply STOP to opt out', body)
        self.assertLessEqual(len(body), 160)

    @patch('core.services.sms_service.SMSService._send_via_aws')
    def test_second_text_omits_stop_wording(self, mock_send):
        mock_send.return_value = 'msg-1'
        InvoiceSendService.send_sms(self.invoice, self.tenant)
        InvoiceSendService.send_sms(self.invoice, self.tenant)
        second_body = mock_send.call_args[0][1]
        self.assertNotIn('Reply STOP', second_body)

    @patch('core.services.sms_service.SMSService._send_via_aws')
    def test_long_shop_name_never_truncates_link(self, mock_send):
        mock_send.return_value = 'msg-1'
        self.tenant.name = 'An Extremely Long Auto Glass Repair And Replacement Company Name LLC'
        self.tenant.save()

        ok, _ = InvoiceSendService.send_sms(self.invoice, self.tenant)

        self.assertTrue(ok)
        body = mock_send.call_args[0][1]
        self.assertLessEqual(len(body), 160)
        # The link must survive intact (ends with the token slash)
        self.assertIn(f'/invoice/{self.invoice.id}/', body)
        self.assertTrue(body.rstrip().endswith(('/', 'opt out.')))

    def test_no_phone_fails_gracefully(self):
        self.customer.phone = ''
        self.customer.save()
        ok, msg = InvoiceSendService.send_sms(self.invoice, self.tenant)
        self.assertFalse(ok)
        self.assertIn('mobile number', msg)

    def test_shop_toggle_off_blocks_send(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.sms_invoicing_enabled = False
        config.save(update_fields=['sms_invoicing_enabled'])
        ok, msg = InvoiceSendService.send_sms(self.invoice, self.tenant)
        self.assertFalse(ok)

    @override_settings(SMS_ORIGINATION_IDENTITY='')
    def test_platform_disabled_blocks_send(self):
        ok, msg = InvoiceSendService.send_sms(self.invoice, self.tenant)
        self.assertFalse(ok)

    def test_sms_available_requires_phone_and_toggle(self):
        self.assertTrue(InvoiceSendService.sms_available(self.invoice, self.tenant))
        self.customer.phone = None
        self.customer.save()
        self.invoice.refresh_from_db()
        self.assertFalse(InvoiceSendService.sms_available(self.invoice, self.tenant))


@override_settings(**SMS_SETTINGS)
class OwnerSendInvoiceSmsTests(SmsInvoicingBase):
    @patch('core.services.sms_service.SMSService._send_via_aws')
    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_send_with_sms_checkbox(self, mock_email, mock_sms):
        mock_email.return_value = (True, 'ok')
        mock_sms.return_value = 'msg-1'

        response = self.client.post(
            f'/owner/invoices/{self.invoice.id}/send/',
            {'send_sms': '1'},
        )
        self.assertEqual(response.status_code, 302)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')
        self.assertEqual(self.invoice.last_sms_to, '+15012827129')
        self.assertTrue(mock_sms.called)

    @patch('core.services.sms_service.SMSService._send_via_aws')
    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_email_failure_skips_sms(self, mock_email, mock_sms):
        mock_email.return_value = (False, 'boom')

        self.client.post(f'/owner/invoices/{self.invoice.id}/send/', {'send_sms': '1'})

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'DRAFT')
        self.assertFalse(mock_sms.called)

    @patch('core.services.sms_service.SMSService._send_via_aws')
    @patch('apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email')
    def test_send_without_checkbox_sends_no_sms(self, mock_email, mock_sms):
        mock_email.return_value = (True, 'ok')

        self.client.post(f'/owner/invoices/{self.invoice.id}/send/', {})

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')
        self.assertEqual(self.invoice.last_sms_to, '')
        self.assertFalse(mock_sms.called)
