"""
Signup Service

Shared business logic for tenant registration.
Used by both the API endpoint (apps/tenants/views.py)
and the UI form (apps/saas/views.py).

Author: Amelia (Clawdbot AI)
"""

import logging
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan

logger = logging.getLogger(__name__)


class SignupError(Exception):
    """Raised when signup fails."""
    pass


def generate_unique_slug(business_name):
    """Generate a unique tenant slug from a business name."""
    base_slug = slugify(business_name)[:50]
    if not base_slug:
        base_slug = 'shop'
    slug = base_slug
    counter = 1
    while Tenant.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def create_tenant_with_owner(
    business_name,
    email,
    password,
    first_name='',
    last_name='',
    phone='',
):
    """
    Create a new tenant with an owner account.

    This is the canonical signup logic — used by both the API
    and the UI form to ensure consistent behavior.

    Args:
        business_name: Name of the glass shop
        email: Owner's email address (also used as username)
        password: Owner's password (should be pre-validated)
        first_name: Owner's first name
        last_name: Owner's last name
        phone: Business phone (optional)

    Returns:
        dict with 'user', 'tenant', 'membership' keys

    Raises:
        SignupError: If any validation fails or creation errors occur
    """
    email = email.strip().lower()

    # Validate uniqueness
    if User.objects.filter(email=email).exists():
        raise SignupError('An account with this email already exists.')

    username = email[:150]
    if User.objects.filter(username=username).exists():
        raise SignupError('An account with this email already exists.')

    if not business_name or len(business_name.strip()) < 2:
        raise SignupError('Business name must be at least 2 characters.')

    business_name = business_name.strip()

    try:
        with transaction.atomic():
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
            )

            # Create tenant
            slug = generate_unique_slug(business_name)
            trial_plan = SubscriptionPlan.objects.filter(
                slug='trial', is_active=True
            ).first()

            tenant = Tenant.objects.create(
                name=business_name,
                slug=slug,
                subdomain=slug,
                owner=user,
                business_email=email,
                business_phone=phone.strip() if phone else '',
                plan='trial',
                subscription_plan=trial_plan,
                subscription_status='trialing',
                trial_started_at=timezone.now(),
            )

            # Create owner membership
            membership = TenantMembership.objects.create(
                tenant=tenant,
                user=user,
                role='owner',
            )

            # Auto-create Technician profile for the owner
            # Every owner starts as a working tech (is_manager=True).
            from apps.technician_portal.models import Technician
            from django.contrib.auth.models import Group

            Technician.objects.create(
                tenant=tenant,
                user=user,
                is_manager=True,
                is_active=True,
            )
            tech_group, _ = Group.objects.get_or_create(name='Technicians')
            user.groups.add(tech_group)

            logger.info(
                f"New signup: {email} — tenant '{business_name}' (slug={slug})"
            )

            return {
                'user': user,
                'tenant': tenant,
                'membership': membership,
            }

    except SignupError:
        raise
    except Exception as e:
        logger.error(f"Signup error for {email}: {e}")
        raise SignupError(f'An unexpected error occurred during signup: {e}')
