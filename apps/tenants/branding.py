"""
Brand color helpers.

A shop picks ONE brand color (Tenant.brand_color). The customer portal's
Tailwind `brand-*` palette reads CSS variables (see assets/css/input.css),
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


# ---- Dark mode --------------------------------------------------------------
# Pure Python on purpose: scripts/dark_palette.py imports this without Django.
# ---- The dark ground ------------------------------------------------------
# Cool graphite, not black: pure #000 under white text smears on OLED and reads
# as a hole rather than a surface. Each rung is a visible step lighter, because
# in the dark depth comes from lightness, not from shadow.
PAGE = '#0d1117'      # --surface-base, body bg (bg-gray-50 on <body>)
RAISED = '#161b22'    # cards, bg-white, the navbar
OVERLAY = '#1c222b'   # modals, dropdowns

def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return '#' + ''.join(f'{c:02x}' for c in rgb)


def mix(a, b, t):
    """t of b blended into a (both rgb tuples)."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def luminance(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


WHITE = (255, 255, 255)


def lift_until(rgb, against, ratio, step=0.04):
    """Blend toward white until `rgb` clears `ratio` against `against`."""
    out = rgb
    t = 0.0
    while contrast(out, against) < ratio and t < 1:
        t += step
        out = mix(rgb, WHITE, t)
    return out


def brand_dark_shades(hex_color):
    """Dark-mode brand scale from one hex. Returns (bg, tx) dicts of 'r g b'.

    The rules a shop's colour has to survive on a dark ground:
    * 50-300 are tints over the card — a selected nav pill, a highlighted row.
    * 600 is the button fill. It keeps the shop's colour, but a navy or black
      brand vanishes on graphite, so it is lifted until it clears 3:1 against
      the card (WCAG's bar for a UI component). 700 — the hover — is a touch
      LIGHTER, the dark-mode convention, and 500 matches 600.
    * Text shades (link, active nav, `text-brand-600`) lift to 6:1 on the card
      (comfortably past the 4.5:1 floor), so further than the fill does.
    scripts/dark_palette.py bakes the default (unbranded) blue through this
    same function, so a branded and an unbranded shop follow one rule.
    """
    base = hex_to_rgb(hex_color)
    raised = hex_to_rgb(RAISED)
    page = hex_to_rgb(PAGE)
    # Start from the shop's own 600 — what their buttons are in light mode.
    light600 = mix(base, (0, 0, 0), 0.12)
    fill = lift_until(light600, raised, 3.0)
    hover = mix(fill, WHITE, 0.12)
    # 6:1, not the 4.5 floor: this is every link and active nav item.
    text = lift_until(base, raised, 6.0)
    text_strong = lift_until(base, raised, 8.0)
    light_tint = mix(base, WHITE, 0.55)
    bg = {
        50: mix(raised, base, 0.12),
        100: mix(raised, base, 0.20),
        200: mix(raised, base, 0.32),
        300: mix(raised, base, 0.50),
        400: mix(fill, WHITE, 0.25),
        500: fill,
        600: fill,
        700: hover,
        800: mix(page, fill, 0.55),
        900: mix(page, fill, 0.40),
    }
    tx = {
        50: mix(base, WHITE, 0.95),
        100: mix(base, WHITE, 0.88),
        200: mix(base, WHITE, 0.75),
        300: light_tint,
        400: text,
        500: text,
        600: text,
        700: text_strong,
        800: text_strong,
        900: lift_until(base, raised, 10.0),
    }
    fmt = lambda d: {k: '{} {} {}'.format(*v) for k, v in d.items()}
    return fmt(bg), fmt(tx)




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


def brand_shades_dark(hex_color):
    """
    The dark-mode counterpart of brand_shades(): (bg, text) dicts of
    space-separated RGB, or ({}, {}) for a falsy/malformed colour.
    """
    if not brand_shades(hex_color):
        return {}, {}
    return brand_dark_shades(hex_color)
