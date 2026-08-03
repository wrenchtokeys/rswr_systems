"""
Tests for invoice delivery/view tracking:

1. Opening a public invoice page (view page, PDF, or pay page) with a real
   browser user-agent records a view: first_viewed_at, last_viewed_at,
   view_count.
2. Mail-gateway scanner traffic does NOT count: empty/bot user-agents, the
   legacy open-pixel endpoint, and any hit inside the post-send grace window
   (security gateways detonate emailed links seconds after delivery).
3. Invalid tokens record nothing.
4. The /pay/ page never creates a Stripe Checkout session on GET — only the
   confirm-page POST does.
5. Invoice.record_email_sent stamps sent_at / last_sent_at / last_sent_to
   and resets email_delivery_status for the new send.
6. The owner invoice list surfaces Viewed / Not viewed.
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer
from rs_systems.views import generate_payment_token

# A real browser UA — the test client sends none by default, which the
# scanner heuristic (correctly) refuses to count.
BROWSER_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
)


def _create_tenant(name, email):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='test-plan-viewtrack',
        defaults={
            'name': 'Test Plan Viewtrack',
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


def _create_invoice(tenant, customer, status='SENT'):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-VT-{uuid.uuid4().hex[:8]}',
        status=status,
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        amount_paid=Decimal('0.00'),
    )


class PublicPageViewTrackingTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_USER_AGENT=BROWSER_UA)
        self.tenant, self.user = _create_tenant('View Track Shop', 'vt-owner@example.com')
        self.customer = Customer.objects.create(
            name='VT Customer', email='vtcust@example.com', tenant=self.tenant,
        )
        self.invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        self.token = generate_payment_token(self.invoice.id)

    def test_view_page_marks_viewed(self):
        self.assertIsNone(self.invoice.first_viewed_at)
        resp = self.client.get(f'/invoice/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertIsNotNone(self.invoice.first_viewed_at)
        self.assertIsNotNone(self.invoice.last_viewed_at)
        self.assertEqual(self.invoice.view_count, 1)

    def test_repeat_views_increment_count_and_keep_first(self):
        self.client.get(f'/invoice/{self.invoice.id}/{self.token}/')
        self.invoice.refresh_from_db()
        first = self.invoice.first_viewed_at
        self.client.get(f'/invoice/{self.invoice.id}/{self.token}/')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.view_count, 2)
        self.assertEqual(self.invoice.first_viewed_at, first)
        self.assertGreaterEqual(self.invoice.last_viewed_at, first)

    def test_pdf_endpoint_marks_viewed(self):
        with patch(
            'apps.billing.services.invoice_service.InvoiceService.generate_invoice_from_record',
            return_value=(b'%PDF-1.4 fake', 'invoices/fake.pdf'),
        ):
            resp = self.client.get(f'/invoice/{self.invoice.id}/{self.token}/pdf/')
        self.assertEqual(resp.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.view_count, 1)

    def test_pay_page_marks_viewed(self):
        # No Stripe configured in tests — page falls through to the
        # "payments unavailable" template, which still counts as a view.
        resp = self.client.get(f'/pay/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.view_count, 1)

    def test_invalid_token_records_nothing(self):
        resp = self.client.get(f'/invoice/{self.invoice.id}/{"0" * 32}/')
        self.assertEqual(resp.status_code, 404)
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.first_viewed_at)
        self.assertEqual(self.invoice.view_count, 0)


class ScannerFilteringTests(TestCase):
    """Mail-gateway scanner traffic must not produce phantom 'viewed' data."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Scan Filter Shop', 'sf-owner@example.com')
        self.customer = Customer.objects.create(
            name='SF Customer', email='sfcust@example.com', tenant=self.tenant,
        )
        self.invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        self.token = generate_payment_token(self.invoice.id)

    def _assert_no_view(self):
        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.first_viewed_at)
        self.assertEqual(self.invoice.view_count, 0)

    def test_empty_user_agent_not_counted(self):
        resp = Client().get(f'/invoice/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self._assert_no_view()

    def test_scanner_user_agents_not_counted(self):
        for ua in (
            'python-requests/2.31.0',
            'curl/8.4.0',
            'Mozilla/5.0 (compatible; Barracuda Sentinel)',
            'Mozilla/5.0 (Windows NT 10.0) HeadlessChrome/120.0',
            'SomeCorp URLScanBot/1.0',
        ):
            resp = Client(HTTP_USER_AGENT=ua).get(
                f'/invoice/{self.invoice.id}/{self.token}/')
            self.assertEqual(resp.status_code, 200, ua)
        self._assert_no_view()

    def test_hit_within_grace_window_not_counted(self):
        # Safe Links detonation happens seconds after the send.
        Invoice.all_objects.filter(pk=self.invoice.pk).update(
            last_sent_at=timezone.now(),
        )
        resp = Client(HTTP_USER_AGENT=BROWSER_UA).get(
            f'/invoice/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self._assert_no_view()

    def test_hit_after_grace_window_counted(self):
        Invoice.all_objects.filter(pk=self.invoice.pk).update(
            last_sent_at=timezone.now() - timezone.timedelta(minutes=30),
        )
        resp = Client(HTTP_USER_AGENT=BROWSER_UA).get(
            f'/invoice/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.view_count, 1)

    def test_open_pixel_never_counts(self):
        resp = Client(HTTP_USER_AGENT=BROWSER_UA).get(
            f'/invoice/{self.invoice.id}/{self.token}/open.gif')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/gif')
        self.assertIn('no-store', resp['Cache-Control'])
        self._assert_no_view()

    def test_open_pixel_bad_token_still_serves_gif(self):
        # Bad token still gets the pixel (no broken image in the email).
        resp = Client().get(f'/invoice/{self.invoice.id}/{"0" * 32}/open.gif')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/gif')
        self._assert_no_view()


class PayPageStripeSessionTests(TestCase):
    """GET must never create a Stripe Checkout session; only POST may."""

    def setUp(self):
        self.client = Client(HTTP_USER_AGENT=BROWSER_UA)
        self.tenant, self.user = _create_tenant('Pay Flow Shop', 'pf-owner@example.com')
        self.customer = Customer.objects.create(
            name='PF Customer', email='pfcust@example.com', tenant=self.tenant,
        )
        self.invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        self.token = generate_payment_token(self.invoice.id)

    def test_get_shows_confirm_page_without_stripe_call(self):
        with patch.object(
            type(self.tenant), 'can_accept_payments',
            property(lambda self: True),
        ), patch(
            'apps.tenants.services.connect_service.ConnectService.create_connected_checkout_session',
        ) as mock_create:
            resp = self.client.get(f'/pay/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        mock_create.assert_not_called()
        self.assertIn('Continue to secure payment', resp.content.decode())

    def test_post_creates_session_and_redirects(self):
        with patch.object(
            type(self.tenant), 'can_accept_payments',
            property(lambda self: True),
        ), patch(
            'apps.tenants.services.connect_service.ConnectService.create_connected_checkout_session',
            return_value={'checkout_url': 'https://checkout.stripe.com/c/pay/test123'},
        ) as mock_create:
            get_resp = self.client.get(f'/pay/{self.invoice.id}/{self.token}/')
            resp = self.client.post(f'/pay/{self.invoice.id}/{self.token}/')
        self.assertEqual(get_resp.status_code, 200)
        mock_create.assert_called_once()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], 'https://checkout.stripe.com/c/pay/test123')

    def test_get_without_connect_shows_unavailable(self):
        resp = self.client.get(f'/pay/{self.invoice.id}/{self.token}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('contact', resp.content.decode().lower())


class EmailPixelRemovedTests(TestCase):
    """Invoice emails must NOT embed an open-tracking pixel — gateways
    prefetch it (phantom views) and a remote 1x1 image is a spam signal."""

    def setUp(self):
        self.tenant, self.user = _create_tenant('Pixel Shop', 'px-owner@example.com')
        self.customer = Customer.objects.create(
            name='Pixel Customer', email='pxcust@example.com', tenant=self.tenant,
        )

    def test_invoice_email_html_has_no_open_pixel(self):
        from django.core import mail
        from django.test import override_settings
        from apps.billing.models import InvoiceLineItem
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Windshield repair',
            quantity=1, unit_price=Decimal('100.00'), amount=Decimal('100.00'),
        )
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            success, msg = InvoiceEmailService(tenant=self.tenant).send_invoice_email(
                customer_id=self.customer.id,
                recipient_email=self.customer.email,
                invoice=invoice,
            )
        self.assertTrue(success, msg)
        self.assertEqual(len(mail.outbox), 1)
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn(f'/invoice/{invoice.id}/', html_body)  # view link stays
        self.assertNotIn('/open.gif', html_body)

    def test_invoice_email_carries_ses_message_tag(self):
        from django.core import mail
        from django.test import override_settings
        from apps.billing.models import InvoiceLineItem
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Windshield repair',
            quantity=1, unit_price=Decimal('100.00'), amount=Decimal('100.00'),
        )
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            success, msg = InvoiceEmailService(tenant=self.tenant).send_invoice_email(
                customer_id=self.customer.id,
                recipient_email=self.customer.email,
                invoice=invoice,
            )
        self.assertTrue(success, msg)
        message = mail.outbox[0].message()
        self.assertEqual(
            message['X-SES-MESSAGE-TAGS'], f'rs_invoice_id={invoice.id}')

    def test_invoice_email_from_uses_via_platform_format(self):
        from django.core import mail
        from django.test import override_settings
        from apps.billing.models import InvoiceLineItem
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Windshield repair',
            quantity=1, unit_price=Decimal('100.00'), amount=Decimal('100.00'),
        )
        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            success, msg = InvoiceEmailService(tenant=self.tenant).send_invoice_email(
                customer_id=self.customer.id,
                recipient_email=self.customer.email,
                invoice=invoice,
            )
        self.assertTrue(success, msg)
        self.assertIn('via RS Systems', mail.outbox[0].from_email)
        # No bracketed subject prefix; "Invoice <num> from <shop>" instead.
        subject = mail.outbox[0].subject
        self.assertFalse(subject.startswith('['), subject)
        self.assertIn(f'Invoice {invoice.invoice_number} from Pixel Shop', subject)


class RecordEmailSentTests(TestCase):
    def setUp(self):
        self.tenant, self.user = _create_tenant('Send Track Shop', 'st-owner@example.com')
        self.customer = Customer.objects.create(
            name='ST Customer', email='stcust@example.com', tenant=self.tenant,
        )

    def test_first_send_promotes_draft_and_stamps(self):
        invoice = _create_invoice(self.tenant, self.customer, status='DRAFT')
        invoice.record_email_sent('billing@fleet.example.com')
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')
        self.assertIsNotNone(invoice.sent_at)
        self.assertEqual(invoice.last_sent_at, invoice.sent_at)
        self.assertEqual(invoice.last_sent_to, 'billing@fleet.example.com')
        self.assertEqual(invoice.email_delivery_status, 'sent')

    def test_resend_updates_last_sent_but_not_sent_at(self):
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        original_sent_at = timezone.now() - timezone.timedelta(days=3)
        Invoice.all_objects.filter(pk=invoice.pk).update(
            sent_at=original_sent_at, last_sent_at=original_sent_at,
            email_delivery_status='bounced',
            email_delivery_detail='old failure',
        )
        invoice.refresh_from_db()
        invoice.record_email_sent('newaddress@fleet.example.com')
        invoice.refresh_from_db()
        self.assertEqual(invoice.sent_at, original_sent_at)
        self.assertGreater(invoice.last_sent_at, original_sent_at)
        self.assertEqual(invoice.last_sent_to, 'newaddress@fleet.example.com')
        self.assertEqual(invoice.status, 'SENT')
        # Resend resets delivery tracking for the new message.
        self.assertEqual(invoice.email_delivery_status, 'sent')
        self.assertEqual(invoice.email_delivery_detail, '')

    def test_send_without_recipient_keeps_existing_recipient(self):
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        invoice.last_sent_to = 'kept@fleet.example.com'
        invoice.save(update_fields=['last_sent_to'])
        invoice.record_email_sent('')
        invoice.refresh_from_db()
        self.assertEqual(invoice.last_sent_to, 'kept@fleet.example.com')


class OwnerInvoiceListIndicatorTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.tenant, self.user = _create_tenant('List Track Shop', 'lt-owner@example.com')
        self.customer = Customer.objects.create(
            name='LT Customer', email='ltcust@example.com', tenant=self.tenant,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_list_shows_viewed_and_not_viewed(self):
        viewed = _create_invoice(self.tenant, self.customer, status='SENT')
        now = timezone.now()
        Invoice.all_objects.filter(pk=viewed.pk).update(
            sent_at=now, first_viewed_at=now, last_viewed_at=now, view_count=2,
        )
        unviewed = _create_invoice(self.tenant, self.customer, status='SENT')
        Invoice.all_objects.filter(pk=unviewed.pk).update(sent_at=now)

        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Viewed', content)
        self.assertIn('Not viewed', content)

    def test_list_shows_delivery_status(self):
        delivered = _create_invoice(self.tenant, self.customer, status='SENT')
        now = timezone.now()
        Invoice.all_objects.filter(pk=delivered.pk).update(
            sent_at=now, email_delivery_status='delivered',
            email_delivery_status_at=now,
        )
        bounced = _create_invoice(self.tenant, self.customer, status='SENT')
        Invoice.all_objects.filter(pk=bounced.pk).update(
            sent_at=now, email_delivery_status='bounced',
            email_delivery_status_at=now,
            email_delivery_detail='550 mailbox not found',
        )
        resp = self.client.get('/owner/invoices/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Delivered', content)
        self.assertIn('Not delivered', content)

    def test_detail_resend_shows_recipient_next_to_resend_time(self):
        # last_sent_to holds only the LATEST recipient. After a resend to a
        # different address, that address must display with the resend
        # timestamp — pairing it with the original send time claims the
        # first email went to an address it never went to.
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        first_send = timezone.now() - timezone.timedelta(hours=2)
        resend = timezone.now()
        Invoice.all_objects.filter(pk=invoice.pk).update(
            sent_at=first_send, last_sent_at=resend,
            last_sent_to='failed-email-address@fakeemail.com',
        )
        resp = self.client.get(f'/owner/invoices/{invoice.id}/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('resent', content)
        # The recipient must appear inside the "(resent ...)" span, not
        # after the original send timestamp.
        resent_idx = content.index('resent')
        addr_idx = content.index('failed-email-address@fakeemail.com')
        self.assertGreater(addr_idx, resent_idx)

    def test_detail_shows_delivery_trail(self):
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        now = timezone.now()
        Invoice.all_objects.filter(pk=invoice.pk).update(
            sent_at=now, last_sent_at=now, last_sent_to='ltcust@example.com',
            email_delivery_status='delivered', email_delivery_status_at=now,
        )
        resp = self.client.get(f'/owner/invoices/{invoice.id}/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('ltcust@example.com', content)
        self.assertIn('Delivered', content)
        self.assertIn('Not viewed by the customer yet', content)

    def test_detail_resend_recipient_shown_next_to_resend_timestamp(self):
        # last_sent_to is the LATEST send's recipient. After a resend to a
        # different address it must render inside the "(resent ...)" trail, not
        # next to the original sent_at.
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        original_sent = timezone.now() - timezone.timedelta(hours=1)
        resent_at = timezone.now()
        Invoice.all_objects.filter(pk=invoice.pk).update(
            sent_at=original_sent, last_sent_at=resent_at,
            last_sent_to='resend-target@example.com',
        )
        resp = self.client.get(f'/owner/invoices/{invoice.id}/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # Recipient appears attached to the resend timestamp.
        resent_idx = content.find('resent')
        self.assertNotEqual(resent_idx, -1)
        recipient_idx = content.find('resend-target@example.com')
        self.assertNotEqual(recipient_idx, -1)
        self.assertGreater(recipient_idx, resent_idx)
        # The explanatory template note must never reach the rendered page.
        self.assertNotIn('LATEST send', content)
