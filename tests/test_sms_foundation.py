"""
SMS foundation tests (PR: feature/sms-foundation).

Covers:
- Phone normalization to E.164
- The SMS_ORIGINATION_IDENTITY master gate (no sends, no log rows when unset)
- The public /sms/ disclosure page (toll-free registration opt-in evidence)
"""

from django.test import TestCase, override_settings

from core.models.notification_delivery_log import NotificationDeliveryLog
from core.services.sms_service import SMSService


class NormalizePhoneTests(TestCase):
    def test_us_ten_digit(self):
        self.assertEqual(SMSService.normalize_phone('5012827129'), '+15012827129')

    def test_us_ten_digit_with_punctuation(self):
        self.assertEqual(SMSService.normalize_phone('(501) 282-7129'), '+15012827129')

    def test_us_eleven_digit_leading_one(self):
        self.assertEqual(SMSService.normalize_phone('1-501-282-7129'), '+15012827129')

    def test_already_e164(self):
        self.assertEqual(SMSService.normalize_phone('+15012827129'), '+15012827129')

    def test_e164_with_spaces(self):
        self.assertEqual(SMSService.normalize_phone('+1 501 282 7129'), '+15012827129')

    def test_unusable_short(self):
        self.assertIsNone(SMSService.normalize_phone('12345'))

    def test_unusable_empty(self):
        self.assertIsNone(SMSService.normalize_phone(''))

    def test_unusable_none(self):
        self.assertIsNone(SMSService.normalize_phone(None))

    def test_unusable_letters(self):
        self.assertIsNone(SMSService.normalize_phone('call me maybe'))


class SmsMasterGateTests(TestCase):
    @override_settings(SMS_ENABLED=True, SMS_ORIGINATION_IDENTITY='')
    def test_no_origination_identity_blocks_send(self):
        success, log = SMSService.send_notification_sms(
            notification_id=None,
            recipient_phone='+15012827129',
            message='should not send',
        )
        self.assertFalse(success)
        self.assertIsNone(log)
        self.assertEqual(NotificationDeliveryLog.objects.count(), 0)

    @override_settings(SMS_ENABLED=False, SMS_ORIGINATION_IDENTITY='+18885550100')
    def test_kill_switch_blocks_send(self):
        success, log = SMSService.send_notification_sms(
            notification_id=None,
            recipient_phone='+15012827129',
            message='should not send',
        )
        self.assertFalse(success)
        self.assertIsNone(log)

    @override_settings(SMS_ENABLED=True, SMS_ORIGINATION_IDENTITY='+18885550100')
    def test_enabled_when_both_set(self):
        self.assertTrue(SMSService.is_enabled())


class SmsProgramPageTests(TestCase):
    def test_page_renders_anonymously(self):
        response = self.client.get('/sms/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('STOP', content)
        self.assertIn('HELP', content)
        self.assertIn('Message and data rates may apply', content)

    def test_sitemap_lists_sms_page(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('https://rssystems.io/sms/', response.content.decode())
