"""
CODE-039 regression: Draft invoices incorrectly marked OVERDUE

_get_billing_context() and owner_invoice_list() both auto-promoted invoices to
OVERDUE when past due_date. The status filter included 'DRAFT', meaning unsent
drafts with a past-due date were silently flipped to OVERDUE — hiding them from
the "Unpaid" filter and showing them as overdue when they were never sent.

Fix: Both update() calls now filter status__in=['SENT', 'PARTIAL'] only.
The canonical InvoiceTrackingService.update_overdue_statuses() was already correct.
"""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone

from apps.billing.models import Invoice
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant(slug):
    # Create an owner user first so tenant.owner_id isn't null
    owner_user = User.objects.create_user(
        username=f"owner_{slug}", email=f"owner_{slug}@example.com", password="pw"
    )
    tenant = Tenant.objects.create(
        name=f"Shop {slug}",
        slug=slug,
        subdomain=slug,
        is_active=True,
        owner=owner_user,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner_user, role="owner", is_active=True)
    return tenant, owner_user


def _make_owner(tenant, email):
    user = User.objects.create_user(username=email, email=email, password="pw")
    TenantMembership.objects.create(tenant=tenant, user=user, role="owner", is_active=True)
    return user


def _make_invoice(tenant, customer, status, due_offset_days):
    """Create an invoice with due_date = today + offset days (negative = overdue)."""
    today = timezone.now().date()
    due = today + datetime.timedelta(days=due_offset_days)
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f"INV-{status}-{due_offset_days}",
        invoice_date=today,
        due_date=due,
        payment_terms="NET_30",
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        status=status,
    )


class DraftOverdueProtectionTests(TestCase):
    """DRAFT invoices must never be auto-promoted to OVERDUE."""

    def setUp(self):
        from core.models import Customer
        self.tenant, self.owner = _make_tenant("draft-test")
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Test Customer",
            email="cust@example.com",
        )

    def _call_billing_context(self):
        """Trigger _get_billing_context() which has the overdue-update side-effect."""
        from apps.saas.views import _get_billing_context
        _get_billing_context(self.tenant)

    def _call_invoice_list_view(self):
        """Trigger owner_invoice_list() view which also has the overdue-update side-effect."""
        from apps.saas.views import owner_invoice_list
        from unittest.mock import MagicMock

        request = RequestFactory().get("/owner/invoices/")
        request.user = self.owner
        request.tenant = self.tenant

        # Patch _get_owner_tenant to return our tenant/membership
        membership = TenantMembership.objects.get(tenant=self.tenant, user=self.owner)
        with patch("apps.saas.views._get_owner_tenant", return_value=(self.tenant, membership)):
            owner_invoice_list(request)

    def test_draft_past_due_not_promoted_by_billing_context(self):
        """_get_billing_context() must NOT flip a DRAFT invoice to OVERDUE."""
        draft = _make_invoice(self.tenant, self.customer, "DRAFT", -5)  # 5 days past due
        self._call_billing_context()
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DRAFT",
                         "DRAFT invoices must not be auto-promoted to OVERDUE by _get_billing_context")

    def test_draft_past_due_not_promoted_by_invoice_list_view(self):
        """owner_invoice_list() must NOT flip a DRAFT invoice to OVERDUE."""
        draft = _make_invoice(self.tenant, self.customer, "DRAFT", -10)  # 10 days past due
        self._call_invoice_list_view()
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DRAFT",
                         "DRAFT invoices must not be auto-promoted to OVERDUE by owner_invoice_list")

    def test_sent_past_due_is_promoted_by_billing_context(self):
        """SENT invoices past due_date SHOULD be promoted to OVERDUE (control test)."""
        sent = _make_invoice(self.tenant, self.customer, "SENT", -3)
        self._call_billing_context()
        sent.refresh_from_db()
        self.assertEqual(sent.status, "OVERDUE")

    def test_sent_past_due_is_promoted_by_invoice_list_view(self):
        """SENT invoices past due_date SHOULD be promoted to OVERDUE in invoice list view."""
        sent = _make_invoice(self.tenant, self.customer, "SENT", -7)
        self._call_invoice_list_view()
        sent.refresh_from_db()
        self.assertEqual(sent.status, "OVERDUE")

    def test_partial_past_due_is_promoted_by_billing_context(self):
        """PARTIAL invoices past due_date SHOULD be promoted to OVERDUE."""
        partial = _make_invoice(self.tenant, self.customer, "PARTIAL", -2)
        self._call_billing_context()
        partial.refresh_from_db()
        self.assertEqual(partial.status, "OVERDUE")

    def test_draft_future_due_untouched(self):
        """DRAFT invoice with future due_date must remain DRAFT."""
        draft = _make_invoice(self.tenant, self.customer, "DRAFT", 10)
        self._call_billing_context()
        draft.refresh_from_db()
        self.assertEqual(draft.status, "DRAFT")

    def test_paid_invoice_not_promoted(self):
        """PAID invoices must never be promoted to OVERDUE."""
        paid = _make_invoice(self.tenant, self.customer, "PAID", -30)
        self._call_billing_context()
        paid.refresh_from_db()
        self.assertEqual(paid.status, "PAID")

    def test_cancelled_invoice_not_promoted(self):
        """CANCELLED invoices must never be promoted to OVERDUE."""
        cancelled = _make_invoice(self.tenant, self.customer, "CANCELLED", -15)
        self._call_billing_context()
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, "CANCELLED")

    def test_cross_tenant_draft_not_promoted(self):
        """Draft invoices from a different tenant must not be promoted."""
        from core.models import Customer
        other_tenant, _ = _make_tenant("other-draft")
        other_customer = Customer.objects.create(
            tenant=other_tenant,
            name="Other Customer",
            email="other@example.com",
        )
        other_draft = _make_invoice(other_tenant, other_customer, "DRAFT", -5)
        self._call_billing_context()  # only touches self.tenant
        other_draft.refresh_from_db()
        self.assertEqual(other_draft.status, "DRAFT")
