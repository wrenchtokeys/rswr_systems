"""
Invoice Email Service for RS Systems

Sends invoice emails with:
- PDF invoice attachment
- Repair photos attached separately (not embedded)
- Photo naming: [unit_number] - before.jpg, [unit_number] - after.jpg

Author: Amelia (Clawdbot AI)
Created: 2026-01-27
"""
from __future__ import annotations

import io
import os
import boto3
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from apps.technician_portal.models import Repair


@dataclass
class PhotoAttachment:
    """Represents a photo to attach to email"""
    filename: str
    content: bytes
    content_type: str = 'image/jpeg'


class InvoiceEmailService:
    """
    Service for sending invoice emails with photo attachments.
    
    Usage:
        service = InvoiceEmailService()
        success = service.send_invoice_email(
            customer_id=1,
            recipient_email='customer@example.com',
            days=30
        )
    """
    
    def __init__(self):
        from apps.billing.services.invoice_service import InvoiceService
        self.invoice_service = InvoiceService()
        self._setup_s3_client()
    
    def _setup_s3_client(self):
        """Initialize S3 client for fetching photos"""
        self.s3_client = None
        self.s3_bucket = None
        
        try:
            aws_key = os.environ.get('AWS_ACCESS_KEY_ID')
            aws_secret = os.environ.get('AWS_SECRET_ACCESS_KEY')
            self.s3_bucket = os.environ.get('AWS_STORAGE_BUCKET_NAME')
            region = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
            
            if aws_key and aws_secret and self.s3_bucket:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_key,
                    aws_secret_access_key=aws_secret,
                    region_name=region
                )
        except Exception as e:
            print(f"Warning: Could not initialize S3 client: {e}")
    
    def _fetch_photo_from_s3(self, photo_field) -> Optional[bytes]:
        """
        Fetch a photo from S3.
        
        Args:
            photo_field: Django ImageField with the photo
            
        Returns:
            Photo bytes or None if not available
        """
        if not photo_field or not self.s3_client:
            return None
            
        try:
            # Get the S3 key from the field
            key = f"media/{photo_field.name}"
            
            # Download to memory
            response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=key)
            return response['Body'].read()
            
        except Exception as e:
            print(f"Error fetching photo from S3: {e}")
            return None
    
    def _get_photo_attachments(self, repairs: List[Repair]) -> List[PhotoAttachment]:
        """
        Get all photo attachments for a list of repairs.
        
        Args:
            repairs: List of Repair objects
            
        Returns:
            List of PhotoAttachment objects
        """
        attachments = []
        
        for repair in repairs:
            unit = repair.unit_number
            
            # Before photo
            if repair.damage_photo_before:
                content = self._fetch_photo_from_s3(repair.damage_photo_before)
                if content:
                    attachments.append(PhotoAttachment(
                        filename=f"{unit} - before.jpg",
                        content=content
                    ))
            
            # After photo
            if repair.damage_photo_after:
                content = self._fetch_photo_from_s3(repair.damage_photo_after)
                if content:
                    attachments.append(PhotoAttachment(
                        filename=f"{unit} - after.jpg",
                        content=content
                    ))
            
            # Customer submitted photo
            if repair.customer_submitted_photo:
                content = self._fetch_photo_from_s3(repair.customer_submitted_photo)
                if content:
                    attachments.append(PhotoAttachment(
                        filename=f"{unit} - customer_submitted.jpg",
                        content=content
                    ))
        
        return attachments
    
    def _build_email_body(self, invoice_data, include_photos: bool,
                          payment_link: str = None) -> str:
        """Build the email body text"""
        lines = [
            f"Invoice #{invoice_data.invoice_number}",
            f"Date: {invoice_data.invoice_date.strftime('%B %d, %Y')}",
            f"Payment Terms: {invoice_data.payment_terms_display}",
            "",
            f"Customer: {invoice_data.customer_name}",
            "",
            "Repair Summary:",
            "-" * 40,
        ]
        
        for item in invoice_data.line_items:
            lines.append(f"  • Unit {item.unit_number} - {item.damage_type} - ${item.final_cost:.2f}")
            if item.description:
                lines.append(f"    {item.description[:100]}")
        
        lines.append("-" * 40)

        if invoice_data.total_discount > 0:
            lines.append(f"Subtotal: ${invoice_data.subtotal:.2f}")
            lines.append(f"Discounts: -${invoice_data.total_discount:.2f}")

        if hasattr(invoice_data, 'tax_amount') and invoice_data.tax_amount > 0:
            has_breakdown = (
                getattr(invoice_data, 'state_tax_rate', 0) > 0 or
                getattr(invoice_data, 'county_tax_rate', 0) > 0 or
                getattr(invoice_data, 'city_tax_rate', 0) > 0
            )
            if has_breakdown:
                def _fmt(r):
                    return f"{r:.3f}".rstrip('0').rstrip('.')
                if getattr(invoice_data, 'state_tax_rate', 0) > 0:
                    lines.append(f"  State Tax: {_fmt(invoice_data.state_tax_rate)}%")
                if getattr(invoice_data, 'county_tax_rate', 0) > 0:
                    lines.append(f"  County Tax: {_fmt(invoice_data.county_tax_rate)}%")
                if getattr(invoice_data, 'city_tax_rate', 0) > 0:
                    lines.append(f"  City Tax: {_fmt(invoice_data.city_tax_rate)}%")
                if getattr(invoice_data, 'special_tax_rate', 0) > 0:
                    lines.append(f"  Special Tax: {_fmt(invoice_data.special_tax_rate)}%")
            rate_display = f"{invoice_data.tax_rate:.3f}".rstrip('0').rstrip('.')
            lines.append(f"Tax ({rate_display}%): ${invoice_data.tax_amount:.2f}")

        lines.extend([
            f"Total: ${invoice_data.total:.2f}",
            "",
        ])
        
        # Stripe payment link
        if payment_link:
            lines.extend([
                "💳 Pay Online:",
                payment_link,
                "",
            ])
        
        if include_photos:
            lines.extend([
                "📸 Repair photos are attached to this email.",
                "   Photos are named: [Unit#] - before.jpg / [Unit#] - after.jpg",
                "",
            ])
        
        lines.extend([
            "Thank you for your business!",
            "",
            "—",
            self.invoice_service.COMPANY_NAME,
        ])
        
        if self.invoice_service.COMPANY_PHONE:
            lines.append(self.invoice_service.COMPANY_PHONE)
        if self.invoice_service.COMPANY_EMAIL:
            lines.append(self.invoice_service.COMPANY_EMAIL)
        
        return "\n".join(lines)
    
    def send_invoice_email(
        self,
        customer_id: int,
        recipient_email: str,
        repair_ids: Optional[List[int]] = None,
        days: int = 30,
        include_photos: bool = True,
        cc_emails: Optional[List[str]] = None,
        subject_prefix: str = "[RS Systems]"
    ) -> Tuple[bool, str]:
        """
        Send an invoice email with PDF and photo attachments.
        
        Args:
            customer_id: Customer ID to invoice
            recipient_email: Primary recipient email
            repair_ids: Optional specific repair IDs
            days: Number of days to look back (default 30)
            include_photos: Whether to attach repair photos
            cc_emails: Optional CC recipients
            subject_prefix: Email subject prefix
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Generate invoice
            start_date = timezone.now() - timedelta(days=days) if not repair_ids else None
            pdf_bytes, invoice_data = self.invoice_service.generate_invoice(
                customer_id=customer_id,
                repair_ids=repair_ids,
                start_date=start_date
            )
            
            if not invoice_data.line_items:
                return False, "No completed repairs found for invoicing"
            
            # Get repairs for photo attachments
            photos = []
            if include_photos:
                repairs = self.invoice_service.get_completed_repairs(
                    customer_id=customer_id,
                    repair_ids=repair_ids,
                    start_date=start_date
                )
                photos = self._get_photo_attachments(list(repairs))
            
            # Look up Stripe payment link from invoice record (if exists)
            # We search by repair_ids since the invoice_number in invoice_data
            # is freshly generated and won't match the DB record.
            payment_link = None
            try:
                from apps.billing.models import InvoiceLineItem
                if repair_ids:
                    line_item = InvoiceLineItem.objects.filter(
                        repair_id__in=repair_ids,
                        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL'],
                    ).select_related('invoice').first()
                    if line_item and line_item.invoice.stripe_hosted_url:
                        payment_link = line_item.invoice.stripe_hosted_url
                else:
                    # Fallback: find most recent invoice for this customer
                    from apps.billing.models import Invoice
                    invoice_record = Invoice.objects.filter(
                        customer_id=customer_id,
                        stripe_hosted_url__gt='',
                    ).order_by('-created_at').first()
                    if invoice_record:
                        payment_link = invoice_record.stripe_hosted_url
            except Exception:
                pass
            
            # Build email
            subject = f"{subject_prefix} Invoice {invoice_data.invoice_number} - {invoice_data.customer_name}"
            body = self._build_email_body(
                invoice_data, include_photos=len(photos) > 0,
                payment_link=payment_link
            )
            
            email = EmailMessage(
                subject=subject,
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient_email],
                cc=cc_emails or [],
            )
            
            # Attach PDF
            pdf_filename = f"Invoice_{invoice_data.customer_name.replace(' ', '_')}_{invoice_data.invoice_number}.pdf"
            email.attach(pdf_filename, pdf_bytes, 'application/pdf')
            
            # Attach photos
            for photo in photos:
                email.attach(photo.filename, photo.content, photo.content_type)
            
            # Send
            result = email.send()
            
            # Save invoice locally for record keeping
            # (S3 saving requires write permissions - not available yet)
            try:
                invoice_dir = f"/home/ubuntu/invoices/{customer_id}"
                os.makedirs(invoice_dir, exist_ok=True)
                local_path = f"{invoice_dir}/{invoice_data.invoice_number}.pdf"
                with open(local_path, 'wb') as f:
                    f.write(pdf_bytes)
                print(f"Invoice saved locally: {local_path}")
            except Exception as e:
                print(f"Warning: Could not save invoice locally: {e}")
            
            photo_count = len(photos)
            return True, f"Email sent successfully with invoice + {photo_count} photos"
            
        except Exception as e:
            return False, f"Error sending email: {str(e)}"
    
    def preview_invoice_email(
        self,
        customer_id: int,
        repair_ids: Optional[List[int]] = None,
        days: int = 30
    ) -> Dict:
        """
        Preview what an invoice email would contain without sending.
        
        Returns:
            Dict with invoice data and photo counts
        """
        try:
            start_date = timezone.now() - timedelta(days=days) if not repair_ids else None
            
            # Build invoice data
            invoice_data = self.invoice_service.build_invoice_data(
                customer_id=customer_id,
                repair_ids=repair_ids,
                start_date=start_date
            )
            
            # Count available photos
            repairs = self.invoice_service.get_completed_repairs(
                customer_id=customer_id,
                repair_ids=repair_ids,
                start_date=start_date
            )
            
            photo_count = 0
            photos_by_unit = {}
            for repair in repairs:
                unit_photos = []
                if repair.damage_photo_before:
                    unit_photos.append('before')
                    photo_count += 1
                if repair.damage_photo_after:
                    unit_photos.append('after')
                    photo_count += 1
                if repair.customer_submitted_photo:
                    unit_photos.append('customer_submitted')
                    photo_count += 1
                if unit_photos:
                    photos_by_unit[repair.unit_number] = unit_photos
            
            return {
                'success': True,
                'invoice_number': invoice_data.invoice_number,
                'customer_name': invoice_data.customer_name,
                'line_item_count': len(invoice_data.line_items),
                'total': float(invoice_data.total),
                'photo_count': photo_count,
                'photos_by_unit': photos_by_unit,
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


# Convenience function
def send_customer_invoice(
    customer_id: int,
    recipient_email: str,
    days: int = 30,
    include_photos: bool = True
) -> Tuple[bool, str]:
    """Send an invoice email to a customer"""
    service = InvoiceEmailService()
    return service.send_invoice_email(
        customer_id=customer_id,
        recipient_email=recipient_email,
        days=days,
        include_photos=include_photos
    )
