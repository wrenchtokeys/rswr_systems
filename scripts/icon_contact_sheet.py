#!/usr/bin/env python
"""Render the `{% icon %}` vocabulary to an HTML contact sheet.

S13a found two broken icons that no assertion could have caught — `car` drawn
from the wrong angle, and a `$` inside a document that smudged shut at 16px.
The test suite holds the set to its geometry rules; only looking at it tells
you an icon is unreadable. That check was done by hand once, which means the
next sweep would have to re-author it — so it lives here instead.

    python scripts/icon_contact_sheet.py -o /tmp/icons.html

Two sections:

* **The grid** — every entry at 24px with its name, aliases underneath.
* **Side by side** — each icon next to the Font Awesome glyph it replaces, at
  five font sizes, over the real vendored `fontawesome.min.css`. Drop-in is a
  CSS fact: if a baseline or an optical weight is off, a two-line diff on a
  migrated template reads as a redesign.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.icons import ALIASES, ICONS  # noqa: E402

STATIC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
SIZES = [12, 14, 16, 20, 24]

# `.icon` as input.css defines it — copied, not imported, so the sheet renders
# without a Tailwind build. If these drift apart the side-by-side lies.
CSS = """
body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       margin: 0; padding: 32px; color: #111827; background: #fff; }
h2 { font-size: 15px; letter-spacing: .04em; text-transform: uppercase;
     color: #6b7280; margin: 40px 0 16px; }
.icon { width: 1em; height: 1em; display: inline-block; vertical-align: -0.125em; }
.grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 4px 8px; }
.cell { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px 8px; text-align: center; }
.cell svg { font-size: 24px; color: #111827; }
.name { font-size: 11px; color: #374151; margin-top: 8px; word-break: break-all; }
.alias { font-size: 10px; color: #9ca3af; }
table { border-collapse: collapse; }
td, th { padding: 6px 14px; border-bottom: 1px solid #f3f4f6; text-align: left;
         vertical-align: middle; white-space: nowrap; }
th { font-size: 11px; color: #6b7280; font-weight: 500; }
td.pair { border-left: 1px solid #f3f4f6; }
.label { font-size: 12px; color: #374151; }
.rule { display: inline-block; border-bottom: 1px solid #ef4444; }
"""


def _svg(body, style=''):
    return (
        f'<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true"{style}>{body}</svg>'
    )


def grid():
    reverse = {}
    for alias, target in ALIASES.items():
        reverse.setdefault(target, []).append(alias)
    out = ['<h2>The set — %d icons at 24px</h2><div class="grid">' % len(ICONS)]
    for name in sorted(ICONS):
        aka = ', '.join(sorted(reverse.get(name, [])))
        out.append(
            f'<div class="cell">{_svg(ICONS[name])}'
            f'<div class="name">{name}</div>'
            f'<div class="alias">{aka}</div></div>'
        )
    out.append('</div>')
    return '\n'.join(out)


def side_by_side(pairs):
    """`pairs` is [(icon name, font awesome class), ...]."""
    head = ''.join(f'<th colspan="2">{s}px</th>' for s in SIZES)
    rows = [f'<h2>Drop-in check — against the vendored Font Awesome</h2>'
            f'<table><tr><th></th>{head}</tr>']
    for name, fa in pairs:
        body = ICONS.get(name)
        if body is None:
            continue
        cells = []
        for size in SIZES:
            style = f' style="font-size:{size}px"'
            cells.append(f'<td class="pair"><span class="rule">{_svg(body, style)}</span></td>')
            cells.append(f'<td><span class="rule"><i class="{fa}"{style}></i></span></td>')
        rows.append(f'<tr><td class="label">{name} / {fa}</td>{"".join(cells)}</tr>')
    rows.append('</table>')
    return '\n'.join(rows)


def default_pairs():
    """Every icon paired with the Font Awesome name that resolves to it."""
    seen, pairs = set(), []
    for alias, target in sorted(ALIASES.items()):
        if target not in seen:
            seen.add(target)
            pairs.append((target, f'fas fa-{alias}'))
    for name in sorted(ICONS):
        if name not in seen:
            pairs.append((name, f'fas fa-{name}'))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', default='icon_contact_sheet.html')
    args = ap.parse_args()
    html = (
        '<!doctype html><meta charset="utf-8"><title>Icon contact sheet</title>'
        f'<link rel="stylesheet" href="file://{STATIC}/css/vendor/fontawesome.min.css">'
        f'<style>{CSS}</style>{grid()}{side_by_side(default_pairs())}'
    )
    with open(args.out, 'w') as fh:
        fh.write(html)
    print(args.out)


if __name__ == '__main__':
    main()
