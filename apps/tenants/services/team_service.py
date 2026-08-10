"""
Team service — the one way to add a new team member to a shop.

Used by both the owner settings invite flow and the onboarding wizard so
every new member gets the same treatment: a User with an unusable password,
a Technician record with ability flags derived from what the shop does,
a TenantMembership, and an InviteToken emailed as a set-password link.
"""
import logging

from django.contrib.auth.models import User, Group
from django.db import transaction

logger = logging.getLogger(__name__)


class TeamServiceError(Exception):
    """Raised when a team member cannot be added."""
    pass


def resolve_ability_flags(tenant, can_repair=None, can_replace=None):
    """Return (can_repair, can_replace) for a new/updated technician.

    Single-service shops ignore the passed values — everyone does the one
    service the shop offers. Shops doing both use the passed values,
    defaulting to True/True (both boxes pre-checked).
    """
    if tenant.services_offered != 'both':
        return tenant.offers_repairs, tenant.offers_replacements
    return (
        True if can_repair is None else can_repair,
        True if can_replace is None else can_replace,
    )


def add_team_member(
    tenant,
    invited_by,
    *,
    email,
    first_name='',
    last_name='',
    role='technician',
    phone='',
    can_repair=None,
    can_replace=None,
    base_url='',
):
    """Create a new team member and email them an invite link.

    Returns dict with 'user', 'invite_token', 'invite_url', 'email_sent'.
    Raises TeamServiceError for invalid input or an already-active member.
    The caller is responsible for permission and seat-limit checks.
    """
    from apps.tenants.models import TenantMembership, InviteToken
    from apps.technician_portal.models import Technician

    email = (email or '').strip().lower()
    if not email:
        raise TeamServiceError('Email is required.')
    if role not in ('manager', 'technician', 'viewer'):
        raise TeamServiceError('Invalid role.')

    can_repair, can_replace = resolve_ability_flags(tenant, can_repair, can_replace)

    user = User.objects.filter(email__iexact=email).first()
    if not user:
        from apps.tenants.services.signup_service import generate_unique_username
        user = User.objects.create_user(
            username=generate_unique_username(email, first_name),
            email=email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
        )
        # No usable password until they accept the invite — this also makes
        # the Team tab show them as "invite pending".
        user.set_unusable_password()
        user.save()

    existing = TenantMembership.objects.filter(tenant=tenant, user=user).first()
    if existing and existing.is_active:
        raise TeamServiceError(f'{email} is already a team member.')
    if existing:
        raise TeamServiceError(
            f'{email} was previously on the team. Re-add them from Settings → Team.'
        )

    with transaction.atomic():
        TenantMembership.objects.create(tenant=tenant, user=user, role=role)

        if role in ('technician', 'manager'):
            tech_group, _ = Group.objects.get_or_create(name='Technicians')
            user.groups.add(tech_group)

            # Technician.user is a OneToOneField across ALL tenants — never
            # steal another tenant's record (CODE-217).
            foreign_tech = Technician.objects.filter(user=user).exclude(tenant=tenant).first()
            if foreign_tech:
                logger.warning(
                    "add_team_member: user %s already has a Technician record for "
                    "tenant %s. Skipping Technician creation for tenant %s.",
                    user.id, foreign_tech.tenant_id, tenant.id,
                )
            elif not Technician.objects.filter(user=user, tenant=tenant).exists():
                Technician.objects.create(
                    tenant=tenant,
                    user=user,
                    is_manager=(role == 'manager'),
                    is_active=True,
                    can_repair=can_repair,
                    can_replace=can_replace,
                    phone_number=(phone or '').strip(),
                )

        invite_token = InviteToken.objects.create(
            tenant=tenant,
            user=user,
            role=role,
            invited_by=invited_by,
        )

    invite_url = f"{base_url.rstrip('/')}/invite/{invite_token.token}/"

    email_sent = False
    try:
        from core.email_utils import send_branded_email
        inviter_name = invited_by.get_full_name() or invited_by.email
        send_branded_email(
            subject=f"You're invited to join {tenant.name} on RS Systems",
            recipient_list=[email],
            headline=f"You're Invited to {tenant.name}!",
            body_paragraphs=[
                f"Hi {first_name or email},",
                f"{inviter_name} has invited you to join {tenant.name} as a {role}.",
                "Click the button below to set your password and get started. This link expires in 7 days.",
            ],
            button_text='Accept Invitation',
            button_url=invite_url,
            tenant=tenant,
        )
        email_sent = True
    except Exception as e:
        logger.warning(f"Failed to send invite email to {email}: {e}")

    return {
        'user': user,
        'invite_token': invite_token,
        'invite_url': invite_url,
        'email_sent': email_sent,
    }
