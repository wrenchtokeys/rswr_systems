from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from apps.customer_portal.models import CustomerUser
from .models import ReferralCode, Referral, Reward, RewardOption, RewardRedemption
import uuid
import random
import string
from django.contrib import messages
from .services import ReferralService, RewardService, RewardFulfillmentService

# Helper functions
def generate_unique_code(length=8):
    """
    Generate a unique alphanumeric code for referrals.
    
    Creates random codes and checks against the database to ensure uniqueness.
    
    Args:
        length (int): The length of the code to generate
        
    Returns:
        str: A unique alphanumeric code
    """
    characters = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choice(characters) for _ in range(length))
        if not ReferralCode.objects.filter(code=code).exists():
            return code

def get_customer_user(request):
    """
    Helper function to get the CustomerUser for the current authenticated user.
    
    Args:
        request: HTTP request object
        
    Returns:
        CustomerUser: The customer user object for the current user
    """
    return CustomerUser.objects.get(user=request.user)

def get_user_referral_code(customer_user):
    """
    Helper function to get a user's referral code.
    
    Args:
        customer_user: The CustomerUser object
        
    Returns:
        ReferralCode or None: The user's referral code object, or None if not found
    """
    return ReferralCode.objects.filter(customer_user=customer_user).first()

def get_user_reward(customer_user):
    """
    Helper function to get a user's reward record.
    
    Args:
        customer_user: The CustomerUser object
        
    Returns:
        Reward or None: The user's reward object, or None if not found
    """
    return Reward.objects.filter(customer_user=customer_user).first()

# Referral code management
@login_required
def generate_referral_code(request):
    """
    Generate a new referral code for the logged-in user.
    
    If the user already has a referral code, it returns the existing code.
    If the user doesn't have a code, it generates a new one when a POST request is received.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered template or redirect
    """
    customer_user = get_customer_user(request)
    
    # Check if user already has a referral code
    existing_code = get_user_referral_code(customer_user)
    
    if request.method == 'POST':
        if existing_code:
            return JsonResponse({
                'success': False,
                'message': 'You already have a referral code',
                'code': existing_code.code
            })
        
        # Generate new code using the service
        code = ReferralService.generate_code_for_user(customer_user).code
        
        # Redirect back to the same page to show the new code
        return redirect('generate_referral_code')
    
    # GET request - render the form
    return render(request, 'customer_portal/referrals/generate_code.html', {
        'existing_code': existing_code.code if existing_code else None
    })

@login_required
def referral_code(request):
    """
    Get the current user's referral code.
    
    Returns the user's existing referral code as JSON response.
    
    Args:
        request: HTTP request object
        
    Returns:
        JsonResponse: Contains the referral code or error message
    """
    customer_user = get_customer_user(request)
    referral_code = get_user_referral_code(customer_user)
    
    if referral_code:
        return JsonResponse({
            'success': True,
            'code': referral_code.code
        })
    else:
        return JsonResponse({
            'success': False,
            'message': 'No referral code found'
        })

# Referral tracking
@login_required
def referral_tracking(request):
    """
    Track a successful referral.
    
    Processes a POST request containing a referral code.
    Validates the code, creates a referral record, and awards points.
    
    Args:
        request: HTTP request object
        
    Returns:
        JsonResponse: Result of the referral processing
    """
    if request.method == 'POST':
        code = request.POST.get('code')
        if not code:
            return JsonResponse({'success': False, 'message': 'Referral code is required'})
        
        try:
            # Use the service to validate and process the referral
            referral_code = ReferralService.validate_referral_code(code)
            if not referral_code:
                return JsonResponse({'success': False, 'message': 'Invalid referral code'})
                
            customer_user = get_customer_user(request)
            
            # Use the service to process the referral
            success = ReferralService.process_referral(referral_code, customer_user)
            
            if success:
                return JsonResponse({'success': True, 'message': 'Referral processed successfully'})
            else:
                return JsonResponse({'success': False, 'message': 'Unable to process referral'})
            
        except ReferralCode.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'Invalid referral code'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error: {str(e)}'})
    
    return JsonResponse({'success': False, 'message': 'Only POST method is allowed'})

@login_required
def referral_history(request):
    """
    Get referral history for the current user.
    
    Displays all successful referrals made using the user's referral code.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered template with referral history
    """
    customer_user = get_customer_user(request)
    
    # Get the user's referral code
    referral_code = get_user_referral_code(customer_user)
    
    if referral_code:
        # Get all referrals using this code
        referrals = Referral.objects.filter(referral_code=referral_code).order_by('-created_at')
        
        context = {
            'referrals': referrals,
            'referral_code': referral_code.code
        }
        
        return render(request, 'customer_portal/referrals/dashboard.html', context)
    else:
        # User doesn't have a referral code yet
        return render(request, 'customer_portal/referrals/dashboard.html', {'has_code': False})

@login_required
def referral_stats(request):
    """
    Get statistics about the user's referrals.
    
    Returns a JSON response with the total number of referrals,
    current reward points, and the user's referral code.
    
    Args:
        request: HTTP request object
        
    Returns:
        JsonResponse: Referral statistics
    """
    customer_user = get_customer_user(request)
    referral_code = get_user_referral_code(customer_user)
    
    if not referral_code:
        return JsonResponse({
            'success': False,
            'message': 'No referral code found'
        })
    
    # Count referrals using the service
    referral_count = ReferralService.get_referral_count(customer_user)
    
    # Get reward points using the service
    points = RewardService.get_reward_balance(customer_user)
    
    return JsonResponse({
        'success': True,
        'total_referrals': referral_count,
        'points': points,
        'code': referral_code.code
    })

@login_required
def referral_leaderboard(request):
    """
    View top referrers.
    
    Displays a leaderboard of customers with the most successful referrals.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered template with leaderboard data
    """
    # Get referral counts for each user (tenant-scoped)
    top_referrers = []
    tenant = getattr(request, 'tenant', None)
    
    code_qs = ReferralCode.objects.all()
    if tenant:
        code_qs = code_qs.filter(customer_user__customer__tenant=tenant)
    
    for code in code_qs:
        count = Referral.objects.filter(referral_code=code).count()
        if count > 0:
            top_referrers.append({
                'user': code.customer_user,
                'count': count
            })
    
    # Sort by count, take top 10
    top_referrers = sorted(top_referrers, key=lambda x: x['count'], reverse=True)[:10]
    
    return render(request, 'customer_portal/referrals/leaderboard.html', {'top_referrers': top_referrers})

# Reward management
@login_required
def reward_balance(request):
    """
    Get the current user's reward balance.
    
    Returns a JSON response with the user's current point balance.
    
    Args:
        request: HTTP request object
        
    Returns:
        JsonResponse: Current reward points
    """
    customer_user = get_customer_user(request)
    points = RewardService.get_reward_balance(customer_user)
    
    return JsonResponse({
        'success': True,
        'points': points
    })

@login_required
def reward_history(request):
    """
    View reward history.
    
    Displays a history of the user's reward redemptions.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered template with redemption history
    """
    customer_user = get_customer_user(request)
    redemptions = RewardService.get_reward_redemptions(customer_user)
    points = RewardService.get_reward_balance(customer_user)
    
    # Get reward options scoped to tenant
    tenant = getattr(request, 'tenant', None)
    reward_opts_qs = RewardOption.objects.all()
    if tenant:
        reward_opts_qs = reward_opts_qs.filter(tenant=tenant)

    else:
        reward_opts_qs = reward_opts_qs.none()
    reward_opts_qs = reward_opts_qs.order_by('points_required')

    context = {
        'redemptions': redemptions,
        'points': points,
        'reward_options': reward_opts_qs
    }

    return render(request, 'customer_portal/referrals/rewards.html', context)

@login_required
def reward_options(request):
    """
    List available reward options.
    
    Returns all reward options, either as JSON for API requests or as
    rendered HTML for browser requests.
    
    Args:
        request: HTTP request object
        
    Returns:
        JsonResponse or HttpResponse: Available reward options
    """
    tenant = getattr(request, 'tenant', None)
    options = RewardService.get_reward_options(tenant=tenant).order_by('points_required')
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Return JSON for API requests
        return JsonResponse({
            'success': True,
            'options': [
                {
                    'id': option.id,
                    'name': option.name,
                    'description': option.description,
                    'points_required': option.points_required
                }
                for option in options
            ]
        })
    
    # Return HTML for direct browser requests
    return render(request, 'customer_portal/referrals/rewards.html', {
        'reward_options': options
    })

@login_required
@require_POST
def redeem_reward(request):
    """
    Redeem points for a reward.
    
    Processes a redemption request, validates the user has enough points,
    creates a redemption record, and deducts points from the user's balance.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Redirect to rewards page with success or error message
    """
    option_id = request.POST.get('option_id')
    
    if not option_id:
        messages.error(request, 'Reward option is required')
        return redirect('referral_rewards')
    
    try:
        customer_user = get_customer_user(request)
        
        # Use the reward service to handle the redemption
        success, result = RewardService.redeem_reward(customer_user, option_id)
        
        if not success:
            messages.error(request, result)  # Result contains the error message
            return redirect('referral_rewards')
            
        redemption = result  # Result contains the redemption object
        
        # Assign a technician to fulfill this redemption
        assigned_technician = RewardFulfillmentService.assign_technician(redemption)
        
        reward_option = redemption.reward_option
        if assigned_technician:
            messages.success(
                request, 
                f'Successfully redeemed {reward_option.name}. A technician will be assigned to fulfill your reward.'
            )
        else:
            messages.success(
                request, 
                f'Successfully redeemed {reward_option.name}. Your request is pending technician assignment.'
            )
        
        return redirect('referral_rewards')
        
    except RewardOption.DoesNotExist:
        messages.error(request, 'Invalid reward option')
        return redirect('referral_rewards')
    except Exception as e:
        messages.error(request, f'An error occurred while processing your redemption: {str(e)}')
        return redirect('referral_rewards')

@login_required
def referral_rewards(request):
    """
    View dashboard for rewards system.
    
    Displays the user's current point balance, available reward options,
    and redemption history.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered template with rewards dashboard
    """
    customer_user = get_customer_user(request)
    
    # Get reward points
    reward = get_user_reward(customer_user)
    points = reward.points if reward else 0
    
    # Get referral code
    referral_code = get_user_referral_code(customer_user)
    code = referral_code.code if referral_code else None
    
    # Get referral count
    referral_count = 0
    if referral_code:
        # Limit to the 5 most recent referrals for display
        referrals = Referral.objects.filter(referral_code=referral_code).order_by('-created_at')[:5]
        # Get total count separately
        referral_count = Referral.objects.filter(referral_code=referral_code).count()
    else:
        referrals = []
    
    # Get reward options scoped to tenant - limit to 6 for better display on mobile
    tenant = getattr(request, 'tenant', None)
    reward_options_qs = RewardOption.objects.all()
    if tenant:
        reward_options_qs = reward_options_qs.filter(tenant=tenant)

    else:
        reward_options_qs = reward_options_qs.none()
    reward_options = reward_options_qs.order_by('points_required')[:6]
    
    # Get redemption history - limit to 5 recent for better display
    redemptions = RewardRedemption.objects.filter(
        reward__customer_user=customer_user
    ).order_by('-created_at')[:5]
    
    context = {
        'points': points,
        'referral_code': code,
        'referral_count': referral_count,
        'referrals': referrals,
        'reward_options': reward_options,
        'redemptions': redemptions
    }
    
    # Check if we should use a simplified template based on the URL
    if request.path.endswith('/referral-rewards/'):
        return render(request, 'customer_portal/referrals/rewards_compact.html', context)
    
    return render(request, 'customer_portal/referrals/dashboard.html', context)

@login_required
def referral_rewards_history(request):
    """
    View complete redemption history.
    
    Displays a complete history of the user's reward redemptions
    with their current status.
    
    Args:
        request: HTTP request object
        
    Returns:
        HttpResponse: Rendered template with full redemption history
    """
    customer_user = get_customer_user(request)
    redemptions = RewardRedemption.objects.filter(
        reward__customer_user=customer_user
    ).order_by('-created_at')
    
    return render(request, 'customer_portal/referrals/rewards.html', {
        'redemptions': redemptions
    })

@login_required
def referral_rewards_balance(request):
    """
    Get the current reward balance.
    
    Returns a JSON response with the user's current point balance.
    
    Args:
        request: HTTP request object
        
    Returns:
        JsonResponse: Current reward points
    """
    customer_user = get_customer_user(request)
    reward = get_user_reward(customer_user)
    points = reward.points if reward else 0
    
    return JsonResponse({
        'success': True,
        'points': points
    })
