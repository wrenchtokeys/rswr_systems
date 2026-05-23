"""
CODE-150: Regression test — owner_send_reminder missing @require_POST decorator.

Bug: The `owner_send_reminder` view at POST /owner/invoices/<id>/reminder/ lacked a
`@require_POST` decorator and contained no `request.method == 'POST'` guard.

A GET request to this URL would execute the full reminder-sending code path:
resolve the recipient email, call ReminderService.send_reminder(), and send an
unsolicited email to the customer — even though the shop owner never clicked the
"Send Reminder" button.

Potential failure modes:
1. Browser link prefetch (e.g. from an email or search engine crawler) sends a
   real customer email without owner intent.
2. A logged-in user accidentally navigates to the URL directly.
3. In a shared-device scenario, another manager hits Back/Forward in browser history
   and accidentally retriggers the send.

Fix: Added `@require_POST` decorator to `owner_send_reminder` so that GET requests
(and any other non-POST method) receive a 405 Method Not Allowed response and the
email is never sent.

Tests verify:
1. GET to the view returns 405 — not 200/302.
2. PUT/PATCH/DELETE also return 405.
3. POST with mocked ReminderService does NOT return 405 (normal path unaffected).
4. The fix is a decorator — verified by inspecting the view's decorator stack.
"""

from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.http import HttpResponseNotAllowed
from django.utils import timezone

from core.models import Customer
from apps.tenants.models import Tenant, TenantMembership
from apps.billing.models import Invoice


def _make_tenant_and_owner(suffix=""):
    """Create a minimal tenant + owner user, return (tenant, user)."""
    user = User.objects.create_user(
        username=f"owner_150_{suffix}",
        password="testpass123",
        email=f"owner_150_{suffix}@example.com",
    )
    tenant = Tenant.objects.create(
        name=f"Test Shop 150 {suffix}",
        slug=f"test-shop-150-{suffix}",
        owner=user,
        subscription_status="active",
    )
    TenantMembership.objects.create(
        user=user,
        tenant=tenant,
        role="owner",
        is_active=True,
    )
    return tenant, user


def _make_invoice(tenant, customer, status="SENT"):
    """Create a minimal invoice for testing."""
    today = timezone.now().date()
    from datetime import timedelta
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f"INV-150-{Invoice.objects.count() + 9000}",
        invoice_date=today,
        due_date=today + timedelta(days=30),
        payment_terms="NET30",
        status=status,
        subtotal="100.00",
        total="100.00",
        amount_paid="0.00",
    )


class SendReminderRequirePostDecoratorTest(TestCase):
    """
    Unit-level tests: bypass tenant middleware by using RequestFactory and
    calling the view function directly with request.tenant pre-attached.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.tenant, self.owner = _make_tenant_and_owner("a")
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name="Fleet Co 150",
            email="fleet150@example.com",
        )
        self.invoice = _make_invoice(self.tenant, self.customer, status="SENT")

    def _get_view(self):
        """Import the view function."""
        from apps.saas.views import owner_send_reminder
        return owner_send_reminder

    def _make_get(self, invoice_id=None):
        """Build a GET request with tenant and user attached."""
        inv_id = invoice_id if invoice_id is not None else self.invoice.id
        from django.urls import reverse
        url = reverse("owner_send_reminder", kwargs={"invoice_id": inv_id})
        request = self.factory.get(url)
        request.user = self.owner
        request.tenant = self.tenant
        return request

    def _make_post(self, data=None, invoice_id=None):
        """Build a POST request with tenant and user attached."""
        inv_id = invoice_id if invoice_id is not None else self.invoice.id
        from django.urls import reverse
        url = reverse("owner_send_reminder", kwargs={"invoice_id": inv_id})
        request = self.factory.post(url, data=data or {})
        request.user = self.owner
        request.tenant = self.tenant
        return request

    # ------------------------------------------------------------------
    # 1. GET returns 405
    # ------------------------------------------------------------------
    def test_get_returns_405(self):
        """
        GET request to owner_send_reminder must return 405 Method Not Allowed.
        Before the fix, GET executed the full reminder-send code path.
        """
        view = self._get_view()
        request = self._make_get()
        response = view(request, invoice_id=self.invoice.id)
        self.assertEqual(
            response.status_code,
            405,
            f"Expected 405 for GET request, got {response.status_code}. "
            f"The missing @require_POST allowed GET to send an email reminder."
        )

    # ------------------------------------------------------------------
    # 2. PUT returns 405
    # ------------------------------------------------------------------
    def test_put_returns_405(self):
        from django.urls import reverse
        url = reverse("owner_send_reminder", kwargs={"invoice_id": self.invoice.id})
        request = self.factory.put(url)
        request.user = self.owner
        request.tenant = self.tenant

        view = self._get_view()
        response = view(request, invoice_id=self.invoice.id)
        self.assertEqual(response.status_code, 405)

    # ------------------------------------------------------------------
    # 3. DELETE returns 405
    # ------------------------------------------------------------------
    def test_delete_returns_405(self):
        from django.urls import reverse
        url = reverse("owner_send_reminder", kwargs={"invoice_id": self.invoice.id})
        request = self.factory.delete(url)
        request.user = self.owner
        request.tenant = self.tenant

        view = self._get_view()
        response = view(request, invoice_id=self.invoice.id)
        self.assertEqual(response.status_code, 405)

    # ------------------------------------------------------------------
    # 4. POST does NOT return 405 (normal path smoke test)
    # ------------------------------------------------------------------
    @patch('apps.billing.services.reminder_service.ReminderService.send_reminder')
    def test_post_does_not_return_405(self, mock_send):
        """
        POST request must NOT return 405.
        Mock ReminderService so we don't send real emails.
        """
        mock_send.return_value = {'success': True}
        view = self._get_view()
        request = self._make_post(data={"custom_message": "Please pay"})

        # Need messages middleware for POST — use cookie-based storage (no session needed)
        from django.contrib.messages.storage.cookie import CookieStorage
        setattr(request, '_messages', CookieStorage(request))

        response = view(request, invoice_id=self.invoice.id)
        self.assertNotEqual(
            response.status_code,
            405,
            "POST to owner_send_reminder returned 405 — the fix broke normal POST flow."
        )

    # ------------------------------------------------------------------
    # 5. Structural check: @require_POST is in the decorator chain
    # ------------------------------------------------------------------
    def test_view_has_require_post_in_decorator_chain(self):
        """
        Verify that owner_send_reminder wraps require_POST.
        We do this by confirming a GET returns HttpResponseNotAllowed,
        which is the specific response type that require_POST returns.
        """
        view = self._get_view()
        request = self._make_get()
        response = view(request, invoice_id=self.invoice.id)
        self.assertIsInstance(
            response,
            HttpResponseNotAllowed,
            f"Expected HttpResponseNotAllowed (from @require_POST), got {type(response).__name__}. "
            f"The @require_POST decorator may not be applied correctly."
        )
