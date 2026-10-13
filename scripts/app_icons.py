#!/usr/bin/env python
"""Draw the home-screen icons for the installed app.

    python scripts/app_icons.py

Writes `static/images/app/*.png`. Commit the output.

WHY A SCRIPT AND NOT AN EXPORTED IMAGE
--------------------------------------
The RS mark exists only as an inline SVG (`templates/includes/rs_mark.html`)
— there is no logo file. The one image in
`static/images/` that looks like one, `rs_logo.jpg`, is Rockstar Windshield
Repair's logo: a shop's, not the platform's. Putting it on every owner's home
screen would be the same leak as the 2026-09-18 email signature. So the icon is
drawn here as the same letters at the same weight, in the same Inter the app
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

# The mark is Inter Black "RS" and nothing else (templates/includes/rs_mark.html).
WEIGHT = 900
# Letter height as a share of the tile. At 0.51 the letters span 68% of the
# width, so their corners sit 0.38 from centre — inside the 0.4 maskable zone.
FONT_SHARE = 0.51
SUPERSAMPLE = 4


def draw_icon(size, rounded):
    s = size * SUPERSAMPLE
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=TILE)
    else:
        d.rectangle([0, 0, s, s], fill=TILE)

    font = ImageFont.truetype(str(FONT), int(s * FONT_SHARE))
    font.set_variation_by_axes([WEIGHT])
    # Centre the ink, not the line box: 'mm' centres on ascender-to-descender,
    # which sits capitals visibly high.
    left, top, right, bottom = d.textbbox((0, 0), 'RS', font=font, anchor='ls')
    d.text(((s - (right + left)) / 2, (s - (bottom + top)) / 2), 'RS',
           font=font, fill=WHITE, anchor='ls')

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
