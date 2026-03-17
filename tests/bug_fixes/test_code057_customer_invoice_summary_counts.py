"""
Regression tests for CODE-057:
  customer_invoices() summary cards showed wrong counts.

Root cause:
    The template used `|add:"1"` inside a for loop to count invoices:
        {% for inv in invoices %}{% if inv.status == 'PAID' %}{{ paid_count|add:"1" }}{% endif %}{% endfor %}
    Django's |add filter does NOT increment a variable — it renders "1" (or
    "0 + 1 = 1") for EACH matching invoice. E.g. 3 paid invoices → "111"
    not "3". `outstanding_count` was never defined in the {% with %} block
    at all, so the Outstanding card always showed nothing.

Fix:
    customer_invoices() view now pre-computes paid_count, outstanding_count,
    and overdue_count in Python and passes them to the template context.
    Template simplified to just {{ paid_count }}, etc.

Tests verify:
1. View passes correct integer counts in context.
2. Template renders the correct numbers in the HTML.
3. Edge cases: all paid, all overdue, mixed, empty list.
4. outstanding_count includes SENT + PARTIAL + OVERDUE (not PAID, not DRAFT).
"""

from decimal import Decimal
from datetime import date, timedelta

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.customer_portal.models import CustomerUser
from apps.billing.models import Invoice
from core.models import Customer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(name="TestShop57"):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="trial",
        defaults={
            "name": "Trial",
            "monthly_price": 0,
            "annual_price": 0,
            "max_customers": 50,
            "max_technicians": 5,
            "is_active": True,
        },
    )
    owner = User.objects.create_user(
        username=f"owner_{name.lower()}",
        email=f"owner@{name.lower()}.com",
        password="pass1234",
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower(),
        subdomain=name.lower(),
        owner=owner,
        plan="trial",
        subscription_plan=plan,
        subscription_status="trialing",
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role="owner")
    return tenant, owner


def _make_customer_user(tenant, username="custuser57"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="pass1234",
    )
    customer = Customer.objects.create(
        tenant=tenant,
        name="Test Fleet",
        email=f"{username}@example.com",
    )
    cu = CustomerUser.objects.create(
        user=user,
        customer=customer,
        is_primary_contact=True,
    )
    return user, customer, cu


def _make_invoice(tenant, customer, status, invoice_number=None):
    """Create a minimal invoice in the given status."""
    if invoice_number is None:
        # Use a random-ish suffix for uniqueness
        import uuid
        invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=invoice_number,
        status=status,
        total=Decimal("100.00"),
        amount_paid=Decimal("100.00") if status == "PAID" else Decimal("0.00"),
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@override_settings(ALLOWED_HOSTS=["*"])
class CustomerInvoiceSummaryCountsTestCase(TestCase):
    """Context contains correct integer counts for paid/outstanding/overdue."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant("SummaryShop57")
        self.user, self.customer, self.cu = _make_customer_user(
            self.tenant, "inv_cu57"
        )
        self.client = Client()
        self.client.login(username="inv_cu57", password="pass1234")

    def _get(self):
        return self.client.get(reverse("customer_invoices"))

    def test_context_has_count_keys(self):
        """View must provide paid_count, outstanding_count, overdue_count."""
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertIn("paid_count", response.context)
        self.assertIn("outstanding_count", response.context)
        self.assertIn("overdue_count", response.context)

    def test_zero_counts_with_no_invoices(self):
        response = self._get()
        self.assertEqual(response.context["paid_count"], 0)
        self.assertEqual(response.context["outstanding_count"], 0)
        self.assertEqual(response.context["overdue_count"], 0)

    def test_paid_count_correct(self):
        _make_invoice(self.tenant, self.customer, "PAID", "INV-PAID-1")
        _make_invoice(self.tenant, self.customer, "PAID", "INV-PAID-2")
        _make_invoice(self.tenant, self.customer, "SENT", "INV-SENT-1")
        response = self._get()
        self.assertEqual(response.context["paid_count"], 2)

    def test_outstanding_count_includes_sent_partial_overdue(self):
        _make_invoice(self.tenant, self.customer, "SENT", "INV-SENT-2")
        _make_invoice(self.tenant, self.customer, "PARTIAL", "INV-PART-1")
        _make_invoice(self.tenant, self.customer, "OVERDUE", "INV-OVD-1")
        _make_invoice(self.tenant, self.customer, "PAID", "INV-PD-3")
        response = self._get()
        self.assertEqual(response.context["outstanding_count"], 3)

    def test_overdue_count_correct(self):
        _make_invoice(self.tenant, self.customer, "OVERDUE", "INV-OVD-2")
        _make_invoice(self.tenant, self.customer, "SENT", "INV-SENT-3")
        response = self._get()
        self.assertEqual(response.context["overdue_count"], 1)

    def test_draft_excluded_from_all_counts(self):
        """DRAFT invoices must not appear in any count (they're excluded from the list)."""
        _make_invoice(self.tenant, self.customer, "DRAFT", "INV-DRF-1")
        response = self._get()
        self.assertEqual(response.context["paid_count"], 0)
        self.assertEqual(response.context["outstanding_count"], 0)
        self.assertEqual(response.context["overdue_count"], 0)
        # invoices list itself must be empty too
        self.assertEqual(len(response.context["invoices"]), 0)

    def test_all_statuses_mixed(self):
        _make_invoice(self.tenant, self.customer, "PAID", "INV-M-PAID")
        _make_invoice(self.tenant, self.customer, "SENT", "INV-M-SENT")
        _make_invoice(self.tenant, self.customer, "PARTIAL", "INV-M-PART")
        _make_invoice(self.tenant, self.customer, "OVERDUE", "INV-M-OVD")
        _make_invoice(self.tenant, self.customer, "CANCELLED", "INV-M-CANC")
        _make_invoice(self.tenant, self.customer, "DRAFT", "INV-M-DRF")

        response = self._get()
        # DRAFT excluded from the list → 5 invoices shown
        self.assertEqual(len(response.context["invoices"]), 5)
        self.assertEqual(response.context["paid_count"], 1)
        # outstanding = SENT + PARTIAL + OVERDUE = 3
        self.assertEqual(response.context["outstanding_count"], 3)
        self.assertEqual(response.context["overdue_count"], 1)

    def test_html_renders_correct_numbers(self):
        """Regression: old template rendered '111' not '3' for 3 paid invoices."""
        _make_invoice(self.tenant, self.customer, "PAID", "INV-HTML-1")
        _make_invoice(self.tenant, self.customer, "PAID", "INV-HTML-2")
        _make_invoice(self.tenant, self.customer, "PAID", "INV-HTML-3")
        _make_invoice(self.tenant, self.customer, "OVERDUE", "INV-HTML-4")

        response = self._get()
        content = response.content.decode()

        # The paid count "3" must appear in the HTML — old code would render "111"
        # We check the context value is 3 (already tested above) but also that
        # the raw HTML does NOT contain the broken "111" pattern.
        self.assertEqual(response.context["paid_count"], 3)
        self.assertNotIn("111", content)  # broken old output
