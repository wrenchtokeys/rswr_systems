"""
Stripe Integration Service - Handles Stripe invoice and payment processing.

Provides:
- Create Stripe invoices from our Invoice records
- Generate payment links for customers
- Process Stripe webhook events
- Sync payment status

SETUP REQUIRED:
1. Set STRIPE_SECRET_KEY in environment
2. Set STRIPE_WEBHOOK_SECRET for webhook verification
3. Configure webhook endpoint in Stripe dashboard

Author: Amelia (Clawdbot AI)
"""

import logging
from decimal import Decimal
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Stripe SDK - only import if available
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    STRIPE_AVAILABLE = False
    logger.warning("Stripe SDK not installed. Run: pip install stripe")


class StripeService:
    """
    Handles all Stripe integration for invoices and payments.
    """
    
    def __init__(self):
        self.api_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
        self.webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
        
        if STRIPE_AVAILABLE and self.api_key:
            stripe.api_key = self.api_key
            self.enabled = True
        else:
            self.enabled = False
            if not STRIPE_AVAILABLE:
                logger.debug("Stripe SDK not available")
            elif not self.api_key:
                logger.debug("STRIPE_SECRET_KEY not configured")
    
    def is_enabled(self):
        """Check if Stripe integration is properly configured."""
        return self.enabled
    
    def get_or_create_customer(self, customer):
        """
        Get or create a Stripe Customer for our Customer record.
        
        Args:
            customer: Our Customer model instance
            
        Returns:
            str: Stripe customer ID
        """
        if not self.enabled:
            raise RuntimeError("Stripe not configured")
        
        # Check if customer already has a Stripe ID stored
        # We'll store this in a simple way - could add a field to Customer model later
        stripe_customer_id = getattr(customer, 'stripe_customer_id', None)
        
        if stripe_customer_id:
            try:
                # Verify it still exists in Stripe
                stripe.Customer.retrieve(stripe_customer_id)
                return stripe_customer_id
            except stripe.error.InvalidRequestError:
                # Customer doesn't exist in Stripe, create new one
                pass
        
        # Search for existing customer by email
        if customer.email:
            existing = stripe.Customer.list(email=customer.email, limit=1)
            if existing.data:
                return existing.data[0].id
        
        # Create new Stripe customer
        stripe_customer = stripe.Customer.create(
            name=customer.name,
            email=customer.email,
            phone=customer.phone,
            metadata={
                'rs_systems_customer_id': str(customer.id),
            }
        )
        
        logger.info(f"Created Stripe customer {stripe_customer.id} for {customer.name}")
        return stripe_customer.id
    
    def create_stripe_invoice(self, invoice, auto_send=False):
        """
        Create a Stripe Invoice from our Invoice record.
        
        Args:
            invoice: Our Invoice model instance
            auto_send: Whether to finalize and send immediately
            
        Returns:
            dict: Stripe invoice details
        """
        if not self.enabled:
            return {'success': False, 'error': 'Stripe not configured'}
        
        try:
            # Get or create Stripe customer
            stripe_customer_id = self.get_or_create_customer(invoice.customer)
            
            # Create Stripe invoice
            stripe_invoice = stripe.Invoice.create(
                customer=stripe_customer_id,
                collection_method='send_invoice',
                days_until_due=30 if not invoice.due_date else (invoice.due_date - timezone.now().date()).days,
                metadata={
                    'rs_systems_invoice_id': str(invoice.id),
                    'rs_systems_invoice_number': invoice.invoice_number,
                },
            )
            
            # Add line items
            for item in invoice.line_items.all():
                # Calculate total amount in cents for this line item
                amount_cents = int(item.amount * 100)
                stripe.InvoiceItem.create(
                    customer=stripe_customer_id,
                    invoice=stripe_invoice.id,
                    description=item.description,
                    amount=amount_cents,  # Total amount in cents
                    currency='usd',
                    metadata={
                        'repair_id': str(item.repair_id) if item.repair_id else '',
                        'unit_number': item.unit_number,
                    }
                )
            
            # Finalize to get hosted URL (required before sending)
            stripe_invoice = stripe.Invoice.finalize_invoice(stripe_invoice.id)
            
            # Send to customer if requested
            if auto_send:
                stripe_invoice = stripe.Invoice.send_invoice(stripe_invoice.id)
            
            # Update our invoice with Stripe IDs
            invoice.stripe_invoice_id = stripe_invoice.id
            invoice.stripe_hosted_url = stripe_invoice.hosted_invoice_url or ''
            invoice.save()
            
            logger.info(f"Created Stripe invoice {stripe_invoice.id} for {invoice.invoice_number}")
            
            return {
                'success': True,
                'stripe_invoice_id': stripe_invoice.id,
                'hosted_url': stripe_invoice.hosted_invoice_url,
                'pdf_url': stripe_invoice.invoice_pdf,
                'status': stripe_invoice.status,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating invoice: {e}")
            return {'success': False, 'error': str(e)}
    
    def create_payment_link(self, invoice):
        """
        Create a Stripe Payment Link for an invoice.
        This allows one-click payment without needing a full Stripe invoice.
        
        Args:
            invoice: Our Invoice model instance
            
        Returns:
            dict: Payment link details
        """
        if not self.enabled:
            return {'success': False, 'error': 'Stripe not configured'}
        
        try:
            # Create a price for this specific invoice
            price = stripe.Price.create(
                currency='usd',
                unit_amount=int(invoice.amount_due * 100),  # Cents
                product_data={
                    'name': f'Invoice {invoice.invoice_number}',
                    'metadata': {
                        'invoice_id': str(invoice.id),
                        'customer_name': invoice.customer.name,
                    }
                },
            )
            
            # Create payment link
            payment_link = stripe.PaymentLink.create(
                line_items=[{'price': price.id, 'quantity': 1}],
                metadata={
                    'rs_systems_invoice_id': str(invoice.id),
                    'rs_systems_invoice_number': invoice.invoice_number,
                },
                after_completion={
                    'type': 'redirect',
                    'redirect': {
                        'url': f'https://rockstarwindshield.repair/payment-complete?invoice={invoice.invoice_number}'
                    }
                }
            )
            
            logger.info(f"Created payment link for invoice {invoice.invoice_number}")
            
            return {
                'success': True,
                'payment_link': payment_link.url,
                'price_id': price.id,
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating payment link: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_webhook(self, payload, sig_header):
        """
        Process incoming Stripe webhook events.
        
        Args:
            payload: Raw request body
            sig_header: Stripe-Signature header
            
        Returns:
            dict: Processing result
        """
        if not self.enabled:
            return {'success': False, 'error': 'Stripe not configured'}
        
        if not self.webhook_secret:
            return {'success': False, 'error': 'Webhook secret not configured'}
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {e}")
            return {'success': False, 'error': 'Invalid payload'}
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            return {'success': False, 'error': 'Invalid signature'}
        
        # Handle specific events
        event_type = event['type']
        data = event['data']['object']
        
        handlers = {
            'invoice.paid': self._handle_invoice_paid,
            'invoice.payment_failed': self._handle_payment_failed,
            'payment_intent.succeeded': self._handle_payment_succeeded,
            'checkout.session.completed': self._handle_checkout_completed,
        }
        
        handler = handlers.get(event_type)
        if handler:
            return handler(data)
        
        logger.debug(f"Unhandled webhook event type: {event_type}")
        return {'success': True, 'handled': False, 'event_type': event_type}
    
    def _handle_invoice_paid(self, stripe_invoice):
        """Handle Stripe invoice.paid event."""
        from apps.billing.models import Invoice
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        
        invoice_id = stripe_invoice.get('metadata', {}).get('rs_systems_invoice_id')
        if not invoice_id:
            logger.warning("No rs_systems_invoice_id in Stripe invoice metadata")
            return {'success': False, 'error': 'No invoice mapping'}
        
        try:
            invoice = Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist:
            logger.error(f"Invoice {invoice_id} not found for Stripe invoice")
            return {'success': False, 'error': 'Invoice not found'}
        
        # Record the payment
        amount_paid = Decimal(stripe_invoice['amount_paid']) / 100  # Convert from cents
        
        tracking = InvoiceTrackingService()
        tracking.record_payment(
            invoice=invoice,
            amount=amount_paid,
            payment_method='STRIPE',
            stripe_payment_id=stripe_invoice.get('payment_intent', ''),
            notes=f"Paid via Stripe invoice {stripe_invoice['id']}"
        )
        
        # Update Stripe payment intent ID
        invoice.stripe_payment_intent_id = stripe_invoice.get('payment_intent', '')
        invoice.save()
        
        logger.info(f"Recorded Stripe payment for invoice {invoice.invoice_number}")
        
        return {'success': True, 'invoice_id': invoice.id, 'amount': float(amount_paid)}
    
    def _handle_payment_failed(self, stripe_invoice):
        """Handle Stripe invoice.payment_failed event."""
        from apps.billing.models import Invoice
        
        invoice_id = stripe_invoice.get('metadata', {}).get('rs_systems_invoice_id')
        if invoice_id:
            try:
                invoice = Invoice.objects.get(id=invoice_id)
                invoice.internal_notes += f"\n[Stripe] Payment failed at {timezone.now()}"
                invoice.save()
                logger.warning(f"Payment failed for invoice {invoice.invoice_number}")
            except Invoice.DoesNotExist:
                pass
        
        return {'success': True, 'event': 'payment_failed'}
    
    def _handle_payment_succeeded(self, payment_intent):
        """Handle payment_intent.succeeded event (for payment links)."""
        from apps.billing.models import Invoice
        from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
        
        # Get invoice ID from metadata
        metadata = payment_intent.get('metadata', {})
        invoice_id = metadata.get('rs_systems_invoice_id')
        
        if not invoice_id:
            # Try to find from charges
            logger.debug("No invoice_id in payment_intent metadata")
            return {'success': True, 'handled': False}
        
        try:
            invoice = Invoice.objects.get(id=invoice_id)
        except Invoice.DoesNotExist:
            return {'success': False, 'error': 'Invoice not found'}
        
        amount = Decimal(payment_intent['amount_received']) / 100
        
        tracking = InvoiceTrackingService()
        tracking.record_payment(
            invoice=invoice,
            amount=amount,
            payment_method='STRIPE',
            stripe_payment_id=payment_intent['id'],
            notes='Paid via Stripe payment link'
        )
        
        logger.info(f"Recorded payment link payment for invoice {invoice.invoice_number}")
        
        return {'success': True, 'invoice_id': invoice.id, 'amount': float(amount)}
    
    def _handle_checkout_completed(self, session):
        """Handle checkout.session.completed event."""
        # Similar to payment_intent.succeeded
        return self._handle_payment_succeeded(session.get('payment_intent', {}))
    
    def sync_invoice_status(self, invoice):
        """
        Sync our invoice status with Stripe.
        
        Args:
            invoice: Our Invoice model instance
            
        Returns:
            dict: Sync result
        """
        if not self.enabled or not invoice.stripe_invoice_id:
            return {'success': False, 'error': 'No Stripe invoice to sync'}
        
        try:
            stripe_invoice = stripe.Invoice.retrieve(invoice.stripe_invoice_id)
            
            result = {
                'stripe_status': stripe_invoice.status,
                'amount_paid': float(stripe_invoice.amount_paid / 100),
                'amount_remaining': float(stripe_invoice.amount_remaining / 100),
            }
            
            # Update hosted URL if changed
            if stripe_invoice.hosted_invoice_url != invoice.stripe_hosted_url:
                invoice.stripe_hosted_url = stripe_invoice.hosted_invoice_url or ''
                invoice.save()
            
            return {'success': True, **result}
            
        except stripe.error.StripeError as e:
            return {'success': False, 'error': str(e)}
