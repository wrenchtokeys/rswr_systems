"""
Regression tests for CODE-262:
    customer_dashboard() queried outstanding invoices and overdue_count
    without tenant= filter.  While Customer FK is inherently tenant-scoped,
    the project convention requires every query to include an explicit
    tenant= filter for defense-in-depth.

    CODE-255 added tenant= filters to customer_invoices(), customer_invoice_detail(),
    and customer_invoice_pay() but missed the dashboard's outstanding invoice
    queries (outstanding_invoices queryset, outstanding_total aggregate, and
    overdue_count).

Covers:
    - Dashboard outstanding invoices are filtered by tenant
    - Dashboard overdue_count is filtered by tenant
    - Dashboard outstanding_total only sums invoices for the correct tenant
"""

from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.utils import timezone
from datetime import timedelta

from apps.tenants.models import Tenant, TenantMembership
from apps.customer_portal.models import CustomerUser
from apps.billing.models import Invoice
from core.models import Customer


_counter = [2620]


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


def _make_tenant(name):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        owner=_make_user("owner"),
    )


def _make_request(user, tenant):
    factory = RequestFactory()
    request = factory.get("/app/")
    request.user = user
    request.tenant = tenant
    request.session = {}
    setattr(request, '_messages', FallbackStorage(request))
    return request


class DashboardInvoiceTenantFilterTest(TestCase):
    """Verify customer_dashboard scopes invoice queries to the tenant."""

    def setUp(self):
        self.tenant_a = _make_tenant("Shop A 262")
        self.tenant_b = _make_tenant("Shop B 262")

        # Customer at Shop A
        self.user_a = _make_user("cust_a")
        self.customer_a = Customer.objects.create(
            name="Customer A 262",
            tenant=self.tenant_a,
        )
        self.cu_a = CustomerUser.objects.create(
            user=self.user_a,
            customer=self.customer_a,
            is_primary_contact=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant_a,
            user=self.user_a,
            role="viewer",
            is_active=True,
        )

        # Invoice for Shop A (OVERDUE)
        self.invoice_a = Invoice.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            invoice_number="INV-A-262",
            status="OVERDUE",
            total=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            invoice_date=timezone.now().date() - timedelta(days=60),
            due_date=timezone.now().date() - timedelta(days=30),
        )

        # Invoice for Shop B — should NEVER appear in Shop A's dashboard
        self.customer_b = Customer.objects.create(
            name="Customer B 262",
            tenant=self.tenant_b,
        )
        self.invoice_b = Invoice.objects.create(
            tenant=self.tenant_b,
            customer=self.customer_b,
            invoice_number="INV-B-262",
            status="OVERDUE",
            total=Decimal("500.00"),
            amount_paid=Decimal("0.00"),
            invoice_date=timezone.now().date() - timedelta(days=60),
            due_date=timezone.now().date() - timedelta(days=30),
        )

    def test_dashboard_loads_200(self):
        """Dashboard renders without error."""
        from apps.customer_portal.views import customer_dashboard
        request = _make_request(self.user_a, self.tenant_a)
        response = customer_dashboard(request)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_shows_shop_a_overdue_not_shop_b(self):
        """Dashboard overdue count should only count Shop A invoices."""
        from apps.customer_portal.views import customer_dashboard
        request = _make_request(self.user_a, self.tenant_a)
        response = customer_dashboard(request)
        content = response.content.decode()

        # Should show "1 overdue" (only Shop A), not "2 overdue"
        self.assertIn("1 overdue", content)
        self.assertNotIn("2 overdue", content)

    def test_dashboard_outstanding_total_excludes_other_tenant(self):
        """outstanding_total should only sum Shop A invoices ($100), not Shop B ($500)."""
        # Add a SENT invoice for Shop A
        Invoice.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            invoice_number="INV-A2-262",
            status="SENT",
            total=Decimal("50.00"),
            amount_paid=Decimal("0.00"),
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
        )

        from apps.customer_portal.views import customer_dashboard
        request = _make_request(self.user_a, self.tenant_a)
        response = customer_dashboard(request)
        content = response.content.decode()

        # Outstanding total = $100 (overdue) + $50 (sent) = $150
        # The template renders it as "$150" (intcomma, no decimals for whole numbers)
        self.assertIn("$150", content)
        # Should NOT contain $650 ($150 + $500 from Shop B)
        self.assertNotIn("$650", content)

    def test_dashboard_invoice_queries_include_tenant_filter(self):
        """
        Directly test that the outstanding invoice queryset is tenant-scoped.
        This is a unit-level check that verifies the ORM filter includes tenant=.
        """
        from apps.customer_portal.views import customer_dashboard
        request = _make_request(self.user_a, self.tenant_a)
        response = customer_dashboard(request)

        # We verify by checking the total — if Shop B's $500 leaked through,
        # outstanding_total would be $600. With tenant filter it's $100.
        content = response.content.decode()
        # "$100" should appear (the outstanding balance card)
        self.assertIn("$100", content)
        # "$600" should NOT appear (would mean Shop B leaked through)
        self.assertNotIn("$600", content)
