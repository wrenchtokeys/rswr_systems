"""
SaaS UI Forms

Django forms for signup, onboarding, and replacement entry.

Author: Amelia (Clawdbot AI)
"""

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.tenants.models import SubscriptionPlan
from apps.technician_portal.models import Replacement, Technician
from core.models import Customer


# ------------------------------------------------------------------
# Signup Form
# ------------------------------------------------------------------

class SignupForm(forms.Form):
    """Registration form for new shop owners."""

    business_name = forms.CharField(
        max_length=200,
        min_length=2,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'e.g. Quick Fix Auto Glass',
            'autocomplete': 'organization',
        }),
    )
    first_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'First name',
            'autocomplete': 'given-name',
        }),
    )
    last_name = forms.CharField(
        max_length=30,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'Last name',
            'autocomplete': 'family-name',
        }),
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'you@yourbusiness.com',
            'autocomplete': 'email',
        }),
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': '••••••••',
            'autocomplete': 'new-password',
        }),
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': '••••••••',
            'autocomplete': 'new-password',
        }),
        label='Confirm password',
    )

    services_offered = forms.ChoiceField(
        required=False,
        choices=[
            ('both', 'Both repairs and replacements'),
            ('repair', 'Repairs only'),
            ('replacement', 'Replacements only'),
        ],
        initial='both',
        widget=forms.RadioSelect,
        label='What does your shop do?',
    )

    plan = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white',
        }),
        label='Which plan interests you?',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        plan_choices = [('', "I'll decide during my trial")]
        plan_choices += [
            (p.slug, p.name)
            for p in SubscriptionPlan.objects.filter(is_active=True).exclude(slug='trial').order_by('display_order')
        ]
        plan_choices.append(('not_sure', "Not sure yet"))

        self.fields['plan'].choices = plan_choices

    def clean_services_offered(self):
        # Blank (e.g. API callers or old cached forms) means "both".
        return self.cleaned_data.get('services_offered') or 'both'

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        # iexact: mixed-case duplicates (e.g. created via admin) must not
        # slip past this check — duplicate emails break login-by-email.
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('An account with this email already exists.')
        return email

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        pw2 = cleaned.get('password_confirm')
        if pw and pw2 and pw != pw2:
            self.add_error('password_confirm', 'Passwords do not match.')
        if pw:
            # Run Django's password validators
            temp_user = User(
                username=cleaned.get('email', '')[:150],
                email=cleaned.get('email', ''),
                first_name=cleaned.get('first_name', ''),
                last_name=cleaned.get('last_name', ''),
            )
            try:
                validate_password(pw, user=temp_user)
            except ValidationError as e:
                self.add_error('password', e)
        return cleaned


# ------------------------------------------------------------------
# Onboarding Forms
# ------------------------------------------------------------------

class OnboardingBusinessForm(forms.Form):
    """Step 1: Business info (phone, email, address, logo)."""

    business_phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': '(555) 123-4567',
        }),
    )
    business_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'info@yourbusiness.com',
        }),
    )
    business_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': '123 Main St, Suite 100\nAnytown, TX 78701',
            'rows': 3,
        }),
    )
    logo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100',
            'accept': 'image/*',
        }),
    )


class OnboardingTechnicianForm(forms.Form):
    """Step 2: Add first technician.
    
    If 'add_self' is checked, name fields are optional (auto-filled from owner).
    If adding someone else, first name is required.
    """

    tech_first_name = forms.CharField(
        max_length=30,
        required=False,  # Not required when add_self is checked
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'First name',
        }),
    )
    tech_last_name = forms.CharField(
        max_length=30,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'Last name',
        }),
    )
    tech_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'tech@yourbusiness.com',
        }),
    )
    tech_phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': '(555) 987-6543',
        }),
    )
    add_self = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500',
        }),
        label='Add myself as a technician',
    )
    # Only shown when the shop does both services; single-service shops
    # set these automatically from what the shop does.
    tech_can_repair = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500',
        }),
        label='Does repairs',
    )
    tech_can_replace = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500',
        }),
        label='Does replacements',
    )

    def clean(self):
        cleaned = super().clean()
        # Adding someone else requires an email — without one there is no
        # way to send them a login invite and the account is stranded.
        if not cleaned.get('add_self'):
            has_info = any(
                cleaned.get(f) for f in ('tech_first_name', 'tech_last_name', 'tech_phone')
            )
            if has_info and not cleaned.get('tech_email'):
                self.add_error(
                    'tech_email',
                    "Please add their email — that's how they get their login link.",
                )
        return cleaned


class OnboardingCustomerForm(forms.Form):
    """Step 3: Add first customer."""

    CUSTOMER_TYPE_CHOICES = [
        ('FLEET', 'Fleet Account'),
        ('RETAIL', 'Individual / Retail'),
        ('WALK_IN', 'Walk-In'),
    ]

    customer_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'e.g. Acme Trucking',
        }),
    )
    customer_type = forms.ChoiceField(
        choices=CUSTOMER_TYPE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white',
        }),
    )
    customer_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': 'contact@customer.com',
        }),
    )
    customer_phone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
            'placeholder': '(555) 456-7890',
        }),
    )


# ------------------------------------------------------------------
# Replacement Form
# ------------------------------------------------------------------

class ReplacementForm(forms.ModelForm):
    """Form for creating a new glass replacement."""

    class Meta:
        model = Replacement
        fields = [
            'customer', 'technician', 'unit_number',
            'glass_position', 'glass_type', 'nags_number',
            'parts_cost', 'labor_cost',
            'requires_adas_calibration', 'adas_calibration_cost',
            'insurance_claim', 'insurance_company', 'claim_number', 'deductible',
            'description',
            'damage_photo_before', 'damage_photo_after',
        ]
        widgets = {
            'customer': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white',
            }),
            'technician': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white',
            }),
            'unit_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': 'e.g. T-1045 or 2023 Toyota Camry',
            }),
            'glass_position': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white',
            }),
            'glass_type': forms.Select(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition bg-white',
            }),
            'nags_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': 'e.g. FW04567',
            }),
            'parts_cost': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
            }),
            'labor_cost': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
            }),
            'requires_adas_calibration': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500',
                'id': 'adas-checkbox',
            }),
            'adas_calibration_cost': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
                'id': 'adas-cost',
            }),
            'insurance_claim': forms.CheckboxInput(attrs={
                'class': 'h-4 w-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500',
                'id': 'insurance-checkbox',
            }),
            'insurance_company': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': 'e.g. State Farm',
            }),
            'claim_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': 'Claim #',
            }),
            'deductible': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full px-4 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': 'Additional notes about this replacement...',
                'rows': 3,
            }),
            'damage_photo_before': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100',
                'accept': 'image/*',
            }),
            'damage_photo_after': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['customer'].queryset = Customer.objects.filter(tenant=tenant)
            self.fields['technician'].queryset = Technician.objects.filter(
                tenant=tenant, can_replace=True, is_active=True
            )
