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

import html
import io
import logging
import os
import boto3
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.utils import timezone

from apps.technician_portal.models import Repair

logger = logging.getLogger(__name__)


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
    
    def __init__(self, tenant=None):
        from apps.billing.services.invoice_service import InvoiceService
        self.tenant = tenant
        self.invoice_service = InvoiceService(tenant=tenant)
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
    
    def _render_invoice_template(self, template_str, invoice_data, points_line=None) -> str:
        """Render a shop-defined invoice email template.

        Supports the same placeholders documented in BillingConfig.invoice_email_template
        help_text:
          {customer_name}, {invoice_number}, {total}, {invoice_date}, {company_name},
          {points_balance}

        {points_balance} renders as an empty string when the loyalty program
        (or its email toggle) is off, so custom templates never break.

        Falls back to the original hardcoded body if rendering fails (e.g. unknown
        placeholder in a legacy template).
        """
        company_name = ''
        if self.tenant:
            try:
                from apps.billing.models import BillingConfig
                config = BillingConfig.get_for_tenant(self.tenant)
                company_name = config.company_name or self.tenant.name
            except Exception:
                company_name = self.tenant.name

        try:
            return template_str.format(
                customer_name=invoice_data.customer_name,
                invoice_number=invoice_data.invoice_number,
                total=f'${invoice_data.total:,.2f}',
                invoice_date=invoice_data.invoice_date.strftime('%B %d, %Y') if invoice_data.invoice_date else 'N/A',
                company_name=company_name,
                points_balance=points_line or '',
            )
        except (KeyError, IndexError, ValueError):
            # Unknown placeholder or malformed template — fall back to default body.
            return ''

    @staticmethod
    def _service_phrase(invoice_data) -> str:
        """Describe what the invoice covers, derived from its line items.

        Replacement-only invoices used to read "recent windshield repair
        services" — wrong for a replacement shop. Classify each line item by
        its linked service object (falling back to the PDF label) and pick
        matching wording.
        """
        kinds = set()
        for item in invoice_data.line_items:
            if getattr(item, 'replacement_obj', None) is not None:
                kinds.add('replacement')
            elif getattr(item, 'repair_obj', None) is not None:
                kinds.add('repair')
            else:
                label = (item.damage_type or '').lower()
                if 'replacement' in label:
                    kinds.add('replacement')
                elif label and label != 'service':
                    kinds.add('repair')
        if kinds == {'repair'}:
            return 'recent windshield repair services'
        if kinds == {'replacement'}:
            return 'recent glass replacement services'
        if kinds == {'repair', 'replacement'}:
            return 'recent glass repair and replacement services'
        return 'recent services'

    def _public_view_link(self, invoice_id) -> str:
        """Public tokened page where the customer can VIEW the invoice
        (summary + PDF) — distinct from the /pay/ URL, which goes straight
        to Stripe Checkout."""
        from rs_systems.views import generate_payment_token
        base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
        token = generate_payment_token(invoice_id)
        return f"{base_url}/invoice/{invoice_id}/{token}/"

    def _build_email_body(self, invoice_data, include_photos: bool,
                          payment_link: str = None, view_link: str = None,
                          points_line: str = None) -> str:
        """Build the email body text"""
        lines = [
            f"Invoice #{invoice_data.invoice_number}",
            f"Date: {invoice_data.invoice_date.strftime('%B %d, %Y')}",
            f"Payment Terms: {invoice_data.payment_terms_display}",
            "",
            f"Customer: {invoice_data.customer_name}",
            "",
            "Service Summary:",
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

        # Short factual loyalty line (already gated by the caller).
        if points_line:
            lines.extend([points_line, ""])


        # View link — the public tokened invoice page (no login needed).
        # Falls back to the customer portal when we don't know the invoice
        # record (CODE-178: use BASE_URL so custom domains get the right host).
        if view_link:
            portal_url = view_link
        else:
            invoice_id = getattr(invoice_data, 'id', None) or getattr(invoice_data, 'pk', None)
            _base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
            if invoice_id:
                portal_url = f"{_base_url}/app/invoices/{invoice_id}/"
            else:
                portal_url = f"{_base_url}/app/invoices/"
        lines.extend([
            "View your invoice online:",
            portal_url,
            "",
        ])

        # Stripe payment link
        if payment_link:
            lines.extend([
                "Pay online:",
                payment_link,
                "",
            ])

        if include_photos:
            lines.extend([
                "Repair photos are attached to this email.",
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
        include_photos: bool = False,
        cc_emails: Optional[List[str]] = None,
        bcc_emails: Optional[List[str]] = None,
        subject_prefix: str = "[RS Systems]",
        invoice_number: Optional[str] = None,
        invoice_date=None,
        invoice=None,
    ) -> Tuple[bool, str]:
        """
        Send an invoice email with PDF and photo attachments.

        Args:
            customer_id: Customer ID to invoice
            recipient_email: Primary recipient email
            repair_ids: Optional specific repair IDs
            days: Number of days to look back (default 30)
            include_photos: Whether to attach repair photos. Off by default —
                multi-MB photo attachments get invoice email quarantined at
                corporate mail gateways; photos live on the public invoice
                page instead.
            cc_emails: Optional CC recipients
            subject_prefix: Email subject prefix
            invoice_number: Stored invoice number to embed in PDF (CODE-120).
                Pass Invoice.invoice_number when re-sending for an existing invoice
                so the PDF content matches the record. When None a new number is
                generated (used during initial invoice creation).
            invoice_date: Stored invoice date to embed in PDF (CODE-120).
            invoice: Existing Invoice model record. When provided, the PDF is
                rendered from the invoice's OWN line items and stored totals
                (A4) — never from a repair lookback. Always pass this when
                sending an invoice that already exists; the repair-lookback
                path below is only for generating a NEW invoice.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            if invoice is not None:
                # A4: render the existing record. A replacement-only invoice
                # (no repair-backed line items) must send fine, and the PDF
                # must never contain repairs that aren't on this invoice.
                pdf_bytes, invoice_data = self.invoice_service.generate_invoice_from_record(invoice)
                if not invoice_data.line_items:
                    return False, "Invoice has no line items"
                repair_ids = list(
                    invoice.line_items.exclude(repair_id__isnull=True)
                    .values_list('repair_id', flat=True)
                )
                start_date = None
            else:
                # Generate a NEW invoice from completed repairs
                start_date = timezone.now() - timedelta(days=days) if not repair_ids else None
                pdf_bytes, invoice_data = self.invoice_service.generate_invoice(
                    customer_id=customer_id,
                    repair_ids=repair_ids,
                    start_date=start_date,
                    invoice_number=invoice_number,
                    invoice_date=invoice_date,
                )

                if not invoice_data.line_items:
                    return False, "No completed repairs found for invoicing"

            # Get repairs for photo attachments. In the existing-invoice path,
            # only the invoice's own repair-backed line items may contribute
            # photos — with no repair line items there are no photos (never
            # fall back to an unbounded repair query here).
            photos = []
            if include_photos and (invoice is None or repair_ids):
                repairs = self.invoice_service.get_completed_repairs(
                    customer_id=customer_id,
                    repair_ids=repair_ids,
                    start_date=start_date
                )
                photos = self._get_photo_attachments(list(repairs))
            
            # Resolve the invoice record — needed for BOTH the public view
            # link (always included when we know the record) and the Stripe
            # payment link (gated on the tenant accepting payments).
            invoice_record = None
            try:
                from apps.billing.models import InvoiceLineItem, Invoice

                if invoice is not None:
                    # Existing-record path: this IS the invoice being sent.
                    invoice_record = invoice
                elif repair_ids:
                    line_qs = InvoiceLineItem.objects.all()
                    if self.tenant:
                        line_qs = line_qs.filter(invoice__tenant=self.tenant)
                    line_item = line_qs.filter(
                        repair_id__in=repair_ids,
                        invoice__status__in=['DRAFT', 'SENT', 'PARTIAL'], invoice__deleted_at__isnull=True,
                    ).select_related('invoice').first()
                    if line_item:
                        invoice_record = line_item.invoice
                else:
                    inv_qs = Invoice.objects.filter(
                        customer_id=customer_id,
                        status__in=['SENT', 'PARTIAL'],
                    )
                    if self.tenant:
                        inv_qs = inv_qs.filter(tenant=self.tenant)
                    invoice_record = inv_qs.order_by('-created_at').first()
            except Exception:
                pass

            # Public view link — invoice summary page, NOT Stripe checkout.
            view_link = None
            if invoice_record:
                try:
                    view_link = self._public_view_link(invoice_record.id)
                except Exception as e:
                    logger.warning(f"Could not generate view URL: {e}")

            # Stripe payment link — only when the tenant can take payments.
            payment_link = None
            tenant_can_pay = (
                self.tenant and self.tenant.can_accept_payments
            ) if self.tenant else False

            if tenant_can_pay and invoice_record:
                # Public payment URL (HMAC-token based, no login needed).
                # Redirects to Stripe Checkout if available, or shows a
                # fallback page with contact info.
                try:
                    from rs_systems.views import generate_payment_token
                    base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
                    token = generate_payment_token(invoice_record.id)
                    payment_link = f"{base_url}/pay/{invoice_record.id}/{token}/"
                except Exception as e:
                    logger.warning(f"Could not generate payment URL: {e}")
            
            # Loyalty balance line — one short factual sentence, or None.
            # Gated inside get_email_balance_line (program active + shop
            # toggle + positive balance). Never let loyalty break invoicing.
            points_line = None
            try:
                from core.models import Customer as CoreCustomer
                from apps.rewards_referrals.services import LoyaltyService
                _cust = CoreCustomer.objects.filter(pk=customer_id).first()
                if _cust:
                    points_line = LoyaltyService.get_email_balance_line(_cust)
            except Exception:
                points_line = None

            # Build email — use shop-defined template if configured (CODE-119)
            # Subject carries the SHOP's name, not the platform's — customers
            # know their glass shop, not RS Systems. No bracketed tag: [Shop]
            # prefixes read as bulk mail to corporate spam filters.
            if subject_prefix == "[RS Systems]":
                shop = self.tenant.name if self.tenant else "RS Systems"
                subject = f"Invoice {invoice_data.invoice_number} from {shop}"
            else:
                subject = f"{subject_prefix} Invoice {invoice_data.invoice_number} - {invoice_data.customer_name}"
            body = ''
            if self.tenant:
                try:
                    from apps.billing.models import BillingConfig
                    cfg = BillingConfig.get_for_tenant(self.tenant)
                    if cfg.invoice_email_template:
                        body = self._render_invoice_template(
                            cfg.invoice_email_template, invoice_data,
                            points_line=points_line,
                        )
                except Exception:
                    pass
            if not body:
                body = self._build_email_body(
                    invoice_data, include_photos=len(photos) > 0,
                    payment_link=payment_link, view_link=view_link,
                    points_line=points_line,
                )

            # Build HTML version of the email
            html_body = self._build_html_email(invoice_data, payment_link=payment_link,
                                                include_photos=len(photos) > 0,
                                                view_link=view_link,
                                                points_line=points_line)

            from core.email_utils import shop_sender
            from_email, reply_to = shop_sender(
                shop_name=self.tenant.name if self.tenant else None,
                reply_to_email=self.tenant.business_email if self.tenant else '',
            )
            # SES message tag: echoed back in configuration-set event
            # payloads (mail.tags) so the SES webhook can attribute
            # Delivery/Bounce events to this exact invoice.
            headers = {}
            if invoice_record:
                headers['X-SES-MESSAGE-TAGS'] = f'rs_invoice_id={invoice_record.id}'
            email = EmailMultiAlternatives(
                subject=subject,
                body=body,  # plain text fallback
                from_email=from_email,
                to=[recipient_email],
                cc=cc_emails or [],
                bcc=bcc_emails or [],
                reply_to=reply_to,
                headers=headers or None,
            )
            email.attach_alternative(html_body, 'text/html')
            
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
    
    def _build_html_email(self, invoice_data, payment_link=None, include_photos=False,
                          view_link=None, points_line=None) -> str:
        """Build an HTML email with clickable buttons.

        "View Invoice Online" goes to the public invoice VIEW page; only the
        "Pay Invoice" button goes to the payment URL (the two used to share
        the /pay/ URL, so both buttons dumped the customer into Stripe).

        No open-tracking pixel: security gateways (Microsoft Defender etc.)
        prefetch remote images while scanning, producing phantom "viewed"
        events, and a remote 1x1 image is itself a spam-filter signal.
        Delivery is tracked via SES events; views via the invoice page.
        """
        invoice_id = getattr(invoice_data, 'id', None) or getattr(invoice_data, 'pk', None)
        if view_link:
            portal_url = view_link
        elif invoice_id:
            try:
                portal_url = self._public_view_link(invoice_id)
            except Exception:
                _fb_base = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
                portal_url = f"{_fb_base}/app/invoices/{invoice_id}/"
        else:
            _fb_base = getattr(settings, 'BASE_URL', 'https://rssystems.io').rstrip('/')
            portal_url = f"{_fb_base}/app/invoices/"

        # Company info — escape all user-controlled strings before embedding in HTML
        # (CODE-232: XSS in invoice email HTML body)
        company_name = html.escape('RS Systems')
        company_address = ''
        company_phone = ''
        if self.tenant:
            company_name = html.escape(self.tenant.name or 'RS Systems')
            company_address = html.escape(self.tenant.business_address or '')
            company_phone = html.escape(self.tenant.business_phone or '')

        # Line items HTML
        items_html = ''
        for item in invoice_data.line_items:
            unit_esc = html.escape(str(item.unit_number))
            damage_esc = html.escape(str(item.damage_type))
            items_html += f'''
            <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;color:#374151;">Unit {unit_esc}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;color:#374151;">{damage_esc}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;color:#374151;text-align:right;">${item.final_cost:.2f}</td>
            </tr>'''

        # Tax info
        tax_html = ''
        if hasattr(invoice_data, 'tax_amount') and invoice_data.tax_amount > 0:
            rate_display = f"{invoice_data.tax_rate:.3f}".rstrip('0').rstrip('.')
            tax_html = f'''
            <tr>
                <td colspan="2" style="padding:6px 12px;font-size:14px;color:#6b7280;text-align:right;">Tax ({rate_display}%)</td>
                <td style="padding:6px 12px;font-size:14px;color:#374151;text-align:right;">${invoice_data.tax_amount:.2f}</td>
            </tr>'''

        # Discount info
        discount_html = ''
        if invoice_data.total_discount > 0:
            discount_html = f'''
            <tr>
                <td colspan="2" style="padding:6px 12px;font-size:14px;color:#059669;text-align:right;">Discount</td>
                <td style="padding:6px 12px;font-size:14px;color:#059669;text-align:right;">-${invoice_data.total_discount:.2f}</td>
            </tr>'''

        # Loyalty balance — one quiet factual line under the totals.
        points_html = ''
        if points_line:
            points_html = f'''
    <p style="font-size:13px;color:#6b7280;text-align:right;margin:0 0 16px;">{html.escape(points_line)}</p>'''

        # Payment button
        pay_button_html = ''
        if payment_link:
            pay_button_html = f'''
            <div style="text-align:center;margin:24px 0;">
                <a href="{payment_link}" style="display:inline-block;padding:14px 32px;background-color:#2563eb;color:#ffffff;text-decoration:none;font-size:16px;font-weight:600;border-radius:8px;">
                    Pay Invoice — ${invoice_data.total:.2f}
                </a>
            </div>'''

        # Escape remaining user-controlled values used in the HTML template
        cust_name_esc = html.escape(str(invoice_data.customer_name))
        inv_number_esc = html.escape(str(invoice_data.invoice_number))
        pay_terms_esc = html.escape(str(invoice_data.payment_terms_display))

        html_doc = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">

<!-- Header -->
<div style="background-color:#1e40af;padding:24px;border-radius:12px 12px 0 0;text-align:center;">
    <h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;">{company_name}</h1>
    <p style="margin:4px 0 0;color:#93c5fd;font-size:14px;">Invoice #{inv_number_esc}</p>
</div>

<!-- Body -->
<div style="background-color:#ffffff;padding:24px;border:1px solid #e5e7eb;border-top:none;">

    <p style="font-size:15px;color:#374151;margin:0 0 16px;">
        Hi {cust_name_esc},<br><br>
        Here's your invoice for {html.escape(self._service_phrase(invoice_data))}.
    </p>

    <!-- Invoice Details -->
    <div style="background-color:#f9fafb;border-radius:8px;padding:16px;margin-bottom:20px;">
        <table style="width:100%;font-size:14px;color:#6b7280;">
            <tr><td style="padding:4px 0;">Invoice #</td><td style="text-align:right;font-weight:600;color:#111827;">{inv_number_esc}</td></tr>
            <tr><td style="padding:4px 0;">Date</td><td style="text-align:right;">{invoice_data.invoice_date.strftime('%B %d, %Y')}</td></tr>
            <tr><td style="padding:4px 0;">Payment Terms</td><td style="text-align:right;">{pay_terms_esc}</td></tr>
        </table>
    </div>

    <!-- Line Items -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
        <tr style="background-color:#f3f4f6;">
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#6b7280;text-transform:uppercase;font-weight:600;">Unit</th>
            <th style="padding:10px 12px;text-align:left;font-size:12px;color:#6b7280;text-transform:uppercase;font-weight:600;">Service</th>
            <th style="padding:10px 12px;text-align:right;font-size:12px;color:#6b7280;text-transform:uppercase;font-weight:600;">Amount</th>
        </tr>
        {items_html}
        {discount_html}
        {tax_html}
        <tr style="background-color:#eff6ff;">
            <td colspan="2" style="padding:12px;font-size:16px;font-weight:700;color:#1e40af;text-align:right;">Total Due</td>
            <td style="padding:12px;font-size:16px;font-weight:700;color:#1e40af;text-align:right;">${invoice_data.total:.2f}</td>
        </tr>
    </table>
    {points_html}
    {pay_button_html}

    <!-- View Online Link -->
    <div style="text-align:center;margin:16px 0;">
        <a href="{portal_url}" style="display:inline-block;padding:10px 24px;background-color:#ffffff;color:#2563eb;text-decoration:none;font-size:14px;font-weight:500;border:2px solid #2563eb;border-radius:8px;">
            View Invoice Online
        </a>
    </div>

    <p style="font-size:13px;color:#9ca3af;text-align:center;margin:20px 0 0;">
        A PDF copy of this invoice is attached to this email.
    </p>
</div>

<!-- Footer -->
<div style="padding:16px 24px;text-align:center;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;background-color:#f9fafb;">
    <p style="margin:0;font-size:13px;color:#6b7280;font-weight:600;">{company_name}</p>
    {"<p style='margin:4px 0 0;font-size:12px;color:#9ca3af;'>" + company_address + "</p>" if company_address else ""}
    {"<p style='margin:4px 0 0;font-size:12px;color:#9ca3af;'>" + company_phone + "</p>" if company_phone else ""}
</div>

</div>
</body>
</html>'''
        return html_doc

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
    include_photos: bool = False
) -> Tuple[bool, str]:
    """Send an invoice email to a customer"""
    service = InvoiceEmailService()
    return service.send_invoice_email(
        customer_id=customer_id,
        recipient_email=recipient_email,
        days=days,
        include_photos=include_photos
    )
