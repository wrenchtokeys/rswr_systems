from django import forms
from .models import Technician, Repair, Replacement, Customer, UnitRepairCount
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.forms.widgets import DateTimeInput
import logging

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Technician, Repair, Replacement, Customer, UnitRepairCount
from core.models import TechnicianNotificationPreference
from django.utils import timezone
from django.forms.widgets import DateTimeInput
from django.db import transaction
import logging
logger = logging.getLogger(__name__)

class TechnicianForm(forms.Form):
    """
    Form for technicians to update their profile.
    Combines User and Technician model fields.
    Expertise is read-only (only admins can change it).
    """
    # User fields (editable)
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    username = forms.CharField(max_length=150, required=True)

    # Technician fields (editable)
    phone_number = forms.CharField(max_length=15, required=False)

    # Password fields (optional)
    password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput,
        required=False,
        help_text="Leave blank if you don't want to change your password."
    )
    password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput,
        required=False
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.technician = kwargs.pop('technician', None)
        super().__init__(*args, **kwargs)

        # Pre-populate fields if instances provided
        if self.user and not kwargs.get('data'):
            self.fields['first_name'].initial = self.user.first_name
            self.fields['last_name'].initial = self.user.last_name
            self.fields['email'].initial = self.user.email
            self.fields['username'].initial = self.user.username

        if self.technician and not kwargs.get('data'):
            self.fields['phone_number'].initial = self.technician.phone_number

    def clean_username(self):
        username = self.cleaned_data.get('username')
        # Check if username is taken by another user
        if self.user:
            if User.objects.filter(username=username).exclude(pk=self.user.pk).exists():
                raise forms.ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        # If password fields are provided, validate they match
        if password1 or password2:
            if password1 != password2:
                raise forms.ValidationError("Passwords don't match.")
            if password1 and len(password1) < 8:
                raise forms.ValidationError("Password must be at least 8 characters long.")

        return cleaned_data

    def save(self):
        """Save both User and Technician data"""
        if not self.user or not self.technician:
            raise ValueError("User and Technician instances required")

        # Update User fields
        self.user.first_name = self.cleaned_data['first_name']
        self.user.last_name = self.cleaned_data['last_name']
        self.user.email = self.cleaned_data['email']
        self.user.username = self.cleaned_data['username']

        # Update password if provided
        if self.cleaned_data.get('password1'):
            self.user.set_password(self.cleaned_data['password1'])

        self.user.save()

        # Update Technician fields
        self.technician.phone_number = self.cleaned_data['phone_number']
        self.technician.save()

        return self.user


class TechnicianRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=15, required=True)
    expertise = forms.CharField(max_length=100, required=True)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2')

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.email = self.cleaned_data['email']
        
        if commit:
            user.save()
            # Create the technician profile
            Technician.objects.create(
                user=user,
                phone_number=self.cleaned_data['phone_number'],
                expertise=self.cleaned_data['expertise']
            )
        return user
    
def _clean_customer_email(form):
    """Shared email cleaning for customer forms.

    Returns None for blank input (the DB stores "no email" as NULL — the
    unique_customer_email_per_tenant constraint only ignores NULL, so ''
    must never be saved). Raises a friendly ValidationError when another
    customer in the same tenant already uses the address; without this the
    conditional unique constraint surfaces as an IntegrityError 500, since
    Django's ModelForm validation skips constraints that have a condition.
    """
    email = (form.cleaned_data.get('email') or '').strip()
    if not email:
        return None
    tenant = form.tenant or getattr(form.instance, 'tenant', None)
    qs = Customer.objects.filter(email__iexact=email)
    if tenant:
        qs = qs.filter(tenant=tenant)
    if form.instance.pk:
        qs = qs.exclude(pk=form.instance.pk)
    existing = qs.first()
    if existing:
        raise forms.ValidationError(
            f'"{existing.name}" already uses this email address. '
            'Each customer needs a unique email.'
        )
    return email


def _configure_account_discount_fields(form, tenant):
    """Wire up the fleet-linked discount fields on a customer form.

    ``parent_account`` is scoped to this tenant's FLEET accounts (an individual
    links to one to inherit its discount) and excludes the customer being
    edited. ``account_discount_percentage`` is the flat % a fleet account grants.
    Both are optional; the template shows the relevant one per customer type.
    """
    if 'parent_account' in form.fields:
        qs = Customer.objects.filter(customer_type='FLEET')
        if tenant:
            qs = qs.filter(tenant=tenant)
        instance = getattr(form, 'instance', None)
        if instance is not None and instance.pk:
            qs = qs.exclude(pk=instance.pk)
        form.fields['parent_account'].queryset = qs.order_by('name')
        form.fields['parent_account'].required = False
        form.fields['parent_account'].label = 'Linked fleet account'
        form.fields['parent_account'].empty_label = '— None (standalone) —'
    if 'account_discount_percentage' in form.fields:
        form.fields['account_discount_percentage'].required = False
        form.fields['account_discount_percentage'].label = 'Account discount %'


class CustomerForm(forms.ModelForm):
    """Form for creating customers with optional portal invitation."""
    
    # Invitation fields (optional)
    invite_email = forms.EmailField(
        required=False,
        label="Contact Email",
        help_text="Email address for the fleet manager who will access the portal"
    )
    invite_first_name = forms.CharField(
        max_length=100,
        required=False,
        label="Contact First Name"
    )
    invite_last_name = forms.CharField(
        max_length=100,
        required=False,
        label="Contact Last Name"
    )
    send_invitation = forms.BooleanField(
        required=False,
        initial=True,
        label="Send portal invitation",
        help_text="Send an email invitation to access the customer portal"
    )
    is_primary_contact = forms.BooleanField(
        required=False,
        initial=True,
        label="Set as primary contact",
        help_text="Primary contact receives approval requests and billing notifications"
    )
    is_primary_contact = forms.BooleanField(
        required=False,
        initial=True,
        label="Set as primary contact",
        help_text="Primary contacts receive repair lifecycle notifications by default"
    )

    # Billing preference fields (optional — collapsed section)
    invoice_preference = forms.ChoiceField(
        required=False,
        choices=[('', '(use shop default)')] + list(
            __import__('apps.customer_portal.models', fromlist=['CustomerRepairPreference'])
            .CustomerRepairPreference.INVOICE_PREFERENCE_CHOICES
        ),
        label="Invoice Preference",
    )
    payment_terms = forms.ChoiceField(
        required=False,
        choices=[],  # populated in __init__ with shop default label
        label="Payment Terms",
    )
    billing_email = forms.EmailField(
        required=False,
        label="Billing Email",
        help_text="Dedicated AP/billing email (optional — uses customer email if blank)"
    )
    batch_invoice_day = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=28,
        label="Batch Invoice Day",
        help_text="Day of month (1-28) for batch invoicing. Leave blank for shop default."
    )

    class Meta:
        model = Customer
        fields = ['name', 'customer_type', 'email', 'phone', 'primary_technician',
                  'parent_account', 'account_discount_percentage']
        widgets = {
            'customer_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        # Scope primary_technician choices to tenant
        from apps.technician_portal.models import Technician
        qs = Technician.objects.filter(is_active=True)
        if self.tenant:
            qs = qs.filter(tenant=self.tenant)
        self.fields['primary_technician'].queryset = qs.order_by('user__first_name')
        self.fields['primary_technician'].required = False
        self.fields['email'].required = False
        self.fields['phone'].required = False
        self.fields['customer_type'].required = False
        _configure_account_discount_fields(self, self.tenant)

        # Build payment_terms choices with actual shop default label
        from apps.billing.models import BillingConfig
        shop_default_terms = 'COD'
        if self.tenant:
            billing_config = BillingConfig.get_for_tenant(self.tenant)
            shop_default_terms = billing_config.default_payment_terms
        terms_display = dict(BillingConfig.PAYMENT_TERMS_CHOICES).get(shop_default_terms, shop_default_terms)
        self.fields['payment_terms'].choices = [
            ('', f'{terms_display} — shop default'),
        ] + BillingConfig.PAYMENT_TERMS_CHOICES

    def clean_batch_invoice_day(self):
        day = self.cleaned_data.get('batch_invoice_day')
        if day is not None and not (1 <= day <= 28):
            raise forms.ValidationError('Batch invoice day must be between 1 and 28.')
        return day

    def clean_email(self):
        return _clean_customer_email(self)

    def clean_phone(self):
        """Normalize phone to digits-only, accept common formats."""
        import re
        phone = self.cleaned_data.get('phone', '')
        if not phone:
            return phone
        # Strip everything except digits and leading +
        digits = re.sub(r'[^\d]', '', phone)
        if len(digits) == 10:
            # US number without country code
            return f'+1{digits}'
        elif len(digits) == 11 and digits.startswith('1'):
            return f'+{digits}'
        elif 9 <= len(digits) <= 15:
            return f'+{digits}'
        # Return as-is if it doesn't match — model no longer has strict validator
        return phone


class CustomerEditForm(forms.ModelForm):
    """Full form for editing customer details."""
    class Meta:
        model = Customer
        fields = [
            'name', 'customer_type', 'email', 'phone',
            'address', 'city', 'state', 'zip_code',
            'primary_technician', 'tax_exempt', 'tax_exempt_certificate',
            'parent_account', 'account_discount_percentage',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'customer_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        
        # Scope primary_technician choices to tenant
        from apps.technician_portal.models import Technician
        qs = Technician.objects.filter(is_active=True)
        if self.tenant:
            qs = qs.filter(tenant=self.tenant)
        self.fields['primary_technician'].queryset = qs.order_by('user__first_name')
        self.fields['primary_technician'].required = False
        
        # Make fields optional where appropriate
        self.fields['email'].required = False
        self.fields['phone'].required = False
        self.fields['address'].required = False
        self.fields['city'].required = False
        self.fields['state'].required = False
        self.fields['zip_code'].required = False
        self.fields['tax_exempt_certificate'].required = False
        _configure_account_discount_fields(self, self.tenant)

        # Add placeholders
        self.fields['email'].widget.attrs['placeholder'] = 'billing@company.com'
        self.fields['phone'].widget.attrs['placeholder'] = '+1 (555) 123-4567'
        self.fields['tax_exempt_certificate'].widget.attrs['placeholder'] = 'Certificate number (if exempt)'

    def clean_email(self):
        return _clean_customer_email(self)

class CustomDateTimeInput(DateTimeInput):
    input_type = 'datetime-local'
    def __init__(self, attrs=None, format=None):
        super().__init__(attrs={'step': '60', **(attrs or {})}, format='%Y-%m-%dT%H:%M')

class RepairForm(forms.ModelForm):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),  # Filtered by tenant in __init__
        required=False,  # Not required for walk-in / individual repairs
    )

    # Walk-in / individual toggle: create a ticket without a pre-existing fleet account.
    is_walkin = forms.BooleanField(
        required=False,
        label="Walk-in / Individual (no account)",
        help_text="Create a repair for an individual car without a fleet customer account.",
    )
    walkin_name = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Customer name'}),
        label="Customer Name",
    )
    walkin_phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={'placeholder': '(555) 123-4567'}),
        label="Phone (optional)",
    )
    technician = forms.ModelChoiceField(
        queryset=Technician.objects.none(),  # Filtered by tenant in __init__
        required=False,  # Not required because it might be set automatically for non-admin users
        help_text="Only required for admin users. Regular technicians will be automatically assigned."
    )
    # Expose service_date as repair_date for backward compatibility in templates/views
    repair_date = forms.DateTimeField(
        widget=CustomDateTimeInput()
    )
    damage_type = forms.ChoiceField(
        choices=[],  # Will be set in __init__
        required=False,
        help_text="Select the type of windshield damage"
    )

    # Batch repair tracking fields (hidden)
    repair_batch_id = forms.UUIDField(required=False, widget=forms.HiddenInput())
    break_number = forms.IntegerField(required=False, widget=forms.HiddenInput())
    total_breaks_in_batch = forms.IntegerField(required=False, widget=forms.HiddenInput())

    # Vehicle fields for retail/walk-in customers
    vehicle_year = forms.IntegerField(
        required=False,
        min_value=1990,
        max_value=2030,
        widget=forms.NumberInput(attrs={'placeholder': '2019'})
    )
    vehicle_make = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={'placeholder': 'Ford'})
    )
    vehicle_model = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={'placeholder': 'F-150'})
    )

    class Meta:
        model = Repair
        fields = ['technician', 'customer', 'unit_number', 'vehicle_year', 'vehicle_make', 'vehicle_model',
                  'queue_status', 'damage_type', 'damage_location_x', 'damage_location_y',
                  'drilled_before_repair', 'windshield_temperature', 'resin_viscosity', 'customer_submitted_photo',
                  'damage_photo_before', 'damage_photo_after', 'customer_notes', 'technician_notes',
                  'cost_override', 'override_reason', 'no_tax',
                  'repair_batch_id', 'break_number', 'total_breaks_in_batch']
        labels = {
            'no_tax': "Don't charge sales tax on this job",
        }
        widgets = {
            'no_tax': forms.CheckboxInput(attrs={
                'class': 'w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.tenant = kwargs.pop('tenant', None)
        super(RepairForm, self).__init__(*args, **kwargs)
        
        # Set the damage type choices
        self.fields['damage_type'].choices = Repair.DAMAGE_TYPE_CHOICES

        # CRITICAL: Filter customer and technician dropdowns by tenant
        # Without this, users see ALL customers/techs across all shops
        if self.tenant:
            self.fields['customer'].queryset = Customer.objects.filter(
                tenant=self.tenant
            ).order_by('name')
            self.fields['technician'].queryset = Technician.objects.filter(
                tenant=self.tenant, can_repair=True, is_active=True
            )
        else:
            # Fallback for superusers / admin — still filter by active
            self.fields['customer'].queryset = Customer.objects.all().order_by('name')
            self.fields['technician'].queryset = Technician.objects.filter(
                can_repair=True, is_active=True
            )
        
        # Hide technician field for non-admin users
        if self.user and not self.user.is_staff:
            self.fields['technician'].widget = forms.HiddenInput()

        # Hide pricing override fields for non-managers
        # Use tenant-scoped lookup to avoid cross-tenant manager privilege leak
        # (CODE-091: unscoped self.user.technician would return Shop A's Technician
        # even when the form is rendered in Shop B's context).
        _form_technician = None
        if self.user and self.tenant:
            _form_technician = Technician.objects.filter(
                user=self.user, tenant=self.tenant
            ).first()
        elif self.user and hasattr(self.user, 'technician'):
            # Fallback for superusers / dev (no tenant context)
            try:
                _form_technician = self.user.technician
            except Technician.DoesNotExist:
                pass

        if _form_technician and _form_technician.is_manager and _form_technician.can_override_pricing:
            pass  # Show override fields
        else:
            self.fields['cost_override'].widget = forms.HiddenInput()
            self.fields['override_reason'].widget = forms.HiddenInput()
        
        # Auto-populate repair_date from service_date for existing repairs
        if self.instance and self.instance.pk:
            # This is an existing repair being edited - keep existing date
            # But ensure widget has proper format
            if self.instance.service_date:
                self.fields['repair_date'].initial = self.instance.service_date
                # Convert to local timezone for datetime-local input
                local_time = timezone.localtime(self.instance.service_date)
                self.fields['repair_date'].widget.attrs['value'] = local_time.strftime('%Y-%m-%dT%H:%M')
        # For new repairs, JavaScript will set the current time in the user's browser timezone
        # See static/js/repair_form.js lines 40-54 for client-side initialization
        
        # Make customer_notes read-only for technicians - they should not modify customer input
        if 'customer_notes' in self.fields:
            self.fields['customer_notes'].widget.attrs['readonly'] = True
            self.fields['customer_notes'].help_text = "Notes provided by the customer (read-only)"

        # Make customer_submitted_photo read-only (display only, cannot be edited/uploaded by technician)
        if 'customer_submitted_photo' in self.fields:
            self.fields['customer_submitted_photo'].widget.attrs['disabled'] = True
            self.fields['customer_submitted_photo'].required = False
            self.fields['customer_submitted_photo'].help_text = "Photo uploaded by customer with repair request (read-only)"

        # Add helpful labels for the note fields
        if 'technician_notes' in self.fields:
            self.fields['technician_notes'].help_text = "Add your internal notes about the repair process"

        # Unit number is not always required (depends on customer type)
        self.fields['unit_number'].required = False
        self.fields['unit_number'].widget.attrs.update({
            'placeholder': 'e.g., TRUCK-1045',
            'class': 'icon-field-input'
        })
        
        # Vehicle fields have placeholder attrs set in field definition

        self.fields['windshield_temperature'].widget.attrs.update({
            'placeholder': 'e.g., 72.5',
            'step': '0.1',
            'class': 'icon-field-input'
        })

        self.fields['resin_viscosity'].widget.attrs.update({
            'placeholder': 'e.g., Low(l), Medium(m), High(h)',
            'maxlength': '50',
            'class': 'icon-field-input'
        })

        if 'technician_notes' in self.fields:
            self.fields['technician_notes'].widget.attrs.update({
                'placeholder': 'Add any internal notes about the repair process, challenges encountered, or follow-up needed...',
                'rows': '4',
                'class': 'icon-field-input'
            })

    def clean(self):
        cleaned_data = super().clean()
        
        # Map repair_date form field → service_date model field
        repair_date_value = cleaned_data.get('repair_date')
        if repair_date_value:
            cleaned_data['service_date'] = repair_date_value
        
        customer = cleaned_data.get('customer')
        unit_number = cleaned_data.get('unit_number')
        queue_status = cleaned_data.get('queue_status')
        technician = cleaned_data.get('technician')
        cost_override = cleaned_data.get('cost_override')
        override_reason = cleaned_data.get('override_reason')
        is_walkin = cleaned_data.get('is_walkin')

        # Walk-in / individual repairs don't need a fleet customer account.
        # They require a name and vehicle info instead. A WALK_IN Customer
        # record is auto-created in the view.
        if is_walkin:
            if not cleaned_data.get('walkin_name'):
                self.add_error('walkin_name', 'Customer name is required for a walk-in repair.')
            vehicle_make = cleaned_data.get('vehicle_make')
            vehicle_model = cleaned_data.get('vehicle_model')
            if not vehicle_make:
                self.add_error('vehicle_make', 'Vehicle make is required for a walk-in repair.')
            if not vehicle_model:
                self.add_error('vehicle_model', 'Vehicle model is required for a walk-in repair.')
        elif not customer:
            # Standard (non-walk-in) repairs require a customer selection.
            self.add_error('customer', 'Please select a customer, or toggle "Walk-in / Individual".')

        # Admin users must select a technician
        if hasattr(self, 'user') and self.user.is_staff and not technician:
            self.add_error('technician', 'Please select a technician to assign this repair to.')

        # Validate pricing override permissions and limits.
        # Must use tenant-scoped Technician lookup — CODE-091: an unscoped
        # self.user.technician resolves the OneToOneField globally and could
        # return a manager record from another tenant, bypassing cost controls.
        if cost_override is not None:
            _clean_technician = None
            if hasattr(self, 'user') and self.user:
                if self.tenant:
                    _clean_technician = Technician.objects.filter(
                        user=self.user, tenant=self.tenant
                    ).first()
                elif hasattr(self.user, 'technician'):
                    try:
                        _clean_technician = self.user.technician
                    except Technician.DoesNotExist:
                        pass

            if not _clean_technician:
                self.add_error('cost_override', 'Only managers can override pricing.')
            else:
                if not (_clean_technician.is_manager and _clean_technician.can_override_pricing):
                    self.add_error('cost_override', 'You do not have permission to override pricing.')
                # Use `is not None` so approval_limit=Decimal('0.00') is a valid
                # "zero cap" — bare truthiness would treat 0.00 as "no limit" (AGENTS.md).
                elif _clean_technician.approval_limit is not None and cost_override > _clean_technician.approval_limit:
                    self.add_error('cost_override', f'Override amount exceeds your approval limit of ${_clean_technician.approval_limit}.')
                elif not override_reason:
                    self.add_error('override_reason', 'Override reason is required when setting a custom price.')

        # If override reason is provided, cost_override should also be provided
        if override_reason and cost_override is None:
            self.add_error('cost_override', 'Please provide an override amount when specifying a reason.')

        # Photo validation when completing a repair
        if queue_status == 'COMPLETED':
            # Check if after photo exists (from form upload or existing instance)
            after_photo = cleaned_data.get('damage_photo_after')

            # Check for existing photo more robustly by reloading from database
            has_existing_after_photo = False
            if self.instance.pk:
                try:
                    # Reload from DB to ensure we have the latest state
                    existing_repair = Repair.objects.get(pk=self.instance.pk)
                    has_existing_after_photo = bool(existing_repair.damage_photo_after)
                except Repair.DoesNotExist:
                    pass

            # Determine if user is a manager who can override photo requirement.
            # Must use tenant-scoped lookup — same CODE-091 pattern: unscoped
            # self.user.technician could return a manager from a different tenant,
            # granting them the ability to skip after-photo requirements in any shop.
            is_manager = False
            if hasattr(self, 'user') and self.user:
                if self.user.is_staff:
                    is_manager = True
                elif self.tenant:
                    _photo_tech = Technician.objects.filter(
                        user=self.user, tenant=self.tenant
                    ).first()
                    if _photo_tech and _photo_tech.is_manager:
                        is_manager = True
                elif hasattr(self.user, 'technician'):
                    try:
                        if self.user.technician.is_manager:
                            is_manager = True
                    except Technician.DoesNotExist:
                        pass

            # Require after photo for non-managers only if no existing photo
            if not is_manager and not after_photo and not has_existing_after_photo:
                self.add_error('damage_photo_after', 'After photo is required to complete a repair. Managers can override if needed.')

            # Soft warning for missing before photo (doesn't block submission)
            before_photo = cleaned_data.get('damage_photo_before')
            has_existing_before_photo = self.instance.pk and self.instance.damage_photo_before
            if not before_photo and not has_existing_before_photo:
                # Add a warning message (won't block form submission)
                import warnings
                from django.contrib import messages
                logger.warning(f"Repair being completed without before photo. User: {self.user.username if hasattr(self, 'user') else 'Unknown'}")

        if customer and unit_number:
            repair_batch_id = cleaned_data.get('repair_batch_id')

            # Skip duplicate check entirely when editing an existing repair
            # (only warn on NEW repairs to prevent accidental duplicates)
            if not self.instance.pk:
                existing_repairs = Repair.objects.filter(
                    customer=customer,
                    unit_number=unit_number,
                    queue_status__in=['PENDING', 'APPROVED', 'IN_PROGRESS']
                )

                # Allow duplicates if part of same batch
                if repair_batch_id:
                    existing_repairs = existing_repairs.exclude(repair_batch_id=repair_batch_id)

                if existing_repairs.exists():
                    existing_repair = existing_repairs.first()
                    if queue_status in ['PENDING', 'APPROVED', 'IN_PROGRESS']:
                        from django.utils.html import format_html
                        raise forms.ValidationError(
                            format_html(
                                "There is already a {} repair for this unit. "
                                "<a href='/tech/repairs/{}/'>View existing repair</a>",
                                existing_repair.get_queue_status_display(),
                                existing_repair.id
                            ),
                            code='existing_repair'
                        )

        # Customer type validation: require appropriate fields
        if customer:
            customer_type = customer.customer_type
            vehicle_year = cleaned_data.get('vehicle_year')
            vehicle_make = cleaned_data.get('vehicle_make')
            vehicle_model = cleaned_data.get('vehicle_model')
            
            if customer_type == 'FLEET':
                # Fleet customers require unit_number
                if not unit_number:
                    self.add_error('unit_number', 'Unit number is required for fleet customers.')
            else:
                # Retail/Walk-in customers require vehicle info
                if not vehicle_year and not vehicle_make and not vehicle_model:
                    # None provided - require at least make/model
                    self.add_error('vehicle_make', 'Vehicle make is required for retail customers.')
                    self.add_error('vehicle_model', 'Vehicle model is required for retail customers.')
                elif not vehicle_make:
                    self.add_error('vehicle_make', 'Vehicle make is required.')
                elif not vehicle_model:
                    self.add_error('vehicle_model', 'Vehicle model is required.')

        return cleaned_data

    def save(self, commit=True):
        """Override save to map repair_date → service_date on the model instance."""
        instance = super().save(commit=False)
        repair_date_value = self.cleaned_data.get('repair_date')
        if repair_date_value:
            instance.service_date = repair_date_value
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class TechnicianNotificationPreferenceForm(forms.ModelForm):
    """
    Form for technician notification preferences.

    Groups settings into logical sections with helpful descriptions.
    """

    class Meta:
        model = TechnicianNotificationPreference
        fields = [
            # Global preferences
            'receive_email_notifications',
            'receive_sms_notifications',
            'receive_in_app_notifications',

            # Category preferences
            'notify_repair_status',
            'notify_new_assignments',
            'notify_reassignments',
            'notify_customer_approvals',
            'notify_reward_redemptions',
            'notify_system',

            # Quiet hours
            'quiet_hours_enabled',
            'quiet_hours_start',
            'quiet_hours_end',

            # Digest mode
            'digest_enabled',
            'digest_time',
        ]

        widgets = {
            'quiet_hours_start': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'quiet_hours_end': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'digest_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        }

        help_texts = {
            'receive_sms_notifications': 'Receive high-priority notifications via text message (standard SMS rates may apply)',
            'quiet_hours_enabled': 'Pause non-urgent notifications during specified hours',
            'digest_enabled': 'Receive one daily email summary instead of individual notifications',
        }

    def clean(self):
        cleaned_data = super().clean()

        # Validate quiet hours
        quiet_enabled = cleaned_data.get('quiet_hours_enabled')
        quiet_start = cleaned_data.get('quiet_hours_start')
        quiet_end = cleaned_data.get('quiet_hours_end')

        if quiet_enabled and (not quiet_start or not quiet_end):
            raise forms.ValidationError(
                "Quiet hours start and end times are required when quiet hours are enabled."
            )

        # Validate digest settings
        digest_enabled = cleaned_data.get('digest_enabled')
        digest_time = cleaned_data.get('digest_time')

        if digest_enabled and not digest_time:
            raise forms.ValidationError(
                "Digest time is required when daily digest is enabled."
            )

        return cleaned_data


class CustomerEmailSelect(forms.Select):
    """Customer dropdown whose options carry data-email — the address an
    invoice for that customer would go to — so the "Save & Send Invoice"
    confirmation dialog can show the recipient before anything sends."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(
            name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            from apps.billing.services.invoice_send_service import InvoiceSendService
            option['attrs']['data-email'] = InvoiceSendService.resolve_recipient(instance)
            # Tax-exempt customers never get tax — the job form's "charge
            # sales tax" checkbox unchecks + locks itself off this attribute.
            if instance.tax_exempt:
                option['attrs']['data-tax-exempt'] = '1'
        return option


class QuickJobForm(forms.Form):
    """The job creation form (/tech/jobs/new/).

    The common path stays short — customer, what was done, price. Everything
    else is optional and lives behind a "More details" disclosure in the
    template rather than on a separate page: a tech does not know whether a
    job needs photos or insurance details until they are looking at it, so
    making them choose a form up front was always a guess.

    The per-type forms (RepairForm, ReplacementForm) still exist and still
    back /tech/repairs/create/ and the edit flows; they are simply no longer
    something the UI asks anyone to pick.
    """

    _INPUT = ('w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 '
              'focus:ring-green-500 focus:border-green-500 outline-none transition')

    service_type = forms.ChoiceField(
        choices=[('repair', 'Repair'), ('replacement', 'Replacement')],
        widget=forms.RadioSelect,
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.none(),
        required=False,
        widget=CustomerEmailSelect(attrs={'class': _INPUT + ' bg-white'}),
    )
    # Add an individual customer on the fly — no "create the customer first" detour.
    new_customer_name = forms.CharField(
        required=False, max_length=100,
        widget=forms.TextInput(attrs={
            'class': _INPUT,
            'placeholder': 'e.g. John Smith',
        }),
    )
    new_customer_phone = forms.CharField(
        required=False, max_length=20,
        widget=forms.TextInput(attrs={
            'class': _INPUT,
            'placeholder': 'Phone (optional)',
        }),
    )
    new_customer_is_walkin = forms.BooleanField(required=False)
    unit_number = forms.CharField(
        required=False, max_length=100,
        widget=forms.TextInput(attrs={
            'class': _INPUT,
            'placeholder': 'e.g. T-1045 or 2023 Toyota Camry',
        }),
    )
    work_done = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': _INPUT, 'rows': 2,
            'placeholder': 'e.g. Windshield replacement',
        }),
    )
    price = forms.DecimalField(
        required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': _INPUT, 'placeholder': '0.00', 'step': '0.01', 'min': '0',
        }),
    )
    already_completed = forms.BooleanField(required=False, initial=True)
    # Rendered only when the shop has tax enabled. Unchecking makes this a
    # no-tax job (cash deal); the view maps it onto Repair/Replacement.no_tax.
    charge_tax = forms.BooleanField(required=False, initial=True)

    # Repair details
    damage_type = forms.ChoiceField(
        choices=Repair.DAMAGE_TYPE_CHOICES, required=False,
        widget=forms.Select(attrs={'class': _INPUT + ' bg-white'}),
    )
    damage_location_x = forms.FloatField(required=False, widget=forms.HiddenInput())
    damage_location_y = forms.FloatField(required=False, widget=forms.HiddenInput())

    # Replacement details
    glass_position = forms.ChoiceField(
        choices=[('', '— Select —')] + Replacement.GLASS_POSITION_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': _INPUT + ' bg-white'}),
    )
    glass_type = forms.ChoiceField(
        choices=[('', '— Select —')] + Replacement.GLASS_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': _INPUT + ' bg-white'}),
    )
    nags_number = forms.CharField(
        required=False, max_length=50,
        widget=forms.TextInput(attrs={
            'class': _INPUT, 'placeholder': 'e.g. FW04567',
        }),
    )

    # ---- "More details" ---------------------------------------------------
    # All optional. Previously the only way to reach any of these was to
    # abandon this form and start again on a per-type one.

    technician = forms.ModelChoiceField(
        queryset=Technician.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': _INPUT + ' bg-white'}),
        help_text='Leave blank to assign yourself.',
    )
    vehicle_year = forms.IntegerField(
        required=False, min_value=1990, max_value=2030,
        widget=forms.NumberInput(attrs={'class': _INPUT, 'placeholder': '2019'}),
    )
    vehicle_make = forms.CharField(
        required=False, max_length=50,
        widget=forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Toyota'}),
    )
    vehicle_model = forms.CharField(
        required=False, max_length=50,
        widget=forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Camry'}),
    )
    damage_photo_before = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'accept': 'image/*', 'capture': 'environment',
        }),
    )
    damage_photo_after = forms.ImageField(
        required=False,
        widget=forms.ClearableFileInput(attrs={
            'accept': 'image/*', 'capture': 'environment',
        }),
    )
    customer_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': _INPUT, 'rows': 2,
            'placeholder': 'Anything the customer asked for or should see',
        }),
    )

    # Repair-only extras
    windshield_temperature = forms.DecimalField(
        required=False, max_digits=5, decimal_places=1,
        widget=forms.NumberInput(attrs={
            'class': _INPUT, 'placeholder': '°F', 'step': '0.1',
        }),
    )
    resin_viscosity = forms.CharField(
        required=False, max_length=50,
        widget=forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'e.g. Medium'}),
    )
    drilled_before_repair = forms.BooleanField(required=False)

    # Replacement-only extras
    requires_adas_calibration = forms.BooleanField(required=False)
    adas_calibration_cost = forms.DecimalField(
        required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': _INPUT, 'placeholder': '0.00', 'step': '0.01', 'min': '0',
        }),
    )

    # Insurance (both types)
    insurance_claim = forms.BooleanField(required=False)
    insurance_company = forms.CharField(
        required=False, max_length=100,
        widget=forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Insurer'}),
    )
    claim_number = forms.CharField(
        required=False, max_length=100,
        widget=forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Claim #'}),
    )
    deductible = forms.DecimalField(
        required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': _INPUT, 'placeholder': '0.00', 'step': '0.01', 'min': '0',
        }),
    )

    def __init__(self, *args, tenant=None, allowed_types=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allowed_types = allowed_types or ['repair', 'replacement']
        self.fields['service_type'].choices = [
            (t, t.title()) for t in self.allowed_types
        ]
        if len(self.allowed_types) == 1:
            self.fields['service_type'].initial = self.allowed_types[0]
            self.fields['service_type'].widget = forms.HiddenInput()
        if tenant:
            # select_related keeps the data-email annotation in
            # CustomerEmailSelect from issuing one query per option.
            self.fields['customer'].queryset = Customer.objects.filter(
                tenant=tenant).select_related('repair_preferences')
            # Tenant-scoped, same as RepairForm — never offer a technician from
            # another shop in the assignment dropdown.
            self.fields['technician'].queryset = Technician.objects.filter(
                tenant=tenant, is_active=True,
            ).select_related('user').order_by('user__first_name')

    def clean_service_type(self):
        value = self.cleaned_data['service_type']
        if value not in self.allowed_types:
            raise forms.ValidationError('Your shop does not offer that service.')
        return value

    def clean(self):
        cleaned = super().clean()
        # Exactly one of: pick an existing customer, OR add a new individual.
        existing = cleaned.get('customer')
        new_name = (cleaned.get('new_customer_name') or '').strip()
        if not existing and not new_name:
            self.add_error('customer', 'Pick a customer or add a new individual.')
        elif existing and new_name:
            self.add_error(
                'new_customer_name',
                'Choose an existing customer or add a new one — not both.',
            )
        # Repairs auto-price from the price book when blank; replacements have
        # no price book, so a blank price would make a $0 invoice.
        if cleaned.get('service_type') == 'replacement' and cleaned.get('price') in (None, ''):
            self.add_error('price', 'Enter a price for the replacement.')
        return cleaned
