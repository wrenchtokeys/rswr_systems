"""
Tests for invoice delivery/view tracking (feature/invoice-delivery-tracking):

1. Opening a public invoice page (view page, PDF, or pay page) records a
   view on the invoice: first_viewed_at, last_viewed_at, view_count.
2. Invalid tokens record nothing.
3. Invoice.record_email_sent stamps sent_at / last_sent_at / last_sent_to
   consistently, on first sends and resends.
4. The owner invoice list surfaces Viewed / Not viewed.
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
        self.client = Client()
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

    def test_resend_updates_last_sent_but_not_sent_at(self):
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        original_sent_at = timezone.now() - timezone.timedelta(days=3)
        Invoice.all_objects.filter(pk=invoice.pk).update(
            sent_at=original_sent_at, last_sent_at=original_sent_at,
        )
        invoice.refresh_from_db()
        invoice.record_email_sent('newaddress@fleet.example.com')
        invoice.refresh_from_db()
        self.assertEqual(invoice.sent_at, original_sent_at)
        self.assertGreater(invoice.last_sent_at, original_sent_at)
        self.assertEqual(invoice.last_sent_to, 'newaddress@fleet.example.com')
        self.assertEqual(invoice.status, 'SENT')

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

    def test_detail_shows_delivery_trail(self):
        invoice = _create_invoice(self.tenant, self.customer, status='SENT')
        now = timezone.now()
        Invoice.all_objects.filter(pk=invoice.pk).update(
            sent_at=now, last_sent_at=now, last_sent_to='ltcust@example.com',
        )
        resp = self.client.get(f'/owner/invoices/{invoice.id}/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('ltcust@example.com', content)
        self.assertIn('Not viewed by the customer yet', content)
