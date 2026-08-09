"""
Tests for the Stripe reconciliation service and manual-payment guard.

The design promise under test: a manual (cash/check) payment can never be
left to chance against an in-flight online payment —
- a checkout session that already got paid is recorded as the real Stripe
  payment before any manual one;
- a still-open session is expired on Stripe so the customer can't pay
  after handing over cash;
- if Stripe can't confirm the state, manual recording is blocked;
- every recovery path (webhook, sweep, payment-complete landing) records
  through the same dedup-keyed function, so double-recording is impossible.
"""

from decimal import Decimal
from unittest.mock import patch

import stripe as stripe_module

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.billing.models import Invoice, Payment, StripeCheckoutAttempt


def _invalid_request(msg='No such session'):
    return stripe_module.error.InvalidRequestError(msg, param=None)


@override_settings(STRIPE_SECRET_KEY='sk_test_reconcile')
class StripeReconcileBase(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.owner = User.objects.create_user(
            username='reconowner', email='recon@test.com', password='x',
        )
        self.tenant = Tenant.objects.create(
            name='Reconcile Shop',
            slug='reconcile-shop',
            owner=self.owner,
            stripe_connect_account_id='acct_recon',
            subscription_status='trialing',
            plan='trial',
            trial_started_at=timezone.now(),
        )
        from core.models import Customer
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Recon Fleet', email='fleet@recon.test',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='INV-RECON-1',
            subtotal=Decimal('137.19'),
            total=Decimal('137.19'),
            status='SENT',
        )
        self.attempt = StripeCheckoutAttempt.objects.create(
            invoice=self.invoice,
            tenant=self.tenant,
            session_id='cs_recon_1',
            stripe_account_id='acct_recon',
        )

    def _paid_session(self, pi='pi_recon_1'):
        return {
            'id': 'cs_recon_1',
            'status': 'complete',
            'payment_status': 'paid',
            'amount_total': 13719,
            'payment_intent': pi,
        }

    def _open_session(self):
        return {
            'id': 'cs_recon_1',
            'status': 'open',
            'payment_status': 'unpaid',
            'amount_total': 13719,
            'payment_intent': None,
        }

    def _paid_pi(self, pi='pi_recon_1'):
        return {
            'id': pi,
            'amount_received': 13719,
            'application_fee_amount': None,
            'on_behalf_of': None,
        }


class GuardManualPaymentTests(StripeReconcileBase):
    def test_no_attempts_allows_manual(self):
        from apps.billing.services.stripe_reconcile import guard_manual_payment
        self.attempt.delete()
        allow, info = guard_manual_payment(self.invoice)
        self.assertTrue(allow)
        self.assertEqual(info['recorded'], 0)

    @patch('stripe.PaymentIntent.retrieve')
    @patch('stripe.checkout.Session.retrieve')
    def test_paid_session_recorded_before_manual(self, mock_retrieve, mock_pi):
        from apps.billing.services.stripe_reconcile import guard_manual_payment
        mock_retrieve.return_value = self._paid_session()
        mock_pi.return_value = self._paid_pi()

        allow, info = guard_manual_payment(self.invoice)

        self.assertTrue(allow)
        self.assertEqual(info['recorded'], 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(
            self.invoice.payments.filter(stripe_payment_id='pi_recon_1').count(), 1,
        )
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'COMPLETE')
        self.assertEqual(self.attempt.payment_intent_id, 'pi_recon_1')

    @patch('stripe.checkout.Session.expire')
    @patch('stripe.checkout.Session.retrieve')
    def test_open_session_expired_then_manual_allowed(self, mock_retrieve, mock_expire):
        from apps.billing.services.stripe_reconcile import guard_manual_payment
        mock_retrieve.return_value = self._open_session()

        allow, info = guard_manual_payment(self.invoice)

        self.assertTrue(allow)
        self.assertEqual(info['expired'], 1)
        mock_expire.assert_called_once_with('cs_recon_1', stripe_account='acct_recon')
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'EXPIRED')
        self.assertEqual(self.invoice.payments.count(), 0)

    @patch('stripe.checkout.Session.retrieve')
    def test_stripe_error_blocks_manual(self, mock_retrieve):
        from apps.billing.services.stripe_reconcile import guard_manual_payment
        mock_retrieve.side_effect = stripe_module.error.APIConnectionError('down')

        allow, info = guard_manual_payment(self.invoice)

        self.assertFalse(allow)
        self.assertIn('could not be verified', info['message'])
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'OPEN')  # still pending
        self.assertEqual(self.invoice.payments.count(), 0)

    @patch('stripe.PaymentIntent.retrieve')
    @patch('stripe.checkout.Session.expire')
    @patch('stripe.checkout.Session.retrieve')
    def test_expire_race_customer_paid_first(self, mock_retrieve, mock_expire, mock_pi):
        """Customer completes payment between our retrieve and expire —
        the payment must be recorded, not lost."""
        from apps.billing.services.stripe_reconcile import guard_manual_payment
        mock_retrieve.side_effect = [self._open_session(), self._paid_session()]
        mock_expire.side_effect = _invalid_request('Session is complete')
        mock_pi.return_value = self._paid_pi()

        allow, info = guard_manual_payment(self.invoice)

        self.assertTrue(allow)
        self.assertEqual(info['recorded'], 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

    @patch('stripe.PaymentIntent.retrieve')
    @patch('stripe.checkout.Session.retrieve')
    def test_reconcile_then_webhook_retry_no_double_record(self, mock_retrieve, mock_pi):
        """A webhook retry arriving after reconcile must dedup on the
        payment_intent id."""
        from apps.billing.services.stripe_reconcile import guard_manual_payment
        from apps.billing.services.stripe_service import StripeService

        mock_retrieve.return_value = self._paid_session()
        mock_pi.return_value = self._paid_pi()
        guard_manual_payment(self.invoice)

        svc = StripeService()
        result = svc._handle_payment_succeeded(
            {
                'id': 'pi_recon_1',
                'amount_received': 13719,
                'metadata': {'rs_invoice_id': str(self.invoice.id)},
            },
            event_account='acct_recon',
        )
        self.assertTrue(result.get('duplicate'))
        self.assertEqual(self.invoice.payments.count(), 1)


class InPortalNotificationTests(StripeReconcileBase):
    @patch('stripe.PaymentIntent.retrieve')
    @patch('stripe.checkout.Session.retrieve')
    def test_managers_get_bell_notification_on_online_payment(
            self, mock_retrieve, mock_pi):
        from apps.technician_portal.models import Technician, TechnicianNotification
        from apps.billing.services.stripe_reconcile import guard_manual_payment

        manager = Technician.objects.create(
            tenant=self.tenant, user=self.owner, is_manager=True, is_active=True,
        )
        mock_retrieve.return_value = self._paid_session()
        mock_pi.return_value = self._paid_pi()

        guard_manual_payment(self.invoice)

        notes = TechnicianNotification.objects.filter(technician=manager)
        self.assertEqual(notes.count(), 1)
        self.assertIn('INV-RECON-1', notes.first().message)
        self.assertIn('paid in full', notes.first().message)


class PaymentCompleteLandingTests(StripeReconcileBase):
    @patch('stripe.PaymentIntent.retrieve')
    @patch('stripe.checkout.Session.retrieve')
    def test_landing_records_payment_and_shows_shop(self, mock_retrieve, mock_pi):
        mock_retrieve.return_value = self._paid_session()
        mock_pi.return_value = self._paid_pi()

        response = self.client.get('/payment-complete', {'session': 'cs_recon_1'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Received')
        self.assertContains(response, 'Reconcile Shop')
        self.assertContains(response, 'INV-RECON-1')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

    @patch('stripe.checkout.Session.retrieve')
    def test_landing_open_session_shows_processing_not_received(self, mock_retrieve):
        mock_retrieve.return_value = self._open_session()

        response = self.client.get('/payment-complete', {'session': 'cs_recon_1'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Processing')
        self.assertNotContains(response, 'Payment Received!')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')

    def test_landing_without_session_renders_neutral_page(self):
        response = self.client.get('/payment-complete')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Thank You')


class ReconcileSweepTests(StripeReconcileBase):
    @patch('stripe.PaymentIntent.retrieve')
    @patch('stripe.checkout.Session.retrieve')
    def test_sweep_records_missed_payment(self, mock_retrieve, mock_pi):
        from apps.billing.services.stripe_reconcile import reconcile_open_attempts
        mock_retrieve.return_value = self._paid_session()
        mock_pi.return_value = self._paid_pi()

        summary = reconcile_open_attempts()

        self.assertEqual(summary['checked'], 1)
        self.assertEqual(summary['recorded'], 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

    @patch('stripe.checkout.Session.retrieve')
    def test_sweep_leaves_open_sessions_alone(self, mock_retrieve):
        """The sweep must NOT expire open sessions — the customer may still
        be typing their card number."""
        from apps.billing.services.stripe_reconcile import reconcile_open_attempts
        mock_retrieve.return_value = self._open_session()

        summary = reconcile_open_attempts()

        self.assertEqual(summary['open'], 1)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'OPEN')

    @patch('stripe.checkout.Session.retrieve')
    def test_sweep_dry_run_touches_nothing(self, mock_retrieve):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('reconcile_stripe_payments', '--dry-run', stdout=out)
        mock_retrieve.assert_not_called()
        self.assertIn('1 open session(s) would be checked', out.getvalue())

    @patch('stripe.checkout.Session.retrieve')
    def test_unknown_session_marked_expired(self, mock_retrieve):
        from apps.billing.services.stripe_reconcile import reconcile_open_attempts
        mock_retrieve.side_effect = _invalid_request()

        summary = reconcile_open_attempts()

        self.assertEqual(summary['expired'], 1)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.status, 'EXPIRED')


class CheckoutAttemptCreationTests(StripeReconcileBase):
    @patch('stripe.checkout.Session.create')
    def test_connected_checkout_records_attempt(self, mock_create):
        from apps.tenants.services.connect_service import ConnectService

        class _Session:
            id = 'cs_created_1'
            url = 'https://checkout.stripe.com/c/pay/cs_created_1'
        mock_create.return_value = _Session()

        self.tenant.stripe_onboarding_status = 'active'
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_payouts_enabled = True
        self.tenant.save()

        result = ConnectService().create_connected_checkout_session(self.invoice)

        self.assertTrue(result['success'])
        attempt = StripeCheckoutAttempt.objects.get(session_id='cs_created_1')
        self.assertEqual(attempt.invoice, self.invoice)
        self.assertEqual(attempt.stripe_account_id, 'acct_recon')
        self.assertEqual(attempt.status, 'OPEN')


class LateWebhookAfterManualPaymentTests(StripeReconcileBase):
    """The Aug 2026 recovery scenario: invoices were manually caught up
    while webhook retries were still queued at Stripe. A late retry must
    not double-credit the invoice and must NOT email the customer —
    shop-only alert."""

    def _manually_pay_in_full(self):
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal('137.19'),
            payment_date=timezone.now().date(),
            payment_method='CASH',
            notes='caught up by hand during webhook outage',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')

    def test_late_retry_not_recorded_and_customer_not_emailed(self):
        from django.core import mail
        from apps.billing.models import PlatformFeeRecord
        from apps.billing.services.stripe_service import StripeService
        from apps.technician_portal.models import Technician, TechnicianNotification

        manager = Technician.objects.create(
            tenant=self.tenant, user=self.owner, is_manager=True, is_active=True,
        )
        self._manually_pay_in_full()
        mail.outbox = []

        result = StripeService()._handle_payment_succeeded(
            {
                'id': 'pi_late_retry',
                'amount_received': 13719,
                'application_fee_amount': 686,
                'metadata': {'rs_invoice_id': str(self.invoice.id)},
            },
            event_account='acct_recon',
        )

        self.assertEqual(result.get('skipped'), 'already_paid')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.payments.count(), 1)  # only the manual one
        self.assertEqual(self.invoice.amount_paid, Decimal('137.19'))
        self.assertFalse(
            PlatformFeeRecord.objects.filter(payment_intent_id='pi_late_retry').exists()
        )

        # Shop is alerted in-portal...
        notes = TechnicianNotification.objects.filter(technician=manager)
        self.assertEqual(notes.count(), 1)
        self.assertIn('already fully paid', notes.first().message)

        # ...and by email — but the CUSTOMER is never emailed.
        all_recipients = [r for m in mail.outbox for r in m.to]
        self.assertNotIn('fleet@recon.test', all_recipients)
        self.assertIn('recon@test.com', all_recipients)

    def test_late_retry_idempotent_when_pi_already_recorded(self):
        """If the Stripe payment itself was recorded (with its pi id), a
        retry is a plain duplicate — no alert spam."""
        from django.core import mail
        from apps.billing.services.stripe_service import StripeService

        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal('137.19'),
            payment_date=timezone.now().date(),
            payment_method='STRIPE',
            stripe_payment_id='pi_known',
        )
        mail.outbox = []

        result = StripeService()._handle_payment_succeeded(
            {
                'id': 'pi_known',
                'amount_received': 13719,
                'metadata': {'rs_invoice_id': str(self.invoice.id)},
            },
            event_account='acct_recon',
        )

        self.assertTrue(result.get('duplicate'))
        self.assertEqual(self.invoice.payments.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
