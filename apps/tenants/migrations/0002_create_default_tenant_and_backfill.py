"""
Data migration: Create default tenant and backfill all existing records.

This ensures all existing data from the single-tenant era gets assigned
to the 'Rockstar Windshield Repair' tenant, maintaining backward compatibility.
"""

from django.db import migrations


def create_default_tenant_and_backfill(apps, schema_editor):
    """Create default tenant and assign all existing records to it."""
    Tenant = apps.get_model('tenants', 'Tenant')
    TenantMembership = apps.get_model('tenants', 'TenantMembership')
    User = apps.get_model('auth', 'User')
    Customer = apps.get_model('core', 'Customer')
    Vehicle = apps.get_model('core', 'Vehicle')
    Technician = apps.get_model('technician_portal', 'Technician')
    UnitRepairCount = apps.get_model('technician_portal', 'UnitRepairCount')
    Repair = apps.get_model('technician_portal', 'Repair')
    Replacement = apps.get_model('technician_portal', 'Replacement')
    Invoice = apps.get_model('billing', 'Invoice')
    
    # Find an owner — prefer the first superuser, otherwise first user
    owner = User.objects.filter(is_superuser=True).first()
    if not owner:
        owner = User.objects.first()
    
    if not owner:
        # No users exist — skip (fresh install, no data to backfill)
        return
    
    # Create the default tenant
    tenant = Tenant.objects.create(
        name='Rockstar Windshield Repair',
        slug='rockstar-windshield',
        subdomain='rockstar',
        owner=owner,
        business_phone='',
        business_email='',
        business_address='',
        is_active=True,
        plan='pro',
    )
    
    # Create memberships for all existing users
    for user in User.objects.all():
        if user == owner:
            role = 'owner'
        elif hasattr(user, 'technician'):
            role = 'technician'
        else:
            role = 'viewer'
        TenantMembership.objects.create(
            tenant=tenant,
            user=user,
            role=role,
            is_active=True,
        )
    
    # Backfill all business models
    Customer.objects.filter(tenant__isnull=True).update(tenant=tenant)
    Vehicle.objects.filter(tenant__isnull=True).update(tenant=tenant)
    Technician.objects.filter(tenant__isnull=True).update(tenant=tenant)
    UnitRepairCount.objects.filter(tenant__isnull=True).update(tenant=tenant)
    Repair.objects.filter(tenant__isnull=True).update(tenant=tenant)
    Replacement.objects.filter(tenant__isnull=True).update(tenant=tenant)
    Invoice.objects.filter(tenant__isnull=True).update(tenant=tenant)


def reverse_backfill(apps, schema_editor):
    """Reverse: set all tenant FKs to NULL and delete default tenant."""
    Tenant = apps.get_model('tenants', 'Tenant')
    Customer = apps.get_model('core', 'Customer')
    Vehicle = apps.get_model('core', 'Vehicle')
    Technician = apps.get_model('technician_portal', 'Technician')
    UnitRepairCount = apps.get_model('technician_portal', 'UnitRepairCount')
    Repair = apps.get_model('technician_portal', 'Repair')
    Replacement = apps.get_model('technician_portal', 'Replacement')
    Invoice = apps.get_model('billing', 'Invoice')
    
    Customer.objects.all().update(tenant=None)
    Vehicle.objects.all().update(tenant=None)
    Technician.objects.all().update(tenant=None)
    UnitRepairCount.objects.all().update(tenant=None)
    Repair.objects.all().update(tenant=None)
    Replacement.objects.all().update(tenant=None)
    Invoice.objects.all().update(tenant=None)
    
    Tenant.objects.filter(slug='rockstar-windshield').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_create_tenant_and_membership'),
        ('core', '0012_add_tenant_fk'),
        ('technician_portal', '0023_add_tenant_fk'),
        ('billing', '0002_add_tenant_fk'),
        ('auth', '__latest__'),
    ]

    operations = [
        migrations.RunPython(
            create_default_tenant_and_backfill,
            reverse_backfill,
        ),
    ]
