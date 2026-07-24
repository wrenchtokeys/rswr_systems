"""
Brand color helpers.

A shop picks ONE brand color (Tenant.brand_color). The customer portal's
Tailwind `brand-*` palette reads CSS variables (see static/css/src/input.css),
so we generate the full 50–900 shade scale from that single hex here and
inject it as an inline <style> override (core/templatetags/branding_tags.py).
"""

# Mix ratios that approximate Tailwind's shade curve. Values are
# (mix_target, ratio) where ratio is how much of the target to blend in.
_SHADE_MIX = {
    50: ('white', 0.95),
    100: ('white', 0.88),
    200: ('white', 0.75),
    300: ('white', 0.55),
    400: ('white', 0.25),
    500: (None, 0.0),
    600: ('black', 0.12),
    700: ('black', 0.26),
    800: ('black', 0.40),
    900: ('black', 0.52),
}


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _mix(rgb, target, ratio):
    t = (255, 255, 255) if target == 'white' else (0, 0, 0)
    return tuple(round(c + (tc - c) * ratio) for c, tc in zip(rgb, t))


def brand_shades(hex_color):
    """
    Generate a Tailwind-style 50–900 shade scale from a single hex color.

    Returns:
        dict: {50: 'r g b', 100: 'r g b', ...} — space-separated RGB channel
        values, the format CSS variables consumed by `rgb(var(--x) / alpha)`
        require. Returns {} for a falsy/malformed color so callers can fall
        back to the default palette.
    """
    try:
        base = _hex_to_rgb(hex_color)
        if len(hex_color.lstrip('#')) != 6:
            return {}
    except (ValueError, AttributeError, TypeError):
        return {}
    shades = {}
    for shade, (target, ratio) in _SHADE_MIX.items():
        rgb = base if target is None else _mix(base, target, ratio)
        shades[shade] = f'{rgb[0]} {rgb[1]} {rgb[2]}'
    return shades
