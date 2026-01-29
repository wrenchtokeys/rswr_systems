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
import os
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any, Tuple
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
    notes: str = ""


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
    
    def __init__(self):
        # Load company info from EmailBrandingConfig
        self._load_branding_config()
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _load_branding_config(self):
        """Load company info and logo from EmailBrandingConfig or use defaults"""
        self.logo_path = None
        
        try:
            from core.models.email_branding import EmailBrandingConfig
            config = EmailBrandingConfig.get_instance()
            self.COMPANY_NAME = config.company_name or "Rockstar Windshield Repair"
            self.COMPANY_ADDRESS = config.company_address or ""
            self.COMPANY_PHONE = config.support_phone or ""
            self.COMPANY_EMAIL = config.support_email or ""
            self.COMPANY_WEBSITE = config.website_url or ""
            
            # Colors - use secondary color for headers (more readable)
            self.HEADER_COLOR = config.secondary_color or ROYAL_BLUE
            self.PRIMARY_COLOR = config.primary_color or "#2C5282"
            
            # Logo - try to get the file path or URL
            if config.logo:
                try:
                    # Try local file path first
                    if hasattr(config.logo, 'path') and os.path.exists(config.logo.path):
                        self.logo_path = config.logo.path
                    else:
                        # Get URL for S3/remote storage
                        self.logo_url = config.logo.url
                except Exception as e:
                    print(f"Could not load logo path: {e}")
                    
        except Exception as e:
            # Fallback to defaults if config not available
            print(f"Could not load branding config: {e}")
            self.COMPANY_NAME = "Rockstar Windshield Repair"
            self.COMPANY_ADDRESS = ""
            self.COMPANY_PHONE = ""
            self.COMPANY_EMAIL = ""
            self.COMPANY_WEBSITE = ""
            self.HEADER_COLOR = ROYAL_BLUE
            self.PRIMARY_COLOR = "#2C5282"
    
    def _get_logo_for_pdf(self, max_width=3*inch, max_height=1.2*inch):
        """
        Get logo as a ReportLab Image object, properly sized.
        
        Returns:
            RLImage or None if no logo available
        """
        if not hasattr(self, 'logo_path') and not hasattr(self, 'logo_url'):
            return None
            
        try:
            # Try local path first
            if hasattr(self, 'logo_path') and self.logo_path and os.path.exists(self.logo_path):
                img = RLImage(self.logo_path)
            elif hasattr(self, 'logo_url') and self.logo_url:
                # Download from URL to temp file
                if self.logo_url.startswith('http'):
                    # Remote URL
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                        urllib.request.urlretrieve(self.logo_url, tmp.name)
                        img = RLImage(tmp.name)
                else:
                    # Local media URL - construct full path
                    media_root = getattr(settings, 'MEDIA_ROOT', '')
                    full_path = os.path.join(media_root, self.logo_url.lstrip('/media/'))
                    if os.path.exists(full_path):
                        img = RLImage(full_path)
                    else:
                        return None
            else:
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
        ).select_related('customer', 'technician', 'technician__user')
        
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
            after_photo_url=repair.damage_photo_after.url if repair.damage_photo_after else None
        )
    
    def _generate_invoice_number(self, customer_id: int) -> str:
        """Generate a unique invoice number"""
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        return f"INV-{customer_id}-{timestamp}"
    
    def build_invoice_data(
        self,
        customer_id: int,
        repair_ids: Optional[List[int]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> InvoiceData:
        """
        Build complete invoice data structure from repairs.
        
        Args:
            customer_id: Customer to invoice
            repair_ids: Optional specific repairs to include
            start_date: Optional date range start
            end_date: Optional date range end
            
        Returns:
            InvoiceData object ready for PDF generation
        """
        # Get customer
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
        
        return InvoiceData(
            invoice_number=self._generate_invoice_number(customer_id),
            invoice_date=timezone.now(),
            customer_name=customer.name.title(),  # Capitalize customer name
            customer_email=customer.email,
            customer_address='\n'.join(address_parts) if address_parts else None,
            line_items=line_items,
            subtotal=subtotal,
            total_discount=total_discount,
            total=total
        )
    
    def generate_pdf(self, invoice_data: InvoiceData, include_photos: bool = True) -> bytes:
        """
        Generate PDF invoice from InvoiceData.
        
        Args:
            invoice_data: Complete invoice data
            include_photos: Whether to include repair photos
            
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
        
        # Logo (if available)
        logo = self._get_logo_for_pdf()
        if logo:
            story.append(logo)
            story.append(Spacer(1, 10))
        
        # Header / Company Name (only if no logo, or as subtitle)
        if not logo:
            story.append(Paragraph(
                f"<b>{self.COMPANY_NAME}</b>",
                self.styles['InvoiceTitle']
            ))
        
        # Company contact info
        contact_parts = []
        if self.COMPANY_PHONE:
            contact_parts.append(self.COMPANY_PHONE)
        if self.COMPANY_EMAIL:
            contact_parts.append(self.COMPANY_EMAIL)
        if self.COMPANY_WEBSITE:
            contact_parts.append(self.COMPANY_WEBSITE)
        if self.COMPANY_ADDRESS:
            contact_parts.append(self.COMPANY_ADDRESS)
            
        if contact_parts:
            story.append(Paragraph(
                ' | '.join(contact_parts),
                self.styles['CompanyInfo']
            ))
        
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
        ]
        
        if invoice_data.customer_email:
            invoice_info.append([
                Paragraph("", self.styles['Normal']),
                Paragraph(f"{invoice_data.customer_email}", self.styles['CustomerInfo'])
            ])
        
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
        
        if invoice_data.total_discount > 0:
            totals_data.append([
                '',
                Paragraph("<b>Subtotal:</b>", self.styles['Normal']),
                Paragraph(f"${invoice_data.subtotal:.2f}", self.styles['Normal'])
            ])
            totals_data.append([
                '',
                Paragraph("<b>Discounts:</b>", self.styles['Normal']),
                Paragraph(f"-${invoice_data.total_discount:.2f}", self.styles['Normal'])
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
        
        # Footer note
        story.append(Spacer(1, 40))
        story.append(Paragraph(
            "Thank you for your business!",
            ParagraphStyle(
                name='ThankYou',
                parent=self.styles['Normal'],
                fontSize=12,
                alignment=TA_CENTER,
                textColor=colors.HexColor('#4a4a4a')
            )
        ))
        
        # Build PDF
        doc.build(story)
        
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
        include_photos: bool = False  # Photos disabled by default for now
    ) -> Tuple[bytes, InvoiceData]:
        """
        Generate a complete invoice PDF.
        
        Args:
            customer_id: Customer to invoice
            repair_ids: Optional specific repairs
            start_date: Optional date range start  
            end_date: Optional date range end
            include_photos: Whether to embed photos (increases file size)
            
        Returns:
            Tuple of (PDF bytes, InvoiceData)
        """
        invoice_data = self.build_invoice_data(
            customer_id=customer_id,
            repair_ids=repair_ids,
            start_date=start_date,
            end_date=end_date
        )
        
        pdf_bytes = self.generate_pdf(invoice_data, include_photos=include_photos)
        
        return pdf_bytes, invoice_data


# Convenience functions
def generate_customer_invoice(
    customer_id: int,
    repair_ids: Optional[List[int]] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Tuple[bytes, InvoiceData]:
    """Convenience function to generate an invoice"""
    service = InvoiceService()
    return service.generate_invoice(
        customer_id=customer_id,
        repair_ids=repair_ids,
        start_date=start_date,
        end_date=end_date
    )


def get_invoiceable_repairs(customer_id: int) -> QuerySet:
    """Get all completed repairs that can be invoiced for a customer"""
    service = InvoiceService()
    return service.get_completed_repairs(customer_id=customer_id)
