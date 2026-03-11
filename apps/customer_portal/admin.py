from django.contrib import admin
from django import forms
from .models import CustomerUser, CustomerPreference, RepairApproval, CustomerRepairPreference, CustomerInvitation
from .pricing_models import CustomerPricing

# Custom admin class for CustomerUser model
class CustomerUserAdmin(admin.ModelAdmin):
    # Define the fields to display in the list view
    list_display = ['user', 'customer', 'get_email', 'get_full_name', 'is_primary_contact']
    # Define the fields to filter by in the list view
    list_filter = ['is_primary_contact', 'customer']
    # Define the fields to search by in the list view
    search_fields = ['user__username', 'user__email', 'user__first_name', 'user__last_name', 'customer__name']
    # Select related fields to improve performance
    list_select_related = ['user', 'customer']
    
    # Method to display the user's email in the list view
    def get_email(self, obj):
        return obj.user.email
    get_email.short_description = 'Email'  # Column header in the list view
    get_email.admin_order_field = 'user__email'  # Field to order by
    
    # Method to display the user's full name in the list view
    def get_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"
    get_full_name.short_description = 'Full Name'  # Column header in the list view
    get_full_name.admin_order_field = 'user__first_name'  # Field to order by
    
    # Define the layout of the form in the detail view
    fieldsets = (
        (None, {
            'fields': ('user', 'customer', 'is_primary_contact')
        }),
    )

# Custom admin class for CustomerPreference model
class CustomerPreferenceAdmin(admin.ModelAdmin):
    # Define the fields to display in the list view
    list_display = ['customer', 'receive_email_notifications', 'receive_sms_notifications', 'default_view']
    # Define the fields to filter by in the list view
    list_filter = ['receive_email_notifications', 'receive_sms_notifications', 'default_view']
    # Define the fields to search by in the list view
    search_fields = ['customer__name']

# Custom admin class for RepairApproval model
class RepairApprovalAdmin(admin.ModelAdmin):
    # Define the fields to display in the list view
    list_display = ['repair', 'approved', 'approved_by', 'approval_date']
    # Define the fields to filter by in the list view
    list_filter = ['approved', 'approval_date']
    # Define the fields to search by in the list view
    search_fields = ['repair__id', 'repair__customer__name', 'approved_by__user__username']
    # Make the approval_date field read-only
    readonly_fields = ['approval_date']

# Custom admin class for CustomerPricing model
class CustomerPricingAdmin(admin.ModelAdmin):
    list_display = ['customer', 'use_custom_pricing', 'created_at', 'created_by']
    list_filter = ['use_custom_pricing', 'created_at']
    search_fields = ['customer__name', 'notes']
    list_select_related = ['customer', 'created_by']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Customer & Settings', {
            'fields': ('customer', 'use_custom_pricing', 'notes')
        }),
        ('Custom Repair Pricing', {
            'fields': ('repair_1_price', 'repair_2_price', 'repair_3_price',
                      'repair_4_price', 'repair_5_plus_price'),
            'description': 'Set custom prices for each repair tier. Leave blank to use default pricing.'
        }),
        ('Volume Discounts', {
            'fields': ('volume_discount_threshold', 'volume_discount_percentage'),
            'description': 'Configure volume discounts for high-volume customers.'
        }),
        ('Tracking', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

# Custom form for CustomerRepairPreference with conditional validation
class CustomerRepairPreferenceForm(forms.ModelForm):
    """
    Enhanced form for CustomerRepairPreference model with lot walking configuration.

    Features:
    - Field repair approval mode selection (AUTO_APPROVE, REQUIRE_APPROVAL, UNIT_THRESHOLD)
    - Unit threshold validation (required only when using UNIT_THRESHOLD mode)
    - Lot walking service configuration with user-friendly widgets
    - Automatic conversion between JSONField storage and checkbox UI

    Lot Walking Fields:
    - lot_walking_enabled: Boolean checkbox to enable/disable service
    - lot_walking_frequency: Dropdown (Weekly/Bi-weekly/Monthly/Quarterly)
    - lot_walking_time: Time picker for preferred time
    - lot_walking_days_choices: Checkbox widget for selecting days (converts to/from JSON)
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

    # Override the lot_walking_days JSONField to make it checkbox-friendly in admin
    # This field is NOT in the model - it's a UI-only field that converts to/from JSON
    lot_walking_days_choices = forms.MultipleChoiceField(
        choices=DAYS_OF_WEEK,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Preferred Days for Lot Walking",
        help_text="Select all days that work for your schedule"
    )

    class Meta:
        model = CustomerRepairPreference
        fields = '__all__'
        widgets = {
            'lot_walking_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'vTimeField'
            }),
        }

    def __init__(self, *args, **kwargs):
        """
        Custom initialization to pre-populate the days checkboxes from JSONField data.

        When editing an existing CustomerRepairPreference, this converts the
        lot_walking_days JSONField (e.g., ['Monday', 'Wednesday', 'Friday'])
        into initial checkbox selections for the admin UI.

        Args:
            *args: Positional arguments passed to parent form
            **kwargs: Keyword arguments including 'instance' for existing objects
        """
        super().__init__(*args, **kwargs)

        # If editing existing preference, populate the days checkboxes from JSON data
        if self.instance and self.instance.pk and self.instance.lot_walking_days:
            self.fields['lot_walking_days_choices'].initial = self.instance.lot_walking_days

    def clean(self):
        """
        Validate form data with conditional requirements for approval and lot walking settings.

        Validation Rules:
        1. Field Repair Approval:
           - units_per_visit_threshold required when mode is UNIT_THRESHOLD
           - units_per_visit_threshold cleared when mode is not UNIT_THRESHOLD

        2. Lot Walking Service:
           - lot_walking_frequency required when lot_walking_enabled is True
           - lot_walking_time optional (preferred time for lot walks)
           - lot_walking_days optional (defaults to empty list if not selected)

        Returns:
            dict: Cleaned and validated form data

        Raises:
            ValidationError: If required fields are missing based on mode selection
        """
        cleaned_data = super().clean()
        approval_mode = cleaned_data.get('field_repair_approval_mode')
        threshold = cleaned_data.get('units_per_visit_threshold')
        lot_walking_enabled = cleaned_data.get('lot_walking_enabled')
        lot_walking_frequency = cleaned_data.get('lot_walking_frequency')
        lot_walking_time = cleaned_data.get('lot_walking_time')

        # Require threshold only when mode is UNIT_THRESHOLD
        if approval_mode == 'UNIT_THRESHOLD' and not threshold:
            raise forms.ValidationError({
                'units_per_visit_threshold': 'This field is required when using Unit Threshold mode.'
            })

        # Clear threshold when not using UNIT_THRESHOLD mode (prevents confusion)
        if approval_mode != 'UNIT_THRESHOLD' and threshold is not None:
            cleaned_data['units_per_visit_threshold'] = None

        # Validate lot walking settings - only frequency required if service enabled
        if lot_walking_enabled:
            if not lot_walking_frequency:
                raise forms.ValidationError({
                    'lot_walking_frequency': 'Frequency is required when lot walking is enabled.'
                })
            # Note: lot_walking_time and lot_walking_days are optional

        return cleaned_data

    def save(self, commit=True):
        """
        Custom save method to convert checkbox selections to JSONField storage.

        This method bridges the gap between the checkbox UI (lot_walking_days_choices)
        and the database JSONField (lot_walking_days). It converts selected days from
        the checkbox widget into a JSON list for storage.

        Example:
            User selects: [Monday, Wednesday, Friday] (checkboxes)
            Stored as: ['Monday', 'Wednesday', 'Friday'] (JSON)

        Args:
            commit (bool): Whether to save to database immediately (default: True)

        Returns:
            CustomerRepairPreference: The saved instance
        """
        instance = super().save(commit=False)

        # Convert checkbox selections to list and store in JSONField
        # lot_walking_days_choices is UI-only, lot_walking_days is the actual model field
        instance.lot_walking_days = self.cleaned_data.get('lot_walking_days_choices', [])

        if commit:
            instance.save()

        return instance

# Custom admin class for CustomerRepairPreference model
class CustomerRepairPreferenceAdmin(admin.ModelAdmin):
    """
    Django admin configuration for CustomerRepairPreference model.

    Features:
    - Field repair approval workflow configuration (AUTO_APPROVE, REQUIRE_APPROVAL, UNIT_THRESHOLD)
    - Lot walking service scheduling preferences
    - Enhanced list view showing approval mode and lot walking status
    - Filtering by approval mode, lot walking enabled/frequency
    - Organized fieldsets for better UX

    List Display Columns:
    - Customer name
    - Approval mode (with display name)
    - Unit threshold (if applicable)
    - Lot walking enabled (✓/✗)
    - Lot walking frequency (Weekly/Bi-weekly/Monthly/Quarterly)
    - Last updated timestamp

    Filtering Options:
    - Field repair approval mode
    - Lot walking enabled (Yes/No)
    - Lot walking frequency
    - Update date

    Fieldsets:
    1. Customer - Select which customer this preference applies to
    2. Field Repair Approval Settings - Configure approval workflow
    3. Lot Walking Service Settings - Configure lot walking schedule (NEW in v1.6.1)
    4. Tracking - Created/updated timestamps (collapsed)
    """
    form = CustomerRepairPreferenceForm
    list_display = ['customer', 'field_repair_approval_mode', 'units_per_visit_threshold', 'invoice_preference', 'auto_email_invoices', 'lot_walking_enabled', 'updated_at']
    list_filter = ['field_repair_approval_mode', 'invoice_preference', 'auto_email_invoices', 'lot_walking_enabled', 'lot_walking_frequency', 'updated_at']
    search_fields = ['customer__name']
    list_select_related = ['customer']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Customer', {
            'fields': ('customer',)
        }),
        ('Field Repair Approval Settings', {
            'fields': ('field_repair_approval_mode', 'units_per_visit_threshold'),
            'description': 'Configure how field-discovered repairs should be handled for this customer.'
        }),
        ('Lot Walking Service Settings', {
            'fields': ('lot_walking_enabled', 'lot_walking_frequency', 'lot_walking_time', 'lot_walking_days_choices'),
            'description': 'Configure scheduled lot walking service for this customer. Enable the service and set the frequency, preferred time, and days.'
        }),
        ('Invoice Settings', {
            'fields': ('invoice_preference', 'billing_email', 'auto_email_invoices', 'include_photos_in_invoice'),
            'description': 'Configure how invoices should be generated and delivered for this customer. '
                          '"Per repair" = auto-generate when each repair completes. '
                          '"Batch" = group repairs together (manual trigger). '
                          '"Manual" = never auto-generate.'
        }),
        ('Tracking', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# CustomerInvitation Admin
class CustomerInvitationAdmin(admin.ModelAdmin):
    list_display = ['email', 'customer', 'status', 'created_at', 'expires_at', 'sent_at']
    list_filter = ['status', 'created_at']
    search_fields = ['email', 'customer__name', 'first_name', 'last_name']
    readonly_fields = ['token', 'created_at', 'sent_at', 'accepted_at', 'accepted_user']
    raw_id_fields = ['customer', 'invited_by', 'accepted_user']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Invitation Details', {
            'fields': ('customer', 'email', 'first_name', 'last_name', 'status')
        }),
        ('Token & Expiry', {
            'fields': ('token', 'expires_at'),
        }),
        ('Tracking', {
            'fields': ('invited_by', 'created_at', 'sent_at', 'accepted_at', 'accepted_user'),
            'classes': ('collapse',)
        }),
    )


# Register the models with their custom admin classes
admin.site.register(CustomerUser, CustomerUserAdmin)
admin.site.register(CustomerPreference, CustomerPreferenceAdmin)
admin.site.register(RepairApproval, RepairApprovalAdmin)
admin.site.register(CustomerPricing, CustomerPricingAdmin)
admin.site.register(CustomerRepairPreference, CustomerRepairPreferenceAdmin)
admin.site.register(CustomerInvitation, CustomerInvitationAdmin) 