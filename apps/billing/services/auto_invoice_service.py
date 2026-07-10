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
        Generate an invoice for a single repair and save to S3.
        
        Args:
            repair: The Repair instance to invoice
            
        Returns:
            dict: Result with success status, s3_key, and any errors
        """
        from apps.billing.services.invoice_service import InvoiceService
        
        result = {
            'success': False,
            's3_key': None,
            'invoice_number': None,
            'error': None,
            'emailed': False,
        }
        
        try:
            # Generate PDF — pass tenant so InvoiceService loads the correct
            # BillingConfig (company name, address, payment terms).  Without
            # tenant, InvoiceService() generates PDFs with blank company info.
            # (CODE-092: mirrors reminder_service and clawdbot fixes)
            repair_tenant = getattr(repair, 'tenant', None) or getattr(
                getattr(repair, 'customer', None), 'tenant', None
            )
            invoice_service = InvoiceService(tenant=repair_tenant)
            pdf_bytes, invoice_data = invoice_service.generate_invoice(
                customer_id=repair.customer.id,
                repair_ids=[repair.id]
            )
            
            if not invoice_data.line_items:
                result['error'] = "No line items generated"
                return result
            
            result['invoice_number'] = invoice_data.invoice_number
            
            # Save to S3
            s3_key = self._save_to_s3(
                pdf_bytes=pdf_bytes,
                customer_id=repair.customer.id,
                invoice_number=invoice_data.invoice_number
            )
            
            if s3_key:
                result['success'] = True
                result['s3_key'] = s3_key
                
                # Create tracked Invoice record (prevents double-billing).
                # CODE-094 fixes:
                #   1. Pass tenant= so InvoiceTrackingService loads the correct
                #      BillingConfig (payment terms).  Without tenant, all
                #      auto-invoices defaulted to COD regardless of shop settings.
                #   2. Create as DRAFT first; only mark SENT after confirming email
                #      delivery.  Previously auto_send=True marked SENT before the
                #      email was even attempted — violating the invariant in AGENTS.md
                #      ("Don't mark invoices SENT before confirming email delivery").
                invoice_record = None
                try:
                    from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
                    tracking_service = InvoiceTrackingService(tenant=repair_tenant)

                    # Resolve customer-specific payment terms override.
                    # CustomerRepairPreference.payment_terms was added (migration 0013)
                    # but auto_invoice_service was not updated to read it — customer
                    # overrides were silently ignored.  (CODE-219)
                    _cust_payment_terms = None
                    try:
                        _cprefs = repair.customer.repair_preferences
                        if _cprefs.payment_terms:
                            _cust_payment_terms = _cprefs.payment_terms
                    except Exception:
                        pass  # No preferences — use shop default via tracking_service

                    invoice_record = tracking_service.create_invoice_from_repairs(
                        customer=repair.customer,
                        repairs=[repair],
                        invoice_number=invoice_data.invoice_number,
                        s3_key=s3_key,
                        auto_send=False,  # Start as DRAFT; mark SENT after email confirms
                        payment_terms=_cust_payment_terms,
                    )
                    result['invoice_id'] = invoice_record.id
                    logger.info(f"Created invoice record #{invoice_record.id}")
                except Exception as e:
                    # A missing Invoice row means the repair still counts as
                    # "uninvoiced": if we email the customer anyway, they pay
                    # an invoice the system has no record of, and the next
                    # batch run bills the repair AGAIN. Surface it loudly and
                    # (below) do NOT email. (C6)
                    logger.error(
                        f"Could not create invoice record for repair #{repair.id} "
                        f"(invoice {invoice_data.invoice_number}): {e} — "
                        f"invoice email suppressed to avoid double-billing"
                    )
                    result['error'] = f"Invoice record creation failed: {e}"
                
                # Generate Stripe payment link if Stripe is configured
                if invoice_record:
                    try:
                        stripe_result = self._create_payment_link(invoice_record)
                        if stripe_result and stripe_result.get('success'):
                            result['payment_link'] = stripe_result['payment_link']
                            logger.info(f"Stripe payment link created for {invoice_data.invoice_number}")
                    except Exception as e:
                        logger.warning(f"Could not create Stripe payment link: {e}")
                
                logger.info(f"Auto-generated invoice {invoice_data.invoice_number} for repair #{repair.id} -> s3://{self.s3_bucket}/{s3_key}")
                
                # Check if we should email; mark invoice SENT only on success.
                # NEVER email when the Invoice record failed to create (C6):
                # the customer would pay an invoice the system can't track,
                # and the repair would be billed again on the next batch run.
                try:
                    prefs = repair.customer.repair_preferences
                    if prefs.auto_email_invoices and invoice_record:
                        email_result = self._send_invoice_email(
                            repair=repair,
                            pdf_bytes=pdf_bytes,
                            invoice_data=invoice_data,
                            prefs=prefs
                        )
                        result['emailed'] = email_result

                        # Mark SENT only after confirmed delivery (AGENTS.md gotcha)
                        if email_result and invoice_record:
                            from django.utils import timezone as _tz
                            invoice_record.status = 'SENT'
                            invoice_record.sent_at = _tz.now()
                            invoice_record.save(update_fields=['status', 'sent_at'])
                            logger.info(f"Invoice #{invoice_record.id} marked SENT after email delivery confirmed")
                except Exception as e:
                    logger.warning(f"Could not check/send email for invoice: {e}")
            else:
                result['error'] = "Failed to save to S3"
                
        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error generating auto-invoice for repair #{repair.id}: {e}")
        
        return result
    
    def _create_payment_link(self, invoice):
        """
        Generate a Stripe payment link for an invoice (if Stripe is configured).
        
        Args:
            invoice: Invoice model instance
            
        Returns:
            dict with success/payment_link or None if Stripe not configured
        """
        try:
            from apps.billing.services.stripe_service import StripeService
            stripe_svc = StripeService()
            if not stripe_svc.is_enabled():
                logger.debug("Stripe not configured, skipping payment link")
                return None
            
            if invoice.amount_due <= 0:
                return None
            
            return stripe_svc.create_payment_link(invoice)
        except Exception as e:
            logger.warning(f"Stripe payment link error: {e}")
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
    
    def _send_invoice_email(self, repair, pdf_bytes, invoice_data, prefs):
        """
        Send invoice email to customer.
        
        Args:
            repair: The Repair instance
            pdf_bytes: The PDF content
            invoice_data: InvoiceData dataclass
            prefs: CustomerRepairPreference instance
            
        Returns:
            bool: True if email sent successfully
        """
        from apps.billing.services.invoice_email_service import InvoiceEmailService
        
        # Use billing_email if set, otherwise fall back to customer email
        recipient = prefs.billing_email or repair.customer.email
        
        if not recipient:
            logger.warning(f"No email address for customer {repair.customer.id}")
            return False
        
        try:
            email_service = InvoiceEmailService(tenant=getattr(repair, 'tenant', None))
            success, message = email_service.send_invoice_email(
                customer_id=repair.customer.id,
                recipient_email=recipient,
                repair_ids=[repair.id],
                include_photos=prefs.include_photos_in_invoice
            )
            
            if success:
                logger.info(f"Invoice emailed to {recipient} for repair #{repair.id}")
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
