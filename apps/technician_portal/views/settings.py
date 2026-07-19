"""
Manager settings views for the technician portal.

Includes viscosity rule management and team overview.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, Http404
from django.db import models
from django.db.models import Prefetch
import json
import logging

from apps.technician_portal.models import Technician, Repair, ViscosityRecommendation, WarrantyPolicy
from apps.technician_portal.decorators import technician_required, manager_required, is_tenant_admin

logger = logging.getLogger(__name__)


def _get_viscosity_rule_or_404(request, rule_id):
    """Fetch a ViscosityRecommendation scoped to the request's tenant.

    Returns 404 when the tenant cannot be resolved from the request so we
    never accidentally return a rule belonging to a different shop (IDOR
    defence-in-depth: mirrors the qs.none() pattern used elsewhere).
    """
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        from django.http import Http404
        raise Http404("Tenant not resolved for this request")
    return get_object_or_404(ViscosityRecommendation, id=rule_id, tenant=tenant)


def get_ordinal_suffix(n):
    """
    Return the ordinal suffix for a number (st, nd, rd, th).

    Examples: 1 → "st", 2 → "nd", 3 → "rd", 4 → "th", 11 → "th"
    """
    if 10 <= n % 100 <= 20:
        return 'th'
    else:
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')


@manager_required
def manager_settings_dashboard(request):
    """Main manager settings dashboard with navigation tiles."""
    tenant = getattr(request, 'tenant', None)
    # Use tenant-scoped lookup so an owner/admin at Shop B who also has a
    # Technician record at Shop A does not leak Shop A's team data here.
    # (CODE-080 cross-tenant settings dashboard fix)
    manager = (
        Technician.objects.filter(user=request.user, tenant=tenant).first()
        if tenant else None
    )
    viscosity_qs = ViscosityRecommendation.objects.filter(is_active=True)
    if tenant:
        viscosity_qs = viscosity_qs.filter(tenant=tenant)
    else:
        viscosity_qs = viscosity_qs.none()
    viscosity_rules_count = viscosity_qs.count()

    warranty_qs = WarrantyPolicy.objects.filter(is_active=True)
    if tenant:
        warranty_qs = warranty_qs.filter(tenant=tenant)
    else:
        warranty_qs = warranty_qs.none()
    warranty_policies_count = warranty_qs.count()

    team_count = 0
    if manager:
        team_count = manager.managed_technicians.filter(is_active=True).count()

    context = {
        'is_admin': is_tenant_admin(request.user, tenant=getattr(request, "tenant", None)),
        'technician': manager,
        'viscosity_rules_count': viscosity_rules_count,
        'warranty_policies_count': warranty_policies_count,
        'team_count': team_count,
    }

    return render(request, 'technician_portal/settings/settings_dashboard.html', context)


@manager_required
@ensure_csrf_cookie
def manage_viscosity_rules(request):
    """Manage viscosity recommendation rules with card-based interface."""
    tenant = getattr(request, 'tenant', None)
    # Use tenant-scoped lookup to prevent cross-tenant Technician bleed. (CODE-080)
    try:
        manager = (
            Technician.objects.filter(user=request.user, tenant=tenant).first()
            if tenant else None
        )
    except Exception:
        manager = None
    rules = ViscosityRecommendation.objects.all()
    if tenant:
        rules = rules.filter(tenant=tenant)

    else:
        rules = rules.none()
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
        'is_admin': is_tenant_admin(request.user, tenant=getattr(request, "tenant", None)),
        'technician': manager,
        'rules_with_position': rules_with_position,
        'badge_colors': ViscosityRecommendation.BADGE_COLOR_CHOICES,
    }

    return render(request, 'technician_portal/settings/viscosity_rules.html', context)


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

    except Http404:
        raise
    except Exception as e:
        logger.error(f'Error fetching viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@manager_required
def create_viscosity_rule(request):
    """AJAX endpoint to create a new viscosity recommendation rule."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Tenant not resolved'}, status=400)

    try:
        data = json.loads(request.body)

        required_fields = ['name', 'recommended_viscosity', 'suggestion_text', 'badge_color']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }, status=400)

        order_qs = ViscosityRecommendation.objects.filter(tenant=tenant)
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

    except Http404:
        raise
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f'Error updating viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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

    except Http404:
        raise
    except Exception as e:
        logger.error(f'Error deleting viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


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

    except Http404:
        raise
    except Exception as e:
        logger.error(f'Error toggling viscosity rule: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@manager_required
def team_overview(request):
    """Team overview dashboard showing managed technicians and their stats."""
    tenant = getattr(request, 'tenant', None)
    # Use tenant-scoped Technician lookup so an owner/admin at Shop B who also
    # has a Technician record at Shop A cannot see Shop A's managed_technicians
    # on Shop B's team overview. (CODE-080 cross-tenant settings dashboard fix)
    manager = (
        Technician.objects.filter(user=request.user, tenant=tenant).first()
        if tenant else None
    )

    if not manager:
        messages.warning(request, "Technician profile not found")
        return redirect('technician_dashboard')

    # Build a Prefetch for the 5 most-recent repairs per technician so we avoid
    # firing one Repair query per tech inside the loop below (N+1).
    # Django's Prefetch with to_attr allows slicing per-object after the fact.
    recent_repairs_qs = Repair.objects.select_related('customer').order_by('-service_date')
    if tenant:
        recent_repairs_qs = recent_repairs_qs.filter(tenant=tenant)

    # Annotate team members with repair stats to minimize queries.
    # NOTE: Count('repair') must include repair__tenant=tenant so we only count
    # repairs that belong to the current shop.  Without this, a technician who
    # somehow also has repairs in another tenant would show inflated counts —
    # leaking cross-tenant data into the team dashboard.  (CODE-075)
    from django.db.models import Count, Q
    tenant_filter = Q(repair__tenant=tenant) if tenant else Q(repair__tenant__isnull=False)
    team_members_annotated = (
        manager.managed_technicians
        .filter(is_active=True)
        .select_related('user')
        .prefetch_related(
            Prefetch(
                'repair_set',
                queryset=recent_repairs_qs,
                to_attr='_recent_repairs_cache',
            )
        )
        .annotate(
            total_repairs=Count('repair', filter=tenant_filter),
            pending_repairs_count=Count(
                'repair',
                filter=tenant_filter & Q(repair__queue_status__in=['REQUESTED', 'PENDING', 'APPROVED'])
            ),
            completed_repairs_count=Count(
                'repair',
                filter=tenant_filter & Q(repair__queue_status='COMPLETED')
            ),
        )
    )

    team_stats = []
    for tech in team_members_annotated:
        completion_rate = (tech.completed_repairs_count / tech.total_repairs * 100) if tech.total_repairs > 0 else 0

        # Use the prefetched cache instead of issuing a new query per technician
        recent_repairs = tech._recent_repairs_cache[:5]

        team_stats.append({
            'technician': tech,
            'total_repairs': tech.total_repairs,
            'pending_repairs': tech.pending_repairs_count,
            'completed_repairs': tech.completed_repairs_count,
            'completion_rate': round(completion_rate, 1),
            'recent_repairs': recent_repairs,
        })

    total_team_repairs = sum(stat['total_repairs'] for stat in team_stats)
    total_team_pending = sum(stat['pending_repairs'] for stat in team_stats)
    total_team_completed = sum(stat['completed_repairs'] for stat in team_stats)

    context = {
        'is_admin': is_tenant_admin(request.user, tenant=getattr(request, "tenant", None)),
        'technician': manager,
        'team_stats': team_stats,
        'total_team_repairs': total_team_repairs,
        'total_team_pending': total_team_pending,
        'total_team_completed': total_team_completed,
        'team_members_count': len(team_stats),
    }

    return render(request, 'technician_portal/settings/team_overview.html', context)


# ─── Warranty Policy Views ────────────────────────────────────────────────────

WARRANTY_SEED_DEFAULTS = {
    'repairs': {
        'name': 'Standard Warranty',
        'coverage_description': (
            'One year warranty on all repairs against defects in workmanship.'
        ),
    },
    'replacements': {
        'name': 'Replacement Warranty',
        'coverage_description': (
            'One year warranty on all glass replacements against leaks and '
            'defects in workmanship.'
        ),
    },
}


def _get_or_create_tenant_policy(tenant, applies_to):
    """Return the tenant-wide policy for a service type, creating a sensible
    default (365 days) if the tenant doesn't have one yet."""
    policy = (
        WarrantyPolicy.objects
        .filter(tenant=tenant, customer__isnull=True, applies_to=applies_to)
        .order_by('-is_active', 'pk')
        .first()
    )
    if policy:
        return policy

    seed = WARRANTY_SEED_DEFAULTS[applies_to]
    name = seed['name']
    counter = 2
    while WarrantyPolicy.objects.filter(tenant=tenant, name=name).exists():
        name = f"{seed['name']} {counter}"
        counter += 1

    return WarrantyPolicy.objects.create(
        tenant=tenant,
        name=name,
        applies_to=applies_to,
        duration_type='custom_days',
        duration_days=365,
        coverage_description=seed['coverage_description'],
    )


@manager_required
@ensure_csrf_cookie
def manage_warranty_policies(request):
    """Warranty settings: one policy for repairs, one for replacements."""
    tenant = getattr(request, 'tenant', None)
    try:
        manager = (
            Technician.objects.filter(user=request.user, tenant=tenant).first()
            if tenant else None
        )
    except Exception:
        manager = None

    repair_policy = _get_or_create_tenant_policy(tenant, 'repairs') if tenant else None
    replacement_policy = _get_or_create_tenant_policy(tenant, 'replacements') if tenant else None

    context = {
        'is_admin': is_tenant_admin(request.user, tenant=getattr(request, 'tenant', None)),
        'technician': manager,
        'repair_policy': repair_policy,
        'replacement_policy': replacement_policy,
        'policy_cards': [p for p in (repair_policy, replacement_policy) if p],
    }
    return render(request, 'technician_portal/settings/warranty_policies.html', context)


@manager_required
def get_warranty_policy(request, policy_id):
    """AJAX endpoint to fetch a single warranty policy."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    tenant = getattr(request, 'tenant', None)
    try:
        policy = get_object_or_404(WarrantyPolicy, id=policy_id, tenant=tenant)
        return JsonResponse({
            'success': True,
            'policy': {
                'id': policy.id,
                'name': policy.name,
                'applies_to': policy.applies_to,
                'duration_type': policy.duration_type,
                'duration_days': policy.duration_days,
                'coverage_description': policy.coverage_description,
                'covers_labor': policy.covers_labor,
                'covers_materials': policy.covers_materials,
                'is_default': policy.is_default,
                'is_active': policy.is_active,
            }
        })
    except Http404:
        raise
    except Exception as e:
        logger.error(f'Error fetching warranty policy: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@manager_required
def create_warranty_policy(request):
    """AJAX endpoint to create a new warranty policy."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return JsonResponse({'success': False, 'error': 'Tenant not resolved'}, status=400)

    try:
        data = json.loads(request.body)

        if not data.get('name'):
            return JsonResponse({'success': False, 'error': 'Policy name is required'}, status=400)

        applies_to = data.get('applies_to', 'repairs')
        valid_applies = [c[0] for c in WarrantyPolicy.APPLIES_TO_CHOICES]
        if applies_to not in valid_applies:
            return JsonResponse({'success': False, 'error': 'Invalid "Applies To" value.'}, status=400)

        duration_type = data.get('duration_type', 'custom_days')
        valid_duration_types = [c[0] for c in WarrantyPolicy.WARRANTY_DURATION_CHOICES]
        if duration_type not in valid_duration_types:
            return JsonResponse({'success': False, 'error': 'Invalid "Duration Type" value.'}, status=400)

        duration_days = data.get('duration_days', 365)
        try:
            duration_days = int(duration_days)
        except (ValueError, TypeError):
            duration_days = 365

        policy = WarrantyPolicy.objects.create(
            tenant=tenant,
            name=data['name'],
            applies_to=applies_to,
            duration_type=duration_type,
            duration_days=duration_days,
            coverage_description=data.get('coverage_description', ''),
            covers_labor=data.get('covers_labor', True),
            covers_materials=data.get('covers_materials', True),
            is_default=data.get('is_default', False),
            is_active=data.get('is_active', True),
        )

        return JsonResponse({
            'success': True,
            'message': 'Warranty policy created successfully',
            'policy': {
                'id': policy.id,
                'name': policy.name,
                'applies_to': policy.applies_to,
                'applies_to_display': policy.get_applies_to_display(),
                'duration_type': policy.duration_type,
                'duration_days': policy.duration_days,
                'coverage_description': policy.coverage_description,
                'covers_labor': policy.covers_labor,
                'covers_materials': policy.covers_materials,
                'is_default': policy.is_default,
                'is_active': policy.is_active,
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f'Error creating warranty policy: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@manager_required
def update_warranty_policy(request, policy_id):
    """AJAX endpoint to update an existing warranty policy."""
    if request.method not in ['PUT', 'POST']:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    tenant = getattr(request, 'tenant', None)
    try:
        policy = get_object_or_404(WarrantyPolicy, id=policy_id, tenant=tenant)
        data = json.loads(request.body)

        if 'name' in data:
            policy.name = data['name']
        if 'applies_to' in data:
            valid_applies = [c[0] for c in WarrantyPolicy.APPLIES_TO_CHOICES]
            if data['applies_to'] not in valid_applies:
                return JsonResponse({'success': False, 'error': 'Invalid "Applies To" value.'}, status=400)
            policy.applies_to = data['applies_to']
        if 'duration_type' in data:
            valid_duration_types = [c[0] for c in WarrantyPolicy.WARRANTY_DURATION_CHOICES]
            if data['duration_type'] not in valid_duration_types:
                return JsonResponse({'success': False, 'error': 'Invalid "Duration Type" value.'}, status=400)
            policy.duration_type = data['duration_type']
        if 'duration_days' in data:
            try:
                policy.duration_days = int(data['duration_days'])
            except (ValueError, TypeError):
                policy.duration_days = 365
        if 'coverage_description' in data:
            policy.coverage_description = data['coverage_description']
        if 'covers_labor' in data:
            policy.covers_labor = data['covers_labor']
        if 'covers_materials' in data:
            policy.covers_materials = data['covers_materials']
        if 'is_default' in data:
            policy.is_default = data['is_default']
        if 'is_active' in data:
            policy.is_active = data['is_active']

        policy.save()

        return JsonResponse({
            'success': True,
            'message': 'Warranty policy updated successfully',
            'policy': {
                'id': policy.id,
                'name': policy.name,
                'applies_to': policy.applies_to,
                'applies_to_display': policy.get_applies_to_display(),
                'duration_type': policy.duration_type,
                'duration_days': policy.duration_days,
                'coverage_description': policy.coverage_description,
                'covers_labor': policy.covers_labor,
                'covers_materials': policy.covers_materials,
                'is_default': policy.is_default,
                'is_active': policy.is_active,
            }
        })

    except Http404:
        raise
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        logger.error(f'Error updating warranty policy: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@manager_required
def delete_warranty_policy(request, policy_id):
    """AJAX endpoint to delete a warranty policy."""
    if request.method not in ['DELETE', 'POST']:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    tenant = getattr(request, 'tenant', None)
    try:
        policy = get_object_or_404(WarrantyPolicy, id=policy_id, tenant=tenant)
        policy_name = policy.name
        policy.delete()

        return JsonResponse({
            'success': True,
            'message': f'Warranty policy "{policy_name}" deleted successfully',
        })

    except Http404:
        raise
    except Exception as e:
        logger.error(f'Error deleting warranty policy: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@manager_required
def toggle_warranty_policy(request, policy_id):
    """AJAX endpoint to toggle active status of a warranty policy."""
    if request.method not in ['PATCH', 'POST']:
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    tenant = getattr(request, 'tenant', None)
    try:
        policy = get_object_or_404(WarrantyPolicy, id=policy_id, tenant=tenant)
        policy.is_active = not policy.is_active
        policy.save()

        return JsonResponse({
            'success': True,
            'message': f'Warranty policy {"activated" if policy.is_active else "deactivated"}',
            'is_active': policy.is_active,
        })

    except Http404:
        raise
    except Exception as e:
        logger.error(f'Error toggling warranty policy: {str(e)}')
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
