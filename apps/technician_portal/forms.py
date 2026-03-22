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

    class Meta:
        model = Customer
        fields = ['name', 'customer_type', 'email', 'phone', 'primary_technician']
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
            'primary_technician', 'tax_exempt', 'tax_exempt_certificate'
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
        
        # Add placeholders
        self.fields['email'].widget.attrs['placeholder'] = 'billing@company.com'
        self.fields['phone'].widget.attrs['placeholder'] = '+1 (555) 123-4567'
        self.fields['tax_exempt_certificate'].widget.attrs['placeholder'] = 'Certificate number (if exempt)'

class CustomDateTimeInput(DateTimeInput):
    input_type = 'datetime-local'
    def __init__(self, attrs=None, format=None):
        super().__init__(attrs={'step': '60', **(attrs or {})}, format='%Y-%m-%dT%H:%M')

class RepairForm(forms.ModelForm):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none())  # Filtered by tenant in __init__
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
                  'cost_override', 'override_reason', 'repair_batch_id', 'break_number', 'total_breaks_in_batch']

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
