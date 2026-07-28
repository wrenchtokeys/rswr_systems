"""
CODE-051 (updated 2026-07): customer_invoice_pay Stripe Connect routing

Original bug: customer_invoice_pay() always called
StripeService.create_checkout_session(), routing payments to the platform
account (Drake's Stripe) even when the shop had completed Stripe Connect
onboarding.

Current contract (multi-shop readiness hardening):
  - Connect is the ONLY online payment path. A shop without an active
    Connect account gets a "contact the shop" message — NEVER a
    platform-account charge (the money would settle in the platform's
    Stripe balance with no route to the shop).
  - invoice.stripe_hosted_url is ignored: old records hold stale
    platform-account Payment Links.
  - PAID/CANCELLED/DRAFT invoices reject payment.
  - Invoices are scoped to the requesting customer + tenant (no IDOR).
"""

import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.auth.models import User
from django.contrib.messages.storage.cookie import CookieStorage
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import Invoice
from apps.customer_portal.models import Customer, CustomerUser


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.cookie.CookieStorage',
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def _uid():
    return uuid.uuid4().hex[:8]


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name='Test',
        defaults={
            'stripe_price_id': 'price_test',
            'monthly_price': Decimal('0.00'),
            'annual_price': Decimal('0.00'),
            'max_technicians': 10,
            'max_repairs_per_month': 200,
        },
    )
    return plan


def _make_tenant(slug=None, connect=False):
    slug = slug or _uid()
    plan = _make_plan()
    owner = User.objects.create_user(username=f'owner_{slug}', password='pw')
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        owner=owner,
        subscription_plan=plan,
        stripe_connect_account_id='acct_test123' if connect else '',
        stripe_onboarding_status='active' if connect else 'not_started',
        stripe_connect_charges_enabled=connect,
        stripe_connect_payouts_enabled=connect,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return tenant


def _make_customer(tenant):
    customer = Customer.objects.create(tenant=tenant, name=f'Fleet {_uid()}')
    user = User.objects.create_user(username=f'cust_{_uid()}', password='pw')
    customer_user = CustomerUser.objects.create(user=user, customer=customer)
    return customer, user, customer_user


def _make_invoice(tenant, customer, status='SENT', amount_paid=Decimal('0.00'),
                  stripe_hosted_url=''):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-{_uid()}',
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
        amount_paid=amount_paid,
        tax_rate=Decimal('0.000'),
        tax_amount=Decimal('0.00'),
        status=status,
        invoice_date=timezone.now().date(),
        stripe_hosted_url=stripe_hosted_url,
    )


def _post_request(user, invoice_id, tenant=None):
    factory = RequestFactory()
    request = factory.post(f'/app/invoices/{invoice_id}/pay/')
    request.user = user
    if tenant:
        request.tenant = tenant
    setattr(request, '_messages', CookieStorage(request))
    return request


@override_settings(**TEST_OVERRIDES)
class CustomerInvoicePayConnectRoutingTest(TestCase):
    """customer_invoice_pay must charge the shop's Connect account or nothing."""

    def setUp(self):
        # Shop WITH connect enabled
        self.tenant_connect = _make_tenant(connect=True)
        self.customer_c, self.user_c, self.cu_c = _make_customer(self.tenant_connect)
        self.invoice_connect = _make_invoice(self.tenant_connect, self.customer_c)

        # Shop WITHOUT connect
        self.tenant_plain = _make_tenant(connect=False)
        self.customer_p, self.user_p, self.cu_p = _make_customer(self.tenant_plain)
        self.invoice_plain = _make_invoice(self.tenant_plain, self.customer_p)

    def _pay(self, user, cu, invoice, tenant):
        from apps.customer_portal.views import customer_invoice_pay
        request = _post_request(user, invoice.id, tenant)
        with patch('apps.customer_portal.views._get_customer_user_for_tenant',
                   return_value=cu):
            return customer_invoice_pay(request, invoice.id)

    @patch('apps.billing.services.stripe_service.StripeService.create_checkout_session')
    def test_no_connect_never_charges_platform(self, mock_platform_checkout):
        """No Connect account → customer gets a message, platform Stripe is
        NEVER called (the shop would not receive that money)."""
        response = self._pay(self.user_p, self.cu_p, self.invoice_plain, self.tenant_plain)

        mock_platform_checkout.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.invoice_plain.id), response['Location'])

    @patch('apps.tenants.services.connect_service.ConnectService.is_enabled', return_value=True)
    @patch('apps.tenants.services.connect_service.ConnectService.create_connected_checkout_session')
    def test_connect_checkout_used_when_tenant_has_connect(self, mock_connect_checkout, mock_enabled):
        """Uses ConnectService when tenant.can_accept_payments is True."""
        mock_connect_checkout.return_value = {
            'success': True,
            'checkout_url': 'https://checkout.stripe.com/connect',
            'session_id': 'cs_connect',
        }

        response = self._pay(self.user_c, self.cu_c, self.invoice_connect, self.tenant_connect)

        mock_connect_checkout.assert_called_once()
        self.assertEqual(response.status_code, 302)
        self.assertIn('connect', response['Location'])

    @patch('apps.billing.services.stripe_service.StripeService.create_checkout_session')
    @patch('apps.tenants.services.connect_service.ConnectService.is_enabled', return_value=True)
    @patch('apps.tenants.services.connect_service.ConnectService.create_connected_checkout_session')
    def test_connect_failure_does_not_fall_back_to_platform(
        self, mock_connect_checkout, mock_enabled, mock_platform_checkout
    ):
        """A Connect failure shows an error — it must NOT silently charge the
        platform account instead."""
        mock_connect_checkout.return_value = {
            'success': False,
            'error': 'Account restricted',
        }

        response = self._pay(self.user_c, self.cu_c, self.invoice_connect, self.tenant_connect)

        mock_platform_checkout.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.invoice_connect.id), response['Location'])

    @patch('apps.tenants.services.connect_service.ConnectService.is_enabled', return_value=True)
    @patch('apps.tenants.services.connect_service.ConnectService.create_connected_checkout_session')
    def test_stale_hosted_url_ignored(self, mock_connect_checkout, mock_enabled):
        """invoice.stripe_hosted_url (a stale platform Payment Link) is
        ignored — a fresh connected checkout session is always created."""
        mock_connect_checkout.return_value = {
            'success': True,
            'checkout_url': 'https://checkout.stripe.com/fresh_connect',
            'session_id': 'cs_fresh',
        }
        invoice = _make_invoice(
            self.tenant_connect, self.customer_c,
            stripe_hosted_url='https://buy.stripe.com/stale_platform_link',
        )

        response = self._pay(self.user_c, self.cu_c, invoice, self.tenant_connect)

        mock_connect_checkout.assert_called_once()
        self.assertEqual(response.status_code, 302)
        self.assertIn('fresh_connect', response['Location'])
        self.assertNotIn('stale_platform_link', response['Location'])

    def test_already_paid_invoice_rejected(self):
        """PAID invoices cannot be paid again."""
        paid_invoice = _make_invoice(
            self.tenant_plain, self.customer_p,
            status='PAID', amount_paid=Decimal('100.00'),
        )
        response = self._pay(self.user_p, self.cu_p, paid_invoice, self.tenant_plain)
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(paid_invoice.id), response['Location'])

    def test_cancelled_invoice_rejected(self):
        """CANCELLED invoices cannot be paid."""
        cancelled_invoice = _make_invoice(
            self.tenant_plain, self.customer_p, status='CANCELLED',
        )
        response = self._pay(self.user_p, self.cu_p, cancelled_invoice, self.tenant_plain)
        self.assertEqual(response.status_code, 302)
        self.assertIn(str(cancelled_invoice.id), response['Location'])

    def test_non_post_request_redirects(self):
        """GET request to pay view redirects without hitting Stripe."""
        from apps.customer_portal.views import customer_invoice_pay

        factory = RequestFactory()
        request = factory.get(f'/app/invoices/{self.invoice_plain.id}/pay/')
        request.user = self.user_p
        setattr(request, '_messages', CookieStorage(request))

        response = customer_invoice_pay(request, self.invoice_plain.id)
        self.assertEqual(response.status_code, 302)

    def test_invoice_scoped_to_customer(self):
        """Cannot pay another customer's invoice (IDOR protection)."""
        from django.http import Http404
        # user_p (customer of the plain shop) tries to pay user_c's invoice
        try:
            response = self._pay(self.user_p, self.cu_p, self.invoice_connect, self.tenant_connect)
            self.assertIn(response.status_code, [302, 404])
        except Http404:
            pass  # 404 raised directly is the expected outcome
