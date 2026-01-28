"""
Vehicle Model - Represents a vehicle that receives glass services.

For FLEET customers: Vehicles are identified by unit_number (fleet ID).
For RETAIL customers: Vehicles are identified by year/make/model.
For WALK_INS: Vehicle info captured at time of service (minimal).

This model bridges fleet and retail worlds — the same repair workflow
applies regardless of customer type.

Author: Amelia (Clawdbot AI)
"""

from django.db import models


class Vehicle(models.Model):
    """
    A vehicle that receives glass services.
    
    Usage by customer type:
    - Fleet: unit_number is primary identifier (e.g., "Truck #4521")
    - Retail: year/make/model is primary (e.g., "2024 Ford F-150")
    - Walk-in: minimal info, maybe just make/model
    """
    
    customer = models.ForeignKey(
        'core.Customer',
        on_delete=models.CASCADE,
        related_name='vehicles',
    )
    
    # Fleet identifier (primary for fleet customers)
    unit_number = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text="Fleet unit number (e.g., 'Truck #4521'). Primary ID for fleet vehicles."
    )
    
    # Vehicle details (primary for retail customers)
    year = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Vehicle model year (e.g., 2024)"
    )
    make = models.CharField(
        max_length=50, blank=True,
        help_text="Vehicle make (e.g., Ford, Peterbilt)"
    )
    model = models.CharField(
        max_length=50, blank=True,
        help_text="Vehicle model (e.g., F-150, 389)"
    )
    vin = models.CharField(
        max_length=17, blank=True,
        help_text="Vehicle Identification Number (17 characters)"
    )
    
    # Glass details
    GLASS_TYPE_CHOICES = [
        ('WINDSHIELD', 'Windshield'),
        ('FRONT_LEFT', 'Front Left Window'),
        ('FRONT_RIGHT', 'Front Right Window'),
        ('REAR_LEFT', 'Rear Left Window'),
        ('REAR_RIGHT', 'Rear Right Window'),
        ('REAR', 'Rear Window'),
        ('SUNROOF', 'Sunroof'),
        ('OTHER', 'Other'),
    ]
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['customer', 'unit_number', 'make', 'model']
        indexes = [
            models.Index(fields=['customer', 'unit_number']),
            models.Index(fields=['vin']),
        ]
    
    def __str__(self):
        if self.unit_number:
            return f"{self.unit_number} ({self.display_name})"
        return self.display_name
    
    @property
    def display_name(self):
        """Human-readable vehicle description."""
        parts = []
        if self.year:
            parts.append(str(self.year))
        if self.make:
            parts.append(self.make)
        if self.model:
            parts.append(self.model)
        if parts:
            return ' '.join(parts)
        if self.unit_number:
            return f"Unit #{self.unit_number}"
        return "Unknown Vehicle"
    
    @property  
    def identifier(self):
        """Primary identifier based on customer type."""
        if self.unit_number:
            return self.unit_number
        return self.display_name
