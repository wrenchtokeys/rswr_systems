"""
Repair the NULL-vs-0.00 ambiguity on Tenant.platform_fee_percent.

`NULL` is supposed to mean "use the global default" and a literal `0.00`
"explicitly zero-rated" (a comped shop). That distinction has never
actually worked:

- migration 0011 added the column as `default=0`, NOT NULL, so every tenant
  in existence got a literal 0.00;
- migration 0012 made it nullable but did not backfill.

So every pre-0012 tenant carries an explicit 0.00 that silently beats any
global rate. The trap is documented in docs/deployment/STRIPE_ARCHITECTURE.md
and has bitten once already; leaving the data alone guarantees it bites again
the first time a global fee is set.

Nobody has ever deliberately zero-rated a shop: there are zero
PlatformFeeRecord rows and PlatformConfig.default_fee_percent itself
defaults to 0.00, so the field has never had operational meaning. Every
0.00 in the table is migration 0011's default, not an intent.

**This migration changes nothing about money on the day it runs.** The
global default stays 0.00 and PlatformConfig.fee_enabled ships False, so
the resolved fee is zero either way. It only restores the semantics, so
that when a fee IS switched on it applies to the tenants it should.

Kept separate from the schema migration (0025) so it can be reviewed, and
reverted, on its own.
"""

from decimal import Decimal

from django.db import migrations


def zero_to_null(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    updated = Tenant.objects.filter(platform_fee_percent=Decimal('0.00')).update(
        platform_fee_percent=None,
    )
    if updated:
        print(
            f"\n  Cleared {updated} legacy platform_fee_percent=0.00 override(s) "
            f"to NULL (use global default)."
        )


def null_to_zero(apps, schema_editor):
    """Reverse: restore the legacy 'explicit 0.00 everywhere' state.

    Lossy in principle -- a genuinely comped shop set to 0.00 after this
    migration would be indistinguishable from one that was never set. There
    are none today, and the reverse exists so the migration is not a
    one-way door.
    """
    Tenant = apps.get_model('tenants', 'Tenant')
    Tenant.objects.filter(platform_fee_percent__isnull=True).update(
        platform_fee_percent=Decimal('0.00'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0025_tenant_platform_fee_fixed_cents_and_more'),
    ]

    operations = [
        migrations.RunPython(zero_to_null, null_to_zero),
    ]
