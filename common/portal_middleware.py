import logging
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages

logger = logging.getLogger(__name__)


class PortalAccessMiddleware:
    """
    Middleware to ensure users access the correct portal based on their account type.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process the request before view
        self.process_request(request)
        
        # Get the response from the view
        response = self.get_response(request)
        
        return response

    def process_request(self, request):
        """Check portal access permissions"""
        
        # Skip middleware for unauthenticated users and certain paths
        if not request.user.is_authenticated:
            return None
            
        # Skip for admin, API, auth, and public/SaaS UI URLs
        skip_paths = ['/admin/', '/api/', '/setup-database/', '/logout/', '/referrals/',
                      '/signup/', '/pricing/', '/onboarding/', '/login/', '/invite/',
                      '/join/', '/health/']
        if any(request.path.startswith(path) for path in skip_paths):
            return None
        
        # Owner portal: only owners/managers
        if request.path.startswith('/owner/'):
            if not self._is_owner_or_manager(request.user):
                try:
                    messages.error(request, "You don't have access to the owner dashboard.")
                except Exception as e:
                    logger.debug(f"Could not add portal access message: {e}")
                # Route them to where they belong
                if self._is_customer_user(request.user):
                    return redirect('customer_dashboard')
                elif self._is_technician_user(request.user):
                    return redirect('technician_dashboard')
                return redirect('login')

        # Customer portal: only customer users (and owners/managers for oversight)
        elif request.path.startswith('/app/'):
            if not self._is_customer_user(request.user) and not self._is_owner_or_manager(request.user):
                try:
                    messages.error(request, "You don't have access to the customer portal.")
                except Exception as e:
                    logger.debug(f"Could not add portal access message: {e}")
                if self._is_technician_user(request.user):
                    return redirect('technician_dashboard')
                return redirect('login')
                
        # Technician portal: only technicians (and owners/managers who are also techs)
        elif request.path.startswith('/tech/'):
            if not self._is_technician_user(request.user) and not self._is_owner_or_manager(request.user):
                try:
                    messages.error(request, "You don't have access to the technician portal.")
                except Exception as e:
                    logger.debug(f"Could not add portal access message: {e}")
                if self._is_customer_user(request.user):
                    return redirect('customer_dashboard')
                return redirect('login')
        
        return None
    
    def _is_owner_or_manager(self, user):
        """Check if user is a tenant owner or manager."""
        if user.is_staff:
            return True
        try:
            from apps.tenants.models import TenantMembership
            return TenantMembership.objects.filter(
                user=user, is_active=True, role__in=['owner', 'manager']
            ).exists()
        except Exception:
            return False
    
    def _is_customer_user(self, user):
        """Check if user is a customer."""
        try:
            from apps.customer_portal.models import CustomerUser
            return CustomerUser.objects.filter(user=user).exists()
        except Exception:
            return False
    
    def _is_technician_user(self, user):
        """Check if user has a technician profile."""
        if user.is_staff:
            return True
        try:
            from apps.technician_portal.models import Technician
            return Technician.objects.filter(user=user).exists()
        except Exception:
            return False