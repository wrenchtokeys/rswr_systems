from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages


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
            
        # Skip for admin, API, auth, and SaaS UI URLs
        skip_paths = ['/admin/', '/api/', '/setup-database/', '/logout/', '/referrals/',
                      '/signup/', '/pricing/', '/onboarding/', '/owner/']
        if any(request.path.startswith(path) for path in skip_paths):
            return None
            
        # Check customer portal access
        if request.path.startswith('/app/'):
            if not self._is_customer_user(request.user):
                try:
                    messages.error(request, "You don't have access to the customer portal.")
                except:
                    pass  # Continue without message if messages framework unavailable
                return redirect('technician_dashboard')
                
        # Check technician portal access  
        elif request.path.startswith('/tech/'):
            if not self._is_technician_user(request.user):
                try:
                    messages.error(request, "You don't have access to the technician portal.")
                except:
                    pass  # Continue without message if messages framework unavailable
                return redirect('customer_dashboard')
        
        return None
    
    def _is_customer_user(self, user):
        """Check if user is a customer"""
        try:
            from apps.customer_portal.models import CustomerUser
            CustomerUser.objects.get(user=user)
            return True
        except CustomerUser.DoesNotExist:
            return False
    
    def _is_technician_user(self, user):
        """Check if user is a technician"""
        try:
            from apps.technician_portal.models import Technician
            Technician.objects.get(user=user)
            return True
        except Technician.DoesNotExist:
            return False