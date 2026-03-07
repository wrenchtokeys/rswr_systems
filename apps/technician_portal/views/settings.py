"""
Manager settings views for the technician portal.

Includes viscosity rule management and team overview.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse
from django.db import models
import json
import logging

from apps.technician_portal.models import Technician, Repair, ViscosityRecommendation
from apps.technician_portal.decorators import technician_required, manager_required, is_tenant_admin

logger = logging.getLogger(__name__)


def _get_viscosity_rule_or_404(request, rule_id):
    """Fetch a ViscosityRecommendation scoped to the request's tenant."""
    tenant = getattr(request, 'tenant', None)
    lookup = {'id': rule_id}
    if tenant:
        lookup['tenant'] = tenant
    return get_object_or_404(ViscosityRecommendation, **lookup)


def get_ordinal_suffix(n):
    """
    Return the ordinal suffix for a number (st, nd, rd, th).

    Examples: 1 → "st", 2 → "nd", 3 → "rd", 4 → "th", 11 → "th"
    """
    if 10 <= n % 100 <= 20:
        return 'th'
    else:
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


@technician_required
@manager_required
def manager_settings_dashboard(request):
    """Main manager settings dashboard with navigation tiles."""
    manager = request.user.technician if hasattr(request.user, 'technician') else None

    tenant = getattr(request, 'tenant', None)
    viscosity_qs = ViscosityRecommendation.objects.filter(is_active=True)
    if tenant:
        viscosity_qs = viscosity_qs.filter(tenant=tenant)
    viscosity_rules_count = viscosity_qs.count()

    team_count = 0
    if manager:
        team_count = manager.managed_technicians.filter(is_active=True).count()

    context = {
        'is_admin': is_tenant_admin(request.user),
        'technician': manager,
        'viscosity_rules_count': viscosity_rules_count,
        'team_count': team_count,
    }

    return render(request, 'technician_portal/settings/settings_dashboard.html', context)


@technician_required
@manager_required
@ensure_csrf_cookie
def manage_viscosity_rules(request):
    """Manage viscosity recommendation rules with card-based interface."""
    manager = request.user.technician if hasattr(request.user, 'technician') else None

    tenant = getattr(request, 'tenant', None)
    rules = ViscosityRecommendation.objects.all()
    if tenant:
        rules = rules.filter(tenant=tenant)
    rules = rules.order_by('display_order', 'id')
    rules_with_position = [
        {
            'rule': rule,
            'position': idx + 1,
            'position_suffix': get_ordinal_suffix(idx + 1)
        }
        for idx, rule in enumerate(rules)
    ]

    context = {
        'is_admin': is_tenant_admin(request.user),
        'technician': manager,
        'rules_with_position': rules_with_position,
        'badge_colors': ViscosityRecommendation.BADGE_COLOR_CHOICES,
    }

    return render(request, 'technician_portal/settings/viscosity_rules.html', context)


@technician_required
@manager_required
def get_viscosity_rule(request, rule_id):
    """AJAX endpoint to fetch a single viscosity recommendation rule."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = _get_viscosity_rule_or_404(request, rule_id)

        return JsonResponse({
            'success': True,
            'rule': {
                'id': rule.id,
                'name': rule.name,
                'min_temperature': str(rule.min_temperature) if rule.min_temperature is not None else '',
                'max_temperature': str(rule.max_temperature) if rule.max_temperature is not None else '',
                'recommended_viscosity': rule.recommended_viscosity,
                'suggestion_text': rule.suggestion_text,
                'badge_color': rule.badge_color,
                'display_order': rule.display_order,
                'is_active': rule.is_active,
            }
        })

    except Exception as e:
        logger.error(f'Error fetching viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def create_viscosity_rule(request):
    """AJAX endpoint to create a new viscosity recommendation rule."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)

        required_fields = ['name', 'recommended_viscosity', 'suggestion_text', 'badge_color']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }, status=400)

        tenant = getattr(request, 'tenant', None)
        order_qs = ViscosityRecommendation.objects.all()
        if tenant:
            order_qs = order_qs.filter(tenant=tenant)
        max_order = order_qs.aggregate(
            max_order=models.Max('display_order')
        )['max_order']
        next_order = (max_order or 0) + 10

        rule = ViscosityRecommendation.objects.create(
            tenant=tenant,
            name=data['name'],
            min_temperature=data.get('min_temperature') or None,
            max_temperature=data.get('max_temperature') or None,
            recommended_viscosity=data['recommended_viscosity'],
            suggestion_text=data['suggestion_text'],
            badge_color=data['badge_color'],
            display_order=next_order,
            is_active=data.get('is_active', True)
        )

        return JsonResponse({
            'success': True,
            'message': 'Viscosity rule created successfully',
            'rule': {
                'id': rule.id,
                'name': rule.name,
                'temp_range': rule._get_temp_range_display(),
                'recommended_viscosity': rule.recommended_viscosity,
                'suggestion_text': rule.suggestion_text,
                'badge_color': rule.badge_color,
                'display_order': rule.display_order,
                'is_active': rule.is_active,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f'Error creating viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def update_viscosity_rule(request, rule_id):
    """AJAX endpoint to update an existing viscosity recommendation rule."""
    if request.method not in ['PUT', 'POST']:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = _get_viscosity_rule_or_404(request, rule_id)
        data = json.loads(request.body)

        if 'name' in data:
            rule.name = data['name']
        if 'min_temperature' in data:
            rule.min_temperature = data['min_temperature'] or None
        if 'max_temperature' in data:
            rule.max_temperature = data['max_temperature'] or None
        if 'recommended_viscosity' in data:
            rule.recommended_viscosity = data['recommended_viscosity']
        if 'suggestion_text' in data:
            rule.suggestion_text = data['suggestion_text']
        if 'badge_color' in data:
            rule.badge_color = data['badge_color']
        if 'display_order' in data:
            rule.display_order = data['display_order']
        if 'is_active' in data:
            rule.is_active = data['is_active']

        rule.save()

        return JsonResponse({
            'success': True,
            'message': 'Viscosity rule updated successfully',
            'rule': {
                'id': rule.id,
                'name': rule.name,
                'temp_range': rule._get_temp_range_display(),
                'recommended_viscosity': rule.recommended_viscosity,
                'suggestion_text': rule.suggestion_text,
                'badge_color': rule.badge_color,
                'display_order': rule.display_order,
                'is_active': rule.is_active,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f'Error updating viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def delete_viscosity_rule(request, rule_id):
    """AJAX endpoint to delete a viscosity recommendation rule."""
    if request.method not in ['DELETE', 'POST']:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = _get_viscosity_rule_or_404(request, rule_id)
        rule_name = rule.name
        rule.delete()

        return JsonResponse({
            'success': True,
            'message': f'Viscosity rule "{rule_name}" deleted successfully'
        })

    except Exception as e:
        logger.error(f'Error deleting viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def toggle_viscosity_rule(request, rule_id):
    """AJAX endpoint to toggle active status of a viscosity recommendation rule."""
    if request.method not in ['PATCH', 'POST']:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        rule = _get_viscosity_rule_or_404(request, rule_id)
        rule.is_active = not rule.is_active
        rule.save()

        return JsonResponse({
            'success': True,
            'message': f'Viscosity rule {"activated" if rule.is_active else "deactivated"}',
            'is_active': rule.is_active
        })

    except Exception as e:
        logger.error(f'Error toggling viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@technician_required
@manager_required
def team_overview(request):
    """Team overview dashboard showing managed technicians and their stats."""
    manager = request.user.technician if hasattr(request.user, 'technician') else None

    if not manager:
        messages.warning(request, "Technician profile not found")
        return redirect('technician_dashboard')

    team_members = manager.managed_technicians.filter(is_active=True).select_related('user')

    # Annotate team members with repair stats to minimize queries
    from django.db.models import Count, Q
    team_members_annotated = team_members.annotate(
        total_repairs=Count('repair'),
        pending_repairs_count=Count(
            'repair', filter=Q(repair__queue_status__in=['REQUESTED', 'PENDING', 'APPROVED'])
        ),
        completed_repairs_count=Count(
            'repair', filter=Q(repair__queue_status='COMPLETED')
        ),
    )

    tenant = getattr(request, 'tenant', None)

    team_stats = []
    for tech in team_members_annotated:
        completion_rate = (tech.completed_repairs_count / tech.total_repairs * 100) if tech.total_repairs > 0 else 0

        recent_qs = Repair.objects.filter(technician=tech)
        if tenant:
            recent_qs = recent_qs.filter(tenant=tenant)

        team_stats.append({
            'technician': tech,
            'total_repairs': tech.total_repairs,
            'pending_repairs': tech.pending_repairs_count,
            'completed_repairs': tech.completed_repairs_count,
            'completion_rate': round(completion_rate, 1),
            'recent_repairs': recent_qs.select_related('customer').order_by('-service_date')[:5]
        })

    total_team_repairs = sum(stat['total_repairs'] for stat in team_stats)
    total_team_pending = sum(stat['pending_repairs'] for stat in team_stats)
    total_team_completed = sum(stat['completed_repairs'] for stat in team_stats)

    context = {
        'is_admin': is_tenant_admin(request.user),
        'technician': manager,
        'team_stats': team_stats,
        'total_team_repairs': total_team_repairs,
        'total_team_pending': total_team_pending,
        'total_team_completed': total_team_completed,
        'team_members_count': team_members.count(),
    }

    return render(request, 'technician_portal/settings/team_overview.html', context)
