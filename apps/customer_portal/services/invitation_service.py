"""
Customer Invitation Service
Handles sending and managing customer portal invitations.
"""
import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.urls import reverse

from apps.customer_portal.models import CustomerInvitation

logger = logging.getLogger(__name__)


class CustomerInvitationService:
    """Service for managing customer portal invitations."""

    @staticmethod
    def create_invitation(customer, email, invited_by, first_name='', last_name='', is_primary_contact=False):
        """
        Create a new invitation for a customer portal user.
        
        Args:
            customer: Customer model instance
            email: Email address to invite
            invited_by: User who is sending the invitation
            first_name: Optional first name
            last_name: Optional last name
            
        Returns:
            CustomerInvitation instance
        """
        # Check for existing pending invitation
        existing = CustomerInvitation.objects.filter(
            customer=customer,
            email__iexact=email,
            status='pending'
        ).first()
        
        if existing and existing.is_valid:
            # Update primary flag if changed, then resend
            if existing.is_primary_contact != is_primary_contact:
                existing.is_primary_contact = is_primary_contact
                existing.save(update_fields=['is_primary_contact'])
            return existing
        
        # Create new invitation
        invitation = CustomerInvitation.objects.create(
            customer=customer,
            email=email,
            first_name=first_name,
            last_name=last_name,
            invited_by=invited_by,
            is_primary_contact=is_primary_contact,
        )
        
        return invitation

    @staticmethod
    def send_invitation_email(invitation, request=None):
        """
        Send the invitation email to the invitee.
        
        Args:
            invitation: CustomerInvitation instance
            request: Optional HttpRequest for building absolute URLs
            
        Returns:
            bool: True if email sent successfully
        """
        if not invitation.is_valid:
            logger.warning(f"Attempted to send invalid invitation: {invitation.id}")
            return False

        # Build the invitation URL
        if request:
            base_url = request.build_absolute_uri('/')[:-1]
        else:
            base_url = getattr(settings, 'SITE_URL', 'https://rssystems.io')
        
        invite_url = f"{base_url}/app/invite/{invitation.token}/"

        # Get shop name from tenant/customer
        shop_name = invitation.customer.tenant.name if hasattr(invitation.customer, 'tenant') and invitation.customer.tenant else 'RS Systems'
        inviter_name = invitation.invited_by.get_full_name() if invitation.invited_by else shop_name

        # Get email branding
        try:
            from core.models.email_branding import EmailBrandingConfig
            branding = EmailBrandingConfig.get_instance().to_template_context()
        except Exception:
            branding = {
                'company_name': shop_name,
                'primary_color': '#2563eb',
                'text_color': '#1f2937',
                'background_color': '#f3f4f6',
                'heading_font': 'Arial, Helvetica, sans-serif',
                'body_font': 'Arial, Helvetica, sans-serif',
            }
        # Use shop name for branding if not configured
        if not branding.get('company_name'):
            branding['company_name'] = shop_name

        context = {
            'invitation': invitation,
            'invite_url': invite_url,
            'shop_name': shop_name,
            'inviter_name': inviter_name,
            'customer_name': invitation.customer.name,
            'recipient_name': invitation.first_name or 'there',
            'branding': branding,
        }

        # Render email templates
        subject = f"You're invited to manage {invitation.customer.name} on {shop_name}"
        
        html_message = render_to_string('emails/customer_invitation.html', context)
        text_message = render_to_string('emails/customer_invitation.txt', context)

        try:
            send_mail(
                subject=subject,
                message=text_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[invitation.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            # Update sent timestamp
            invitation.sent_at = timezone.now()
            invitation.save(update_fields=['sent_at'])
            
            logger.info(f"Sent customer invitation email to {invitation.email} for {invitation.customer.name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send customer invitation email: {e}")
            return False

    @staticmethod
    def resend_invitation(invitation, request=None):
        """
        Resend an existing invitation (resets expiry).
        
        Args:
            invitation: CustomerInvitation instance
            request: Optional HttpRequest
            
        Returns:
            bool: True if resent successfully
        """
        if invitation.status == 'accepted':
            logger.warning(f"Cannot resend accepted invitation: {invitation.id}")
            return False
        
        # Reset status and expiry
        from datetime import timedelta
        invitation.status = 'pending'
        invitation.expires_at = timezone.now() + timedelta(days=7)
        invitation.save(update_fields=['status', 'expires_at'])
        
        return CustomerInvitationService.send_invitation_email(invitation, request)

    @staticmethod
    def cancel_invitation(invitation):
        """Cancel a pending invitation."""
        if invitation.status not in ('pending', 'expired'):
            return False
        
        invitation.status = 'cancelled'
        invitation.save(update_fields=['status'])
        return True

    @staticmethod
    def get_invitation_by_token(token):
        """
        Get a valid invitation by token.
        
        Returns:
            CustomerInvitation or None
        """
        try:
            invitation = CustomerInvitation.objects.get(token=token)
            if invitation.is_valid:
                return invitation
            return None
        except CustomerInvitation.DoesNotExist:
            return None
