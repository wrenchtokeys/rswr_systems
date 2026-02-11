#!/usr/bin/env python
"""
Quick script to reset a tenant back to trial for testing.
Run via: python manage.py shell < reset_tenant_to_trial.py
Or on EB: eb ssh then run in Django shell
"""
import django
django.setup()

from apps.tenants.models import Tenant, SubscriptionPlan

# Find the tenant (Rockstar Windshield Repair based on screenshot)
tenant = Tenant.objects.filter(name__icontains='Rockstar').first()
if not tenant:
    tenant = Tenant.objects.first()

print(f"Found tenant: {tenant.name} (current plan: {tenant.plan})")

# Get trial plan
trial_plan = SubscriptionPlan.objects.filter(slug='trial').first()

# Reset to trial
tenant.plan = 'trial'
tenant.subscription_plan = trial_plan
tenant.subscription_status = 'trialing'
tenant.stripe_subscription_id = ''
tenant.save()

print(f"Reset {tenant.name} to trial plan")
print(f"  plan: {tenant.plan}")
print(f"  subscription_status: {tenant.subscription_status}")
print(f"  stripe_subscription_id: '{tenant.stripe_subscription_id}'")
