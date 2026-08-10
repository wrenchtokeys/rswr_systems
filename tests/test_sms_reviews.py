"""
SMS review request tests (PR: feature/sms-reviews).

Covers:
- Channel selection at scheduling (SMS preferred when eligible, email
  fallback, SMS-only customers now reachable)
- Sending: SMS branch of send_pending_requests, STOP-once wording,
  click-tracking link, send-time fallback to email
- The Settings → Reviews "Send by Text" toggle
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Technician
from apps.technician_portal.review_models import ReviewConfig, ReviewRequest
from apps.technician_portal.review_service import ReviewRequestService
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


SMS_SETTINGS = dict(SMS_ENABLED=True, SMS_ORIGINATION_IDENTITY='+18885550100')


@override_settings(**SMS_SETTINGS)
class SmsReviewBase(TestCase):
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Test Shop', email='owner@test.com',
            password='testpass123!', first_name='Test', last_name='Owner',
        )
        self.tenant = result['tenant']
        self.technician = Technician.objects.filter(tenant=self.tenant).first()

        self.config = ReviewConfig.get_for_tenant(self.tenant)
        self.config.is_enabled = True
        self.config.sms_enabled = True
        self.config.google_review_url = 'https://g.page/r/test/review'
        self.config.send_delay_hours = 0
        self.config.business_hours_start = 0
        self.config.business_hours_end = 24
        self.config.save()

        self.customer = Customer.objects.create(
            tenant=self.tenant, name='John Smith', customer_type='RETAIL',
            email='john@test.com', phone='(501) 282-7129',
            sms_opt_in=True,
        )

    def make_repair(self, customer=None):
        # Suppress the completion hook's auto-scheduling so each test drives
        # schedule_review_request explicitly (otherwise the duplicate gate
        # would return None for the test's own call).
        with patch.object(ReviewRequestService, 'schedule_review_request',
                          return_value=None):
            return Repair.objects.create(
                tenant=self.tenant, customer=customer or self.customer,
                technician=self.technician, unit_number='1',
                queue_status='COMPLETED',
            )

    def add_portal_contact(self, customer=None):
        user = User.objects.create_user(
            username='johnportal', email='john.portal@test.com', password='x',
        )
        return CustomerUser.objects.create(
            customer=customer or self.customer, user=user, is_primary_contact=True,
        )


class SchedulingChannelTests(SmsReviewBase):
    def test_sms_preferred_when_eligible(self):
        self.add_portal_contact()
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        self.assertIsNotNone(rr)
        self.assertEqual(rr.status, 'pending')
        self.assertEqual(rr.channel, 'sms')

    def test_email_when_sms_channel_off(self):
        self.config.sms_enabled = False
        self.config.save()
        self.add_portal_contact()
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        self.assertEqual(rr.channel, 'email')

    def test_email_when_customer_not_opted_in(self):
        self.customer.sms_opt_in = False
        self.customer.save()
        self.add_portal_contact()
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        self.assertEqual(rr.channel, 'email')

    def test_sms_only_customer_now_reachable(self):
        # No portal contact, no email route — before the SMS channel this
        # customer never got a review request at all.
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        self.assertIsNotNone(rr)
        self.assertEqual(rr.channel, 'sms')
        self.assertIsNone(rr.customer_user)

    def test_unreachable_customer_still_returns_none(self):
        self.customer.sms_opt_in = False
        self.customer.save()
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        self.assertIsNone(rr)

    @override_settings(SMS_ORIGINATION_IDENTITY='')
    def test_platform_disabled_falls_back_to_email(self):
        self.add_portal_contact()
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        self.assertEqual(rr.channel, 'email')


class SendingTests(SmsReviewBase):
    def make_due_request(self):
        rr = ReviewRequestService.schedule_review_request(self.make_repair())
        ReviewRequest.objects.filter(pk=rr.pk).update(scheduled_at=timezone.now())
        return rr

    @patch('core.services.sms_service.SMSService._send_via_aws')
    def test_send_pending_sms(self, mock_send):
        mock_send.return_value = 'msg-1'
        rr = self.make_due_request()

        sent = ReviewRequestService.send_pending_requests()

        self.assertEqual(sent, 1)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'sent')
        self.assertIsNotNone(rr.sent_at)

        body = mock_send.call_args[0][1]
        self.assertIn('John', body)
        self.assertIn('Test Shop', body)
        self.assertIn(f'/r/{rr.token}/', body)
        self.assertIn('Reply STOP to opt out', body)
        self.assertLessEqual(len(body), 160)
        self.assertEqual(mock_send.call_args[0][0], '+15012827129')

    def test_short_click_url_resolves(self):
        rr = self.make_due_request()
        ReviewRequest.objects.filter(pk=rr.pk).update(status='sent')
        response = self.client.get(f'/r/{rr.token}/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.config.google_review_url)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'clicked')

    @patch('core.services.sms_service.SMSService._send_via_aws')
    def test_consent_revoked_before_send_skips(self, mock_send):
        rr = self.make_due_request()
        self.customer.sms_opt_in = False
        self.customer.save()

        sent = ReviewRequestService.send_pending_requests()

        self.assertEqual(sent, 0)
        self.assertFalse(mock_send.called)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'sms_unavailable')

    @patch('apps.technician_portal.review_service._send_review_email')
    def test_consent_revoked_falls_back_to_email_when_possible(self, mock_email):
        mock_email.return_value = True
        self.add_portal_contact()
        rr = self.make_due_request()
        self.assertEqual(rr.channel, 'sms')
        self.customer.sms_opt_in = False
        self.customer.save()

        sent = ReviewRequestService.send_pending_requests()

        self.assertEqual(sent, 1)
        self.assertTrue(mock_email.called)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'sent')
        self.assertEqual(rr.channel, 'email')

    @patch('core.services.sms_service.SMSService._send_via_aws')
    def test_send_failure_leaves_pending_for_retry(self, mock_send):
        mock_send.side_effect = Exception('carrier exploded')
        rr = self.make_due_request()

        sent = ReviewRequestService.send_pending_requests()

        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'pending')


@override_settings(**SMS_SETTINGS)
class SettingsToggleTests(TestCase):
    def test_review_settings_saves_sms_enabled(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Test Shop', email='owner@test.com',
            password='testpass123!', first_name='Test', last_name='Owner',
        )
        self.client.force_login(result['user'])
        session = self.client.session
        session['tenant_id'] = result['tenant'].id
        session.save()

        self.client.post('/owner/settings/', {
            'form_type': 'review_settings',
            'review_enabled': 'on',
            'review_sms_enabled': 'on',
            'google_review_url': 'https://g.page/r/test/review',
        })
        config = ReviewConfig.get_for_tenant(result['tenant'])
        self.assertTrue(config.sms_enabled)

        self.client.post('/owner/settings/', {
            'form_type': 'review_settings',
            'review_enabled': 'on',
            'google_review_url': 'https://g.page/r/test/review',
        })
        config.refresh_from_db()
        self.assertFalse(config.sms_enabled)
