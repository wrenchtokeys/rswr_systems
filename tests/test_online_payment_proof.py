"""
Proof of an online payment, for the shop (Oct 2026).

An invoice paid through Stripe used to show the shop one line: "Paid via
Stripe". These tests pin what the shop now gets beside that line — the
card, Stripe's receipt, Stripe's fee, the net, and where the money is —
and the rules that keep it honest and cheap:

* every number is Stripe's own, read from the shop's Connect account;
* a manual payment never has (or asks Stripe for) a detail row;
* the charge facts are fetched once and cached; a failure is stored and
  retried no sooner than an hour later;
* payouts stamp "deposited" via the payout.* webhooks, or via a bounded
  search from the invoice page when the webhook hasn't arrived;
* the invoice page never 500s because Stripe did not answer.
"""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import stripe
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import Invoice, Payment, StripePaymentDetail
from apps.billing.services import stripe_payment_details as svc
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer

ACCT = 'acct_proof_shop'


def _ts(day):
    return svc._date_to_ts(day)


def intent_payload(pi_id='pi_proof_1', ch_id='ch_proof_1', available_on=None,
                   app_fee_cents=0, expanded=True):
    """A PaymentIntent as `retrieve(expand=['latest_charge.balance_transaction'])`
    returns it on a connected account. 137.19 charged, 4.28 fee, 132.91 net."""
    available_on = available_on or (timezone.localdate() + timedelta(days=2))
    fee_details = [{'type': 'stripe_fee', 'amount': 428 - app_fee_cents}]
    if app_fee_cents:
        fee_details.append({'type': 'application_fee', 'amount': app_fee_cents})
    charge = {
        'id': ch_id,
        'currency': 'usd',
        'receipt_url': f'https://pay.stripe.com/receipts/{ch_id}/rcpt_abc',
        'payment_method_details': {
            'card': {'brand': 'visa', 'last4': '4242', 'wallet': None},
        },
        'balance_transaction': {
            'id': 'txn_proof_1',
            'amount': 13719,
            'fee': 428,
            'net': 13291,
            'currency': 'usd',
            'available_on': _ts(available_on),
            'fee_details': fee_details,
        },
    }
    return {
        'id': pi_id,
        'amount_received': 13719,
        'application_fee_amount': app_fee_cents or None,
        'latest_charge': charge if expanded else ch_id,
        'metadata': {},
    }


def payout_payload(po_id='po_proof_1', status='paid', arrival=None):
    arrival = arrival or timezone.localdate()
    return {'id': po_id, 'object': 'payout', 'status': status,
            'arrival_date': _ts(arrival), 'amount': 13291}


class ProofTestBase(TestCase):
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
                      'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Proof Glass', email='proof-owner@test.com',
            password='testpass123!', first_name='Proof', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.tenant.stripe_connect_account_id = ACCT
        self.tenant.stripe_connect_charges_enabled = True
        self.tenant.stripe_connect_payouts_enabled = True
        self.tenant.stripe_connect_onboarding_complete = True
        self.tenant.save()

        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Carpenter Construction',
            email='ap@carpenter.test',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-PROOF-1',
            subtotal=Decimal('137.19'), total=Decimal('137.19'), status='SENT',
        )

    def stripe_payment(self, pi_id='pi_proof_1', **kw):
        return Payment.objects.create(
            invoice=self.invoice, amount=Decimal('137.19'),
            payment_method='STRIPE', stripe_payment_id=pi_id,
            notes='Paid via Stripe', **kw,
        )

    def login_owner(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def open_invoice(self):
        return self.client.get(reverse('owner_invoice_detail', args=[self.invoice.id]))


@override_settings(STRIPE_SECRET_KEY='sk_test_proof')
class SyncFromStripeTests(ProofTestBase):

    @patch('stripe.PaymentIntent.retrieve')
    def test_manual_payment_never_gets_a_detail_or_a_stripe_call(self, retrieve):
        payment = Payment.objects.create(
            invoice=self.invoice, amount=Decimal('50'), payment_method='CHECK',
            reference_number='1042',
        )
        self.assertIsNone(svc.sync_from_stripe(payment))
        self.assertFalse(StripePaymentDetail.objects.exists())
        retrieve.assert_not_called()

    @patch('stripe.PaymentIntent.retrieve')
    def test_sync_reads_card_receipt_fee_net_and_availability(self, retrieve):
        available = timezone.localdate() + timedelta(days=2)
        retrieve.return_value = intent_payload(available_on=available)
        payment = self.stripe_payment()

        detail = svc.sync_from_stripe(payment)

        retrieve.assert_called_once()
        kwargs = retrieve.call_args.kwargs
        # Read from the SHOP's account, with the charge + txn in one call.
        self.assertEqual(kwargs['stripe_account'], ACCT)
        self.assertIn('latest_charge.balance_transaction', kwargs['expand'])

        self.assertEqual(detail.charge_id, 'ch_proof_1')
        self.assertEqual(detail.card_label, 'Visa ···· 4242')
        self.assertEqual(detail.receipt_url,
                         'https://pay.stripe.com/receipts/ch_proof_1/rcpt_abc')
        self.assertEqual(detail.gross_amount, Decimal('137.19'))
        self.assertEqual(detail.stripe_fee, Decimal('4.28'))
        self.assertEqual(detail.net_amount, Decimal('132.91'))
        self.assertEqual(detail.funds_available_on, available)
        self.assertEqual(detail.deposit_state, 'pending')
        self.assertEqual(detail.sync_error, '')
        self.assertIsNotNone(detail.synced_at)
        # The charge id is written back onto the Payment row, which had the
        # column since day one and nothing ever filled it.
        payment.refresh_from_db()
        self.assertEqual(payment.stripe_charge_id, 'ch_proof_1')

    @patch('stripe.PaymentIntent.retrieve')
    def test_platform_fee_comes_from_the_balance_transaction(self, retrieve):
        retrieve.return_value = intent_payload(app_fee_cents=137)
        detail = svc.sync_from_stripe(self.stripe_payment())
        self.assertEqual(detail.platform_fee, Decimal('1.37'))
        # Stripe's fee figure already includes the application fee; the
        # net is what Stripe says, not gross - fee - platform_fee again.
        self.assertEqual(detail.net_amount, Decimal('132.91'))

    @patch('stripe.PaymentIntent.retrieve')
    def test_wallet_is_named(self, retrieve):
        payload = intent_payload()
        payload['latest_charge']['payment_method_details']['card']['wallet'] = {'type': 'apple_pay'}
        retrieve.return_value = payload
        detail = svc.sync_from_stripe(self.stripe_payment())
        self.assertEqual(detail.wallet, 'apple_pay')
        self.assertEqual(detail.card_label, 'Apple Pay (Visa ···· 4242)')

    @patch('stripe.Charge.retrieve')
    @patch('stripe.PaymentIntent.retrieve')
    def test_unexpanded_charge_is_fetched_separately(self, retrieve, charge_retrieve):
        payload = intent_payload(expanded=False)
        retrieve.return_value = payload
        charge_retrieve.return_value = intent_payload()['latest_charge']
        detail = svc.sync_from_stripe(self.stripe_payment())
        charge_retrieve.assert_called_once()
        self.assertEqual(charge_retrieve.call_args.kwargs['stripe_account'], ACCT)
        self.assertEqual(detail.card_last4, '4242')

    @patch('stripe.PaymentIntent.retrieve')
    def test_once_known_the_charge_is_not_fetched_again(self, retrieve):
        retrieve.return_value = intent_payload()
        payment = self.stripe_payment()
        svc.sync_from_stripe(payment)
        svc.sync_from_stripe(payment)
        svc.sync_from_stripe(payment)
        self.assertEqual(retrieve.call_count, 1)

    @patch('stripe.PaymentIntent.retrieve')
    def test_failure_is_stored_and_retried_no_sooner_than_an_hour(self, retrieve):
        retrieve.side_effect = stripe.error.StripeError('Stripe is down')
        payment = self.stripe_payment()

        detail = svc.sync_from_stripe(payment)
        self.assertFalse(detail.has_charge)
        self.assertIn('Stripe is down', detail.sync_error)

        svc.sync_from_stripe(payment)
        self.assertEqual(retrieve.call_count, 1, 'retried within the hour')

        detail.synced_at = timezone.now() - timedelta(hours=2)
        detail.save(update_fields=['synced_at'])
        retrieve.side_effect = None
        retrieve.return_value = intent_payload()
        detail = svc.sync_from_stripe(payment)
        self.assertEqual(retrieve.call_count, 2)
        self.assertTrue(detail.has_charge)
        self.assertEqual(detail.sync_error, '')

    @patch('stripe.PaymentIntent.retrieve')
    def test_shop_without_connect_account_gets_nothing(self, retrieve):
        self.tenant.stripe_connect_account_id = ''
        self.tenant.save()
        self.assertIsNone(svc.sync_from_stripe(self.stripe_payment()))
        retrieve.assert_not_called()

    @override_settings(STRIPE_SECRET_KEY='')
    @patch('stripe.PaymentIntent.retrieve')
    def test_no_stripe_key_means_a_row_but_no_call(self, retrieve):
        detail = svc.sync_from_stripe(self.stripe_payment())
        self.assertIsNotNone(detail)
        self.assertFalse(detail.has_charge)
        retrieve.assert_not_called()


@override_settings(STRIPE_SECRET_KEY='sk_test_proof')
class PayoutTests(ProofTestBase):

    def synced_detail(self, pi_id='pi_proof_1', ch_id='ch_proof_1', **fields):
        payment = self.stripe_payment(pi_id=pi_id)
        detail = StripePaymentDetail.objects.create(
            payment=payment, payment_intent_id=pi_id, charge_id=ch_id,
            stripe_account_id=ACCT, card_brand='visa', card_last4='4242',
            gross_amount=Decimal('137.19'), stripe_fee=Decimal('4.28'),
            net_amount=Decimal('132.91'),
            funds_available_on=timezone.localdate() - timedelta(days=3),
            synced_at=timezone.now() - timedelta(days=3),
            **fields,
        )
        return detail

    @patch('stripe.BalanceTransaction.list')
    def test_apply_payout_stamps_every_payment_it_carried(self, bt_list):
        mine = self.synced_detail()
        other = self.synced_detail(pi_id='pi_proof_2', ch_id='ch_proof_2')
        untouched = self.synced_detail(pi_id='pi_proof_3', ch_id='ch_proof_3')
        bt_list.return_value = {
            'data': [
                {'id': 'txn_a', 'source': 'ch_proof_1'},
                {'id': 'txn_b', 'source': 'ch_proof_2'},
                {'id': 'txn_c', 'source': 'ch_other_shop'},
            ],
            'has_more': False,
        }
        arrival = timezone.localdate() - timedelta(days=1)

        result = svc.apply_payout(payout_payload(arrival=arrival), ACCT)

        self.assertEqual(result['matched'], 2)
        self.assertEqual(bt_list.call_args.kwargs['payout'], 'po_proof_1')
        self.assertEqual(bt_list.call_args.kwargs['stripe_account'], ACCT)
        for d in (mine, other):
            d.refresh_from_db()
            self.assertEqual(d.payout_id, 'po_proof_1')
            self.assertEqual(d.payout_status, 'paid')
            self.assertEqual(d.payout_arrival_on, arrival)
            self.assertEqual(d.deposit_state, 'deposited')
        untouched.refresh_from_db()
        self.assertEqual(untouched.payout_id, '')
        self.assertEqual(untouched.deposit_state, 'available')

    @patch('stripe.BalanceTransaction.list')
    def test_payout_pages_are_followed(self, bt_list):
        detail = self.synced_detail()
        bt_list.side_effect = [
            {'data': [{'id': 'txn_1', 'source': 'ch_x'}], 'has_more': True},
            {'data': [{'id': 'txn_2', 'source': 'ch_proof_1'}], 'has_more': False},
        ]
        svc.apply_payout(payout_payload(), ACCT)
        self.assertEqual(bt_list.call_count, 2)
        self.assertEqual(bt_list.call_args_list[1].kwargs['starting_after'], 'txn_1')
        detail.refresh_from_db()
        self.assertEqual(detail.payout_id, 'po_proof_1')

    @patch('stripe.BalanceTransaction.list')
    def test_a_failed_payout_overrides_paid(self, bt_list):
        detail = self.synced_detail(payout_id='po_proof_1', payout_status='paid')
        bt_list.return_value = {'data': [], 'has_more': False}
        svc.apply_payout(payout_payload(status='failed'), ACCT)
        detail.refresh_from_db()
        self.assertEqual(detail.payout_status, 'failed')
        self.assertEqual(detail.deposit_state, 'failed')

    @patch('stripe.BalanceTransaction.list')
    def test_another_shops_payout_cannot_stamp_this_shops_payment(self, bt_list):
        detail = self.synced_detail()
        bt_list.return_value = {
            'data': [{'id': 'txn_a', 'source': 'ch_proof_1'}], 'has_more': False,
        }
        svc.apply_payout(payout_payload(), 'acct_someone_else')
        detail.refresh_from_db()
        self.assertEqual(detail.payout_id, '')

    @patch('stripe.BalanceTransaction.list')
    @patch('stripe.Payout.list')
    def test_find_payout_walks_oldest_first_and_stops_on_match(self, po_list, bt_list):
        detail = self.synced_detail()
        po_list.return_value = {'data': [
            payout_payload(po_id='po_newest'),
            payout_payload(po_id='po_middle'),
            payout_payload(po_id='po_oldest'),
        ]}
        bt_list.side_effect = [
            {'data': [{'id': 't1', 'source': 'ch_unrelated'}], 'has_more': False},
            {'data': [{'id': 't2', 'source': 'ch_proof_1'}], 'has_more': False},
        ]
        self.assertTrue(svc.find_payout(detail))
        self.assertEqual(
            [c.kwargs['payout'] for c in bt_list.call_args_list],
            ['po_oldest', 'po_middle'],
        )
        window = po_list.call_args.kwargs['arrival_date']
        self.assertLessEqual(window['gte'], _ts(detail.funds_available_on))
        self.assertEqual(po_list.call_args.kwargs['stripe_account'], ACCT)
        detail.refresh_from_db()
        self.assertEqual(detail.payout_id, 'po_middle')

    @patch('stripe.Payout.list')
    def test_find_payout_failure_is_quiet_and_stamps_synced_at(self, po_list):
        detail = self.synced_detail()
        po_list.side_effect = stripe.error.StripeError('nope')
        self.assertFalse(svc.find_payout(detail))
        detail.refresh_from_db()
        self.assertGreater(detail.synced_at, timezone.now() - timedelta(minutes=1))


@override_settings(STRIPE_SECRET_KEY='sk_test_proof')
class WebhookProofTests(ProofTestBase):

    def billing_svc(self):
        from apps.billing.services.stripe_service import StripeService
        s = StripeService()
        s.enabled = True
        s.webhook_secret = 'whsec_test'
        return s

    def deliver(self, event_dict):
        with patch('stripe.Webhook.construct_event') as construct:
            construct.return_value = event_dict
            return self.billing_svc().handle_webhook(
                json.dumps(event_dict).encode(), 't=1,v1=sig',
            )

    @patch('stripe.PaymentIntent.retrieve')
    def test_recording_an_online_payment_captures_the_proof(self, retrieve):
        retrieve.return_value = intent_payload(pi_id='pi_hook_1')
        result = self.deliver({
            'id': 'evt_proof_pi_1',
            'type': 'payment_intent.succeeded',
            'account': ACCT,
            'data': {'object': {
                'id': 'pi_hook_1',
                'amount_received': 13719,
                'metadata': {'rs_invoice_id': str(self.invoice.id)},
            }},
        })
        self.assertTrue(result['success'])
        payment = self.invoice.payments.get(stripe_payment_id='pi_hook_1')
        detail = payment.stripe_detail
        self.assertEqual(detail.card_last4, '4242')
        self.assertEqual(detail.net_amount, Decimal('132.91'))
        self.assertEqual(payment.stripe_charge_id, 'ch_proof_1')

    @patch('stripe.PaymentIntent.retrieve')
    def test_stripe_outage_during_sync_does_not_lose_the_payment(self, retrieve):
        retrieve.side_effect = stripe.error.StripeError('down')
        result = self.deliver({
            'id': 'evt_proof_pi_2',
            'type': 'payment_intent.succeeded',
            'account': ACCT,
            'data': {'object': {
                'id': 'pi_hook_2',
                'amount_received': 13719,
                'metadata': {'rs_invoice_id': str(self.invoice.id)},
            }},
        })
        self.assertTrue(result['success'])
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        detail = self.invoice.payments.get(stripe_payment_id='pi_hook_2').stripe_detail
        self.assertFalse(detail.has_charge)
        self.assertIn('down', detail.sync_error)

    @patch('stripe.BalanceTransaction.list')
    def test_payout_paid_on_the_shops_account_stamps_deposited(self, bt_list):
        payment = self.stripe_payment()
        StripePaymentDetail.objects.create(
            payment=payment, payment_intent_id='pi_proof_1', charge_id='ch_proof_1',
            stripe_account_id=ACCT, net_amount=Decimal('132.91'),
        )
        bt_list.return_value = {
            'data': [{'id': 'txn_a', 'source': 'ch_proof_1'}], 'has_more': False,
        }
        result = self.deliver({
            'id': 'evt_proof_po_1',
            'type': 'payout.paid',
            'account': ACCT,
            'data': {'object': payout_payload()},
        })
        self.assertTrue(result['success'])
        self.assertTrue(result['handled'])
        self.assertEqual(result['matched'], 1)
        payment.stripe_detail.refresh_from_db()
        self.assertEqual(payment.stripe_detail.deposit_state, 'deposited')

    @patch('stripe.BalanceTransaction.list')
    def test_platform_payout_is_ignored(self, bt_list):
        result = self.deliver({
            'id': 'evt_proof_po_platform',
            'type': 'payout.paid',
            'data': {'object': payout_payload(po_id='po_platform')},
        })
        self.assertTrue(result['success'])
        self.assertFalse(result['handled'])
        bt_list.assert_not_called()

    @patch('stripe.BalanceTransaction.list')
    def test_payout_lookup_failure_asks_stripe_to_redeliver(self, bt_list):
        bt_list.side_effect = stripe.error.StripeError('rate limited')
        result = self.deliver({
            'id': 'evt_proof_po_retry',
            'type': 'payout.paid',
            'account': ACCT,
            'data': {'object': payout_payload()},
        })
        self.assertFalse(result['success'])
        self.assertTrue(result.get('retryable'))


@override_settings(STRIPE_SECRET_KEY='sk_test_proof')
class InvoicePageProofTests(ProofTestBase):

    def setUp(self):
        super().setUp()
        self.login_owner()

    @patch('stripe.Payout.list', return_value={'data': []})
    @patch('stripe.PaymentIntent.retrieve')
    def test_old_online_payment_is_backfilled_when_the_page_opens(self, retrieve, po_list):
        available = timezone.localdate() + timedelta(days=2)
        retrieve.return_value = intent_payload(available_on=available)
        payment = self.stripe_payment()
        self.assertFalse(StripePaymentDetail.objects.exists())

        r = self.open_invoice()

        self.assertEqual(r.status_code, 200)
        retrieve.assert_called_once()
        html = r.content.decode()
        self.assertIn('data-stripe-proof', html)
        self.assertIn('Visa ···· 4242', html)
        self.assertIn('pi_proof_1', html)
        self.assertIn('https://pay.stripe.com/receipts/ch_proof_1/rcpt_abc', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('To your bank', html)
        self.assertIn('$132.91', html)
        self.assertIn('Stripe fee', html)
        self.assertIn('$4.28', html)
        self.assertIn('Available for payout', html)
        self.assertIn(available.strftime('%b %-d, %Y'), html)
        self.assertIn(reverse('connect_dashboard'), html)
        # Funds are not available yet, so no payout search was spent.
        po_list.assert_not_called()
        self.assertTrue(payment.stripe_detail.has_charge)

    @patch('stripe.BalanceTransaction.list')
    @patch('stripe.Payout.list')
    @patch('stripe.PaymentIntent.retrieve')
    def test_page_finds_the_deposit_when_funds_have_cleared(self, retrieve, po_list, bt_list):
        retrieve.return_value = intent_payload(
            available_on=timezone.localdate() - timedelta(days=3),
        )
        arrival = timezone.localdate() - timedelta(days=2)
        po_list.return_value = {'data': [payout_payload(arrival=arrival)]}
        bt_list.return_value = {
            'data': [{'id': 'txn_a', 'source': 'ch_proof_1'}], 'has_more': False,
        }
        self.stripe_payment()

        html = self.open_invoice().content.decode()

        self.assertIn('Deposited to your bank', html)
        self.assertIn(arrival.strftime('%b %-d, %Y'), html)
        self.assertIn('po_proof_1', html)

    @patch('stripe.Payout.list')
    @patch('stripe.PaymentIntent.retrieve')
    def test_a_deposited_payment_costs_no_stripe_calls(self, retrieve, po_list):
        payment = self.stripe_payment()
        StripePaymentDetail.objects.create(
            payment=payment, payment_intent_id='pi_proof_1', charge_id='ch_proof_1',
            stripe_account_id=ACCT, card_brand='mastercard', card_last4='4444',
            gross_amount=Decimal('137.19'), stripe_fee=Decimal('4.28'),
            net_amount=Decimal('132.91'),
            funds_available_on=timezone.localdate() - timedelta(days=3),
            payout_id='po_done', payout_status='paid',
            payout_arrival_on=timezone.localdate() - timedelta(days=2),
            synced_at=timezone.now() - timedelta(days=2),
        )
        html = self.open_invoice().content.decode()
        self.assertIn('Mastercard ···· 4444', html)
        self.assertIn('Deposited to your bank', html)
        retrieve.assert_not_called()
        po_list.assert_not_called()

    @patch('stripe.Payout.list')
    @patch('stripe.PaymentIntent.retrieve')
    def test_payout_search_is_throttled(self, retrieve, po_list):
        payment = self.stripe_payment()
        StripePaymentDetail.objects.create(
            payment=payment, payment_intent_id='pi_proof_1', charge_id='ch_proof_1',
            stripe_account_id=ACCT, net_amount=Decimal('132.91'),
            funds_available_on=timezone.localdate() - timedelta(days=1),
            synced_at=timezone.now() - timedelta(hours=1),
        )
        html = self.open_invoice().content.decode()
        self.assertIn('In your Stripe balance since', html)
        po_list.assert_not_called()
        retrieve.assert_not_called()

    @patch('stripe.PaymentIntent.retrieve')
    def test_page_survives_stripe_being_down(self, retrieve):
        retrieve.side_effect = stripe.error.StripeError('down')
        self.stripe_payment()
        r = self.open_invoice()
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("haven't come back from Stripe yet", html)
        self.assertNotIn('To your bank', html)
        self.assertNotIn('down', StripePaymentDetail.objects.get().card_label)

    @patch('stripe.PaymentIntent.retrieve')
    def test_manual_payment_shows_no_proof_block(self, retrieve):
        Payment.objects.create(
            invoice=self.invoice, amount=Decimal('137.19'), payment_method='CHECK',
            reference_number='1042', recorded_by=self.user,
        )
        html = self.open_invoice().content.decode()
        self.assertNotIn('data-stripe-proof', html)
        retrieve.assert_not_called()

    def test_another_shop_cannot_see_the_proof(self):
        other = create_tenant_with_owner(
            business_name='Other Glass', email='other-owner@test.com',
            password='testpass123!', first_name='Other', last_name='Owner',
        )
        self.client.force_login(other['user'])
        session = self.client.session
        session['tenant_id'] = other['tenant'].id
        session.save()
        self.assertEqual(self.open_invoice().status_code, 404)


class OwnerEmailTests(ProofTestBase):

    @patch('core.email_utils.send_branded_email')
    def test_owner_email_names_the_card_and_the_net_when_known(self, send):
        payment = self.stripe_payment()
        StripePaymentDetail.objects.create(
            payment=payment, payment_intent_id='pi_proof_1', charge_id='ch_proof_1',
            stripe_account_id=ACCT, card_brand='visa', card_last4='4242',
            net_amount=Decimal('132.91'),
        )
        from apps.billing.services.payment_notification_service import PaymentNotificationService
        self.assertTrue(PaymentNotificationService().send_owner_notification(payment))
        rows = send.call_args.kwargs['detail_rows']
        labels = {row[0]: row[1] for row in rows}
        self.assertEqual(labels['Card'], 'Visa ···· 4242')
        self.assertEqual(labels['After Stripe fees'], '$132.91')

    @patch('core.email_utils.send_branded_email')
    def test_owner_email_says_nothing_it_does_not_know(self, send):
        payment = self.stripe_payment()
        from apps.billing.services.payment_notification_service import PaymentNotificationService
        PaymentNotificationService().send_owner_notification(payment)
        labels = [row[0] for row in send.call_args.kwargs['detail_rows']]
        self.assertNotIn('Card', labels)
        self.assertNotIn('After Stripe fees', labels)
