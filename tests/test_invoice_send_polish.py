"""
Tests for the invoice-send polish work (feature/invoice-send-polish):

1. Invoice email wording derives from what's on the invoice
   (repair / replacement / mixed) instead of always saying
   "windshield repair services".
2. Public View Invoice page: /invoice/<id>/<token>/ shows the invoice
   without dumping the customer into Stripe (which is what the /pay/ URL
   does); bad tokens 404; the tokened PDF endpoint serves the PDF.
3. "Send me a copy": copy_to_email BCCs the acting user through
   InvoiceSendService, and owner_email_invoice honors send_me_copy.
4. Delivery tracking: Invoice.last_sent_to is recorded on send, and the
   SES bounce webhook alerts the shop when a sent invoice bounces.
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.billing.services.invoice_email_service import InvoiceEmailService
from apps.billing.services.invoice_send_service import InvoiceSendService
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer
from rs_systems.views import generate_payment_token

LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'


def _create_tenant(name, email):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='test-plan-polish',
        defaults={
            'name': 'Test Plan Polish',
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


def _create_invoice(tenant, customer, status='DRAFT', with_line_item=True):
    invoice = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-POL-{uuid.uuid4().hex[:8]}',
        status=status,
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        amount_paid=Decimal('0.00'),
    )
    if with_line_item:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description='Windshield replacement',
            quantity=1,
            unit_price=Decimal('100.00'),
            amount=Decimal('100.00'),
            unit_number='T-100',
        )
    return invoice


class _FakeLineItem:
    """Just enough of InvoiceLineItem (the dataclass) for _service_phrase."""

    def __init__(self, repair_obj=None, replacement_obj=None, damage_type=''):
        self.repair_obj = repair_obj
        self.replacement_obj = replacement_obj
        self.damage_type = damage_type


class _FakeInvoiceData:
    def __init__(self, line_items):
        self.line_items = line_items


class ServicePhraseTests(TestCase):
    """The email intro must describe what's actually on the invoice."""

    def test_repair_only(self):
        data = _FakeInvoiceData([_FakeLineItem(repair_obj=object())])
        self.assertEqual(
            InvoiceEmailService._service_phrase(data),
            'recent windshield repair services',
        )

    def test_replacement_only(self):
        data = _FakeInvoiceData([_FakeLineItem(replacement_obj=object())])
        self.assertEqual(
            InvoiceEmailService._service_phrase(data),
            'recent glass replacement services',
        )

    def test_mixed(self):
        data = _FakeInvoiceData([
            _FakeLineItem(repair_obj=object()),
            _FakeLineItem(replacement_obj=object()),
        ])
        self.assertEqual(
            InvoiceEmailService._service_phrase(data),
            'recent glass repair and replacement services',
        )

    def test_unknown_falls_back_to_generic(self):
        data = _FakeInvoiceData([_FakeLineItem(damage_type='Service')])
        self.assertEqual(InvoiceEmailService._service_phrase(data), 'recent services')

    def test_label_fallback_classifies_replacement(self):
        # Record path line items without loaded objects still classify by label
        data = _FakeInvoiceData([_FakeLineItem(damage_type='Replacement')])
        self.assertEqual(
            InvoiceEmailService._service_phrase(data),
            'recent glass replacement services',
        )


class PublicInvoiceViewTests(TestCase):
    """/invoice/<id>/<token>/ is a view page, distinct from /pay/."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Polish Shop A', 'ownerpolish-a@test.com')
        self.customer = Customer.objects.create(
            name='View Customer', email='viewcust@example.com', tenant=self.tenant,
        )
        self.invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        self.token = generate_payment_token(self.invoice.id)
        self.client = Client()

    def test_valid_token_shows_invoice(self):
        resp = self.client.get(f'/invoice/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.invoice.invoice_number)
        self.assertContains(resp, 'Windshield replacement')
        # Pay button present and points at the /pay/ URL, not this page
        self.assertContains(resp, f'/pay/{self.invoice.id}/{self.token}/')

    def test_invalid_token_404(self):
        resp = self.client.get(f'/invoice/{self.invoice.id}/{"0" * 32}/')
        self.assertEqual(resp.status_code, 404)

    def test_paid_invoice_hides_pay_button(self):
        self.invoice.status = 'PAID'
        self.invoice.amount_paid = self.invoice.total
        self.invoice.save()
        resp = self.client.get(f'/invoice/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f'/pay/{self.invoice.id}/{self.token}/')

    def test_pdf_endpoint_serves_pdf(self):
        resp = self.client.get(f'/invoice/{self.invoice.id}/{self.token}/pdf/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_pdf_invalid_token_404(self):
        resp = self.client.get(f'/invoice/{self.invoice.id}/{"0" * 32}/pdf/')
        self.assertEqual(resp.status_code, 404)


@override_settings(EMAIL_BACKEND=LOCMEM)
class SendCopyAndTrackingTests(TestCase):
    """copy_to_email BCCs the acting user; last_sent_to is recorded."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Polish Shop B', 'ownerpolish-b@test.com')
        self.customer = Customer.objects.create(
            name='Copy Customer', email='copycust@example.com', tenant=self.tenant,
        )

    def test_send_records_recipient_and_bccs_copy(self):
        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        result = InvoiceSendService.send(
            invoice, self.tenant, copy_to_email='ownerpolish-b@test.com',
        )
        self.assertTrue(result.sent, result.message)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')
        self.assertEqual(invoice.last_sent_to, 'copycust@example.com')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['copycust@example.com'])
        self.assertIn('ownerpolish-b@test.com', mail.outbox[0].bcc)

    def test_send_without_copy_has_no_bcc(self):
        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        result = InvoiceSendService.send(invoice, self.tenant)
        self.assertTrue(result.sent, result.message)
        self.assertEqual(mail.outbox[0].bcc, [])

    def test_replacement_only_email_says_replacement(self):
        """Replacement-only invoice email must not say 'windshield repair'."""
        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT',
                                  with_line_item=False)
        from apps.technician_portal.models import Replacement, Technician
        tech_user = User.objects.create_user(
            username='polishtech-b', email='polishtech-b@test.com', password='x',
        )
        technician = Technician.objects.create(tenant=self.tenant, user=tech_user)
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=technician,
            unit_number='T-200', cost_override=Decimal('250.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, replacement=replacement,
            description='Windshield replacement', quantity=1,
            unit_price=Decimal('250.00'), amount=Decimal('250.00'),
            unit_number='T-200',
        )
        result = InvoiceSendService.send(invoice, self.tenant)
        self.assertTrue(result.sent, result.message)
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn('recent glass replacement services', html_body)
        self.assertNotIn('recent windshield repair services', html_body)

    def test_view_and_pay_links_differ_in_email(self):
        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        result = InvoiceSendService.send(invoice, self.tenant)
        self.assertTrue(result.sent, result.message)
        body = mail.outbox[0].body
        self.assertIn(f'/invoice/{invoice.id}/', body)

    def test_owner_email_invoice_resends_replacement_only_with_copy(self):
        """The 'Email Invoice' resend uses the record path (works for
        replacement-only invoices) and honors send_me_copy."""
        from apps.saas.views import owner_email_invoice

        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        factory = RequestFactory()
        req = factory.post('/', data={'send_me_copy': '1'})
        req.user = self.user
        req.tenant = self.tenant
        req.session = SessionStore()
        req._messages = FallbackStorage(req)

        resp = owner_email_invoice(req, invoice.id)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('ownerpolish-b@test.com', mail.outbox[0].bcc)
        invoice.refresh_from_db()
        self.assertEqual(invoice.last_sent_to, 'copycust@example.com')


@override_settings(EMAIL_BACKEND=LOCMEM)
class SesBounceWebhookTests(TestCase):
    """Bounced invoice email → shop gets in-app + email alert."""

    SECRET = 'test-webhook-secret-123'

    def setUp(self):
        self.tenant, self.user = _create_tenant('Polish Shop C', 'ownerpolish-c@test.com')
        self.customer = Customer.objects.create(
            name='Bounce Customer', email='bouncecust@example.com', tenant=self.tenant,
        )
        from apps.technician_portal.models import Technician
        self.manager = Technician.objects.create(
            tenant=self.tenant, user=self.user, is_manager=True, is_active=True,
        )
        self.invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        self.invoice.last_sent_to = 'bouncecust@example.com'
        self.invoice.sent_at = timezone.now()
        self.invoice.save(update_fields=['last_sent_to', 'sent_at'])
        self.client = Client()

    def _bounce_payload(self, email='bouncecust@example.com', bounce_type='Permanent'):
        return json.dumps({
            'Type': 'Notification',
            'Message': json.dumps({
                'notificationType': 'Bounce',
                'bounce': {
                    'bounceType': bounce_type,
                    'bouncedRecipients': [{'emailAddress': email}],
                },
            }),
        })

    def _post(self, payload, secret=None):
        return self.client.post(
            f'/api/billing/webhooks/ses/{secret or self.SECRET}/',
            data=payload, content_type='application/json',
        )

    def test_wrong_secret_404(self):
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': self.SECRET}):
            resp = self._post(self._bounce_payload(), secret='wrong-secret')
        self.assertEqual(resp.status_code, 404)

    def test_unconfigured_secret_404(self):
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': ''}):
            resp = self._post(self._bounce_payload())
        self.assertEqual(resp.status_code, 404)

    def test_permanent_bounce_alerts_shop(self):
        from apps.technician_portal.models import TechnicianNotification
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': self.SECRET}):
            resp = self._post(self._bounce_payload())
        self.assertEqual(resp.status_code, 200)

        notes = TechnicianNotification.objects.filter(technician=self.manager)
        self.assertEqual(notes.count(), 1)
        self.assertIn(self.invoice.invoice_number, notes.first().message)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('could not be delivered', mail.outbox[0].subject)
        self.assertIn('ownerpolish-c@test.com', mail.outbox[0].to)

    def test_transient_bounce_ignored(self):
        from apps.technician_portal.models import TechnicianNotification
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': self.SECRET}):
            resp = self._post(self._bounce_payload(bounce_type='Transient'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(TechnicianNotification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_unmatched_recipient_no_alert(self):
        from apps.technician_portal.models import TechnicianNotification
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': self.SECRET}):
            resp = self._post(self._bounce_payload(email='stranger@example.com'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(TechnicianNotification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_subscription_confirmation_fetches_sns_url(self):
        payload = json.dumps({
            'Type': 'SubscriptionConfirmation',
            'SubscribeURL': 'https://sns.us-east-1.amazonaws.com/?Action=ConfirmSubscription',
        })
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': self.SECRET}), \
                patch('apps.billing.webhooks.urllib.request.urlopen') as mock_open:
            resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        mock_open.assert_called_once()

    def test_subscription_confirmation_rejects_non_sns_url(self):
        payload = json.dumps({
            'Type': 'SubscriptionConfirmation',
            'SubscribeURL': 'https://evil.example.com/steal',
        })
        with patch.dict('os.environ', {'SES_WEBHOOK_SECRET': self.SECRET}), \
                patch('apps.billing.webhooks.urllib.request.urlopen') as mock_open:
            resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        mock_open.assert_not_called()
