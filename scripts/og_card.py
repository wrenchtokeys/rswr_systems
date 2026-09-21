#!/usr/bin/env python
"""Crop the Open Graph share card out of the real owner-dashboard capture.

    python scripts/og_card.py

Reads `static/images/landing/owner-dashboard.webp` — written by
`scripts/landing_shots.py` from the real app, driven headless against a seeded
demo shop — and writes `static/images/og-card.jpg` at Open Graph's 1200x630.
Commit the output, same as the landing captures.

WHY A SCRIPT AND NOT A HAND-MADE IMAGE
--------------------------------------
CLAUDE.md: never hand-author a mock of an app screen. The last one drifted from
the dashboard twice with nobody editing either file (UI_MAGIC S14). A share card
is the most-seen image the product has; it earns the same rule. This needs no
Chrome and no database — it is a crop — so it is cheap to re-run whenever the
dashboard capture is regenerated.

WHY JPEG
--------
The source is WebP, which Facebook now accepts but LinkedIn, Slack and iMessage
still handle unevenly. A share card that renders nowhere is worse than one that
is 40 KB larger.
"""

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'static' / 'images' / 'landing' / 'owner-dashboard.webp'
DEST = ROOT / 'static' / 'images' / 'og-card.jpg'

WIDTH, HEIGHT = 1200, 630
QUALITY = 88


def main():
    if not SOURCE.exists():
        print(f'Missing {SOURCE.relative_to(ROOT)} — run scripts/landing_shots.py first.')
        return 1

    with Image.open(SOURCE) as src:
        image = src.convert('RGB')

    # Scale to the card's width, then take the top of the frame. The dashboard's
    # capture is 1.6:1 and the card is 1.9:1, so the crop drops the bottom of
    # the page rather than squeezing it — the header, the money tiles and the
    # first rows are what a share should show.
    scale = WIDTH / image.width
    resized = image.resize(
        (WIDTH, max(HEIGHT, round(image.height * scale))),
        Image.LANCZOS,
    )
    card = resized.crop((0, 0, WIDTH, HEIGHT))

    DEST.parent.mkdir(parents=True, exist_ok=True)
    card.save(DEST, 'JPEG', quality=QUALITY, optimize=True, progressive=True)
    print(f'Wrote {DEST.relative_to(ROOT)} ({DEST.stat().st_size // 1024} KB, {WIDTH}x{HEIGHT})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
