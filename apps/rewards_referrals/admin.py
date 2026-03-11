from django.contrib import admin
from django.utils import timezone
from .models import ReferralCode, Referral, Reward, RewardOption, RewardRedemption, RewardType

@admin.register(RewardRedemption)
class RewardRedemptionAdmin(admin.ModelAdmin):
    """
    Admin configuration for RewardRedemption model.
    
    Provides an interface for admins to manage reward redemptions, including
    assigning technicians, updating statuses, and viewing associated details.
    """
    list_display = [
        'id', 
        'get_customer_email', 
        'reward_option', 
        'status', 
        'assigned_technician',
        'get_applied_to_repair',
        'created_at', 
        'processed_at'
    ]
    list_filter = ['status', 'assigned_technician', 'created_at']
    search_fields = [
        'reward__customer_user__user__email',
        'reward_option__name',
        'notes'
    ]
    # autocomplete_fields where target admins have search_fields defined
    autocomplete_fields = ['reward_option', 'processed_by', 'assigned_technician', 'applied_to_repair']
    raw_id_fields = ['reward']  # Reward admin has search_fields but reward__customer_user chain is complex
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'processed_at', 'fulfilled_at']
    list_per_page = 25
    
    fieldsets = [
        ('Redemption Information', {
            'fields': ['reward', 'reward_option', 'status', 'notes']
        }),
        ('Assignment Details', {
            'fields': ['assigned_technician', 'applied_to_repair']
        }),
        ('Processing Details', {
            'fields': ['processed_by', 'processed_at', 'fulfilled_at'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at'],
            'classes': ['collapse']
        }),
    ]
    
    def get_customer_email(self, obj):
        """
        Get the email of the customer who redeemed the reward.
        
        Args:
            obj (RewardRedemption): The redemption object
            
        Returns:
            str: The customer's email address
        """
        return obj.reward.customer_user.user.email
    get_customer_email.short_description = 'Customer'
    get_customer_email.admin_order_field = 'reward__customer_user__user__email'
    
    def get_applied_to_repair(self, obj):
        """
        Display information about the repair this redemption was applied to.
        
        Args:
            obj (RewardRedemption): The redemption object
            
        Returns:
            str: Description of the repair or "Not applied"
        """
        if obj.applied_to_repair:
            return f"Unit #{obj.applied_to_repair.unit_number} - {obj.applied_to_repair.damage_type}"
        return "Not applied"
    get_applied_to_repair.short_description = 'Applied To Repair'
    
    def save_model(self, request, obj, form, change):
        """
        Custom save method to track who processed a redemption and when.
        
        When the status is changed, this automatically records the admin
        who made the change and the timestamp.
        
        Args:
            request: The HTTP request
            obj (RewardRedemption): The redemption object being saved
            form: The form being used to edit the object
            change (bool): Whether this is a change to an existing object
        """
        if change and 'status' in form.changed_data:
            # If status is being changed, record who processed it
            if obj.status in ['APPROVED', 'FULFILLED', 'REJECTED']:
                obj.processed_by = request.user
                obj.processed_at = timezone.now()
                
                # If status is fulfilled, also set fulfilled_at
                if obj.status == 'FULFILLED' and not obj.fulfilled_at:
                    obj.fulfilled_at = timezone.now()
                    
        super().save_model(request, obj, form, change)

@admin.register(RewardOption)
class RewardOptionAdmin(admin.ModelAdmin):
    """
    Admin configuration for RewardOption model.
    
    Provides an interface for admins to manage reward options, including
    setting point requirements and activating/deactivating options.
    """
    list_display = ['name', 'points_required', 'get_reward_type', 'is_active']
    list_filter = ['is_active', 'reward_type__category']
    search_fields = ['name', 'description']
    list_editable = ['points_required', 'is_active']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at']
    list_per_page = 25
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'description', 'points_required', 'is_active']
        }),
        ('Reward Type', {
            'fields': ['reward_type']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]
    
    def get_reward_type(self, obj):
        """
        Get the reward type name for display in the admin list.
        
        Args:
            obj (RewardOption): The reward option object
            
        Returns:
            str: The reward type name or "No Type" if none is set
        """
        return obj.reward_type.name if obj.reward_type else "No Type"
    get_reward_type.short_description = 'Reward Type'

@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    """
    Admin configuration for Reward model.
    
    Provides an interface for admins to view and manage customer reward points.
    """
    list_display = ['customer_email', 'points', 'created_at', 'updated_at']
    search_fields = ['customer_user__user__email']
    list_filter = ['created_at']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    list_per_page = 25
    
    fieldsets = [
        ('Customer Information', {
            'fields': ['customer_user']
        }),
        ('Reward Points', {
            'fields': ['points']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]
    
    def customer_email(self, obj):
        """
        Get the email of the customer associated with this reward.
        
        Args:
            obj (Reward): The reward object
            
        Returns:
            str: The customer's email address
        """
        return obj.customer_user.user.email
    customer_email.short_description = 'Customer'
    customer_email.admin_order_field = 'customer_user__user__email'

@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    """
    Admin configuration for ReferralCode model.
    
    Provides an interface for admins to view and manage customer referral codes.
    """
    list_display = ['code', 'customer_email', 'created_at', 'get_referral_count']
    search_fields = ['code', 'customer_user__user__email']
    list_filter = ['created_at']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'
    list_per_page = 25
    
    fieldsets = [
        ('Referral Code', {
            'fields': ['code', 'customer_user']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]
    
    def customer_email(self, obj):
        """
        Get the email of the customer associated with this referral code.
        
        Args:
            obj (ReferralCode): The referral code object
            
        Returns:
            str: The customer's email address
        """
        return obj.customer_user.user.email
    customer_email.short_description = 'Customer'
    customer_email.admin_order_field = 'customer_user__user__email'
    
    def get_referral_count(self, obj):
        """
        Get the count of successful referrals using this code.
        
        Args:
            obj (ReferralCode): The referral code object
            
        Returns:
            int: Number of successful referrals
        """
        return Referral.objects.filter(referral_code=obj).count()
    get_referral_count.short_description = 'Referral Count'

@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    """
    Admin configuration for Referral model.
    
    Provides an interface for admins to view and manage customer referrals.
    Displays both the referrer and the referred customer for each referral.
    """
    list_display = ['referrer_email', 'referred_email', 'created_at']
    search_fields = ['referral_code__customer_user__user__email', 'customer_user__user__email']
    list_filter = ['created_at']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    list_per_page = 25
    
    fieldsets = [
        ('Referral Details', {
            'fields': ['referral_code', 'customer_user']
        }),
        ('Timestamps', {
            'fields': ['created_at'],
            'classes': ['collapse']
        }),
    ]
    
    def referrer_email(self, obj):
        """
        Get the email of the customer who made the referral.
        
        Args:
            obj (Referral): The referral object
            
        Returns:
            str: The referrer's email address
        """
        return obj.referral_code.customer_user.user.email
    referrer_email.short_description = 'Referrer'
    referrer_email.admin_order_field = 'referral_code__customer_user__user__email'
    
    def referred_email(self, obj):
        """
        Get the email of the customer who was referred.
        
        Args:
            obj (Referral): The referral object
            
        Returns:
            str: The referred customer's email address
        """
        return obj.customer_user.user.email
    referred_email.short_description = 'Referred User'
    referred_email.admin_order_field = 'customer_user__user__email'

@admin.register(RewardType)
class RewardTypeAdmin(admin.ModelAdmin):
    """
    Admin configuration for RewardType model.
    
    Provides an interface for admins to manage different types of rewards,
    including discount types, values, and categories.
    """
    list_display = ['name', 'category', 'discount_type', 'discount_value', 'is_active']
    list_filter = ['category', 'discount_type', 'is_active']
    search_fields = ['name', 'description']
    list_editable = ['discount_value', 'is_active']
    list_per_page = 25
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['name', 'description', 'is_active']
        }),
        ('Reward Classification', {
            'fields': ['category']
        }),
        ('Discount Details', {
            'fields': ['discount_type', 'discount_value']
        }),
    ] 