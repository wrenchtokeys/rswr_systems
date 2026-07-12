"""
Invoice Generation Service for RS Systems

Generates PDF invoices from repair data, including:
- Customer and repair details
- Company logo from EmailBrandingConfig
- Pricing with discounts applied
- Batch and single-repair invoice support

Author: Amelia (Clawdbot AI)
Created: 2026-01-27
Updated: 2026-01-27 - Royal blue styling, logo support
"""

import io
import logging
import os
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)
from dataclasses import dataclass

from django.conf import settings
from django.db.models import QuerySet, Sum
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

from PIL import Image

from core.models import Customer
from apps.technician_portal.models import Repair, Replacement


# Royal Blue color for better readability
ROYAL_BLUE = "#4169E1"
LIGHT_BLUE = "#E8F0FE"


@dataclass
class InvoiceLineItem:
    """Single line item on an invoice"""
    repair_id: int
    unit_number: str
    damage_type: str
    repair_date: datetime
    description: str
    original_cost: Decimal
    final_cost: Decimal
    discount_description: str
    has_photos: bool
    before_photo_url: Optional[str] = None
    after_photo_url: Optional[str] = None
    repair_obj: object = None


@dataclass
class InvoiceData:
    """Complete invoice data structure"""
    invoice_number: str
    invoice_date: datetime
    customer_name: str
    customer_email: Optional[str]
    customer_address: Optional[str]
    line_items: List[InvoiceLineItem]
    subtotal: Decimal
    total_discount: Decimal
    total: Decimal
    description: str = ""
    notes: str = ""
    payment_terms: str = "COD"
    payment_terms_display: str = "Cash on Delivery (COD)"
    tax_rate: Decimal = Decimal('0.000')
    state_tax_rate: Decimal = Decimal('0.000')
    county_tax_rate: Decimal = Decimal('0.000')
    city_tax_rate: Decimal = Decimal('0.000')
    special_tax_rate: Decimal = Decimal('0.000')
    tax_amount: Decimal = Decimal('0.00')


class InvoiceService:
    """
    Service for generating invoices from RS Systems repair data.
    
    Usage:
        service = InvoiceService()
        
        # Generate invoice for specific repairs
        pdf_bytes = service.generate_invoice(
            customer_id=1,
            repair_ids=[1, 2, 3]
        )
        
        # Generate invoice for date range
        pdf_bytes = service.generate_invoice_for_period(
            customer_id=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31)
        )
    """
    
    def __init__(self, tenant=None):
        self.tenant = tenant
        # Load company info from EmailBrandingConfig
        self._load_branding_config()
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _load_branding_config(self):
        """
        Load company info from BillingConfig first, then EmailBrandingConfig
        for colors/logo. BillingConfig is the source of truth for address
        and payment terms on invoices.
        """
        self.logo_path = None
        self.DEFAULT_PAYMENT_TERMS = 'COD'
        self.INVOICE_FOOTER = 'Thank you for your business!'
        
        # --- BillingConfig (address + payment terms) ---
        try:
            from apps.billing.models import BillingConfig
            billing_cfg = BillingConfig.get_for_tenant(self.tenant) if self.tenant else None
            if billing_cfg is None:
                raise ValueError("No tenant available")
            self.COMPANY_NAME = billing_cfg.company_name or (self.tenant.name if self.tenant else "")
            self.COMPANY_ADDRESS = billing_cfg.full_address or (self.tenant.business_address if self.tenant else "")
            self.COMPANY_PHONE = billing_cfg.company_phone or (self.tenant.business_phone if self.tenant else "")
            self.COMPANY_EMAIL = billing_cfg.company_email or (self.tenant.business_email if self.tenant else "")
            self.COMPANY_WEBSITE = billing_cfg.company_website or ""
            self.DEFAULT_PAYMENT_TERMS = billing_cfg.default_payment_terms
            self.DEFAULT_DUE_DAYS = billing_cfg.due_days_for_terms
            self.INVOICE_FOOTER = billing_cfg.invoice_footer_note or 'Thank you for your business!'
            self.INVOICE_PREFIX = billing_cfg.invoice_number_prefix or 'INV'
        except Exception as e:
            print(f"Could not load billing config: {e}")
            self.COMPANY_NAME = self.tenant.name if self.tenant else ""
            self.COMPANY_ADDRESS = ""
            self.COMPANY_PHONE = ""
            self.COMPANY_EMAIL = ""
            self.COMPANY_WEBSITE = ""
            self.DEFAULT_DUE_DAYS = 0
            self.INVOICE_PREFIX = 'INV'
        
        # --- EmailBrandingConfig (colors + logo) ---
        try:
            from core.models.email_branding import EmailBrandingConfig
            config = EmailBrandingConfig.get_instance()
            
            # Colors - use secondary color for headers (more readable)
            self.HEADER_COLOR = config.secondary_color or ROYAL_BLUE
            self.PRIMARY_COLOR = config.primary_color or "#2C5282"
            
            # Logo - get URL (works for both local and S3 storage)
            if config.logo:
                try:
                    self.logo_url = config.logo.url
                except Exception as e:
                    print(f"Could not load logo URL: {e}")
                    
        except Exception as e:
            print(f"Could not load email branding config: {e}")
            self.HEADER_COLOR = ROYAL_BLUE
            self.PRIMARY_COLOR = "#2C5282"
    
    def _get_logo_for_pdf(self, max_width=3*inch, max_height=1.2*inch):
        """
        Get logo as a ReportLab Image object, properly sized.
        Supports local files and S3/remote URLs.
        
        Returns:
            RLImage or None if no logo available
        """
        import tempfile
        
        if not hasattr(self, 'logo_path') and not hasattr(self, 'logo_url'):
            return None
            
        try:
            img = None
            
            # Try local path first
            if hasattr(self, 'logo_path') and self.logo_path and os.path.exists(self.logo_path):
                img = RLImage(self.logo_path)
            elif hasattr(self, 'logo_url') and self.logo_url:
                url = self.logo_url
                
                # Make sure we have a full URL
                if url.startswith('//'):
                    url = 'https:' + url
                elif not url.startswith('http'):
                    # Try to build full URL from S3 settings
                    s3_domain = getattr(settings, 'AWS_S3_CUSTOM_DOMAIN', None)
                    if s3_domain:
                        url = f'https://{s3_domain}/{url.lstrip("/")}'
                    else:
                        # Local media URL — construct full path
                        media_root = getattr(settings, 'MEDIA_ROOT', '')
                        full_path = os.path.join(media_root, url.lstrip('/media/'))
                        if os.path.exists(full_path):
                            img = RLImage(full_path)
                
                # Download from URL if we haven't loaded yet
                if img is None and url.startswith('http'):
                    tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    try:
                        urllib.request.urlretrieve(url, tmp.name)
                        img = RLImage(tmp.name)
                    finally:
                        tmp.close()
            
            if img is None:
                return None
            
            # Calculate aspect ratio and size
            aspect = img.imageWidth / img.imageHeight
            if aspect > (max_width / max_height):
                # Width-constrained
                img.drawWidth = max_width
                img.drawHeight = max_width / aspect
            else:
                # Height-constrained
                img.drawHeight = max_height
                img.drawWidth = max_height * aspect
                
            return img
            
        except Exception as e:
            print(f"Error loading logo for PDF: {e}")
            return None
    
    def _setup_custom_styles(self):
        """Set up custom paragraph styles for the invoice"""
        self.styles.add(ParagraphStyle(
            name='InvoiceTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            spaceAfter=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor(self.PRIMARY_COLOR)
        ))
        
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=14,
            spaceBefore=20,
            spaceAfter=10,
            textColor=colors.HexColor(self.PRIMARY_COLOR)
        ))
        
        self.styles.add(ParagraphStyle(
            name='CompanyInfo',
            parent=self.styles['Normal'],
            fontSize=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#4a4a4a')
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomerInfo',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceBefore=5,
            spaceAfter=5
        ))
        
        self.styles.add(ParagraphStyle(
            name='TotalAmount',
            parent=self.styles['Normal'],
            fontSize=16,
            fontName='Helvetica-Bold',
            alignment=TA_RIGHT,
            textColor=colors.HexColor(self.PRIMARY_COLOR)
        ))
        
        # White text style for table headers
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=10,
            fontName='Helvetica-Bold',
            textColor=colors.white
        ))
    
    def get_completed_repairs(
        self,
        customer_id: int,
        repair_ids: Optional[List[int]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> QuerySet:
        """
        Get completed repairs for invoicing.
        
        Args:
            customer_id: Customer ID to filter by
            repair_ids: Optional specific repair IDs to include
            start_date: Optional start date filter
            end_date: Optional end date filter
            
        Returns:
            QuerySet of Repair objects
        """
        queryset = Repair.objects.filter(
            customer_id=customer_id,
            queue_status='COMPLETED'
        )
        if self.tenant:
            queryset = queryset.filter(tenant=self.tenant)
        queryset = queryset.select_related('customer', 'technician', 'technician__user', 'warranty_policy')
        
        if repair_ids:
            queryset = queryset.filter(id__in=repair_ids)
        
        if start_date:
            queryset = queryset.filter(service_date__gte=start_date)
        
        if end_date:
            queryset = queryset.filter(service_date__lte=end_date)
        
        return queryset.order_by('service_date')
    
    def _build_line_item(self, repair: Repair) -> InvoiceLineItem:
        """Convert a Repair object to an InvoiceLineItem"""
        discounted = repair.get_discounted_cost()
        
        # Combine all notes into description
        description_parts = []
        if repair.description:
            description_parts.append(repair.description)
        if repair.technician_notes:
            description_parts.append(repair.technician_notes)
        if repair.customer_notes:
            description_parts.append(f"Customer: {repair.customer_notes}")
        
        full_description = ' | '.join(description_parts) if description_parts else ''
        
        return InvoiceLineItem(
            repair_id=repair.id,
            unit_number=repair.unit_number,
            damage_type=repair.get_damage_type_display() or 'Repair',
            repair_date=repair.repair_date,
            description=full_description,
            original_cost=discounted['original_cost'],
            final_cost=discounted['final_cost'],
            discount_description=discounted['discount_description'] if discounted['discount_applied'] else '',
            has_photos=repair.has_photos(),
            before_photo_url=repair.damage_photo_before.url if repair.damage_photo_before else None,
            after_photo_url=repair.damage_photo_after.url if repair.damage_photo_after else None,
            repair_obj=repair,
        )
    
    def _generate_invoice_number(self, customer_id: int) -> str:
        """Generate a unique invoice number using configurable prefix"""
        prefix = getattr(self, 'INVOICE_PREFIX', 'INV')
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        return f"{prefix}-{customer_id}-{timestamp}"
    
    def build_invoice_data(
        self,
        customer_id: int,
        repair_ids: Optional[List[int]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        invoice_description: str = "",
        invoice_number: Optional[str] = None,
        invoice_date: Optional[datetime] = None,
    ) -> InvoiceData:
        """
        Build complete invoice data structure from repairs.
        
        Args:
            customer_id: Customer to invoice
            repair_ids: Optional specific repairs to include
            start_date: Optional date range start
            end_date: Optional date range end
            invoice_number: Override invoice number (use stored value when re-generating PDF
                for an existing invoice so the number in the PDF matches records).
            invoice_date: Override invoice date (use stored value when re-generating PDF).
            
        Returns:
            InvoiceData object ready for PDF generation
        """
        # Get customer (tenant-scoped when available)
        if self.tenant:
            customer = Customer.objects.filter(tenant=self.tenant).get(id=customer_id)
        else:
            customer = Customer.objects.get(id=customer_id)
        
        # Get repairs
        repairs = self.get_completed_repairs(
            customer_id=customer_id,
            repair_ids=repair_ids,
            start_date=start_date,
            end_date=end_date
        )
        
        # Build line items
        line_items = [self._build_line_item(r) for r in repairs]
        
        # Calculate totals
        subtotal = sum(item.original_cost for item in line_items)
        total = sum(item.final_cost for item in line_items)
        total_discount = subtotal - total
        
        # Build address string
        address_parts = []
        if customer.address:
            address_parts.append(customer.address)
        if customer.city:
            city_state_zip = customer.city
            if customer.state:
                city_state_zip += f", {customer.state}"
            if customer.zip_code:
                city_state_zip += f" {customer.zip_code}"
            address_parts.append(city_state_zip)
        
        # Calculate tax (if enabled)
        tax_rate = Decimal('0.000')
        state_tax_rate = Decimal('0.000')
        county_tax_rate = Decimal('0.000')
        city_tax_rate = Decimal('0.000')
        special_tax_rate = Decimal('0.000')
        tax_amount = Decimal('0.00')
        try:
            from apps.billing.services.tax_service import TaxService
            tax_svc = TaxService(tenant=getattr(customer, 'tenant', None))
            tax_result = tax_svc.calculate_tax(
                subtotal=total,  # tax on post-discount amount
                customer=customer,
            )
            tax_rate = tax_result['rate']
            state_tax_rate = tax_result['state_rate']
            county_tax_rate = tax_result['county_rate']
            city_tax_rate = tax_result['city_rate']
            special_tax_rate = tax_result['special_rate']
            tax_amount = tax_result['amount']
        except Exception as e:
            import logging, traceback
            logging.getLogger(__name__).error(f"TAX CALCULATION FAILED in PDF: {e}\n{traceback.format_exc()}")

        total_with_tax = total + tax_amount

        # Get payment terms (from BillingConfig defaults)
        payment_terms = getattr(self, 'DEFAULT_PAYMENT_TERMS', 'COD')
        terms_display_map = {
            'COD': 'Cash on Delivery (COD)',
            'DUE_ON_RECEIPT': 'Due on Receipt',
            'NET15': 'Net 15',
            'NET30': 'Net 30',
            'NET45': 'Net 45',
            'NET60': 'Net 60',
        }
        
        # Use caller-supplied values when re-generating a PDF for an existing invoice
        # so the number and date in the PDF match the stored Invoice record.
        # Without this, every PDF download shows a brand-new number like
        # INV-5-20260321123456 instead of the original INV-5-20260101080000.
        resolved_invoice_number = invoice_number or self._generate_invoice_number(customer_id)
        resolved_invoice_date = invoice_date if invoice_date is not None else timezone.now()

        return InvoiceData(
            invoice_number=resolved_invoice_number,
            invoice_date=resolved_invoice_date,
            customer_name=customer.name,  # Preserve original casing
            customer_email=customer.email,
            customer_address='\n'.join(address_parts) if address_parts else None,
            line_items=line_items,
            subtotal=subtotal,
            total_discount=total_discount,
            total=total_with_tax,
            description=invoice_description,
            tax_rate=tax_rate,
            state_tax_rate=state_tax_rate,
            county_tax_rate=county_tax_rate,
            city_tax_rate=city_tax_rate,
            special_tax_rate=special_tax_rate,
            tax_amount=tax_amount,
            payment_terms=payment_terms,
            payment_terms_display=terms_display_map.get(payment_terms, payment_terms),
        )
    
    def build_invoice_data_from_record(self, invoice) -> InvoiceData:
        """
        Build InvoiceData from an existing Invoice model record — its OWN
        line items and STORED totals — never by re-querying repairs.

        This is the correct source when re-rendering a PDF for an invoice
        that already exists (owner "Send Invoice", overdue reminders).
        The repair-lookback path in build_invoice_data() is only for
        GENERATING a new invoice. Rendering an existing invoice from a
        repair query produced two failure modes (A4/A5): replacement-only
        invoices could never send ("no completed repairs found"), or the
        emailed PDF contained unrelated repairs at recomputed totals.
        """
        customer = invoice.customer

        line_items = []
        for li in invoice.line_items.select_related('repair').all():
            repair = li.repair
            if repair is not None:
                damage_type = repair.get_damage_type_display() or 'Repair'
            elif li.replacement_id:
                damage_type = 'Replacement'
            else:
                damage_type = 'Service'

            unit_price = li.unit_price if li.unit_price is not None else Decimal('0.00')
            original_cost = unit_price * li.quantity
            discount = li.discount or Decimal('0.00')

            line_items.append(InvoiceLineItem(
                repair_id=li.repair_id,
                unit_number=li.unit_number or (repair.unit_number if repair else ''),
                damage_type=damage_type,
                # li.repair_date is nullable; the PDF renderer strftime()s it
                repair_date=li.repair_date or invoice.invoice_date,
                description=li.description or '',
                original_cost=original_cost,
                final_cost=li.amount if li.amount is not None else original_cost - discount,
                discount_description=f'Discount ${discount}' if discount else '',
                has_photos=bool(repair and repair.has_photos()),
                before_photo_url=(
                    repair.damage_photo_before.url
                    if repair and repair.damage_photo_before else None
                ),
                after_photo_url=(
                    repair.damage_photo_after.url
                    if repair and repair.damage_photo_after else None
                ),
                repair_obj=repair,
            ))

        # Address block — same formatting as build_invoice_data()
        address_parts = []
        if customer.address:
            address_parts.append(customer.address)
        if customer.city:
            city_state_zip = customer.city
            if customer.state:
                city_state_zip += f", {customer.state}"
            if customer.zip_code:
                city_state_zip += f" {customer.zip_code}"
            address_parts.append(city_state_zip)

        payment_terms = invoice.payment_terms or getattr(self, 'DEFAULT_PAYMENT_TERMS', 'COD')
        terms_display_map = {
            'COD': 'Cash on Delivery (COD)',
            'DUE_ON_RECEIPT': 'Due on Receipt',
            'NET15': 'Net 15',
            'NET30': 'Net 30',
            'NET45': 'Net 45',
            'NET60': 'Net 60',
        }

        return InvoiceData(
            invoice_number=invoice.invoice_number,
            invoice_date=invoice.invoice_date,
            customer_name=customer.name,
            customer_email=customer.email,
            customer_address='\n'.join(address_parts) if address_parts else None,
            line_items=line_items,
            subtotal=invoice.subtotal,
            total_discount=invoice.discount,
            total=invoice.total,
            description=invoice.description or '',
            notes=invoice.notes or '',
            tax_rate=invoice.tax_rate,
            state_tax_rate=invoice.state_tax_rate,
            county_tax_rate=invoice.county_tax_rate,
            city_tax_rate=invoice.city_tax_rate,
            special_tax_rate=invoice.special_tax_rate,
            tax_amount=invoice.tax_amount,
            payment_terms=payment_terms,
            payment_terms_display=terms_display_map.get(payment_terms, payment_terms),
        )

    def generate_invoice_from_record(
        self,
        invoice,
        include_photos: bool = False,
    ) -> Tuple[bytes, InvoiceData]:
        """
        Render an existing Invoice record to PDF from its own line items.

        Returns (pdf_bytes, invoice_data). The invoice's stored status drives
        the watermark (PAID/OVERDUE/CANCELLED stamp; DRAFT/SENT get none).
        """
        invoice_data = self.build_invoice_data_from_record(invoice)
        pdf_bytes = self.generate_pdf(
            invoice_data,
            include_photos=include_photos,
            invoice_status=invoice.status,
        )
        return pdf_bytes, invoice_data

    def _apply_watermark(self, pdf_buffer, status_text, color_hex, diagonal=True):
        """Overlay a watermark ON TOP of an existing PDF."""
        from reportlab.lib import colors as rl_colors
        from reportlab.pdfgen import canvas as rl_canvas
        try:
            from PyPDF2 import PdfReader, PdfWriter
        except ImportError:
            # PyPDF2 not available — fall back to no watermark
            logger.warning("PyPDF2 not installed — cannot apply watermark")
            return pdf_buffer

        # Create watermark PDF
        watermark_buffer = io.BytesIO()
        c = rl_canvas.Canvas(watermark_buffer, pagesize=letter)
        stamp_color = rl_colors.HexColor(color_hex)

        if diagonal:
            c.saveState()
            c.translate(letter[0] / 2, letter[1] / 2)
            c.rotate(45)
            c.setFont('Helvetica-Bold', 120)
            c.setFillColor(rl_colors.Color(
                stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.25
            ))
            c.drawCentredString(0, 0, status_text)
            c.restoreState()
        else:
            # Top-right corner badge
            badge_w, badge_h = 120, 28
            x = letter[0] - badge_w - 36
            y = letter[1] - badge_h - 36
            c.saveState()
            c.setFillColor(rl_colors.Color(
                stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.12
            ))
            c.roundRect(x, y, badge_w, badge_h, 6, fill=1, stroke=0)
            c.setStrokeColor(rl_colors.Color(
                stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.4
            ))
            c.setLineWidth(1)
            c.roundRect(x, y, badge_w, badge_h, 6, fill=0, stroke=1)
            c.setFont('Helvetica-Bold', 14)
            c.setFillColor(rl_colors.Color(
                stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.7
            ))
            c.drawCentredString(x + badge_w / 2, y + 8, status_text)
            c.restoreState()

        c.save()
        watermark_buffer.seek(0)

        # Merge watermark on top of each page
        reader = PdfReader(pdf_buffer)
        watermark_reader = PdfReader(watermark_buffer)
        watermark_page = watermark_reader.pages[0]
        writer = PdfWriter()

        for page in reader.pages:
            page.merge_page(watermark_page)
            writer.add_page(page)

        output = io.BytesIO()
        writer.write(output)
        return output

    def _make_status_stamp_callback(self, status_text, color_hex, diagonal=True):
        """Create an onPage callback that draws a watermark stamp.
        
        Args:
            status_text: Text to display (e.g. 'PAID', 'VOID', 'OVERDUE')
            color_hex: Color for the stamp
            diagonal: If True, draw at 45° across the page. If False, draw as
                a subtle banner at the top right corner.
        """
        from reportlab.lib import colors as rl_colors

        def _stamp(canvas, doc):
            if not status_text:
                return
            canvas.saveState()
            stamp_color = rl_colors.HexColor(color_hex)

            if diagonal:
                # Big diagonal watermark (PAID, VOID) — drawn OVER content
                canvas.translate(letter[0] / 2, letter[1] / 2)
                canvas.rotate(45)
                canvas.setFont('Helvetica-Bold', 120)
                canvas.setFillColor(rl_colors.Color(
                    stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.25
                ))
                canvas.drawCentredString(0, 0, status_text)
            else:
                # Top-right corner badge (OVERDUE — visible but not aggressive)
                badge_w, badge_h = 120, 28
                x = letter[0] - badge_w - 36  # 0.5" from right edge
                y = letter[1] - badge_h - 36  # 0.5" from top
                # Background pill
                canvas.setFillColor(rl_colors.Color(
                    stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.12
                ))
                canvas.roundRect(x, y, badge_w, badge_h, 6, fill=1, stroke=0)
                # Border
                canvas.setStrokeColor(rl_colors.Color(
                    stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.4
                ))
                canvas.setLineWidth(1)
                canvas.roundRect(x, y, badge_w, badge_h, 6, fill=0, stroke=1)
                # Text
                canvas.setFont('Helvetica-Bold', 14)
                canvas.setFillColor(rl_colors.Color(
                    stamp_color.red, stamp_color.green, stamp_color.blue, alpha=0.7
                ))
                canvas.drawCentredString(x + badge_w / 2, y + 8, status_text)

            canvas.restoreState()

        return _stamp

    def generate_pdf(self, invoice_data: InvoiceData, include_photos: bool = True,
                     invoice_status: str = '') -> bytes:
        """
        Generate PDF invoice from InvoiceData.
        
        Args:
            invoice_data: Complete invoice data
            include_photos: Whether to include repair photos
            invoice_status: Optional invoice status (PAID, OVERDUE, CANCELLED)
                to stamp on the PDF as a diagonal watermark.
            
        Returns:
            PDF file as bytes
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        story = []
        
        # Header: Logo + Company Name side by side
        logo = self._get_logo_for_pdf(max_width=1.5*inch, max_height=1*inch)
        
        # Build company info block (stacked vertically)
        company_info_parts = [f"<b>{self.COMPANY_NAME}</b>"]
        if self.COMPANY_ADDRESS:
            # Split address into lines if it contains commas or newlines
            addr = self.COMPANY_ADDRESS.replace('\n', '<br/>')
            company_info_parts.append(addr)
        if self.COMPANY_PHONE:
            company_info_parts.append(self.COMPANY_PHONE)
        if self.COMPANY_EMAIL:
            company_info_parts.append(self.COMPANY_EMAIL)
        if self.COMPANY_WEBSITE:
            company_info_parts.append(self.COMPANY_WEBSITE)
        
        company_info_text = '<br/>'.join(company_info_parts)
        company_info_para = Paragraph(company_info_text, self.styles['CompanyInfo'])
        
        if logo:
            # Logo on left, company info on right
            header_table = Table(
                [[logo, company_info_para]],
                colWidths=[1.8*inch, 5.2*inch]
            )
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(header_table)
        else:
            # No logo - just company info
            story.append(company_info_para)
        
        story.append(Spacer(1, 20))
        
        # INVOICE header
        story.append(Paragraph(
            "<b>INVOICE</b>",
            ParagraphStyle(
                name='InvoiceHeader',
                parent=self.styles['Heading1'],
                fontSize=18,
                alignment=TA_CENTER,
                textColor=colors.HexColor(self.HEADER_COLOR)
            )
        ))
        
        story.append(Spacer(1, 15))
        
        # Invoice Info and Customer Info side by side
        invoice_info = [
            [
                Paragraph(f"<b>Invoice #:</b> {invoice_data.invoice_number}", self.styles['Normal']),
                Paragraph(f"<b>Bill To:</b>", self.styles['Normal'])
            ],
            [
                Paragraph(f"<b>Date:</b> {invoice_data.invoice_date.strftime('%B %d, %Y')}", self.styles['Normal']),
                Paragraph(f"{invoice_data.customer_name}", self.styles['CustomerInfo'])
            ],
            [
                Paragraph(f"<b>Payment Terms:</b> {invoice_data.payment_terms_display}", self.styles['Normal']),
                Paragraph("", self.styles['Normal'])
            ],
        ]
        
        if invoice_data.customer_email:
            invoice_info[-1][1] = Paragraph(f"{invoice_data.customer_email}", self.styles['CustomerInfo'])
        
        if invoice_data.customer_address:
            invoice_info.append([
                Paragraph("", self.styles['Normal']),
                Paragraph(invoice_data.customer_address.replace('\n', '<br/>'), self.styles['CustomerInfo'])
            ])
        
        info_table = Table(invoice_info, colWidths=[3.5*inch, 3.5*inch])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 25))

        # Optional invoice-level description / summary
        if getattr(invoice_data, 'description', ''):
            story.append(Paragraph(
                invoice_data.description.replace('\n', '<br/>'),
                self.styles['Normal']
            ))
            story.append(Spacer(1, 15))

        # Line Items Table
        story.append(Paragraph("Repair Details", self.styles['SectionHeader']))
        
        # Table header - using royal blue background with white text
        header_style = self.styles['TableHeader']
        table_data = [[
            Paragraph("<b>Unit #</b>", header_style),
            Paragraph("<b>Date</b>", header_style),
            Paragraph("<b>Type</b>", header_style),
            Paragraph("<b>Description</b>", header_style),
            Paragraph("<b>Amount</b>", header_style)
        ]]
        
        # Table rows
        for item in invoice_data.line_items:
            amount_text = f"${item.final_cost:.2f}"
            if item.discount_description:
                amount_text = f"<strike>${item.original_cost:.2f}</strike><br/>${item.final_cost:.2f}<br/><font size='8'><i>({item.discount_description})</i></font>"
            
            # Show full description (notes included)
            desc_text = item.description if item.description else ''
            
            table_data.append([
                Paragraph(item.unit_number, self.styles['Normal']),
                Paragraph(item.repair_date.strftime('%m/%d/%y'), self.styles['Normal']),
                Paragraph(item.damage_type, self.styles['Normal']),
                Paragraph(desc_text, self.styles['Normal']),
                Paragraph(amount_text, self.styles['Normal'])
            ])
        
        # Create and style the table with ROYAL BLUE header
        line_items_table = Table(
            table_data,
            colWidths=[1*inch, 0.9*inch, 1.1*inch, 2.5*inch, 1*inch]
        )
        
        line_items_table.setStyle(TableStyle([
            # Header styling - ROYAL BLUE background with white text
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(self.HEADER_COLOR)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            
            # Alternating row colors - light blue / white
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor(LIGHT_BLUE)]),
            
            # Grid - light gray lines
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(self.HEADER_COLOR)),
            
            # Alignment
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),  # Amount column right-aligned
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(line_items_table)
        story.append(Spacer(1, 20))
        
        # Totals
        totals_data = []
        
        if invoice_data.total_discount > 0 or invoice_data.tax_amount > 0:
            totals_data.append([
                '',
                Paragraph("<b>Subtotal:</b>", self.styles['Normal']),
                Paragraph(f"${invoice_data.subtotal:.2f}", self.styles['Normal'])
            ])
        
        if invoice_data.total_discount > 0:
            totals_data.append([
                '',
                Paragraph("<b>Discounts:</b>", self.styles['Normal']),
                Paragraph(f"-${invoice_data.total_discount:.2f}", self.styles['Normal'])
            ])
        
        if invoice_data.tax_amount > 0:
            # Show component tax rates if breakdown is available
            has_breakdown = (
                invoice_data.state_tax_rate > 0 or
                invoice_data.county_tax_rate > 0 or
                invoice_data.city_tax_rate > 0 or
                invoice_data.special_tax_rate > 0
            )
            if has_breakdown:
                # Individual rate lines
                def _fmt_rate(r):
                    return f"{r:.3f}".rstrip('0').rstrip('.')

                if invoice_data.state_tax_rate > 0:
                    state_amt = (invoice_data.subtotal - invoice_data.total_discount) * invoice_data.state_tax_rate / Decimal('100')
                    state_amt = state_amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    totals_data.append([
                        '',
                        Paragraph(f"State Tax ({_fmt_rate(invoice_data.state_tax_rate)}%):", self.styles['Normal']),
                        Paragraph(f"${state_amt:.2f}", self.styles['Normal'])
                    ])
                if invoice_data.county_tax_rate > 0:
                    county_amt = (invoice_data.subtotal - invoice_data.total_discount) * invoice_data.county_tax_rate / Decimal('100')
                    county_amt = county_amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    totals_data.append([
                        '',
                        Paragraph(f"County Tax ({_fmt_rate(invoice_data.county_tax_rate)}%):", self.styles['Normal']),
                        Paragraph(f"${county_amt:.2f}", self.styles['Normal'])
                    ])
                if invoice_data.city_tax_rate > 0:
                    city_amt = (invoice_data.subtotal - invoice_data.total_discount) * invoice_data.city_tax_rate / Decimal('100')
                    city_amt = city_amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    totals_data.append([
                        '',
                        Paragraph(f"City Tax ({_fmt_rate(invoice_data.city_tax_rate)}%):", self.styles['Normal']),
                        Paragraph(f"${city_amt:.2f}", self.styles['Normal'])
                    ])
                if invoice_data.special_tax_rate > 0:
                    special_amt = (invoice_data.subtotal - invoice_data.total_discount) * invoice_data.special_tax_rate / Decimal('100')
                    special_amt = special_amt.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    totals_data.append([
                        '',
                        Paragraph(f"Special Tax ({_fmt_rate(invoice_data.special_tax_rate)}%):", self.styles['Normal']),
                        Paragraph(f"${special_amt:.2f}", self.styles['Normal'])
                    ])
            else:
                # Fallback: single combined rate (when using default_tax_rate with no breakdown)
                rate_display = f"{invoice_data.tax_rate:.3f}".rstrip('0').rstrip('.')
                totals_data.append([
                    '',
                    Paragraph(f"<b>Tax ({rate_display}%):</b>", self.styles['Normal']),
                    Paragraph(f"${invoice_data.tax_amount:.2f}", self.styles['Normal'])
                ])
        
        totals_data.append([
            '',
            Paragraph("<b>TOTAL:</b>", self.styles['Normal']),
            Paragraph(f"<b>${invoice_data.total:.2f}</b>", self.styles['TotalAmount'])
        ])
        
        totals_table = Table(totals_data, colWidths=[4.5*inch, 1.5*inch, 1*inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('LINEABOVE', (1, -1), (-1, -1), 2, colors.HexColor(self.HEADER_COLOR)),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        
        story.append(totals_table)
        
        # Warranty Terms Section
        warranty_terms = []
        for item in invoice_data.line_items:
            if hasattr(item, 'repair_obj') and item.repair_obj and item.repair_obj.warranty_policy:
                policy = item.repair_obj.warranty_policy
                summary = getattr(policy, 'terms_summary', '')
                if summary:
                    warranty_terms.append(f"WARRANTY: {summary}")
                else:
                    term = f"Unit {item.unit_number}: {policy.name}"
                    if policy.duration_type == 'lifetime':
                        term += " \u2014 Lifetime Warranty"
                    elif policy.duration_type == 'custom_days':
                        term += f" \u2014 {policy.duration_days}-day Warranty"
                    if policy.coverage_description:
                        term += f" ({policy.coverage_description})"
                    warranty_terms.append(term)

        if warranty_terms:
            story.append(Spacer(1, 20))
            story.append(Paragraph(
                "<b>Warranty Terms</b>",
                ParagraphStyle(
                    name='WarrantyHeader',
                    parent=self.styles['Normal'],
                    fontSize=11,
                    textColor=colors.HexColor('#065f46'),
                )
            ))
            story.append(Spacer(1, 5))
            for term in warranty_terms:
                story.append(Paragraph(
                    f"\u26d1 {term}",
                    ParagraphStyle(
                        name='WarrantyTerm',
                        parent=self.styles['Normal'],
                        fontSize=9,
                        textColor=colors.HexColor('#374151'),
                        leftIndent=10,
                    )
                ))

        # Footer note (configurable via BillingConfig)
        footer_text = getattr(self, 'INVOICE_FOOTER', 'Thank you for your business!')
        story.append(Spacer(1, 40))
        story.append(Paragraph(
            footer_text,
            ParagraphStyle(
                name='ThankYou',
                parent=self.styles['Normal'],
                fontSize=12,
                alignment=TA_CENTER,
                textColor=colors.HexColor('#4a4a4a')
            )
        ))
        
        # Build PDF — add status watermark stamp if applicable
        # (label, color, diagonal?)
        stamp_map = {
            'PAID': ('PAID', '#22C55E', True),         # green diagonal
            'OVERDUE': ('OVERDUE', '#EF4444', False),   # red corner badge (not aggressive)
            'CANCELLED': ('VOID', '#991B1B', True),     # dark red diagonal
        }
        stamp_callback = None
        if invoice_status in stamp_map:
            label, color, diagonal = stamp_map[invoice_status]
            stamp_callback = self._make_status_stamp_callback(label, color, diagonal=diagonal)

        doc.build(story)

        # Apply watermark AFTER building — draws on top of content
        if invoice_status in stamp_map:
            label, color, diagonal = stamp_map[invoice_status]
            buffer.seek(0)
            buffer = self._apply_watermark(buffer, label, color, diagonal)
            buffer.seek(0)
        
        # Get the PDF bytes
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        return pdf_bytes
    
    def generate_invoice(
        self,
        customer_id: int,
        repair_ids: Optional[List[int]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        include_photos: bool = False,  # Photos disabled by default for now
        invoice_description: str = "",
        invoice_number: Optional[str] = None,
        invoice_date: Optional[datetime] = None,
        invoice_status: str = '',
    ) -> Tuple[bytes, InvoiceData]:
        """
        Generate a complete invoice PDF.
        
        Args:
            customer_id: Customer to invoice
            repair_ids: Optional specific repairs
            start_date: Optional date range start  
            end_date: Optional date range end
            include_photos: Whether to embed photos (increases file size)
            invoice_number: Override invoice number (pass the stored Invoice.invoice_number
                when re-generating a PDF for an existing invoice so the PDF content matches
                the number shown in the owner portal and emailed to the customer).
            invoice_date: Override invoice date (pass Invoice.invoice_date for same reason).
            
        Returns:
            Tuple of (PDF bytes, InvoiceData)
        """
        invoice_data = self.build_invoice_data(
            customer_id=customer_id,
            repair_ids=repair_ids,
            start_date=start_date,
            end_date=end_date,
            invoice_description=invoice_description,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
        )

        pdf_bytes = self.generate_pdf(invoice_data, include_photos=include_photos,
                                       invoice_status=invoice_status)
        
        return pdf_bytes, invoice_data


# Convenience functions
def generate_customer_invoice(
    customer_id: int,
    tenant=None,
    repair_ids: Optional[List[int]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Tuple[bytes, InvoiceData]:
    """Convenience function to generate an invoice.
    
    Args:
        tenant: Required. The Tenant instance to scope the invoice to.
                Without it, repairs are unscoped and branding info is blank.
    """
    if tenant is None:
        logger.warning("generate_customer_invoice called without tenant — invoice will lack company info")
    service = InvoiceService(tenant=tenant)
    return service.generate_invoice(
        customer_id=customer_id,
        repair_ids=repair_ids,
        start_date=start_date,
        end_date=end_date
    )


def get_invoiceable_repairs(customer_id: int, tenant=None) -> QuerySet:
    """Get all completed repairs that can be invoiced for a customer.
    
    Args:
        tenant: Required. The Tenant instance to scope queries to.
                Without it, repairs from ALL tenants may be returned.
    """
    if tenant is None:
        logger.warning("get_invoiceable_repairs called without tenant — results may be unscoped")
    service = InvoiceService(tenant=tenant)
    return service.get_completed_repairs(customer_id=customer_id)
