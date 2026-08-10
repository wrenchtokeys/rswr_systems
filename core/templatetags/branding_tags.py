"""Template tags for per-shop (tenant) branding."""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.tenants.branding import brand_shades

register = template.Library()


@register.simple_tag(takes_context=True)
def tenant_brand_css(context):
    """
    Emit a <style> block overriding the --brand-* CSS variables with shades
    generated from the shop's brand color. Renders nothing when the tenant
    has no brand color — or when the plan doesn't include custom branding
    (Tenant.branding_enabled) — leaving the default palette untouched.
    """
    request = context.get('request')
    tenant = getattr(request, 'tenant', None) if request else None
    if tenant is not None and not tenant.branding_enabled:
        return ''
    brand_color = getattr(tenant, 'brand_color', '') if tenant else ''
    shades = brand_shades(brand_color)
    if not shades:
        return ''
    lines = ''.join(f'--brand-{shade}: {rgb};' for shade, rgb in sorted(shades.items()))
    return format_html('<style>:root {{ {} }}</style>', mark_safe(lines))
