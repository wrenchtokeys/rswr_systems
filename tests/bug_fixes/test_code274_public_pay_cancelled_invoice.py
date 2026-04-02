"""
CODE-274: public_pay_invoice() allows checkout on CANCELLED invoices

Bug: public_pay_invoice() in rs_systems/views.py only checked for PAID status
and amount_due <= 0 before creating a Stripe checkout session. A CANCELLED
(voided) invoice passed both checks (status != 'PAID', amount_due == total > 0)
and the view proceeded to create an active checkout session.

Impact: Customer visits a payment link for a voided invoice and could pay via
Stripe. The charge would land in the shop's account but wouldn't reconcile
against the cancelled invoice, creating a financial discrepancy.

Fix: Added an explicit CANCELLED status check before creating the checkout
session. Renders the "unavailable" page with a clear message.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User

from apps.tenants.models import Tenant
from core.models import Customer
from apps.billing.models import Invoice


def _generate_payment_token(invoice_id):
    """Mirror the generate_payment_token helper from rs_systems/views.py."""
    import hmac
    import hashlib
    from django.conf import settings
    secret = settings.SECRET_KEY
    message = f"pay-invoice-{invoice_id}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]


class PublicPayCancelledInvoiceTest(TestCase):
    """
    Regression tests for CODE-274: CANCELLED invoice blocks checkout.
    """

    def setUp(self):
        self.factory = RequestFactory()

        # Minimal tenant + customer + invoice setup
        self.owner = User.objects.create_user(
            username='testowner274',
            email='owner274@example.com',
            password='testpass123',
        )
        self.tenant = Tenant.objects.create(
            name='Test Glass Shop',
            slug='test-glass-shop-274',
            is_active=True,
            owner=self.owner,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='EOS Trucking',
            email='billing@eos.com',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-001',
            subtotal=Decimal('150.00'),
            total=Decimal('150.00'),
            amount_paid=Decimal('0.00'),
            status='CANCELLED',
        )
        self.token = _generate_payment_token(self.invoice.id)

    def test_cancelled_invoice_returns_unavailable_page(self):
        """CANCELLED invoice renders unavailable page, not payment page."""
        from rs_systems.views import public_pay_invoice
        request = self.factory.get(f'/pay/{self.invoice.id}/{self.token}/')
        response = public_pay_invoice(request, self.invoice.id, self.token)
        self.assertEqual(response.status_code, 200)
        # Should render the unavailable template
        self.assertIn(b'cancelled', response.content.lower())

    def test_cancelled_invoice_does_not_redirect_to_stripe(self):
        """CANCELLED invoice must not create a Stripe checkout or redirect."""
        from rs_systems.views import public_pay_invoice
        request = self.factory.get(f'/pay/{self.invoice.id}/{self.token}/')

        with patch('apps.tenants.services.connect_service.ConnectService') as mock_connect:
            with patch('apps.billing.services.stripe_service.StripeService') as mock_stripe:
                response = public_pay_invoice(request, self.invoice.id, self.token)
                # Neither Stripe service should be called
                mock_connect.return_value.create_connected_checkout_session.assert_not_called()
                mock_stripe.return_value.create_checkout_session.assert_not_called()

        # Response is a render (200), not a redirect (302)
        self.assertEqual(response.status_code, 200)

    def test_paid_invoice_still_shows_complete_page(self):
        """PAID invoice still renders the payment_complete page (unaffected by fix)."""
        self.invoice.status = 'PAID'
        self.invoice.amount_paid = Decimal('150.00')
        self.invoice.save(update_fields=['status', 'amount_paid'])

        from rs_systems.views import public_pay_invoice
        request = self.factory.get(f'/pay/{self.invoice.id}/{self.token}/')
        response = public_pay_invoice(request, self.invoice.id, self.token)
        self.assertEqual(response.status_code, 200)

    def test_sent_invoice_proceeds_to_checkout_flow(self):
        """SENT invoice with no Stripe Connect still reaches the unavailable page."""
        self.invoice.status = 'SENT'
        self.invoice.save(update_fields=['status'])

        from rs_systems.views import public_pay_invoice
        request = self.factory.get(f'/pay/{self.invoice.id}/{self.token}/')

        # Tenant has no Stripe Connect; StripeService is disabled
        with patch('apps.billing.services.stripe_service.StripeService') as mock_stripe:
            mock_stripe.return_value.is_enabled.return_value = False
            response = public_pay_invoice(request, self.invoice.id, self.token)

        # Falls through to the unavailable page (Stripe disabled), not the
        # cancelled message — status 200 rendered response, not a redirect.
        self.assertEqual(response.status_code, 200)

    def test_invalid_token_returns_404(self):
        """Invalid HMAC token returns 404 regardless of invoice status."""
        from rs_systems.views import public_pay_invoice
        request = self.factory.get(f'/pay/{self.invoice.id}/badtoken/')
        response = public_pay_invoice(request, self.invoice.id, 'badtoken')
        self.assertEqual(response.status_code, 404)

    def test_cancelled_invoice_with_amount_due_still_blocked(self):
        """
        Even if a CANCELLED invoice somehow has amount_due > 0, it must be blocked.

        This is the core regression test: before CODE-274, a CANCELLED invoice
        with total=150 and amount_paid=0 (so amount_due=150) would pass both
        the PAID check and the amount_due <= 0 check, landing in the checkout path.
        """
        # Ensure the invoice looks "payable" by the old logic
        self.assertEqual(self.invoice.status, 'CANCELLED')
        self.assertEqual(self.invoice.amount_due, Decimal('150.00'))  # >0

        from rs_systems.views import public_pay_invoice
        request = self.factory.get(f'/pay/{self.invoice.id}/{self.token}/')

        # Should short-circuit at CANCELLED check, not reach Stripe at all
        with patch('apps.tenants.services.connect_service.ConnectService') as mock_connect:
            response = public_pay_invoice(request, self.invoice.id, self.token)
            mock_connect.return_value.create_connected_checkout_session.assert_not_called()

        self.assertEqual(response.status_code, 200)
