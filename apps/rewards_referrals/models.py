from django.db import models
from django.db.models import Q
from django.utils import timezone
from apps.customer_portal.models import CustomerUser

class ReferralCode(models.Model):
    """
    Stores unique referral codes associated with customer users.
    
    Each customer can have one referral code that they can share with others.
    When a new customer uses this code during registration, both customers 
    receive reward points.
    """
    code = models.CharField(max_length=20, unique=True)
    customer_user = models.ForeignKey(CustomerUser, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.code
    
class Referral(models.Model):
    """
    Tracks successful referrals when new customers use a referral code.
    
    Each record represents a successful referral where a new customer used
    an existing customer's referral code. This triggers reward points for both
    the referrer and the new customer.
    """
    referral_code = models.ForeignKey(ReferralCode, on_delete=models.CASCADE)
    customer_user = models.ForeignKey(CustomerUser, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class RewardType(models.Model):
    """
    Defines types of rewards and how they should be applied.
    
    This model specifies different categories of rewards (repair discounts,
    merchandise, etc.) and how the discount should be calculated (percentage,
    fixed amount, etc.).
    """
    REWARD_CATEGORY_CHOICES = [
        ('REPAIR_DISCOUNT', 'Repair Discount'),
        ('REPLACEMENT_DISCOUNT', 'Replacement Discount'),
        ('FREE_SERVICE', 'Free Service'),
        ('MERCHANDISE', 'Merchandise'),
        ('GIFT_CARD', 'Gift Card'),
        ('OTHER', 'Other'),
    ]
    
    DISCOUNT_TYPE_CHOICES = [
        ('PERCENTAGE', 'Percentage Discount'),
        ('FIXED_AMOUNT', 'Fixed Amount Discount'),
        ('FREE', 'Free (100% Off)'),
        ('NONE', 'No Discount'),
    ]
    
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, choices=REWARD_CATEGORY_CHOICES)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default='NONE')
    discount_value = models.DecimalField(max_digits=5, decimal_places=2, default=0, 
                                       help_text="Percentage or fixed amount, depending on discount type")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        """
        Returns a string representation based on the discount type.
        
        For percentage discounts: "{name} - {value}% off"
        For fixed amounts: "{name} - ${value} off"
        For free items: "{name} - Free"
        Otherwise: Just the name
        """
        if self.discount_type == 'PERCENTAGE':
            return f"{self.name} - {self.discount_value}% off"
        elif self.discount_type == 'FIXED_AMOUNT':
            return f"{self.name} - ${self.discount_value} off"
        elif self.discount_type == 'FREE':
            return f"{self.name} - Free"
        else:
            return self.name

class Reward(models.Model):
    """
    Tracks point balances for customers.

    Each customer has one reward record that keeps track of their current
    point balance. Points are earned through referrals and can be spent
    on reward redemptions.
    """
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='rewards',
        null=True,
        blank=True,
    )
    customer_user = models.ForeignKey(CustomerUser, on_delete=models.CASCADE)
    points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.customer_user.user.email} - {self.points} points"
    
class RewardOption(models.Model):
    """
    Defines available redemption options for customers.

    Each option represents something a customer can redeem their points for,
    such as a discount on a repair, free merchandise, etc. Each option has
    a point cost and is associated with a reward type.
    """
    # Multi-tenant support
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='reward_options',
        null=True,  # Nullable during migration transition
        blank=True,
    )

    name = models.CharField(max_length=100)
    description = models.TextField()
    points_required = models.PositiveIntegerField()
    reward_type = models.ForeignKey(RewardType, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """
        Sorts reward options by the number of points required (ascending).
        """
        ordering = ['points_required']

    def __str__(self):
        return f"{self.name} ({self.points_required} points)"
    
class RewardRedemption(models.Model):
    """
    Tracks redemption requests and their fulfillment status.
    
    When a customer redeems points for a reward, a redemption record is created
    and progresses through various statuses (pending, approved, fulfilled, rejected).
    Technicians can be assigned to fulfill redemptions, and redemptions can be
    applied to specific repairs.
    """
    REDEMPTION_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('FULFILLED', 'Fulfilled'),
        ('REJECTED', 'Rejected'),
    ]
    
    reward = models.ForeignKey(Reward, on_delete=models.CASCADE)
    reward_option = models.ForeignKey(RewardOption, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=REDEMPTION_STATUS_CHOICES,
        default='PENDING'
    )
    notes = models.TextField(blank=True, null=True)
    processed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_redemptions'
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    assigned_technician = models.ForeignKey(
        'technician_portal.Technician',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_redemptions'
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    applied_to_repair = models.ForeignKey('technician_portal.Repair', on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='applied_rewards')
    preferred_date = models.DateField(
        null=True, blank=True,
        help_text="Customer's preferred delivery/fulfillment date"
    )
    preferred_time = models.TimeField(
        null=True, blank=True,
        help_text="Customer's preferred time"
    )
    customer_notes = models.TextField(
        blank=True,
        help_text="Special requests from customer"
    )

    class Meta:
        """
        Sorts redemptions by creation date (newest first).
        """
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reward.customer_user.user.email} - {self.reward_option.name} ({self.status})"


class PointTransaction(models.Model):
    """
    Immutable ledger of all point changes. Every earn/spend creates one row.
    The running balance is stored in balance_after for fast reads.
    """
    TRANSACTION_TYPE_CHOICES = [
        ('repair_complete', 'Repair Complete'),
        ('referral_made', 'Referral Made'),
        ('referral_received', 'Referral Received'),
        ('milestone_bonus', 'Milestone Bonus'),
        ('early_pay_bonus', 'Early Pay Bonus'),
        ('review_bonus', 'Review Bonus'),
        ('tier_bonus', 'Tier Bonus'),
        ('manual_adjustment', 'Manual Adjustment'),
        ('redemption', 'Redemption'),
        ('expiration', 'Expiration'),
    ]

    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='point_transactions',
    )
    customer_user = models.ForeignKey(
        'customer_portal.CustomerUser', on_delete=models.CASCADE,
        related_name='point_transactions',
    )
    amount = models.IntegerField(help_text='Positive for earn, negative for spend')
    balance_after = models.IntegerField(help_text='Running balance after this transaction')
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPE_CHOICES)
    description = models.CharField(max_length=255)

    related_repair = models.ForeignKey(
        'technician_portal.Repair', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='point_transactions',
    )
    related_redemption = models.ForeignKey(
        'rewards_referrals.RewardRedemption', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='point_transactions',
    )
    related_payment = models.ForeignKey(
        'billing.Payment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='point_transactions',
    )

    expires_at = models.DateTimeField(null=True, blank=True)
    expired = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_point_transactions',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer_user', '-created_at']),
            models.Index(fields=['tenant', 'transaction_type']),
            models.Index(
                fields=['expires_at'],
                condition=models.Q(expired=False, expires_at__isnull=False),
                name='idx_pt_unexpired',
            ),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{self.customer_user} {sign}{self.amount} ({self.transaction_type})"


class LoyaltyConfig(models.Model):
    """Per-tenant loyalty program configuration."""
    tenant = models.OneToOneField(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='loyalty_config',
    )
    points_per_repair = models.PositiveIntegerField(default=50)
    referral_bonus_referrer = models.PositiveIntegerField(default=500)
    referral_bonus_referred = models.PositiveIntegerField(default=100)
    milestone_5_bonus = models.PositiveIntegerField(default=250)
    milestone_10_bonus = models.PositiveIntegerField(default=500)
    milestone_25_bonus = models.PositiveIntegerField(default=1000)
    points_for_review = models.PositiveIntegerField(default=100)
    points_for_early_payment = models.PositiveIntegerField(default=25)
    points_expiry_days = models.PositiveIntegerField(
        default=365, help_text='0 = never expire',
    )
    expiry_warning_days = models.PositiveIntegerField(default=30)
    program_name = models.CharField(max_length=100, default='Rewards')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Loyalty Configuration'
        verbose_name_plural = 'Loyalty Configurations'

    def __str__(self):
        return f"{self.tenant.name} — {self.program_name}"

    @classmethod
    def get_for_tenant(cls, tenant):
        """get_or_create pattern — always returns a LoyaltyConfig."""
        config, _created = cls.objects.get_or_create(tenant=tenant)
        return config
