"""
Customer Portal Forms

Django Forms: These classes automatically generate HTML forms from your models
and handle validation. This is one of Django's most powerful features!
"""

from django import forms
from .models import CustomerRepairPreference
from core.models.notification_preferences import CustomerNotificationPreference


class RepairPreferenceForm(forms.ModelForm):
    """
    Form for CustomerRepairPreference model.

    ModelForm automatically creates form fields from your model fields.
    You just specify which model and which fields to include!
    """

    # Days of week for lot walking (multi-select checkboxes)
    DAYS_OF_WEEK = [
        ('Monday', 'Monday'),
        ('Tuesday', 'Tuesday'),
        ('Wednesday', 'Wednesday'),
        ('Thursday', 'Thursday'),
        ('Friday', 'Friday'),
        ('Saturday', 'Saturday'),
        ('Sunday', 'Sunday'),
    ]

    # Override the lot_walking_days field to make it checkbox-friendly
    lot_walking_days_choices = forms.MultipleChoiceField(
        choices=DAYS_OF_WEEK,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Preferred Days for Lot Walking",
        help_text="Select all days that work for your schedule"
    )

    class Meta:
        model = CustomerRepairPreference
        fields = [
            'field_repair_approval_mode',
            'units_per_visit_threshold',
            'lot_walking_enabled',
            'lot_walking_frequency',
            'lot_walking_time',
            # Billing & Invoicing
            'invoice_preference',
            'billing_email',
            'auto_email_invoices',
        ]

        # Customize how fields appear in the form
        widgets = {
            'field_repair_approval_mode': forms.RadioSelect(),  # Radio buttons instead of dropdown
            'units_per_visit_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '50'
            }),
            'lot_walking_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'invoice_preference': forms.RadioSelect(),
            'billing_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'billing@yourcompany.com'
            }),
        }

        # Custom labels (what users see)
        labels = {
            'field_repair_approval_mode': 'Field Repair Approval Mode',
            'units_per_visit_threshold': 'Units Per Visit Threshold',
            'lot_walking_enabled': 'Enable Lot Walking Service',
            'lot_walking_frequency': 'Lot Walking Frequency',
            'lot_walking_time': 'Preferred Time',
            'invoice_preference': 'Invoice Generation Mode',
            'billing_email': 'Billing Email Address',
            'auto_email_invoices': 'Automatically Email Invoices',
        }

    def __init__(self, *args, **kwargs):
        """
        Custom initialization to pre-populate the days checkboxes
        from the JSONField data
        """
        super().__init__(*args, **kwargs)

        # If editing existing preference, populate the days checkboxes
        if self.instance and self.instance.pk and self.instance.lot_walking_days:
            self.fields['lot_walking_days_choices'].initial = self.instance.lot_walking_days

    def save(self, commit=True):
        """
        Custom save method to handle the days checkboxes
        and save them to the JSONField
        """
        instance = super().save(commit=False)

        # Convert checkbox selections to list and store in JSONField
        instance.lot_walking_days = self.cleaned_data.get('lot_walking_days_choices', [])

        if commit:
            instance.save()

        return instance


class CustomerNotificationPreferenceForm(forms.ModelForm):
    """
    Form for customer notification preferences.

    Allows customers to control:
    - Notification delivery channels (email, SMS, in-app)
    - Notification categories (approvals, completions, etc.)
    - Batch mode for pending approvals
    - Quiet hours settings
    """

    class Meta:
        model = CustomerNotificationPreference
        fields = [
            # Global preferences
            'receive_email_notifications',
            'receive_sms_notifications',
            'receive_in_app_notifications',

            # Customer-specific categories
            'notify_new_requests',
            'notify_pending_approvals',
            'notify_completions',
            'notify_in_progress',
            'notify_repair_status',
            'notify_rewards',
            'notify_system',

            # Batch notifications
            'batch_pending_approvals',

            # Quiet hours
            'quiet_hours_enabled',
            'quiet_hours_start',
            'quiet_hours_end',
        ]

        widgets = {
            'quiet_hours_start': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'quiet_hours_end': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        }

        help_texts = {
            'receive_sms_notifications': 'Receive urgent notifications via text message (standard SMS rates may apply)',
            'quiet_hours_enabled': 'Pause non-urgent notifications during specified hours',
            'batch_pending_approvals': 'Receive one daily summary of pending approvals instead of individual notifications',
            'notify_pending_approvals': 'Get notified when repairs require your approval',
            'notify_completions': 'Get notified when repairs are completed',
            'notify_new_requests': 'Get notified when new repair requests are created',
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

        return cleaned_data
