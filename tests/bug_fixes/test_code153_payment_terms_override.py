"""
CODE-153: Regression tests — payment terms override on invoice generation.

Feature: When generating an invoice (via API or repair detail page), the
owner/manager can override the default payment terms for that specific
invoice.  The form shows the shop's default but allows changing it.

Tests verify:
1. API accepts payment_terms and applies it to the created invoice.
2. API without payment_terms falls back to BillingConfig default.
3. Invalid payment_terms returns 400.
4. payment_terms correctly derives due_days (NET30 → 30 days).
5. owner_generate_invoice_from_repair accepts POST payment_terms.
"""

import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from apps.billing.models import Invoice, BillingConfig
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


class PaymentTermsOverrideAPITest(TestCase):
    """Tests for payment_terms override via the billing API."""

    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user('owner153', password='test')
        self.tenant = Tenant.objects.create(
            name='Terms Shop', slug='terms-shop', owner=self.owner_user,
        )
        TenantMembership.objects.create(
            user=self.owner_user, tenant=self.tenant, role='owner',
        )
        self.customer = Customer.objects.create(
            name='Terms Customer', tenant=self.tenant,
        )
        self.tech = Technician.objects.create(
            user=self.owner_user, tenant=self.tenant,
        )
        # BillingConfig with COD default
        self.billing_config = BillingConfig.objects.create(
            tenant=self.tenant,
            default_payment_terms='COD',
        )
        # Completed repair ready to invoice
        self.repair = Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            technician=self.tech,
            unit_number='TERMS-1',
            queue_status='COMPLETED',
            cost=Decimal('75.00'),
            service_date=timezone.now(),
        )
        self.client.login(username='owner153', password='test')

    def test_api_creates_invoice_with_override_terms(self):
        """POST with payment_terms='NET30' should set NET30 on the invoice."""
        resp = self.client.post(
            f'/api/billing/invoices/create/{self.customer.id}/',
            data=json.dumps({
                'repair_ids': [self.repair.id],
                'payment_terms': 'NET30',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('success'), data)

        invoice = Invoice.objects.get(customer=self.customer, tenant=self.tenant)
        self.assertEqual(invoice.payment_terms, 'NET30')
        # Due date should be ~30 days from today
        expected_due = timezone.now().date() + timedelta(days=30)
        self.assertEqual(invoice.due_date, expected_due)

    def test_api_falls_back_to_config_default(self):
        """POST without payment_terms should use BillingConfig default (COD)."""
        resp = self.client.post(
            f'/api/billing/invoices/create/{self.customer.id}/',
            data=json.dumps({
                'repair_ids': [self.repair.id],
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        invoice = Invoice.objects.get(customer=self.customer, tenant=self.tenant)
        self.assertEqual(invoice.payment_terms, 'COD')

    def test_api_rejects_invalid_terms(self):
        """POST with invalid payment_terms should return 400."""
        resp = self.client.post(
            f'/api/billing/invoices/create/{self.customer.id}/',
            data=json.dumps({
                'repair_ids': [self.repair.id],
                'payment_terms': 'NET999',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Invalid payment_terms', resp.json().get('error', ''))

    def test_api_net60_gives_60_day_due_date(self):
        """NET60 should produce a due date 60 days from today."""
        resp = self.client.post(
            f'/api/billing/invoices/create/{self.customer.id}/',
            data=json.dumps({
                'repair_ids': [self.repair.id],
                'payment_terms': 'NET60',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        invoice = Invoice.objects.get(customer=self.customer, tenant=self.tenant)
        self.assertEqual(invoice.payment_terms, 'NET60')
        expected_due = timezone.now().date() + timedelta(days=60)
        self.assertEqual(invoice.due_date, expected_due)


class PaymentTermsOverrideRepairDetailTest(TestCase):
    """Tests for payment_terms override via the repair detail generate button."""

    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user('owner153b', password='test')
        self.tenant = Tenant.objects.create(
            name='Detail Shop', slug='detail-shop', owner=self.owner_user,
        )
        TenantMembership.objects.create(
            user=self.owner_user, tenant=self.tenant, role='owner',
        )
        self.customer = Customer.objects.create(
            name='Detail Customer', tenant=self.tenant,
        )
        self.tech = Technician.objects.create(
            user=self.owner_user, tenant=self.tenant,
        )
        BillingConfig.objects.create(
            tenant=self.tenant,
            default_payment_terms='COD',
        )
        self.repair = Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            technician=self.tech,
            unit_number='DETAIL-1',
            queue_status='COMPLETED',
            cost=Decimal('50.00'),
            service_date=timezone.now(),
        )
        self.client.login(username='owner153b', password='test')

    def test_generate_from_repair_with_terms_override(self):
        """POST with payment_terms='NET15' should create invoice with NET15."""
        resp = self.client.post(
            f'/owner/invoices/generate-from-repair/{self.repair.id}/',
            data={'payment_terms': 'NET15'},
        )
        # Should redirect to invoice detail
        self.assertEqual(resp.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer, tenant=self.tenant)
        self.assertEqual(invoice.payment_terms, 'NET15')
        expected_due = timezone.now().date() + timedelta(days=15)
        self.assertEqual(invoice.due_date, expected_due)

    def test_generate_from_repair_without_terms_uses_default(self):
        """POST without payment_terms should use BillingConfig default."""
        resp = self.client.post(
            f'/owner/invoices/generate-from-repair/{self.repair.id}/',
        )
        self.assertEqual(resp.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer, tenant=self.tenant)
        self.assertEqual(invoice.payment_terms, 'COD')

    def test_generate_from_repair_ignores_invalid_terms(self):
        """POST with invalid payment_terms should fall back to default (not error)."""
        resp = self.client.post(
            f'/owner/invoices/generate-from-repair/{self.repair.id}/',
            data={'payment_terms': 'BOGUS'},
        )
        self.assertEqual(resp.status_code, 302)
        invoice = Invoice.objects.get(customer=self.customer, tenant=self.tenant)
        self.assertEqual(invoice.payment_terms, 'COD')  # fallback to default
