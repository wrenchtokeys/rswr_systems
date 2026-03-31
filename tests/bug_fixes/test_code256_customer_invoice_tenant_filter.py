"""
Regression tests for CODE-256:
    customer_invoices(), customer_invoice_detail(), and customer_invoice_pay()
    filtered invoices by customer=customer but omitted tenant=customer.tenant.

    While Customer FK is inherently tenant-scoped (each Customer belongs to
    exactly one Tenant), the project convention requires every query to include
    an explicit tenant= filter for defense-in-depth.  This prevents data leakage
    if an Invoice row ever ends up with a mismatched tenant (data integrity issue)
    or if the soft-delete manager's behavior changes.

Covers:
    - customer_invoices: only returns invoices for customer's tenant
    - customer_invoice_detail: 404s for invoice with wrong tenant
    - customer_invoice_pay: 404s for invoice with wrong tenant
"""

from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership
from apps.customer_portal.models import CustomerUser
from apps.billing.models import Invoice
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_counter = [2560]


def _uid():
    _counter[0] += 1
    return _counter[0]


def _make_user(prefix="u"):
    n = _uid()
    return User.objects.create_user(
        username=f"{prefix}_{n}",
        email=f"{prefix}_{n}@example.com",
        password="testpass123",
    )


def _make_tenant(name_prefix="shop", owner=None):
    n = _uid()
    if owner is None:
        owner = _make_user(f"owner_{name_prefix}")
    return Tenant.objects.create(
        name=f"{name_prefix} {n}",
        slug=f"{name_prefix}-{n}",
        plan="pro",
        owner=owner,
    )


def _make_request(method, url, user, tenant, data=None):
    factory = RequestFactory()
    if method == "POST":
        req = factory.post(url, data or {})
    else:
        req = factory.get(url)
    req.user = user
    req.tenant = tenant
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class CustomerInvoiceTenantFilterTests(TestCase):
    """Verify that customer invoice views include tenant= in all queries."""

    @classmethod
    def setUpTestData(cls):
        # Shop A
        cls.owner_a = _make_user("ownerA")
        cls.tenant_a = _make_tenant("shopA", owner=cls.owner_a)

        # Shop B
        cls.owner_b = _make_user("ownerB")
        cls.tenant_b = _make_tenant("shopB", owner=cls.owner_b)

        # Customer at Shop A
        cls.customer_a = Customer.objects.create(
            name="Fleet Alpha",
            tenant=cls.tenant_a,
        )

        # A user linked to customer at Shop A
        cls.cust_user = _make_user("custuser")
        cls.customer_user_a = CustomerUser.objects.create(
            user=cls.cust_user,
            customer=cls.customer_a,
            is_primary_contact=True,
        )
        TenantMembership.objects.create(
            user=cls.cust_user, tenant=cls.tenant_a, role="viewer", is_active=True,
        )

        # Invoice correctly at Shop A
        cls.invoice_a = Invoice.objects.create(
            tenant=cls.tenant_a,
            customer=cls.customer_a,
            invoice_number="INV-A-001",
            status="SENT",
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            amount_paid=Decimal("0.00"),
            invoice_date=timezone.now().date(),
        )

        # Simulated data-integrity anomaly: Invoice for same customer but
        # assigned to Shop B's tenant (should never happen, but defense-in-depth
        # must handle it).
        cls.invoice_b_anomaly = Invoice.objects.create(
            tenant=cls.tenant_b,
            customer=cls.customer_a,  # same customer FK
            invoice_number="INV-B-ANOMALY",
            status="SENT",
            total=Decimal("500.00"),
            subtotal=Decimal("500.00"),
            tax_amount=Decimal("0.00"),
            amount_paid=Decimal("0.00"),
            invoice_date=timezone.now().date(),
        )

    def test_customer_invoices_excludes_wrong_tenant(self):
        """customer_invoices should only show invoices matching the customer's tenant."""
        from apps.customer_portal.views import customer_invoices

        req = _make_request("GET", "/app/invoices/", self.cust_user, self.tenant_a)
        resp = customer_invoices(req)

        # Should be 200, not a redirect
        self.assertEqual(resp.status_code, 200)

        # The anomaly invoice (tenant_b) must NOT appear
        content = resp.content.decode()
        self.assertIn("INV-A-001", content)
        self.assertNotIn("INV-B-ANOMALY", content)

    def test_customer_invoice_detail_404_wrong_tenant(self):
        """customer_invoice_detail should 404 for invoice with mismatched tenant."""
        from apps.customer_portal.views import customer_invoice_detail

        req = _make_request(
            "GET",
            f"/app/invoices/{self.invoice_b_anomaly.id}/",
            self.cust_user,
            self.tenant_a,
        )
        # get_object_or_404 with tenant=customer.tenant should raise Http404
        with self.assertRaises(Http404):
            customer_invoice_detail(req, invoice_id=self.invoice_b_anomaly.id)

    def test_customer_invoice_detail_200_correct_tenant(self):
        """customer_invoice_detail should 200 for invoice with correct tenant."""
        from apps.customer_portal.views import customer_invoice_detail

        req = _make_request(
            "GET",
            f"/app/invoices/{self.invoice_a.id}/",
            self.cust_user,
            self.tenant_a,
        )
        resp = customer_invoice_detail(req, invoice_id=self.invoice_a.id)

        self.assertEqual(resp.status_code, 200)

    def test_customer_invoice_pay_404_wrong_tenant(self):
        """customer_invoice_pay should 404 for invoice with mismatched tenant."""
        from apps.customer_portal.views import customer_invoice_pay

        req = _make_request(
            "POST",
            f"/app/invoices/{self.invoice_b_anomaly.id}/pay/",
            self.cust_user,
            self.tenant_a,
        )
        # get_object_or_404 with tenant=customer.tenant should raise Http404
        with self.assertRaises(Http404):
            customer_invoice_pay(req, invoice_id=self.invoice_b_anomaly.id)
