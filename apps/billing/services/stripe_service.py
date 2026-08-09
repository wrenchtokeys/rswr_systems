"""
Stripe Integration Service - Payment processing via Stripe.

ARCHITECTURE:
  Our Invoice (DB) = Source of truth for ALL billing
  Stripe = Payment channel only (not a second invoicing system)

We use Stripe Payment Links / Checkout Sessions for online payment.
We do NOT create Stripe Invoices (which would duplicate our data).

Flow:
  1. Invoice created in our DB
  2. Customer wants to pay online → generate Stripe Payment Link
  3. Customer pays → Stripe webhook fires → we record the Payment
  4. Or customer pays by check/cash/wire → manually record Payment

Author: Amelia (Clawdbot AI)
"""

import json
import logging
from decimal import Decimal
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    logger.warning("Stripe SDK not installed. Run: pip install stripe")


class StripeService:
    """
    Handles Stripe payment processing for invoices.
    
    Stripe is a PAYMENT CHANNEL, not an invoicing system.
    Our DB (Invoice model) is the single source of truth.
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
        self.webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
        self.connect_webhook_secret = getattr(settings, 'STRIPE_CONNECT_WEBHOOK_SECRET', None)
        
        if STRIPE_AVAILABLE and self.api_key:
            stripe.api_key = self.api_key
            self.enabled = True
        else:
            self.enabled = False
    
    def is_enabled(self):
        """Check if Stripe is properly configured."""
        return self.enabled
    
    # =========================================================================
    # CUSTOMER MANAGEMENT
    # =========================================================================
    
    def get_or_create_customer(self, customer):
        """
        Get or create a Stripe Customer. Persists ID on our Customer model.
        """
        if not self.enabled:
            raise RuntimeError("Stripe not configured")
        
        # Use persisted ID if available
        if customer.stripe_customer_id:
            try:
                stripe.Customer.retrieve(customer.stripe_customer_id)
                return customer.stripe_customer_id
            except stripe.error.InvalidRequestError:
                customer.stripe_customer_id = ''
                customer.save(update_fields=['stripe_customer_id'])
        
        # Search by email
        if customer.email:
            existing = stripe.Customer.list(email=customer.email, limit=1)
            if existing.data:
                customer.stripe_customer_id = existing.data[0].id
                customer.save(update_fields=['stripe_customer_id'])
                return customer.stripe_customer_id
        
        # Create new
        stripe_customer = stripe.Customer.create(
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            metadata={'rs_systems_customer_id': str(customer.id)},
        )
        
        customer.stripe_customer_id = stripe_customer.id
        customer.save(update_fields=['stripe_customer_id'])
        logger.info(f"Created Stripe customer {stripe_customer.id} for {customer.name}")
        return stripe_customer.id
    
    # =========================================================================
    # PAYMENT LINKS (PRIMARY PAYMENT METHOD)
    # =========================================================================
    
    def create_payment_link(self, invoice):
        """
        Create a one-time Stripe Payment Link for an invoice.
        
        This is the primary way customers pay online.
        No duplicate invoice is created in Stripe — just a pay button.
        
        Returns:
            dict: {success, payment_link, amount_due}
        """
        if not self.enabled:
            return {'success': False, 'error': 'Stripe not configured'}
        
        if invoice.amount_due <= 0:
            return {'success': False, 'error': 'Invoice already paid'}
        
        try:
            # Build line item description
            item_count = invoice.line_items.count()
            description = (
                f"Invoice {invoice.invoice_number} - "
                f"{invoice.customer.name} - "
                f"{item_count} repair{'s' if item_count != 1 else ''}"
            )
            
            # Create a price for the exact amount due
            price = stripe.Price.create(
                currency='usd',
                unit_amount=int(invoice.amount_due * 100),  # Cents
                product_data={
                    'name': description,
                    'metadata': {
                        'invoice_id': str(invoice.id),
                        'invoice_number': invoice.invoice_number,
                        'customer_id': str(invoice.customer.id),
                    },
                },
            )
            
            # Create payment link
            payment_link = stripe.PaymentLink.create(
                line_items=[{'price': price.id, 'quantity': 1}],
                metadata={
                    'rs_invoice_id': str(invoice.id),
                    'rs_invoice_number': invoice.invoice_number,
                },
                payment_intent_data={
                    'metadata': {
                        'rs_invoice_id': str(invoice.id),
                        'rs_invoice_number': invoice.invoice_number,
                    },
                },
                after_completion={
                    'type': 'redirect',
                    'redirect': {
                        'url': getattr(settings, 'PAYMENT_SUCCESS_URL',
                                       'https://rssystems.io/payment-complete')
                               + f'?invoice={invoice.invoice_number}'
                    },
                },
            )
            
            # Store the payment link on the invoice
            invoice.stripe_hosted_url = payment_link.url
            invoice.save(update_fields=['stripe_hosted_url'])
            
            logger.info(f"Payment link created for {invoice.invoice_number}: {payment_link.url}")
            
            return {
                'success': True,
                'payment_link': payment_link.url,
                'amount_due': float(invoice.amount_due),
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {e}")
            return {'success': False, 'error': str(e)}
    
    def create_checkout_session(self, invoice, success_url=None, cancel_url=None):
        """
        Create a Stripe Checkout Session for an invoice.
        Alternative to Payment Links — gives more control over the flow.
        
        Returns:
            dict: {success, checkout_url, session_id}
        """
        if not self.enabled:
            return {'success': False, 'error': 'Stripe not configured'}
        
        if invoice.amount_due <= 0:
            return {'success': False, 'error': 'Invoice already paid'}
        
        try:
            stripe_customer_id = self.get_or_create_customer(invoice.customer)
            
            base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
            
            session = stripe.checkout.Session.create(
                customer=stripe_customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': int(invoice.amount_due * 100),
                        'product_data': {
                            'name': f'Invoice {invoice.invoice_number}',
                            'description': (
                                f'{invoice.line_items.count()} service(s) '
                                f'for {invoice.customer.name}'
                            ),
                        },
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url or f'{base_url}/payment-complete?session={{CHECKOUT_SESSION_ID}}',
                cancel_url=cancel_url or f'{base_url}/payment-cancelled',
                metadata={
                    'rs_invoice_id': str(invoice.id),
                    'rs_invoice_number': invoice.invoice_number,
                },
            )
            
            logger.info(f"Checkout session created for {invoice.invoice_number}: {session.id}")
            
            return {
                'success': True,
                'checkout_url': session.url,
                'session_id': session.id,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {e}")
            return {'success': False, 'error': str(e)}
    
    # =========================================================================
    # WEBHOOK HANDLING
    # =========================================================================
    
    def handle_webhook(self, payload, sig_header):
        """
        Process Stripe webhook events.
        
        Primary events we handle:
        - checkout.session.completed → customer paid via checkout
        - payment_intent.succeeded → payment completed
        """
        if not self.enabled:
            return {'success': False, 'error': 'Stripe not configured'}
        
        if not self.webhook_secret:
            return {'success': False, 'error': 'Webhook secret not configured'}
        
        # Try platform webhook secret first, then Connect webhook secret.
        # Connect events arrive on the same URL but are signed with the
        # Connect endpoint's secret.
        event = None
        secrets_to_try = [self.webhook_secret]
        if self.connect_webhook_secret:
            secrets_to_try.append(self.connect_webhook_secret)

        for secret in secrets_to_try:
            try:
                event = stripe.Webhook.construct_event(payload, sig_header, secret)
                break
            except stripe.error.SignatureVerificationError:
                continue
            except ValueError:
                return {'success': False, 'error': 'Invalid payload'}

        if event is None:
            return {'success': False, 'error': 'Invalid signature'}

        # stripe-python v15 removed dict inheritance from StripeObject, so
        # event.get(...) / data.get(...) raise AttributeError on real events.
        # The signature is already verified above — re-parse the raw payload
        # so every handler works on plain dicts regardless of SDK version.
        if not isinstance(event, dict):
            event = json.loads(payload)

        event_type = event['type']
        data = event['data']['object']
        # Present only on events that originate from a connected account —
        # used to verify the paying account matches the invoice's tenant.
        event_account = event.get('account')

        # Subscription checkouts must reach the subscription handler — the
        # invoice handler would drop them (no rs_invoice_id metadata) and the
        # paying shop would never get its plan activated.
        if event_type == 'checkout.session.completed' and data.get('mode') == 'subscription':
            from apps.tenants.webhooks import handle_subscription_event
            return handle_subscription_event(event_type, data)

        # Billing payment handlers (invoice checkout + payment intents)
        if event_type == 'checkout.session.completed':
            return self._handle_checkout_completed(data, event_account=event_account)
        if event_type == 'payment_intent.succeeded':
            return self._handle_payment_succeeded(data, event_account=event_account)

        # SaaS subscription handlers (delegated to tenants.webhooks)
        # NOTE: These are also handled by the dedicated subscription webhook
        # at /ap/tenants/webhooks/stripe/ with its own signing secret.
        # We keep the delegation here as a fallback for existing single-endpoint setups.
        from apps.tenants.webhooks import handle_subscription_event
        sub_result = handle_subscription_event(event_type, data)
        if sub_result.get('handled'):
            return sub_result

        # Stripe Connect account updates
        if event_type == 'account.updated':
            from apps.tenants.services.connect_service import handle_account_updated
            return handle_account_updated(data)

        logger.debug(f"Unhandled webhook: {event_type}")
        return {'success': True, 'handled': False, 'event_type': event_type}
    
    def _handle_checkout_completed(self, session, event_account=None):
        """Customer completed a Checkout Session — record the payment.

        IMPORTANT: Stripe sends checkout.session.completed even when
        payment_status='unpaid' (async payment methods like ACH/bank
        transfer). In that case the money hasn't arrived yet and
        payment_intent is None.

        We must only record the payment when payment_status='paid'.
        For 'unpaid' sessions the subsequent payment_intent.succeeded
        event (fired when the money clears, possibly days later) is
        the correct signal — and _handle_payment_succeeded will catch it.

        Skipping unpaid sessions also prevents a double-recording bug:
        if we naively recorded now with stripe_payment_id='' (None
        coerced to empty string), the dedup guard in _record_stripe_payment
        would not match the real pi_xxx id that arrives later, and the
        invoice would be credited twice.
        """
        metadata = session.get('metadata', {})
        invoice_id = metadata.get('rs_invoice_id')

        if not invoice_id:
            logger.debug("No rs_invoice_id in checkout metadata")
            return {'success': True, 'handled': False}

        payment_status = session.get('payment_status', 'unpaid')
        if payment_status != 'paid':
            logger.info(
                f"checkout.session.completed with payment_status={payment_status!r} "
                f"for invoice {invoice_id} — deferring to payment_intent.succeeded"
            )
            return {'success': True, 'handled': False, 'deferred': True, 'reason': 'unpaid'}

        amount = Decimal(str(session.get('amount_total', 0))) / 100
        payment_intent_id = session.get('payment_intent') or ''

        return self._record_stripe_payment(
            invoice_id=invoice_id,
            amount=amount,
            stripe_payment_id=payment_intent_id,
            notes=f"Paid via Stripe Checkout ({session['id']})",
            event_account=event_account,
        )

    def _handle_payment_succeeded(self, payment_intent, event_account=None):
        """Payment intent succeeded — could be from Payment Link or Checkout."""
        metadata = payment_intent.get('metadata', {})
        invoice_id = metadata.get('rs_invoice_id')

        if not invoice_id:
            return {'success': True, 'handled': False}

        amount = Decimal(str(payment_intent.get('amount_received', 0))) / 100
        payment_intent_id = payment_intent['id']

        result = self._record_stripe_payment(
            invoice_id=invoice_id,
            amount=amount,
            stripe_payment_id=payment_intent_id,
            notes='Paid via Stripe',
            event_account=event_account,
        )

        # A refused (wrong-account) charge must not create a fee record either.
        if result.get('flagged') == 'account_mismatch':
            return result

        # A skipped payment (invoice already fully paid — duplicate money)
        # must not create a fee record: the charge should be reviewed and
        # refunded, not booked.
        if result.get('skipped') == 'already_paid':
            return result

        # Record platform fee if this was a direct charge with an application fee
        application_fee_amount = payment_intent.get('application_fee_amount')
        if application_fee_amount and application_fee_amount > 0:
            try:
                from apps.billing.models import Invoice, PlatformFeeRecord
                invoice = Invoice.objects.get(id=invoice_id)
                if not PlatformFeeRecord.objects.filter(payment_intent_id=payment_intent_id).exists():
                    fee_amount = Decimal(str(application_fee_amount)) / 100
                    # Derive fee percent directly from the actual amounts.
                    # application_fee_amount is in cents; amount is in dollars.
                    # fee_percent = (fee_cents / gross_cents) * 100
                    #             = (application_fee_amount / (amount * 100)) * 100
                    #             = application_fee_amount / amount
                    #
                    # NOTE: Do NOT gate this on metadata keys. The checkout
                    # session may have been created via ConnectService (stores
                    # 'rs_fee_percent') OR the module-level helper (stores
                    # 'rs_fee_cents'). Computing from raw amounts is always
                    # correct and avoids the key-name mismatch.
                    if amount > 0:
                        fee_percent = (Decimal(str(application_fee_amount)) / (amount * 100) * 100).quantize(Decimal('0.01'))
                    else:
                        fee_percent = Decimal('0.00')
                    PlatformFeeRecord.objects.create(
                        tenant=invoice.tenant,
                        invoice=invoice,
                        payment_intent_id=payment_intent_id,
                        gross_amount=amount,
                        fee_amount=fee_amount,
                        fee_percent=fee_percent,
                        stripe_account_id=payment_intent.get('on_behalf_of') or invoice.tenant.stripe_connect_account_id or '',
                    )
                    logger.info(
                        f"Recorded platform fee ${fee_amount} for {invoice.invoice_number}"
                    )
            except Exception as e:
                logger.warning(f"Failed to record platform fee for {payment_intent_id}: {e}")

        return result
    
    def _record_stripe_payment(self, invoice_id, amount, stripe_payment_id='', notes='',
                               event_account=None):
        """Record a Stripe payment against our invoice."""
        from apps.billing.models import Invoice
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService

        try:
            # Note: Stripe webhook context has no tenant, but invoice_id
            # comes from our own metadata so this is safe. We still log
            # the tenant for audit purposes.
            invoice = Invoice.objects.get(id=invoice_id)
            logger.info(f"Stripe payment for invoice {invoice_id} (tenant: {invoice.tenant_id})")
        except Invoice.DoesNotExist:
            logger.error(f"Invoice {invoice_id} not found for Stripe payment")
            return {'success': False, 'error': 'Invoice not found'}

        # The paying Connect account must be the invoice tenant's own account.
        # Anything else (a charge on the platform account via a stale Payment
        # Link, or metadata pointing at another shop's invoice) means the
        # money did NOT reach this shop — never mark the invoice paid.
        expected_account = (
            invoice.tenant.stripe_connect_account_id if invoice.tenant else ''
        )
        if not event_account or event_account != expected_account:
            logger.error(
                f"REFUSING to record payment {stripe_payment_id or '(no pi)'} for "
                f"invoice {invoice.invoice_number}: charge account "
                f"{event_account!r} does not match tenant's Connect account "
                f"{expected_account!r}. Money may have settled in the wrong "
                f"Stripe account — investigate and refund/re-collect manually."
            )
            return {
                'success': True,
                'handled': False,
                'flagged': 'account_mismatch',
                'invoice_id': invoice.id,
            }
        
        # Don't double-record payments. The .exists() precheck is a fast
        # path only — two concurrent webhook deliveries (Stripe sends
        # checkout.session.completed AND payment_intent.succeeded for the
        # same pi_..., plus retries) can both pass it. The DB-level partial
        # unique index on stripe_payment_id is what actually closes the
        # race; catch its IntegrityError as "duplicate". (C2)
        if invoice.payments.filter(stripe_payment_id=stripe_payment_id).exists():
            logger.info(f"Payment {stripe_payment_id} already recorded")
            return {'success': True, 'duplicate': True}

        # An unseen Stripe payment for an invoice that is ALREADY fully
        # paid is either the same money recorded manually before the
        # webhook arrived (e.g. late retries after the Aug 2026 webhook
        # outage, reconciled by hand), or a genuine double charge. Never
        # credit it again and never email the customer a receipt — alert
        # the shop only, so a real double charge gets reviewed/refunded.
        if invoice.status == 'PAID' or invoice.amount_due <= 0:
            logger.warning(
                f"Stripe payment {stripe_payment_id or '(no pi)'} arrived for "
                f"already-paid invoice {invoice.invoice_number} — NOT recorded. "
                f"Possible duplicate charge; shop alerted."
            )
            self._alert_shop_payment_for_paid_invoice(
                invoice, amount, stripe_payment_id,
            )
            return {
                'success': True,
                'skipped': 'already_paid',
                'invoice_id': invoice.id,
            }

        from django.db import IntegrityError, transaction as db_transaction
        tracking = InvoiceTrackingService(tenant=invoice.tenant)
        try:
            with db_transaction.atomic():
                payment = tracking.record_payment(
                    invoice=invoice,
                    amount=amount,
                    payment_method='STRIPE',
                    stripe_payment_id=stripe_payment_id,
                    notes=notes,
                )
        except IntegrityError:
            logger.info(
                f"Payment {stripe_payment_id} already recorded (unique "
                f"constraint hit — concurrent webhook delivery)"
            )
            return {'success': True, 'duplicate': True}
        
        logger.info(f"Stripe payment ${amount} recorded for {invoice.invoice_number}")
        
        # Send payment confirmation emails
        try:
            from apps.billing.services.payment_notification_service import PaymentNotificationService
            invoice.refresh_from_db()  # Reload to get updated status/amounts
            notif = PaymentNotificationService()
            notif_result = notif.notify_payment(payment)
            logger.info(f"Payment notifications: customer={notif_result['customer_sent']}, owner={notif_result['owner_sent']}")
        except Exception as e:
            logger.warning(f"Payment notification failed (non-fatal): {e}")

        # In-portal notification: online payments arrive while nobody is
        # looking at their inbox — every manager gets a bell notification,
        # so the shop never has to guess whether a payment went through.
        try:
            from apps.technician_portal.models import Technician, TechnicianNotification
            status_note = (
                'paid in full'
                if invoice.status == 'PAID'
                else f'${invoice.amount_due} remaining'
            )
            summary = (
                f"💰 {invoice.customer.name} paid ${amount} online — "
                f"invoice {invoice.invoice_number} ({status_note})."
            )
            managers = Technician.objects.filter(
                tenant=invoice.tenant, is_active=True, is_manager=True,
            )
            for tech in managers:
                TechnicianNotification.objects.create(
                    technician=tech, message=summary, read=False,
                )
        except Exception as e:
            logger.warning(f"In-portal payment notification failed (non-fatal): {e}")
        
        return {
            'success': True,
            'invoice_id': invoice.id,
            'invoice_number': invoice.invoice_number,
            'amount': float(amount),
        }

    def _alert_shop_payment_for_paid_invoice(self, invoice, amount,
                                             stripe_payment_id):
        """Shop-only alert (in-portal + owner email, NEVER the customer)
        when a Stripe payment arrives for an invoice that is already paid."""
        summary = (
            f"⚠️ Stripe reported a ${amount} payment for invoice "
            f"{invoice.invoice_number} ({invoice.customer.name}), but that "
            f"invoice is already fully paid. It was NOT recorded again. If "
            f"this isn't a payment you already entered manually, the customer "
            f"may have been charged twice — check Stripe and refund if needed."
        )
        try:
            from apps.technician_portal.models import Technician, TechnicianNotification
            managers = Technician.objects.filter(
                tenant=invoice.tenant, is_active=True, is_manager=True,
            )
            for tech in managers:
                TechnicianNotification.objects.create(
                    technician=tech, message=summary, read=False,
                )
        except Exception:
            logger.warning(
                "Could not create already-paid alert notification", exc_info=True,
            )

        try:
            from core.email_utils import send_branded_email
            tenant = invoice.tenant
            recipients = []
            if tenant and tenant.business_email:
                recipients.append(tenant.business_email)
            owner_email = getattr(getattr(tenant, 'owner', None), 'email', '')
            if owner_email and owner_email not in recipients:
                recipients.append(owner_email)
            if not recipients:
                return
            send_branded_email(
                subject=(
                    f"Review needed: Stripe payment for already-paid "
                    f"invoice {invoice.invoice_number}"
                ),
                recipient_list=recipients,
                headline="Stripe Payment Not Recorded",
                body_paragraphs=[
                    f"Stripe reported a ${amount} payment for invoice "
                    f"{invoice.invoice_number} ({invoice.customer.name}), "
                    f"but that invoice is already fully paid in RS Systems.",
                    "The payment was NOT recorded again and the customer was "
                    "not emailed.",
                    "If you already entered this payment manually, no action "
                    "is needed. If not, the customer may have been charged "
                    "twice — check your Stripe payments and refund the "
                    "duplicate.",
                ],
                detail_rows=[
                    ('Invoice', invoice.invoice_number),
                    ('Customer', invoice.customer.name),
                    ('Stripe amount', f"${amount}"),
                    ('Stripe payment ID', stripe_payment_id or '(none)'),
                ],
                tenant=tenant,
                fail_silently=True,
            )
        except Exception:
            logger.warning(
                "Could not send already-paid alert email", exc_info=True,
            )
