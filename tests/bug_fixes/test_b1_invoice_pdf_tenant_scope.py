"""
Regression tests for B1 (Remediation Plan 2026-07-09):
Invoice PDFs were served via unsigned, enumerable S3 URLs.

Root cause:
    Templates embedded Invoice.get_pdf_url() — a raw, unsigned S3 object
    URL with a fully predictable key (invoices/<customer_id>/<year>/
    <invoice_number>.pdf). Combined with a bucket policy that allowed
    public read on the whole bucket, ANY unauthenticated party could
    enumerate and download any tenant's invoices. (The bucket policy has
    been scoped to media/* only; this fixes the application side.)

Fix:
    Templates now link only to ownership-checked Django views:
    - owner_invoice_pdf: tenant-scoped, redirects to a 300s presigned URL
      for the archived copy (or renders the stored record on demand)
    - customer_invoice_pdf (new): scoped to the requesting customer's
      company and tenant, same serve logic, DRAFT never served
    Invoice.get_pdf_url() remains for internal use but is never handed to
    templates.

Tests:
    A. Customer of tenant B requesting tenant A's invoice PDF -> 404.
    B. Owner of tenant B requesting tenant A's invoice PDF -> 404.
    C. Owner of tenant A gets the PDF (on-demand render in tests, no S3).
    D. Customer of tenant A gets their own invoice PDF.
    E. DRAFT invoices are not served to customers.
    F. Neither detail view puts a raw S3 URL in the page context.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer
from django.contrib.auth import get_user_model

User = get_user_model()


def _make_shop(name, email, first_name):
    result = create_tenant_with_owner(
        business_name=name,
        email=email,
        password='testpass123!',
        first_name=first_name,
        last_name='Owner',
    )
    return result['user'], result['tenant']


class InvoicePdfTenantScopeTests(TestCase):
    """B1: invoice PDFs are only reachable through ownership-checked views."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        self.owner_a, self.tenant_a = _make_shop('B1 Shop A', 'owner_b1a@test.com', 'BoneA')
        self.owner_b, self.tenant_b = _make_shop('B1 Shop B', 'owner_b1b@test.com', 'BoneB')

        self.customer_a = Customer.objects.create(
            tenant=self.tenant_a, name='B1 Fleet A', customer_type='FLEET',
            email='ap@b1fleeta.test',
        )
        self.customer_b = Customer.objects.create(
            tenant=self.tenant_b, name='B1 Fleet B', customer_type='FLEET',
            email='ap@b1fleetb.test',
        )

        # Customer-portal users for both companies
        self.cust_user_a = User.objects.create_user(
            username='cust_b1a', email='cust_b1a@test.com', password='pass123!',
        )
        CustomerUser.objects.create(user=self.cust_user_a, customer=self.customer_a)
        TenantMembership.objects.create(
            tenant=self.tenant_a, user=self.cust_user_a, role='viewer', is_active=True,
        )
        self.cust_user_b = User.objects.create_user(
            username='cust_b1b', email='cust_b1b@test.com', password='pass123!',
        )
        CustomerUser.objects.create(user=self.cust_user_b, customer=self.customer_b)
        TenantMembership.objects.create(
            tenant=self.tenant_b, user=self.cust_user_b, role='viewer', is_active=True,
        )

        # Tenant A's invoice (SENT so customers may view it)
        self.invoice_a = Invoice.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            invoice_number='INV-B1-A-001',
            status='SENT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice_a,
            description='Chip repair',
            quantity=1,
            unit_price=Decimal('100.00'),
            amount=Decimal('100.00'),
        )

    def _login(self, user, tenant):
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = tenant.id
        session.save()
        return client

    def test_a_cross_tenant_customer_gets_404(self):
        client = self._login(self.cust_user_b, self.tenant_b)
        response = client.get(reverse('customer_invoice_pdf', args=[self.invoice_a.id]))
        self.assertEqual(
            response.status_code, 404,
            "A tenant-B customer must never reach a tenant-A invoice PDF",
        )

    def test_b_cross_tenant_owner_gets_404(self):
        client = self._login(self.owner_b, self.tenant_b)
        response = client.get(reverse('owner_invoice_pdf', args=[self.invoice_a.id]))
        self.assertEqual(
            response.status_code, 404,
            "A tenant-B owner must never reach a tenant-A invoice PDF",
        )

    def test_c_own_tenant_owner_gets_pdf(self):
        client = self._login(self.owner_a, self.tenant_a)
        response = client.get(reverse('owner_invoice_pdf', args=[self.invoice_a.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_d_own_customer_gets_pdf(self):
        client = self._login(self.cust_user_a, self.tenant_a)
        response = client.get(reverse('customer_invoice_pdf', args=[self.invoice_a.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_e_draft_not_served_to_customer(self):
        self.invoice_a.status = 'DRAFT'
        self.invoice_a.save(update_fields=['status'])
        client = self._login(self.cust_user_a, self.tenant_a)
        response = client.get(reverse('customer_invoice_pdf', args=[self.invoice_a.id]))
        self.assertEqual(response.status_code, 302, "DRAFT invoices redirect away")
        self.assertNotIn('application/pdf', response.get('Content-Type', ''))

    def test_f_detail_views_never_expose_raw_s3_urls(self):
        # Simulate a stored PDF so pdf_url is populated
        self.invoice_a.s3_key = f'invoices/{self.customer_a.id}/2026/INV-B1-A-001.pdf'
        self.invoice_a.save(update_fields=['s3_key'])

        owner_client = self._login(self.owner_a, self.tenant_a)
        response = owner_client.get(reverse('owner_invoice_detail', args=[self.invoice_a.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            b'amazonaws.com', response.content,
            "Owner invoice page must not embed raw S3 object URLs",
        )

        customer_client = self._login(self.cust_user_a, self.tenant_a)
        response = customer_client.get(reverse('customer_invoice_detail', args=[self.invoice_a.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            b'amazonaws.com', response.content,
            "Customer invoice page must not embed raw S3 object URLs",
        )
