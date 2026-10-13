#!/usr/bin/env python
"""Draw the home-screen icons for the installed app.

    python scripts/app_icons.py

Writes `static/images/app/*.png`. Commit the output.

WHY A SCRIPT AND NOT AN EXPORTED IMAGE
--------------------------------------
The RS mark exists only as an inline SVG in the shells (`base_app.html`,
`saas/login.html`, `landing.html`) — there is no logo file. The one image in
`static/images/` that looks like one, `rs_logo.jpg`, is Rockstar Windshield
Repair's logo: a shop's, not the platform's. Putting it on every owner's home
screen would be the same leak as the 2026-09-18 email signature. So the icon is
drawn here from the same geometry the shells use, in the same Inter the app
ships, and can be redrawn when the mark changes.

WHAT EACH FILE IS FOR
---------------------
icon-192 / icon-512     manifest `purpose: any` — rounded tile on transparency
icon-maskable-512       manifest `purpose: maskable` — full bleed; Android crops
                        it to whatever shape the launcher uses, so the mark
                        stays inside the central 80% safe zone
apple-touch-icon        iOS home screen — full bleed and OPAQUE (iOS paints
                        transparency black, then rounds the corners itself)
favicon-32              the browser tab
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / 'static' / 'fonts' / 'inter-variable-latin.woff2'
DEST = ROOT / 'static' / 'images' / 'app'

# brand-600 default (tailwind.config.js) — the platform's blue, never a shop's.
TILE = (37, 99, 235)
WHITE = (255, 255, 255)

# The shells draw the mark in a 40-unit viewBox at 60% of its tile, which reads
# fine beside a wordmark and too small alone on a home screen. 80% keeps the
# far corner of the sparkle 0.37 of the width from centre — inside the 0.4
# maskable safe zone.
MARK_SHARE = 0.8
# Centre of the drawn mark in viewBox units (the letters plus the sparkle sit
# up and to the right of the viewBox's own centre).
MARK_CENTRE = (22, 15.5)
SUPERSAMPLE = 4


def draw_icon(size, rounded):
    s = size * SUPERSAMPLE
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=TILE)
    else:
        d.rectangle([0, 0, s, s], fill=TILE)

    u = s * MARK_SHARE / 40          # one viewBox unit, in pixels
    ox = s / 2 - MARK_CENTRE[0] * u
    oy = s / 2 - MARK_CENTRE[1] * u

    def pt(x, y):
        return (ox + x * u, oy + y * u)

    font = ImageFont.truetype(str(FONT), int(16 * u))
    font.set_variation_by_axes([800])
    d.text(pt(20, 26), 'RS', font=font, fill=WHITE, anchor='ms')

    # The sparkle: a dot and four ticks, as in the shells' SVG.
    cx, cy = pt(32, 10)
    r = 2 * u
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    w = max(1, round(1.5 * u))
    for x1, y1, x2, y2 in ((32, 5, 32, 7), (32, 13, 32, 15), (27, 10, 29, 10), (35, 10, 37, 10)):
        a, b = pt(x1, y1), pt(x2, y2)
        d.line([a, b], fill=WHITE, width=w)
        for px, py in (a, b):       # round caps
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    outputs = (
        ('icon-192.png', 192, True, False),
        ('icon-512.png', 512, True, False),
        ('icon-maskable-512.png', 512, False, True),
        ('apple-touch-icon.png', 180, False, True),
        ('favicon-32.png', 32, True, False),
    )
    for name, size, rounded, opaque in outputs:
        img = draw_icon(size, rounded)
        if opaque:
            img = img.convert('RGB')
        img.save(DEST / name, optimize=True)
        print(f'wrote static/images/app/{name}')


if __name__ == '__main__':
    main()
