"""Shared test helpers for tenant isolation tests."""

from decimal import Decimal

from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan


def make_tenant(name, username):
    """Create a tenant with an owner user and membership."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'display_order': 0},
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'pass')
    tenant = Tenant.objects.create(
        name=name, slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user, subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant
