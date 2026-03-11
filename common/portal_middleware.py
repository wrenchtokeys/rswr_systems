"""
Portal Access Middleware — ensures users access the correct portal.

Uses common.auth as the single source of truth.
"""
import logging
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.messages.api import MessageFailure

from common.auth import can_access, get_user_role, redirect_to_portal

logger = logging.getLogger(__name__)


class PortalAccessMiddleware:
    """Ensure users access the correct portal based on their role."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        result = self.process_request(request)
        if result:
            return result
        return self.get_response(request)

    def process_request(self, request):
        if not request.user.is_authenticated:
            return None

        # Skip for admin, API, auth, and public/SaaS UI URLs
        skip_paths = [
            '/admin/', '/api/', '/setup-database/', '/logout/', '/referrals/',
            '/signup/', '/pricing/', '/onboarding/', '/login/', '/invite/',
            '/join/', '/health/', '/clawdbot/', '/app/invite/',
        ]
        if any(request.path.startswith(path) for path in skip_paths):
            return None

        tenant = getattr(request, 'tenant', None)
        role = get_user_role(request.user, tenant)

        # Owner portal: only owners/managers/superusers/staff
        if request.path.startswith('/owner/'):
            if role not in ('superuser', 'owner', 'manager'):
                try:
                    messages.error(request, "You don't have access to the owner dashboard.")
                except (TypeError, AttributeError, MessageFailure) as e:
                    # Session might not be available in edge cases
                    logger.debug(f"Could not add message for portal access denial: {e}")
                return redirect_to_portal(request.user)

        # Customer portal: customer users + owners/managers for oversight
        elif request.path.startswith('/app/'):
            if role not in ('viewer', 'customer', 'superuser', 'owner', 'manager'):
                try:
                    messages.error(request, "You don't have access to the customer portal.")
                except (TypeError, AttributeError, MessageFailure) as e:
                    logger.debug(f"Could not add message for portal access denial: {e}")
                return redirect_to_portal(request.user)

        # Technician portal: anyone who can access repairs/customers
        elif request.path.startswith('/tech/'):
            if not can_access(request.user, 'repairs', tenant) and not can_access(request.user, 'customers', tenant):
                try:
                    messages.error(request, "You don't have access to the technician portal.")
                except (TypeError, AttributeError, MessageFailure) as e:
                    logger.debug(f"Could not add message for portal access denial: {e}")
                return redirect_to_portal(request.user)

        return None
