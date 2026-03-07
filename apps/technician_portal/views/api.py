"""
JSON API endpoints for the technician portal.

Includes batch pricing, viscosity suggestions, and profile management.
"""

from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
import logging

from apps.technician_portal.models import Technician, Repair
from apps.technician_portal.forms import TechnicianForm
from apps.technician_portal.decorators import technician_required
from apps.technician_portal.services.batch_pricing_service import (
    calculate_batch_pricing,
    get_batch_pricing_preview,
)

logger = logging.getLogger(__name__)


@technician_required
def get_batch_pricing_json(request):
    """AJAX endpoint for getting pricing preview for multi-break batches."""
    customer_id = request.GET.get('customer_id')
    unit_number = request.GET.get('unit_number')
    breaks_count = request.GET.get('breaks_count')

    if not all([customer_id, unit_number, breaks_count]):
        return JsonResponse({'error': 'Missing required parameters'}, status=400)

    try:
        breaks_count = int(breaks_count)
        if breaks_count < 1 or breaks_count > 20:
            return JsonResponse({'error': 'Breaks count must be between 1 and 20'}, status=400)

        pricing_data = get_batch_pricing_preview(int(customer_id), unit_number, breaks_count)

        if pricing_data is None:
            return JsonResponse({'error': 'Customer not found'}, status=404)

        return JsonResponse(pricing_data)

    except ValueError:
        return JsonResponse({'error': 'Invalid parameters'}, status=400)
    except Exception as e:
        logger.error(f"Error calculating batch pricing: {e}")
        return JsonResponse({'error': 'Server error calculating pricing'}, status=500)


@technician_required
def get_viscosity_suggestion(request):
    """
    API endpoint to get viscosity recommendation based on temperature.

    GET /tech/api/viscosity-suggestion/?temperature=72.5
    """
    from apps.technician_portal.models import ViscosityRecommendation

    temperature = request.GET.get('temperature')

    if not temperature:
        return JsonResponse({'error': 'Temperature parameter is required'}, status=400)

    try:
        temp_value = float(temperature)
        tenant = getattr(request, 'tenant', None)
        recommendation = ViscosityRecommendation.get_recommendation_for_temperature(temp_value, tenant=tenant)

        if recommendation:
            return JsonResponse({
                'success': True,
                'recommendation': recommendation['recommendation'],
                'suggestion_text': recommendation['suggestion_text'],
                'badge_color': recommendation['badge_color'],
            })
        else:
            return JsonResponse({
                'success': True,
                'recommendation': None,
                'suggestion_text': 'No recommendation available for this temperature',
                'badge_color': 'gray',
            })

    except ValueError:
        logger.warning(f"Invalid temperature value: {temperature}")
        return JsonResponse({'error': 'Invalid temperature value'}, status=400)
    except Exception as e:
        logger.error(f"Error getting viscosity suggestion: {e}", exc_info=True)
        return JsonResponse({'error': 'Server error getting viscosity suggestion'}, status=500)


@technician_required
def update_technician_profile(request):
    """Update technician profile and password."""
    from django.shortcuts import render
    technician = get_object_or_404(Technician, user=request.user)

    if request.method == 'POST':
        form = TechnicianForm(request.POST, user=request.user, technician=technician)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')

            if form.cleaned_data.get('password1'):
                update_session_auth_hash(request, request.user)
                messages.info(request, 'Your password has been changed successfully.')

            return redirect('technician_dashboard')
    else:
        form = TechnicianForm(user=request.user, technician=technician)

    return render(request, 'technician_portal/update_profile.html', {
        'form': form,
        'technician': technician
    })
