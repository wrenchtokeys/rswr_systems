from django.db import models
from django.contrib.auth.models import User
from core.models import Customer


class CustomerPricing(models.Model):
    """Custom pricing configuration for specific customers"""

    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='pricing')
    use_custom_pricing = models.BooleanField(
        default=False,
        help_text="Enable custom pricing for this customer"
    )

    # Custom pricing tiers
    repair_1_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price for first repair (default: $50)"
    )
    repair_2_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price for second repair (default: $40)"
    )
    repair_3_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price for third repair (default: $35)"
    )
    repair_4_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price for fourth repair (default: $30)"
    )
    repair_5_plus_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Price for fifth+ repairs (default: $25)"
    )

    # Volume discounts
    volume_discount_threshold = models.IntegerField(
        default=10,
        help_text="Number of repairs needed to qualify for volume discount"
    )
    volume_discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentage discount (e.g., 10.00 for 10%)"
    )

    # Tracking fields
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        help_text="User who created this pricing configuration"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(
        blank=True,
        help_text="Internal notes about this pricing arrangement"
    )

    class Meta:
        verbose_name = "Customer Pricing"
        verbose_name_plural = "Customer Pricing"
        ordering = ['customer__name']

    def __str__(self):
        status = "Custom" if self.use_custom_pricing else "Default"
        return f"{self.customer.name} - {status} Pricing"

    def get_repair_price(self, repair_count):
        """Get the price for a repair based on repair count.

        Returns the custom price for the given tier, or None if the tier has not
        been configured (field is NULL) — signalling the caller to fall back to
        default/tenant pricing.

        Important: use ``is not None`` to test whether a tier is configured.
        ``Decimal('0.00')`` is falsy in Python, so a bare truthiness check like
        ``if self.repair_1_price:`` would treat an intentional $0 custom price
        (free service, warranty account, etc.) as "not configured" and silently
        fall back to the standard rate.  This is the same Decimal-falsy bug
        documented in AGENTS.md and previously fixed in CODE-132 / CODE-151.
        """
        if not self.use_custom_pricing:
            return None  # Use default pricing

        if repair_count == 1 and self.repair_1_price is not None:
            return self.repair_1_price
        elif repair_count == 2 and self.repair_2_price is not None:
            return self.repair_2_price
        elif repair_count == 3 and self.repair_3_price is not None:
            return self.repair_3_price
        elif repair_count == 4 and self.repair_4_price is not None:
            return self.repair_4_price
        elif repair_count >= 5 and self.repair_5_plus_price is not None:
            return self.repair_5_plus_price

        # If specific tier not set, return None to use default
        return None

    def has_volume_discount(self, total_repairs):
        """Check if customer qualifies for volume discount"""
        return total_repairs >= self.volume_discount_threshold and self.volume_discount_percentage > 0

    def apply_volume_discount(self, price, total_repairs):
        """Apply volume discount to a price if applicable"""
        if self.has_volume_discount(total_repairs):
            discount_multiplier = 1 - (self.volume_discount_percentage / 100)
            return price * discount_multiplier
        return price