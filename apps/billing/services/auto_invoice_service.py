"""
Auto Invoice Service - Handles automatic invoice generation based on customer preferences.

This service:
1. Checks customer invoice preferences (per_ticket, batch, manual)
2. Generates invoices automatically when repairs are completed
3. Saves PDFs to S3 at invoices/{customer_id}/
4. Optionally emails invoices to customers

Author: Amelia (Clawdbot AI)
"""

import logging
from datetime import datetime
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)


class AutoInvoiceService:
    """
    Handles automatic invoice generation based on customer preferences.
    """
    
    def __init__(self):
        self.s3_bucket = getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None)
        self.s3_prefix = 'invoices'
    
    def should_auto_invoice(self, repair):
        """
        Check if an invoice should be auto-generated for this repair.
        
        Args:
            repair: The Repair instance that was just completed
            
        Returns:
            tuple: (should_generate: bool, reason: str)
        """
        if not repair.customer:
            return False, "No customer associated with repair"
        
        if repair.queue_status != 'COMPLETED':
            return False, "Repair is not completed"
        
        # Check tenant-level setting first (management override)
        tenant = getattr(repair, 'tenant', None)
        if tenant and not getattr(tenant, 'auto_invoice_enabled', True):
            return False, "Auto-invoicing disabled at tenant level"
        
        # Check customer preferences
        try:
            prefs = repair.customer.repair_preferences
            invoice_pref = prefs.invoice_preference
        except Exception:
            # No preferences set - default to manual (don't auto-generate)
            return False, "No invoice preferences configured"
        
        if invoice_pref == 'per_ticket':
            return True, "Customer preference: invoice per repair"
        elif invoice_pref == 'batch':
            return False, "Customer preference: batch invoicing (manual trigger)"
        elif invoice_pref == 'manual':
            return False, "Customer preference: manual only"
        
        return False, f"Unknown preference: {invoice_pref}"
    
    def generate_and_save(self, repair):
        """
        Generate an invoice for a single completed service (Repair or
        Replacement), render its PDF, and save to S3.

        Record-first: the tracked Invoice row is created before the PDF, so a
        PDF/S3 failure leaves a DRAFT invoice (renderable on demand from the
        record) instead of an untracked PDF. This also fixes the old
        Replacement bug where a Replacement PK was passed as a repair_id and
        could match an unrelated Repair with the same integer PK.

        Args:
            repair: The Repair or Replacement instance to invoice

        Returns:
            dict: Result with success status, s3_key, and any errors
        """
        from apps.billing.services.invoice_service import InvoiceService

        service = repair

        result = {
            'success': False,
            's3_key': None,
            'invoice_number': None,
            'error': None,
            'emailed': False,
        }

        try:
            service_tenant = getattr(service, 'tenant', None) or getattr(
                getattr(service, 'customer', None), 'tenant', None
            )

            # Create tracked Invoice record FIRST (prevents double-billing).
            # CODE-094: pass tenant= so InvoiceTrackingService loads the correct
            # BillingConfig (payment terms); create as DRAFT and only mark SENT
            # after confirmed email delivery.
            from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
            tracking_service = InvoiceTrackingService(tenant=service_tenant)

            # Resolve customer-specific payment terms override (CODE-219).
            _cust_payment_terms = None
            try:
                _cprefs = service.customer.repair_preferences
                if _cprefs.payment_terms:
                    _cust_payment_terms = _cprefs.payment_terms
            except Exception:
                pass  # No preferences — use shop default via tracking_service

            invoice_record = tracking_service.create_invoice_from_services(
                customer=service.customer,
                services=[service],
                auto_send=False,  # Start as DRAFT; mark SENT after email confirms
                payment_terms=_cust_payment_terms,
            )
            result['invoice_id'] = invoice_record.id
            result['invoice_number'] = invoice_record.invoice_number
            result['success'] = True
            logger.info(f"Created invoice record #{invoice_record.id}")

            # Render PDF from the record — pass tenant so InvoiceService loads
            # the correct BillingConfig (company name, address). (CODE-092)
            pdf_saved = False
            try:
                invoice_service = InvoiceService(tenant=service_tenant)
                pdf_bytes, invoice_data = invoice_service.generate_invoice_from_record(invoice_record)

                s3_key = self._save_to_s3(
                    pdf_bytes=pdf_bytes,
                    customer_id=service.customer.id,
                    invoice_number=invoice_record.invoice_number
                )
                if s3_key:
                    invoice_record.s3_key = s3_key
                    invoice_record.save(update_fields=['s3_key'])
                    result['s3_key'] = s3_key
                    pdf_saved = True
                    logger.info(
                        f"Auto-generated invoice {invoice_record.invoice_number} "
                        f"for {type(service).__name__.lower()} #{service.id} -> s3://{self.s3_bucket}/{s3_key}"
                    )
                else:
                    logger.error(
                        f"Failed to save PDF to S3 for invoice #{invoice_record.id} — "
                        f"DRAFT record kept; PDF renders on demand from the record"
                    )
            except Exception as e:
                logger.error(
                    f"PDF generation failed for invoice #{invoice_record.id}: {e} — "
                    f"DRAFT record kept; PDF renders on demand from the record"
                )

            # Generate Stripe payment link if Stripe is configured
            try:
                stripe_result = self._create_payment_link(invoice_record)
                if stripe_result and stripe_result.get('success'):
                    result['payment_link'] = stripe_result['payment_link']
                    logger.info(f"Stripe payment link created for {invoice_record.invoice_number}")
            except Exception as e:
                logger.warning(f"Could not create Stripe payment link: {e}")

            # Check if we should email; mark invoice SENT only on success.
            # Skip emailing when the PDF failed — the email service would
            # re-render from the record anyway, but a hard PDF failure above
            # means it would fail here too.
            try:
                prefs = service.customer.repair_preferences
                if prefs.auto_email_invoices and pdf_saved:
                    email_result = self._send_invoice_email(
                        service=service,
                        invoice_record=invoice_record,
                        prefs=prefs,
                    )
                    result['emailed'] = email_result

                    # Mark SENT only after confirmed delivery (AGENTS.md gotcha)
                    if email_result:
                        invoice_record.record_email_sent(
                            prefs.billing_email or service.customer.email
                        )
                        logger.info(f"Invoice #{invoice_record.id} marked SENT after email delivery confirmed")
            except Exception as e:
                logger.warning(f"Could not check/send email for invoice: {e}")

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error generating auto-invoice for {type(service).__name__.lower()} #{service.id}: {e}")

        return result
    
    def _create_payment_link(self, invoice):
        """
        Build the public pay URL for an invoice.

        Routes through the shop's Stripe Connect account at click time.
        Never mints a platform-account Payment Link — that money would
        settle in the platform's Stripe balance, not the shop's.

        Args:
            invoice: Invoice model instance

        Returns:
            dict with success/payment_link or None if the shop can't take payments
        """
        try:
            if invoice.amount_due <= 0:
                return None

            from apps.billing.pay_links import public_pay_url
            pay_url = public_pay_url(invoice)
            if not pay_url:
                logger.debug(
                    f"Tenant for invoice #{invoice.id} cannot accept online "
                    f"payments — skipping payment link"
                )
                return None

            return {'success': True, 'payment_link': pay_url}
        except Exception as e:
            logger.warning(f"Payment link error: {e}")
            return None
    
    def _save_to_s3(self, pdf_bytes, customer_id, invoice_number):
        """
        Save invoice PDF to S3 (or local fallback in development).
        
        Args:
            pdf_bytes: The PDF content as bytes
            customer_id: Customer ID for path
            invoice_number: Invoice number for filename
            
        Returns:
            str: S3 key or local path if successful, None otherwise
        """
        # timezone.localdate(), not naive datetime.now(): the filename date
        # must match the invoice_date the shop sees, not the server's UTC
        # clock (off by one after 7pm Central). (C7)
        date_str = timezone.localdate().strftime('%Y-%m-%d')
        filename = f"invoice_{invoice_number}_{date_str}.pdf"
        
        # Try S3 first
        if self.s3_bucket:
            try:
                import boto3
                from botocore.exceptions import ClientError
                
                s3_client = boto3.client('s3')
                s3_key = f"{self.s3_prefix}/{customer_id}/{filename}"
                
                # Upload to S3
                s3_client.put_object(
                    Bucket=self.s3_bucket,
                    Key=s3_key,
                    Body=pdf_bytes,
                    ContentType='application/pdf',
                    ContentDisposition=f'attachment; filename="invoice_{invoice_number}.pdf"'
                )
                
                logger.info(f"Invoice saved to S3: s3://{self.s3_bucket}/{s3_key}")
                return s3_key
                
            except ClientError as e:
                logger.error(f"S3 upload error: {e}")
                # Fall through to local fallback
            except Exception as e:
                logger.error(f"Unexpected S3 error: {e}")
                # Fall through to local fallback
        
        # Local fallback (development mode)
        import os
        # Sanitize filename to prevent path traversal attacks
        safe_filename = os.path.basename(filename)
        # Also sanitize customer_id to prevent path injection
        safe_customer_id = str(int(customer_id))  # Ensure it's a valid integer
        local_dir = f"/home/ubuntu/invoices/{safe_customer_id}"
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, safe_filename)
        
        try:
            with open(local_path, 'wb') as f:
                f.write(pdf_bytes)
            logger.info(f"Invoice saved locally (S3 not configured): {local_path}")
            return f"local:{local_path}"
        except Exception as e:
            logger.error(f"Local save error: {e}")
            return None
    
    def _send_invoice_email(self, service, invoice_record, prefs):
        """
        Send invoice email to customer, rendered from the tracked record.

        Args:
            service: The Repair or Replacement instance
            invoice_record: The tracked Invoice model instance
            prefs: CustomerRepairPreference instance

        Returns:
            bool: True if email sent successfully
        """
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        # Use billing_email if set, otherwise fall back to customer email
        recipient = prefs.billing_email or service.customer.email

        if not recipient:
            logger.warning(f"No email address for customer {service.customer.id}")
            return False

        try:
            email_service = InvoiceEmailService(tenant=getattr(service, 'tenant', None))
            # Photos are never attached to invoice emails — multi-MB photo
            # payloads get quarantined at corporate mail gateways. Customers
            # see photos on the public invoice page instead.
            success, message = email_service.send_invoice_email(
                customer_id=service.customer.id,
                recipient_email=recipient,
                invoice=invoice_record,
            )

            if success:
                logger.info(f"Invoice emailed to {recipient} for invoice #{invoice_record.id}")
            else:
                logger.warning(f"Failed to email invoice: {message}")

            return success

        except Exception as e:
            logger.error(f"Error emailing invoice: {e}")
            return False
    
    def process_completed_repair(self, repair):
        """
        Main entry point - called when a repair is marked completed.
        Checks preferences and generates invoice if appropriate.
        
        Args:
            repair: The Repair instance that was completed
            
        Returns:
            dict: Result with action taken and details
        """
        should_generate, reason = self.should_auto_invoice(repair)
        
        result = {
            'repair_id': repair.id,
            'customer_id': repair.customer.id if repair.customer else None,
            'should_generate': should_generate,
            'reason': reason,
            'invoice_result': None,
        }
        
        if should_generate:
            result['invoice_result'] = self.generate_and_save(repair)
        
        return result
