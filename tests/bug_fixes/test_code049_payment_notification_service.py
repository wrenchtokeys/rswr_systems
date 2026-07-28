"""
CODE-049: PaymentNotificationService — zero test coverage

The PaymentNotificationService sends:
  1. send_customer_receipt() — email to the paying customer with invoice summary
  2. send_owner_notification() — plain-text alert to the shop owner
  3. notify_payment()        — main entry point; calls both above

These methods fire on every invoice payment (Stripe webhook, manual recording).
A silent bug here means customers get no receipt and owners miss payment alerts.

Tests cover:
  1.  send_customer_receipt — happy path: email sent, returns True
  2.  send_customer_receipt — uses billing_email over customer.email when set
  3.  send_customer_receipt — falls back to customer.email when billing_email is blank
  4.  send_customer_receipt — returns False (no email) when both email sources empty
  5.  send_customer_receipt — returns False on SMTP/template exception
  6.  send_owner_notification — happy path: email sent, returns True
  7.  send_owner_notification — returns False when no owner email configured
  8.  send_owner_notification — uses DEFAULT_OWNER_EMAIL when BillingConfig has no email
  9.  send_owner_notification — returns False on SMTP exception
  10. notify_payment — calls both sub-methods; returns correct dict
  11. notify_payment — partial failure: customer sent, owner not → correct dict
  12. notify_payment — branding lazy-loads and caches (no duplicate DB query)
"""

import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock, PropertyMock

from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant, SubscriptionPlan
from apps.billing.models import BillingConfig, Invoice, Payment
from apps.customer_portal.models import Customer, CustomerRepairPreference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid():
    return uuid.uuid4().hex[:8]


def _make_tenant(slug=None):
    slug = slug or _uid()
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name='Test Plan',
        defaults={
            'stripe_price_id': 'price_test',
            'monthly_price': Decimal('0.00'),
            'annual_price': Decimal('0.00'),
            'max_technicians': 10,
            'max_repairs_per_month': 200,
        },
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@example.com',
        password='testpass',
    )
    return Tenant.objects.create(
        name=f'Tenant {slug}',
        slug=slug,
        plan=plan,
        owner=owner,
        is_active=True,
    )


def _make_customer(tenant, email='fleet@example.com'):
    return Customer.objects.create(
        tenant=tenant,
        name='Acme Fleet',
        email=email,
    )


def _make_invoice(tenant, customer, total='500.00', amount_paid='500.00', status='PAID'):
    invoice = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-{_uid()}',
        subtotal=Decimal(total),
        total=Decimal(total),
        amount_paid=Decimal(amount_paid),
        status=status,
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
    )
    return invoice


def _make_payment(invoice, amount='500.00', method='CHECK'):
    return Payment.objects.create(
        invoice=invoice,
        amount=Decimal(amount),
        payment_date=timezone.now().date(),
        payment_method=method,
    )


# ---------------------------------------------------------------------------
# Test fixtures shared via setUp
# ---------------------------------------------------------------------------

class PaymentNotificationServiceTestCase(TestCase):
    """Base fixture setup."""

    def setUp(self):
        self.tenant = _make_tenant('pns-test')
        self.customer = _make_customer(self.tenant, email='fleet@acme.example.com')
        self.invoice = _make_invoice(self.tenant, self.customer)
        # We create the Payment without triggering save() side-effects in most tests.
        self.payment = Payment(
            invoice=self.invoice,
            amount=Decimal('500.00'),
            payment_date=timezone.now().date(),
            payment_method='CHECK',
        )
        # Give BillingConfig an owner email
        cfg, _ = BillingConfig.objects.get_or_create(tenant=self.tenant)
        cfg.company_email = 'owner@rockstar.example.com'
        cfg.save()

    def _make_svc(self):
        from apps.billing.services.payment_notification_service import PaymentNotificationService
        svc = PaymentNotificationService()
        # Pre-seed branding to avoid DB hit during each test
        svc._branding = {
            'company_name': 'Test Shop',
            'primary_color': '#000',
            'secondary_color': '#000',
            'success_color': '#000',
            'danger_color': '#000',
            'text_color': '#000',
            'background_color': '#fff',
            'heading_font': 'Arial',
            'body_font': 'Arial',
            'button_border_radius': 4,
            'support_email': '',
            'support_phone': '',
        }
        return svc


# ---------------------------------------------------------------------------
# send_customer_receipt
# ---------------------------------------------------------------------------

class SendCustomerReceiptTests(PaymentNotificationServiceTestCase):

    @patch('apps.billing.services.payment_notification_service.render_to_string', return_value='body')
    @patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives')
    def test_happy_path_returns_true(self, mock_email_cls, mock_render):
        """Receipt email sent successfully → returns True."""
        mock_email_instance = MagicMock()
        mock_email_cls.return_value = mock_email_instance

        svc = self._make_svc()
        result = svc.send_customer_receipt(self.payment)

        self.assertTrue(result)
        mock_email_cls.assert_called_once()
        mock_email_instance.send.assert_called_once()

    @patch('apps.billing.services.payment_notification_service.render_to_string', return_value='body')
    @patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives')
    def test_uses_billing_email_over_customer_email(self, mock_email_cls, mock_render):
        """billing_email in CustomerRepairPreference takes priority over customer.email."""
        prefs, _ = CustomerRepairPreference.objects.get_or_create(
            customer=self.customer,
            defaults={'billing_email': 'billing@acme.example.com'},
        )
        prefs.billing_email = 'billing@acme.example.com'
        prefs.save()

        mock_email_instance = MagicMock()
        mock_email_cls.return_value = mock_email_instance

        svc = self._make_svc()
        result = svc.send_customer_receipt(self.payment)

        self.assertTrue(result)
        call_kwargs = mock_email_cls.call_args
        # 'to' positional or keyword arg should contain billing email
        to_list = call_kwargs[1].get('to') or call_kwargs[0][3]
        self.assertIn('billing@acme.example.com', to_list)

    @patch('apps.billing.services.payment_notification_service.render_to_string', return_value='body')
    @patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives')
    def test_falls_back_to_customer_email(self, mock_email_cls, mock_render):
        """When billing_email is blank, falls back to customer.email."""
        prefs, _ = CustomerRepairPreference.objects.get_or_create(
            customer=self.customer,
            defaults={'billing_email': ''},
        )
        prefs.billing_email = ''
        prefs.save()

        mock_email_instance = MagicMock()
        mock_email_cls.return_value = mock_email_instance

        svc = self._make_svc()
        result = svc.send_customer_receipt(self.payment)

        self.assertTrue(result)
        call_kwargs = mock_email_cls.call_args
        to_list = call_kwargs[1].get('to') or call_kwargs[0][3]
        self.assertIn('fleet@acme.example.com', to_list)

    def test_no_email_returns_false(self):
        """Customer has no email and no billing_email → returns False, no email sent."""
        self.customer.email = ''
        self.customer.save()
        prefs, _ = CustomerRepairPreference.objects.get_or_create(
            customer=self.customer,
            defaults={'billing_email': ''},
        )
        prefs.billing_email = ''
        prefs.save()

        svc = self._make_svc()
        with patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives') as mock_email:
            result = svc.send_customer_receipt(self.payment)

        self.assertFalse(result)
        mock_email.assert_not_called()

    @patch('apps.billing.services.payment_notification_service.render_to_string', side_effect=Exception('Template error'))
    def test_template_exception_returns_false(self, mock_render):
        """If render_to_string raises, send_customer_receipt returns False (no crash)."""
        svc = self._make_svc()
        result = svc.send_customer_receipt(self.payment)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# send_owner_notification
# ---------------------------------------------------------------------------

class SendOwnerNotificationTests(PaymentNotificationServiceTestCase):

    @patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives')
    def test_happy_path_returns_true(self, mock_email_cls):
        """Owner notification sent when BillingConfig.company_email is set → True."""
        mock_email_instance = MagicMock()
        mock_email_cls.return_value = mock_email_instance

        svc = self._make_svc()
        result = svc.send_owner_notification(self.payment)

        self.assertTrue(result)
        mock_email_instance.send.assert_called_once()

    def test_no_owner_email_returns_false(self):
        """No email anywhere (BillingConfig, tenant, owner) → returns False."""
        cfg = BillingConfig.objects.get(tenant=self.tenant)
        cfg.company_email = ''
        cfg.save()
        self.tenant.business_email = ''
        self.tenant.save(update_fields=['business_email'])
        if self.tenant.owner:
            self.tenant.owner.email = ''
            self.tenant.owner.save(update_fields=['email'])

        svc = self._make_svc()
        with patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives') as mock_email:
            result = svc.send_owner_notification(self.payment)

        self.assertFalse(result)
        mock_email.assert_not_called()

    @patch('core.email_utils.send_branded_email')
    def test_falls_back_to_tenant_business_email(self, mock_send):
        """Falls back to tenant.business_email when BillingConfig email is
        empty. (The old global DEFAULT_OWNER_EMAIL fallback was removed — it
        would have leaked every shop's payment activity to one address.)"""
        cfg = BillingConfig.objects.get(tenant=self.tenant)
        cfg.company_email = ''
        cfg.save()
        self.tenant.business_email = 'shop-inbox@example.com'
        self.tenant.save(update_fields=['business_email'])

        mock_send.return_value = 1

        svc = self._make_svc()
        result = svc.send_owner_notification(self.payment)

        self.assertTrue(result)
        mock_send.assert_called_once()
        self.assertIn(
            'shop-inbox@example.com',
            mock_send.call_args.kwargs.get('recipient_list', []),
        )

    @patch('apps.billing.services.payment_notification_service.EmailMultiAlternatives')
    def test_smtp_exception_returns_false(self, mock_email_cls):
        """SMTP failure in send_owner_notification → returns False, no crash."""
        mock_email_instance = MagicMock()
        mock_email_instance.send.side_effect = Exception('SMTP error')
        mock_email_cls.return_value = mock_email_instance

        svc = self._make_svc()
        result = svc.send_owner_notification(self.payment)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# notify_payment (main entry point)
# ---------------------------------------------------------------------------

class NotifyPaymentTests(PaymentNotificationServiceTestCase):

    def test_notify_payment_both_succeed(self):
        """notify_payment() calls both sub-methods and returns correct dict on success."""
        svc = self._make_svc()
        with patch.object(svc, 'send_customer_receipt', return_value=True) as mock_cust, \
             patch.object(svc, 'send_owner_notification', return_value=True) as mock_owner:
            result = svc.notify_payment(self.payment)

        mock_cust.assert_called_once_with(self.payment)
        mock_owner.assert_called_once_with(self.payment)
        self.assertEqual(result, {'customer_sent': True, 'owner_sent': True})

    def test_notify_payment_partial_failure(self):
        """If owner notification fails, result reflects that without masking customer success."""
        svc = self._make_svc()
        with patch.object(svc, 'send_customer_receipt', return_value=True), \
             patch.object(svc, 'send_owner_notification', return_value=False):
            result = svc.notify_payment(self.payment)

        self.assertEqual(result, {'customer_sent': True, 'owner_sent': False})

    def test_notify_payment_both_fail(self):
        """Both sub-methods fail → result is all False."""
        svc = self._make_svc()
        with patch.object(svc, 'send_customer_receipt', return_value=False), \
             patch.object(svc, 'send_owner_notification', return_value=False):
            result = svc.notify_payment(self.payment)

        self.assertEqual(result, {'customer_sent': False, 'owner_sent': False})

    def test_branding_is_cached_after_first_access(self):
        """branding property is computed once; second access returns same object (no double load)."""
        from apps.billing.services.payment_notification_service import PaymentNotificationService
        svc = PaymentNotificationService()

        mock_branding = {'company_name': 'Cached Shop'}
        with patch(
            'core.models.email_branding.EmailBrandingConfig.get_instance'
        ) as mock_get:
            mock_cfg = MagicMock()
            mock_cfg.to_template_context.return_value = mock_branding
            mock_get.return_value = mock_cfg

            b1 = svc.branding
            b2 = svc.branding

        # get_instance should only be called once (cached after first load)
        mock_get.assert_called_once()
        self.assertIs(b1, b2)
