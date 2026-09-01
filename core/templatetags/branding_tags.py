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
    # This is the one <style> block in the app that no template sweep can reach,
    # and it only renders for a shop that HAS a brand colour — so a strict
    # style-src would have dropped every branded shop back to the default
    # palette while every unbranded test and dev shop stayed green (UI_MAGIC S18).
    nonce = getattr(request, 'csp_nonce', '') if request else ''
    return format_html('<style nonce="{}">:root {{{{ {} }}}}</style>',
                       nonce, mark_safe(lines))
