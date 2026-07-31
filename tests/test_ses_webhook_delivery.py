"""
Tests for the SES delivery-event webhook (apps/billing/webhooks.py):

- Events are attributed to invoices via the rs_invoice_id message tag
  (exact) or last_sent_to + recency (fallback).
- Each SES event type maps to the right Invoice.email_delivery_status.
- Status transitions never regress (a late Send can't overwrite delivered;
  delivered can't mask a later complaint).
- The URL secret gates the endpoint.
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer

SECRET = 'test-webhook-secret'
WEBHOOK_URL = f'/api/billing/webhooks/ses/{SECRET}/'


def _create_tenant(name, email):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='test-plan-seswebhook',
        defaults={
            'name': 'Test Plan SES Webhook',
            'max_technicians': 5,
            'max_customers': 50,
            'monthly_price': Decimal('29.99'),
        },
    )
    user = User.objects.create_user(username=email, email=email, password='pass123')
    tenant = Tenant.objects.create(
        name=name, owner=user, subscription_plan=plan, plan='starter', is_active=True,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner', is_active=True)
    BillingConfig.objects.get_or_create(tenant=tenant)
    return tenant, user


def _sns_envelope(event):
    return json.dumps({'Type': 'Notification', 'Message': json.dumps(event)})


def _event(event_type, invoice=None, recipient='ap@fleet.example.com', **extra):
    """Build a config-set-format SES event payload."""
    mail = {
        'destination': [recipient],
        'tags': {},
    }
    if invoice is not None:
        mail['tags']['rs_invoice_id'] = [str(invoice.id)]
    body = {'eventType': event_type, 'mail': mail}
    body.update(extra)
    return body


class SesWebhookTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant, self.user = _create_tenant('SES Hook Shop', 'ses-owner@example.com')
        self.customer = Customer.objects.create(
            name='Hook Customer', email='ap@fleet.example.com', tenant=self.tenant,
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=f'INV-WH-{uuid.uuid4().hex[:8]}',
            status='SENT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
        )
        self.invoice.record_email_sent('ap@fleet.example.com')
        self.invoice.refresh_from_db()
        self._env = patch.dict('os.environ', {'SES_WEBHOOK_SECRET': SECRET})
        self._env.start()
        self.addCleanup(self._env.stop)

    def _post(self, event):
        return self.client.post(
            WEBHOOK_URL, data=_sns_envelope(event), content_type='application/json',
        )

    def _status(self):
        self.invoice.refresh_from_db()
        return self.invoice.email_delivery_status


class EventTypeMappingTests(SesWebhookTestCase):
    def test_delivery_marks_delivered(self):
        resp = self._post(_event(
            'Delivery', invoice=self.invoice,
            delivery={'recipients': ['ap@fleet.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._status(), 'delivered')

    def test_delivery_delay_marks_delayed(self):
        resp = self._post(_event(
            'DeliveryDelay', invoice=self.invoice,
            deliveryDelay={
                'delayType': 'MailboxFull',
                'delayedRecipients': [{'emailAddress': 'ap@fleet.example.com'}],
            },
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._status(), 'delayed')
        self.invoice.refresh_from_db()
        self.assertIn('MailboxFull', self.invoice.email_delivery_detail)

    def test_permanent_bounce_marks_bounced_with_diagnostic(self):
        resp = self._post(_event(
            'Bounce', invoice=self.invoice,
            bounce={
                'bounceType': 'Permanent',
                'bounceSubType': 'General',
                'bouncedRecipients': [{
                    'emailAddress': 'ap@fleet.example.com',
                    'diagnosticCode': 'smtp; 550 5.1.1 user unknown',
                }],
            },
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._status(), 'bounced')
        self.invoice.refresh_from_db()
        self.assertIn('550', self.invoice.email_delivery_detail)

    def test_transient_bounce_marks_delayed_not_bounced(self):
        self._post(_event(
            'Bounce', invoice=self.invoice,
            bounce={
                'bounceType': 'Transient',
                'bounceSubType': 'MailboxFull',
                'bouncedRecipients': [{'emailAddress': 'ap@fleet.example.com'}],
            },
        ))
        self.assertEqual(self._status(), 'delayed')

    def test_complaint_marks_complained(self):
        self._post(_event(
            'Complaint', invoice=self.invoice,
            complaint={
                'complainedRecipients': [{'emailAddress': 'ap@fleet.example.com'}],
                'complaintFeedbackType': 'abuse',
            },
        ))
        self.assertEqual(self._status(), 'complained')

    def test_reject_marks_rejected(self):
        self._post(_event(
            'Reject', invoice=self.invoice,
            reject={'reason': 'Bad content'},
        ))
        self.assertEqual(self._status(), 'rejected')

    def test_send_event_keeps_sent(self):
        self._post(_event('Send', invoice=self.invoice))
        self.assertEqual(self._status(), 'sent')


class CorrelationTests(SesWebhookTestCase):
    def test_fallback_matches_by_recipient_and_recency(self):
        # No tag on the event — match via last_sent_to.
        resp = self._post(_event(
            'Delivery',
            delivery={'recipients': ['ap@fleet.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._status(), 'delivered')

    def test_fallback_ignores_stale_sends(self):
        Invoice.all_objects.filter(pk=self.invoice.pk).update(
            last_sent_at=timezone.now() - timezone.timedelta(days=30),
        )
        self._post(_event(
            'Delivery',
            delivery={'recipients': ['ap@fleet.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self.assertEqual(self._status(), 'sent')

    def test_tag_beats_recipient_mismatch(self):
        # Tagged with this invoice even though the recipient doesn't match
        # last_sent_to (e.g. CC address) — tag wins.
        self._post(_event(
            'Delivery', invoice=self.invoice, recipient='cc@other.example.com',
            delivery={'recipients': ['cc@other.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self.assertEqual(self._status(), 'delivered')


class RegressionGuardTests(SesWebhookTestCase):
    def test_late_send_event_does_not_regress_delivered(self):
        self._post(_event(
            'Delivery', invoice=self.invoice,
            delivery={'recipients': ['ap@fleet.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self.assertEqual(self._status(), 'delivered')
        self._post(_event('Send', invoice=self.invoice))
        self.assertEqual(self._status(), 'delivered')

    def test_complaint_overrides_delivered(self):
        self._post(_event(
            'Delivery', invoice=self.invoice,
            delivery={'recipients': ['ap@fleet.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self._post(_event(
            'Complaint', invoice=self.invoice,
            complaint={
                'complainedRecipients': [{'emailAddress': 'ap@fleet.example.com'}],
            },
        ))
        self.assertEqual(self._status(), 'complained')

    def test_delayed_then_delivered(self):
        self._post(_event(
            'DeliveryDelay', invoice=self.invoice,
            deliveryDelay={
                'delayType': 'MailboxFull',
                'delayedRecipients': [{'emailAddress': 'ap@fleet.example.com'}],
            },
        ))
        self.assertEqual(self._status(), 'delayed')
        self._post(_event(
            'Delivery', invoice=self.invoice,
            delivery={'recipients': ['ap@fleet.example.com'], 'reportingMTA': 'a.mx'},
        ))
        self.assertEqual(self._status(), 'delivered')


class WebhookAuthTests(SesWebhookTestCase):
    def test_wrong_secret_404s(self):
        resp = self.client.post(
            '/api/billing/webhooks/ses/wrong-secret/',
            data=_sns_envelope(_event('Delivery', invoice=self.invoice)),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_unset_secret_404s(self):
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': ''}):
            resp = self._post(_event('Delivery', invoice=self.invoice))
        self.assertEqual(resp.status_code, 404)
