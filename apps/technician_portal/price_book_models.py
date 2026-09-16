"""
Shop-owned price book (IMPROVEMENT_SESSIONS B6, the third spine feature).

What it is
----------
A replacement prices itself from *this shop's* history: vehicle year/make/
model + glass position → the price this shop last charged. No licence, no
catalog, nothing shared between tenants — every row belongs to one shop,
which is why it needs nothing new architecturally (compare the repair price
ladder on Tenant and CustomerPricing).

How rows get here
-----------------
- LEARNED — written by `services.price_book.learn_from_job` when a
  replacement with a vehicle and a price is COMPLETED (Replacement.save calls
  it), and by `rebuild_for_tenant`, which replays every completed replacement
  in order so an existing shop's book fills in the moment B6 deploys
  (`manage.py seed_price_book`, or the button on the price book page).
- PINNED — the owner typed or edited the row. Learning never overwrites a
  pinned row; the shop's word beats the shop's history.
- QUOTE — a supplier quote (Mygrant, P1) applied to a job that has not been
  completed yet. Provisional: the next completed job on that vehicle turns
  it into LEARNED. Written only where no row exists or the row is itself a
  quote, so a quote can never replace a charge.

What the price is
-----------------
`price` is what the shop charges *before* any account discount — the number
that becomes `cost_override` on the job (which save() re-discounts), never
`cost` after the discount. `parts_cost` / `labor_cost` / `adas_calibration_cost`
are kept when the job had them; a job priced as one number leaves them null,
and the form JS says so instead of inventing a split.

The key
-------
(tenant, make_key, model_key, vehicle_year, glass_position). Keys are the
lower-cased, whitespace-collapsed make and model, so "Ford" and "ford " are
one truck. `vehicle_year` 0 means "any year" and only a pinned row carries
it; a learned row always has the job's year (0 there too when the job had
none). Lookup order is exact year → any-year pinned → nearest year, and the
suggestion always says which one it found — suggest, never silently apply.
"""

from decimal import Decimal

from django.db import models

from apps.tenants.managers import TenantManager
from rs_systems.model_mixins import AutoUpdateTimestampMixin

ANY_YEAR = 0


def normalize_key(text):
    """'  Ford  ' → 'ford'; None → ''. The same function on write and read."""
    return ' '.join((text or '').split()).lower()[:50]


class PriceBookEntry(AutoUpdateTimestampMixin, models.Model):
    SOURCE_LEARNED = 'LEARNED'
    SOURCE_PINNED = 'PINNED'
    SOURCE_QUOTE = 'QUOTE'
    SOURCE_CHOICES = [
        (SOURCE_LEARNED, 'Learned from a completed job'),
        (SOURCE_PINNED, 'Set by the shop'),
        (SOURCE_QUOTE, 'Supplier quote'),
    ]

    tenant = models.ForeignKey(
        'tenants.Tenant', on_delete=models.CASCADE, related_name='price_book_entries',
    )

    vehicle_make = models.CharField(max_length=50)
    vehicle_model = models.CharField(max_length=50)
    make_key = models.CharField(max_length=50, db_index=True, editable=False)
    model_key = models.CharField(max_length=50, db_index=True, editable=False)
    # 0 = any year (a pinned row that covers the whole run of a model).
    vehicle_year = models.PositiveIntegerField(default=ANY_YEAR)
    # Same choices as Replacement.glass_position; '' when the job left it blank.
    glass_position = models.CharField(max_length=20, blank=True, default='')

    parts_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    labor_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    adas_calibration_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    # What the shop charges for this glass on this vehicle, before any
    # account discount. Always set; the breakdown above may not be.
    price = models.DecimalField(max_digits=10, decimal_places=2)

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_LEARNED)
    # Distinct completed jobs this row was learned from (0 for a pinned row
    # nobody has completed a job against yet).
    times_used = models.PositiveIntegerField(default=0)
    last_job = models.ForeignKey(
        'technician_portal.Replacement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='price_book_entries',
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()

    class Meta:
        ordering = ['make_key', 'model_key', 'vehicle_year', 'glass_position']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'make_key', 'model_key', 'vehicle_year', 'glass_position'],
                name='price_book_one_row_per_vehicle_glass',
            ),
        ]
        indexes = [
            models.Index(
                fields=['tenant', 'make_key', 'model_key'], name='price_book_vehicle_idx',
            ),
        ]
        verbose_name = 'price book entry'
        verbose_name_plural = 'price book entries'

    def __str__(self):
        return f'{self.vehicle_label} {self.glass_label} — ${self.price}'

    def save(self, *args, **kwargs):
        self.vehicle_make = ' '.join((self.vehicle_make or '').split())[:50]
        self.vehicle_model = ' '.join((self.vehicle_model or '').split())[:50]
        self.make_key = normalize_key(self.vehicle_make)
        self.model_key = normalize_key(self.vehicle_model)
        if self.vehicle_year is None:
            self.vehicle_year = ANY_YEAR
        super().save(*args, **kwargs)

    # --- display -----------------------------------------------------------

    @property
    def is_any_year(self):
        return not self.vehicle_year

    @property
    def vehicle_label(self):
        """'2019 Ford F-150', or 'Ford F-150' for an any-year row."""
        parts = [] if self.is_any_year else [str(self.vehicle_year)]
        parts += [self.vehicle_make, self.vehicle_model]
        return ' '.join(p for p in parts if p)

    @property
    def glass_label(self):
        from apps.technician_portal.models import Replacement
        return dict(Replacement.GLASS_POSITION_CHOICES).get(self.glass_position, '') or 'glass'

    @property
    def has_breakdown(self):
        """True when the row knows parts and/or labor, not just one number."""
        return self.parts_cost is not None or self.labor_cost is not None

    @property
    def is_pinned(self):
        return self.source == self.SOURCE_PINNED

    @property
    def source_label(self):
        return dict(self.SOURCE_CHOICES).get(self.source, self.source)

    @staticmethod
    def total_of(parts, labor, adas):
        return sum((v for v in (parts, labor, adas) if v is not None), Decimal('0.00'))
