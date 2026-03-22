"""
Email Preview System

Provides staff-only views to preview email templates with sample data.
This allows administrators to test email rendering before sending.
"""

from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, Http404
from django.template.loader import render_to_string
from datetime import datetime, timedelta
from decimal import Decimal
import uuid

from core.models import EmailBrandingConfig
from apps.technician_portal.models import Repair, Technician
from core.models import Customer
from django.contrib.auth import get_user_model

User = get_user_model()


@staff_member_required
def preview_email_template(request, template_name):
    """
    Preview an email template with sample data.

    Args:
        request: Django request object
        template_name: Name of the template to preview (e.g., 'repair_approved')

    Returns:
        HttpResponse with rendered HTML email template
    """
    # Get branding configuration
    branding_config = EmailBrandingConfig.get_instance()
    branding_context = branding_config.to_template_context()

    # Template mappings
    template_map = {
        'repair_approved': 'emails/notifications/repair_approved.html',
        'repair_denied': 'emails/notifications/repair_denied.html',
        'repair_assigned': 'emails/notifications/repair_assigned.html',
        'repair_completed': 'emails/notifications/repair_completed.html',
        'batch_approved': 'emails/notifications/batch_approved.html',
    }

    if template_name not in template_map:
        raise Http404(f'Template "{template_name}" not found')

    # Generate appropriate sample data based on template
    if template_name == 'repair_approved':
        context = create_repair_approved_context(branding_context)
    elif template_name == 'repair_denied':
        context = create_repair_denied_context(branding_context)
    elif template_name == 'repair_assigned':
        context = create_repair_assigned_context(branding_context)
    elif template_name == 'repair_completed':
        context = create_repair_completed_context(branding_context)
    elif template_name == 'batch_approved':
        context = create_batch_approved_context(branding_context)
    else:
        context = {}

    # Render template
    html_content = render_to_string(template_map[template_name], context)

    return HttpResponse(html_content, content_type='text/html')


def create_sample_repair():
    """
    Create a sample repair object (not saved to database).

    Returns:
        Repair: Mock repair object with sample data
    """
    class MockRepair:
        def __init__(self):
            self.id = 12345
            self.unit_number = 'TRK-789'
            self.break_description = 'Bullseye break, approximately 1 inch diameter, driver side lower corner'
            self.requested_repair_date = datetime.now().date()
            self.actual_repair_date = datetime.now().date()
            self.total_cost = Decimal('75.00')
            self.denial_reason = None
            self.repair_batch_id = None
            self.break_number = 1
            self.total_breaks_in_batch = 1

        @property
        def customer(self):
            return create_sample_customer()

        @property
        def assigned_technician(self):
            return create_sample_technician()

        @property
        def damage_photo_before(self):
            return None

        @property
        def damage_photo_after(self):
            return None

    return MockRepair()


def create_sample_customer():
    """
    Create a sample customer object.

    Returns:
        Customer: Mock customer object
    """
    class MockCustomer:
        def __init__(self):
            self.id = 42
            self.company_name = 'ABC Logistics Inc.'
            self.contact_name = 'John Smith'
            self.email = 'john.smith@abclogistics.com'
            self.phone = '+1 (555) 123-4567'

    return MockCustomer()


def create_sample_technician():
    """
    Create a sample technician object.

    Returns:
        Technician: Mock technician object
    """
    class MockTechnician:
        def __init__(self):
            self.id = 7
            self.user_id = 100
            self.phone = '+1 (555) 987-6543'

        def get_full_name(self):
            return 'Mike Johnson'

    return MockTechnician()


def create_repair_approved_context(branding_context):
    """Create context for repair_approved template"""
    repair = create_sample_repair()

    return {
        'branding': type('obj', (object,), branding_context),
        'repair': repair,
        'view_repair_url': 'https://example.com/app/repairs/12345/',
        'unsubscribe_url': 'https://example.com/app/notifications/preferences/',
    }


def create_repair_denied_context(branding_context):
    """Create context for repair_denied template"""
    repair = create_sample_repair()
    repair.denial_reason = 'Additional photos required. The damage appears larger than initially reported. Please provide clearer photos of the full extent of the break before we can proceed with approval.'

    return {
        'branding': type('obj', (object,), branding_context),
        'repair': repair,
        'view_repair_url': 'https://example.com/app/repairs/12345/',
        'unsubscribe_url': 'https://example.com/app/notifications/preferences/',
    }


def create_repair_assigned_context(branding_context):
    """Create context for repair_assigned template"""
    repair = create_sample_repair()

    return {
        'branding': type('obj', (object,), branding_context),
        'repair': repair,
        'view_repair_url': 'https://example.com/tech/repairs/12345/',
        'unsubscribe_url': 'https://example.com/tech/notifications/preferences/',
    }


def create_repair_completed_context(branding_context):
    """Create context for repair_completed template"""
    repair = create_sample_repair()

    return {
        'branding': type('obj', (object,), branding_context),
        'repair': repair,
        'view_repair_url': 'https://example.com/app/repairs/12345/',
        'unsubscribe_url': 'https://example.com/app/notifications/preferences/',
    }


def create_batch_approved_context(branding_context):
    """Create context for batch_approved template"""
    # Create 3 sample repairs for batch
    repairs = []
    batch_id = uuid.uuid4()

    for i in range(3):
        repair = create_sample_repair()
        repair.id = 12345 + i
        repair.break_number = i + 1
        repair.total_breaks_in_batch = 3
        repair.repair_batch_id = batch_id
        repair.break_description = [
            'Bullseye break, driver side lower corner, approximately 1 inch',
            'Star break, passenger side upper corner, approximately 1.5 inches',
            'Combination break, center windshield, approximately 2 inches'
        ][i]
        repair.total_cost = Decimal(['75.00', '150.00', '225.00'][i])
        repairs.append(repair)

    total_cost = sum(r.total_cost for r in repairs)

    return {
        'branding': type('obj', (object,), branding_context),
        'repairs': repairs,
        'repairs_count': len(repairs),
        'unit_number': 'TRK-789',
        'total_cost': total_cost,
        'pricing_note': 'Progressive pricing applied: Break #1 priced as 4th repair ($75), Break #2 as 5th repair ($150), Break #3 as 6th repair ($225). Volume discount saves you $50 compared to individual repairs.',
        'view_repairs_url': 'https://example.com/app/repairs/?unit=TRK-789',
        'unsubscribe_url': 'https://example.com/app/notifications/preferences/',
    }
