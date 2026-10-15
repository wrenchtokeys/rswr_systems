#!/usr/bin/env python3
"""
Generate assets/css/palette.css — the colour variables behind every utility,
and the staff app's dark palette.

Dark mode here flips the PALETTE, not the templates. 224 templates hold ~5,000
hardcoded light utilities (`text-gray-900`, `bg-white`, `bg-green-100`, ...) and
a `dark:` variant on each would be a months-long sweep that leaves pages half
converted. Instead tailwind.config.js points every colour family the app uses
at CSS variables, `:root` holds Tailwind's own default values (so light mode
paints exactly what it painted before), and this file re-points them.

Two roles, because one variable cannot serve both:
  --c-<family>-<n>   backgrounds, borders, rings, gradients, fills
  --tx-<family>-<n>  text and placeholder colour (falls back to --c-… in light)
`bg-gray-900` must stay a dark surface while `text-gray-900` must become light;
`bg-green-600 text-white` must stay a saturated button while `text-green-600`
on a dark card must lift to stay readable. tailwind.config.js wires textColor
to the --tx-… names.

Run:  python scripts/dark_palette.py        (writes the CSS)
      python scripts/dark_palette.py --check (exit 1 if the file is stale)

Never hand-edit palette.css; tests/test_dark_mode.py fails on a stale file.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'assets' / 'css' / 'palette.css'

sys.path.insert(0, str(ROOT))
from apps.tenants.branding import (  # noqa: E402  (pure Python, no Django)
    OVERLAY, PAGE, RAISED, brand_dark_shades, hex_to_rgb, mix,
)

SHADES = (50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950)

# Tailwind v3.4.17 defaults (tailwindcss/lib/public/colors.js) — the light
# values, byte for byte. tests/test_dark_mode.py checks the compiled app.css
# against this table, so light mode cannot drift from what shipped before.
TAILWIND = {
    'gray': ['#f9fafb', '#f3f4f6', '#e5e7eb', '#d1d5db', '#9ca3af', '#6b7280',
             '#4b5563', '#374151', '#1f2937', '#111827', '#030712'],
    'red': ['#fef2f2', '#fee2e2', '#fecaca', '#fca5a5', '#f87171', '#ef4444',
            '#dc2626', '#b91c1c', '#991b1b', '#7f1d1d', '#450a0a'],
    'orange': ['#fff7ed', '#ffedd5', '#fed7aa', '#fdba74', '#fb923c', '#f97316',
               '#ea580c', '#c2410c', '#9a3412', '#7c2d12', '#431407'],
    'amber': ['#fffbeb', '#fef3c7', '#fde68a', '#fcd34d', '#fbbf24', '#f59e0b',
              '#d97706', '#b45309', '#92400e', '#78350f', '#451a03'],
    'yellow': ['#fefce8', '#fef9c3', '#fef08a', '#fde047', '#facc15', '#eab308',
               '#ca8a04', '#a16207', '#854d0e', '#713f12', '#422006'],
    'green': ['#f0fdf4', '#dcfce7', '#bbf7d0', '#86efac', '#4ade80', '#22c55e',
              '#16a34a', '#15803d', '#166534', '#14532d', '#052e16'],
    'emerald': ['#ecfdf5', '#d1fae5', '#a7f3d0', '#6ee7b7', '#34d399', '#10b981',
                '#059669', '#047857', '#065f46', '#064e3b', '#022c22'],
    'teal': ['#f0fdfa', '#ccfbf1', '#99f6e4', '#5eead4', '#2dd4bf', '#14b8a6',
             '#0d9488', '#0f766e', '#115e59', '#134e4a', '#042f2e'],
    'cyan': ['#ecfeff', '#cffafe', '#a5f3fc', '#67e8f9', '#22d3ee', '#06b6d4',
             '#0891b2', '#0e7490', '#155e75', '#164e63', '#083344'],
    'sky': ['#f0f9ff', '#e0f2fe', '#bae6fd', '#7dd3fc', '#38bdf8', '#0ea5e9',
            '#0284c7', '#0369a1', '#075985', '#0c4a6e', '#082f49'],
    'blue': ['#eff6ff', '#dbeafe', '#bfdbfe', '#93c5fd', '#60a5fa', '#3b82f6',
             '#2563eb', '#1d4ed8', '#1e40af', '#1e3a8a', '#172554'],
    'indigo': ['#eef2ff', '#e0e7ff', '#c7d2fe', '#a5b4fc', '#818cf8', '#6366f1',
               '#4f46e5', '#4338ca', '#3730a3', '#312e81', '#1e1b4b'],
    'purple': ['#faf5ff', '#f3e8ff', '#e9d5ff', '#d8b4fe', '#c084fc', '#a855f7',
               '#9333ea', '#7e22ce', '#6b21a8', '#581c87', '#3b0764'],
    'pink': ['#fdf2f8', '#fce7f3', '#fbcfe8', '#f9a8d4', '#f472b6', '#ec4899',
             '#db2777', '#be185d', '#9d174d', '#831843', '#500724'],
}
FAMILIES = tuple(TAILWIND)

FIELD = '#0f141a'      # inputs: a well a shade below the card

# Neutral ramp, both roles. bg: 50-300 are the surfaces/hairlines a light page
# builds from gray (zebra rows, hover, borders); 600-950 stay DARK, because
# `bg-gray-900 text-white` is a dark chip and must remain one.
GRAY_BG = ['#1b2129', '#222933', '#2c343f', '#3a4350', '#5b6573', '#6e7886',
           '#4a5361', '#3a424e', '#2a313b', '#1f252d', '#12161c']
# text: inverted. text-gray-900 headings -> near white, 500 secondary -> a
# mid-tone that still clears 4.5:1 on a card, 300/200 (dividers, disabled) dim.
GRAY_TX = ['#1b2129', '#2c343f', '#3a4350', '#5b6573', '#7d8796', '#97a1ae',
           '#adb5c0', '#c5ccd5', '#dce1e7', '#eef1f4', '#f7f8fa']


def status_scale(hexes):
    """Dark (bg, text) scales for a hue family.

    bg: 50-200 become low tints of the hue over the card surface, so a
    `bg-green-100` pill is a quiet green chip, not a glowing slab; 300 is a
    border-strength tint; 400-700 keep Tailwind's saturated values so
    `bg-red-600 text-white` is still a red button; 800-950 sink toward the page.
    text: 700-950 (the "dark text on a light tint" half of every badge) become
    the family's light shades; 500/600 lift to 400 so `text-green-600` money
    stays readable on a card; 50-300 keep their light values — they only ever
    sit on a saturated 500-700 fill, which did not move.
    """
    light = [hex_to_rgb(h) for h in hexes]
    base = light[5]
    raised = hex_to_rgb(RAISED)
    page = hex_to_rgb(PAGE)
    bg = [
        mix(raised, base, 0.10),   # 50
        mix(raised, base, 0.18),   # 100
        mix(raised, base, 0.30),   # 200
        mix(raised, base, 0.50),   # 300
        light[4], light[5], light[6], light[7],
        mix(page, light[7], 0.55),  # 800
        mix(page, light[7], 0.40),  # 900
        mix(page, light[7], 0.25),  # 950
    ]
    tx = [
        light[0], light[1], light[2], light[3], light[4],
        light[4], light[4],               # 500, 600 -> 400
        light[3], light[3],               # 700, 800 -> 300
        light[2], light[1],               # 900 -> 200, 950 -> 100
    ]
    return bg, tx


DEFAULT_BRAND = '#3b82f6'   # --brand-500 default in input.css


def chan(rgb):
    return '{} {} {}'.format(*rgb)


def dark_declarations():
    """Every custom property the dark theme sets, in a stable order."""
    lines = []
    g_bg = [hex_to_rgb(h) for h in GRAY_BG]
    g_tx = [hex_to_rgb(h) for h in GRAY_TX]
    for n, b, t in zip(SHADES, g_bg, g_tx):
        lines.append(f'--c-gray-{n}: {chan(b)};')
        lines.append(f'--tx-gray-{n}: {chan(t)};')
    for fam in FAMILIES:
        if fam == 'gray':
            continue
        bg, tx = status_scale(TAILWIND[fam])
        for n, b, t in zip(SHADES, bg, tx):
            lines.append(f'--c-{fam}-{n}: {chan(b)};')
            lines.append(f'--tx-{fam}-{n}: {chan(t)};')
    bbg, btx = brand_dark_shades(DEFAULT_BRAND)
    for n in sorted(bbg):
        lines.append(f'--brand-{n}: {bbg[n]};')
        lines.append(f'--brand-tx-{n}: {btx[n]};')
    lines += [
        # material ladder + legacy tokens (input.css :root)
        f'--surface-base: {PAGE};',
        f'--surface-raised: {RAISED};',
        f'--surface-overlay: {OVERLAY};',
        '--surface-white: 22 27 34;',
        '--hairline: rgb(255 255 255 / 0.08);',
        '--sk-tone: #232a33;',
        '--sk-shine: #2c343f;',
        '--fab-ring: rgb(255 255 255 / 0.10);',
        '--shadow-raised: 0 1px 2px rgb(0 0 0 / 0.30);',
        '--shadow-float: 0 2px 4px rgb(0 0 0 / 0.30), 0 16px 40px -12px rgb(0 0 0 / 0.55);',
        '--shadow-overlay: 0 8px 12px rgb(0 0 0 / 0.35), 0 32px 64px -16px rgb(0 0 0 / 0.70);',
        f'--background-color: {PAGE};',
        f'--surface-color: {RAISED};',
        '--text-color: #dce1e7;',
        '--text-secondary: #adb5c0;',
        '--text-muted: #7d8796;',
        '--border-color: #2c343f;',
        'color-scheme: dark;',
    ]
    return lines


HEADER = """\
/* GENERATED by scripts/dark_palette.py — do not edit by hand.
   tailwind.config.js points every colour family at these variables. :root
   holds Tailwind's own light values, so light mode is unchanged; the dark
   palette applies only under <html data-theme="dark"> (or "system" on a device
   set to dark). Public pages, the customer portal, emails and PDFs never carry
   the attribute and so never go dark. */
"""


def light_declarations():
    lines = []
    for fam in FAMILIES:
        for n, h in zip(SHADES, TAILWIND[fam]):
            lines.append(f'--c-{fam}-{n}: {chan(hex_to_rgb(h))};')
    return lines


# Rules the variables cannot express. `{r}` is the dark root selector; each
# rule is emitted for both the explicit and the "match device" switch.
EXTRA_RULES = [
    # The shells paint <body> bg-gray-50 under bg-white cards. In the dark the
    # card must be LIGHTER than the page, so the page drops to the base rung.
    '{r} body.bg-gray-50 {{ background-color: {page}; }}',
    # Translucent white is a highlight on a saturated header (an icon chip on a
    # brand banner), not a card — it keeps meaning white.
    *[f'{{r}} .bg-white\\/{a} {{{{ background-color: rgb(255 255 255 / {int(a) / 100:g}); }}}}'
      for a in ('5', '10', '15', '20', '25')],
    # Form fields carry no background class (they inherit the UA's `Field`),
    # which under color-scheme: dark is a flat neutral grey slab. Give them a
    # well slightly darker than the card. Wrapped in :where() end to end so it
    # has zero specificity and any `bg-*` class on a field still wins.
    ':where({r}) :where(input:not([type=checkbox],[type=radio],[type=range],[type=file],'
    '[type=color],[type=submit],[type=button],[type=reset],[type=image]), select, textarea) '
    '{{ background-color: {field}; }}',
    # driver.js (the first-visit tour) hard-codes its footer buttons light.
    '{r} .driver-popover-footer button:not(.driver-popover-next-btn) {{ background-color: #222933; border-color: #3a4350; color: #dce1e7; }}',
    '{r} .driver-popover-close-btn:hover, {r} .driver-popover-close-btn:focus {{ color: #eef1f4; }}',
    '{r} .driver-popover-progress-text {{ color: #97a1ae; }}',
    # A shop logo is drawn for a white letterhead; dark lettering on a
    # transparent PNG disappears on graphite. Give it the paper back.
    '{r} img.shop-logo {{ background-color: #fff; border-radius: 0.5rem; padding: 0.25rem 0.375rem; }}',
    # flatpickr (vendored) ships light-only.
    '{r} .flatpickr-calendar {{ background: {overlay}; box-shadow: 0 0 0 1px rgb(255 255 255 / 0.08), 0 16px 40px -12px rgb(0 0 0 / 0.6); }}',
    '{r} .flatpickr-calendar.arrowTop:after, {r} .flatpickr-calendar.arrowTop:before {{ border-bottom-color: {overlay}; }}',
    '{r} .flatpickr-calendar.arrowBottom:after, {r} .flatpickr-calendar.arrowBottom:before {{ border-top-color: {overlay}; }}',
    '{r} .flatpickr-months .flatpickr-month, {r} .flatpickr-current-month input.cur-year, {r} .flatpickr-current-month .flatpickr-monthDropdown-months, {r} span.flatpickr-weekday, {r} .flatpickr-time input, {r} .flatpickr-time .flatpickr-am-pm {{ color: #dce1e7; fill: #dce1e7; background: transparent; }}',
    '{r} .flatpickr-months .flatpickr-prev-month svg, {r} .flatpickr-months .flatpickr-next-month svg {{ fill: #dce1e7; }}',
    '{r} .flatpickr-day {{ color: #dce1e7; }}',
    '{r} .flatpickr-day.prevMonthDay, {r} .flatpickr-day.nextMonthDay, {r} .flatpickr-day.flatpickr-disabled {{ color: #5b6573; }}',
    '{r} .flatpickr-day:hover, {r} .flatpickr-day:focus {{ background: #2c343f; border-color: #2c343f; }}',
    '{r} .flatpickr-day.today {{ border-color: #7d8796; }}',
    '{r} .flatpickr-time {{ border-top-color: #2c343f !important; }}',
    '{r} .flatpickr-time input:hover, {r} .flatpickr-time input:focus {{ background: #222933; }}',
]


def extra_rules(root):
    return [r.format(r=root, page=PAGE, overlay=OVERLAY, field=FIELD) for r in EXTRA_RULES]


def render():
    light = '\n'.join('  ' + d for d in light_declarations())
    decls = '\n'.join('  ' + d for d in dark_declarations())
    return (
        HEADER
        + '\n:root {\n' + light + '\n}\n'
        + '\n:root[data-theme="dark"] {\n' + decls + '\n}\n'
        + '\n@media (prefers-color-scheme: dark) {\n'
        + '  :root[data-theme="system"] {\n'
        + '\n'.join('  ' + l for l in decls.split('\n'))
        + '\n  }\n'
        + '\n'.join('  ' + r for r in extra_rules(':root[data-theme="system"]'))
        + '\n}\n\n'
        + '\n'.join(extra_rules(':root[data-theme="dark"]')) + '\n'
    )


def main(argv):
    css = render()
    if '--check' in argv:
        if not OUT.exists() or OUT.read_text() != css:
            print(f'{OUT} is stale — run python scripts/dark_palette.py', file=sys.stderr)
            return 1
        return 0
    OUT.write_text(css)
    print(f'Wrote {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
