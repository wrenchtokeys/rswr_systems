"""The line-icon vocabulary behind ``{% icon 'name' %}`` (UI_MAGIC S13).

Why this file exists before the migration
-----------------------------------------
There are ~1,300 ``<i class="fas fa-…">`` in this repo and the count *grows*:
it went 1,281 → 1,303 in sixteen days without anyone touching icons on
purpose. Every new surface reaches for the icon vocabulary that already
exists, and Font Awesome is what exists. That is not carelessness — it is the
only thing a fresh session could do.

So the tag ships first and the migration comes later. From the day this lands,
new markup has something else to reach for, and the debt stops growing months
before the last ``<i class="fa`` dies. Font Awesome stays vendored and working
in the meantime; nothing here deletes it.

Drawing rules — every icon in this file obeys them
--------------------------------------------------
* 24×24 viewBox, geometry drawn on the box, never scaled by hand.
* ``fill="none"``, stroke only, **stroke-width 2**, round caps and joins.
  A filled glyph next to a stroked one is the one thing that makes a mixed
  icon set look broken, which is why there are no solid shapes here.
* Colour comes from ``currentColor``. Never put a colour in a path.
* A 2px dot is drawn as a zero-length round-capped line (``x2="12.01"``), the
  same trick the stroke-only sets use — a ``<circle r="1">`` with a 2px stroke
  renders as a muddy blob.

Adding one
----------
Add the entry, keep the rules above, and prefer the plain noun for the name
(``mail``, not ``envelope``; ``trash``, not ``trash-alt``). If a Font Awesome
name is what people will type, add it to ALIASES instead of drawing it twice.
``tests/test_icon_tag.py`` enforces the geometry rules on every entry, so a
malformed addition fails the suite rather than shipping a mismatched icon.
"""

# name -> the inner markup of a 24x24 stroke-only <svg>.
ICONS = {
    # --- status and feedback -------------------------------------------------
    'check': '<polyline points="20 6 9 17 4 12"/>',
    'check-circle': (
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>'
        '<polyline points="22 4 12 14.01 9 11.01"/>'
    ),
    'x': '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    'x-circle': (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>'
    ),
    'info': (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>'
    ),
    'alert-circle': (
        '<circle cx="12" cy="12" r="10"/>'
        '<line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'
    ),
    'alert-triangle': (
        '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3'
        'L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
        '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    'help-circle': (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
        '<line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    'ban': '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>',
    # A spinner is this plus `animate-spin` from the caller — the icon itself
    # never animates, so a static render (email, PDF, print) is still a shape.
    'loader': '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',

    'thumbs-up': (
        '<path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0'
        '-2-2.3z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>'
    ),
    'thumbs-down': (
        '<path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0'
        ' 2 2.3z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/>'
    ),

    # --- direction -----------------------------------------------------------
    'arrow-right': '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    'arrow-left': '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    'chevron-right': '<polyline points="9 18 15 12 9 6"/>',
    'chevron-left': '<polyline points="15 18 9 12 15 6"/>',
    'chevron-down': '<polyline points="6 9 12 15 18 9"/>',
    'chevron-up': '<polyline points="18 15 12 9 6 15"/>',
    'external-link': (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>'
    ),

    # --- actions -------------------------------------------------------------
    'plus': '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    'minus': '<line x1="5" y1="12" x2="19" y2="12"/>',
    'pen': '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5z"/>',
    'trash': (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
        '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>'
    ),
    'save': (
        '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
        '<polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>'
    ),
    'send': '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    'search': '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    'copy': (
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    'link': (
        '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
        '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'
    ),
    'download': (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    'upload': (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'
    ),
    'rotate-ccw': (
        '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>'
    ),
    'rotate-cw': (
        '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'
    ),
    'play': '<polygon points="5 3 19 12 5 21 5 3"/>',
    'eye': (
        '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    'log-in': (
        '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>'
        '<polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>'
    ),
    'log-out': (
        '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>'
        '<polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>'
    ),

    # --- people --------------------------------------------------------------
    'user': (
        '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'
    ),
    'users': (
        '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
        '<path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    'user-plus': (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/>'
        '<line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>'
    ),
    'user-check': (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/>'
        '<polyline points="17 11 19 13 23 9"/>'
    ),

    # --- shop, jobs, field ---------------------------------------------------
    'wrench': (
        '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1'
        '-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>'
    ),
    # Front view, not side: it is what `fa-car` draws (so a half-migrated page
    # does not jump), it holds together at text-sm where the side view goes
    # mushy, and on a glass shop's screens the windshield is the subject.
    'car': (
        '<path d="M7 11 8.4 6.4A2 2 0 0 1 10.3 5h3.4a2 2 0 0 1 1.9 1.4L17 11"/>'
        '<rect x="3.5" y="11" width="17" height="7" rx="2"/>'
        '<path d="M7 14.5h.01"/><path d="M17 14.5h.01"/>'
        '<path d="M6.5 18v1.5"/><path d="M17.5 18v1.5"/>'
    ),
    'car-side': (
        '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3'
        '-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4'
        'c0 .6.4 1 1 1h2"/>'
        '<circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>'
    ),
    'truck': (
        '<rect x="1" y="3" width="15" height="13" rx="1"/>'
        '<polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/>'
        '<circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>'
    ),
    'map-pin': (
        '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>'
    ),
    'building': (
        '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4"/>'
        '<path d="M8 6h.01"/><path d="M12 6h.01"/><path d="M16 6h.01"/>'
        '<path d="M8 10h.01"/><path d="M12 10h.01"/><path d="M16 10h.01"/>'
        '<path d="M8 14h.01"/><path d="M12 14h.01"/><path d="M16 14h.01"/>'
    ),
    'store': (
        '<path d="m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7"/>'
        '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>'
        '<path d="M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4"/><path d="M2 7h20"/>'
        '<path d="M22 7v3a2 2 0 0 1-4 0 2 2 0 0 1-4 0 2 2 0 0 1-4 0 2 2 0 0 1-4 0 2 2 0 0 1-4 0V7"/>'
    ),
    'camera': (
        '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>'
        '<circle cx="12" cy="13" r="4"/>'
    ),
    'layers': (
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
        '<polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>'
    ),
    'thermometer': '<path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>',
    'sparkles': (
        '<path d="m12 3-1.9 5.8L4 10.7l6.1 1.9L12 18.4l1.9-5.8L20 10.7l-6.1-1.9z"/>'
        '<path d="M5 3v4"/><path d="M3 5h4"/><path d="M19 17v4"/><path d="M17 19h4"/>'
    ),

    # --- money ---------------------------------------------------------------
    'dollar-sign': (
        '<line x1="12" y1="1" x2="12" y2="23"/>'
        '<path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>'
    ),
    'credit-card': (
        '<rect x="1" y="4" width="22" height="16" rx="2" ry="2"/>'
        '<line x1="1" y1="10" x2="23" y2="10"/>'
    ),
    'percent': (
        '<line x1="19" y1="5" x2="5" y2="19"/>'
        '<circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>'
    ),
    'receipt': (
        '<path d="M5 22V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v18l-3-2-3 2-3-2-3 2z"/>'
        '<path d="M9 8h6"/><path d="M9 12h6"/>'
    ),
    'file-text': (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>'
    ),
    'gift': (
        '<polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/>'
        '<line x1="12" y1="22" x2="12" y2="7"/>'
        '<path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/>'
        '<path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/>'
    ),
    'star': (
        '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02'
        ' 7 14.14 2 9.27 8.91 8.26 12 2"/>'
    ),

    # --- contact and time ----------------------------------------------------
    'phone': (
        '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6'
        ' 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81'
        ' 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0'
        ' 2.81.7A2 2 0 0 1 22 16.92z"/>'
    ),
    'mail': (
        '<rect x="2" y="4" width="20" height="16" rx="2"/><polyline points="22 6 12 13 2 6"/>'
    ),
    'clock': '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    'calendar': (
        '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>'
        '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>'
        '<line x1="3" y1="10" x2="21" y2="10"/>'
    ),
    'history': (
        '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/>'
        '<polyline points="12 7 12 12 15 14"/>'
    ),
    'bell': (
        '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>'
        '<path d="M13.73 21a2 2 0 0 1-3.46 0"/>'
    ),

    # --- chrome --------------------------------------------------------------
    'home': (
        '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<polyline points="9 22 9 12 15 12 15 22"/>'
    ),
    'settings': (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65'
        ' 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65'
        ' 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65'
        ' 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82'
        'l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3'
        'a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1'
        ' 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4'
        'h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
    ),
    'sliders': (
        '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>'
        '<line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>'
        '<line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/>'
        '<line x1="17" y1="16" x2="23" y2="16"/>'
    ),
    'list': (
        '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>'
        '<line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>'
        '<line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>'
    ),
    'menu': (
        '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/>'
        '<line x1="3" y1="18" x2="21" y2="18"/>'
    ),
    # The "Dashboard" nav item in both shells. An open arc with a needle, not a
    # closed dial: a dial face at 16px fills in and reads as a solid blob.
    'gauge': (
        '<path d="M5.4 19.4A9.2 9.2 0 1 1 18.6 19.4"/>'
        '<line x1="12" y1="13" x2="16.2" y2="8.8"/>'
    ),
    'file': (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
    ),
    'book-open': (
        '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>'
        '<path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>'
    ),
    'note': (
        '<path d="M15.5 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9.5L21 14.5V5a2 2 0 0 0-2-2z"/>'
        '<path d="M15 21v-5a1 1 0 0 1 1-1h5"/>'
    ),
    'lock': (
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    'shield': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    'lightbulb': (
        '<path d="M9 18h6"/><path d="M10 22h4"/>'
        '<path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8'
        'c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/>'
    ),
}

# Font Awesome names people will type out of habit, and the plain-noun synonyms
# worth accepting. Aliasing costs nothing; drawing the same icon twice under two
# names is how a set starts to drift.
ALIASES = {
    'times': 'x',
    'times-circle': 'x-circle',
    'close': 'x',
    'info-circle': 'info',
    'exclamation-circle': 'alert-circle',
    'exclamation-triangle': 'alert-triangle',
    'triangle-exclamation': 'alert-triangle',
    'question-circle': 'help-circle',
    'circle-question': 'help-circle',
    'warning': 'alert-triangle',
    'spinner': 'loader',
    'envelope': 'mail',
    'paper-plane': 'send',
    'trash-alt': 'trash',
    'edit': 'pen',
    'pencil': 'pen',
    'tools': 'wrench',
    'tool': 'wrench',
    'cog': 'settings',
    'gear': 'settings',
    'user-cog': 'settings',
    'sliders-h': 'sliders',
    'map-marker-alt': 'map-pin',
    'map-marker': 'map-pin',
    'shield-alt': 'shield',
    'layer-group': 'layers',
    # There is no legible `$` inside a document at 24x24 with a 2px stroke: the
    # counters of the S close up and it renders as a smudge at the inline size
    # every list row uses it at. `receipt` is already the money document, and it
    # reads at 16px. Drawn once, reached by every name people will try.
    'file-invoice-dollar': 'receipt',
    'file-invoice': 'receipt',
    'invoice': 'receipt',
    'undo': 'rotate-ccw',
    'redo': 'rotate-cw',
    'sync-alt': 'rotate-cw',
    'sync': 'rotate-cw',
    'sticky-note': 'note',
    'sign-in-alt': 'log-in',
    'sign-out-alt': 'log-out',
    'external-link-alt': 'external-link',
    'thermometer-half': 'thermometer',
    'magic': 'sparkles',
    'usd': 'dollar-sign',
    'money': 'dollar-sign',
    'phone-alt': 'phone',
    'bars': 'menu',
    'tachometer-alt': 'gauge',
    'tachometer': 'gauge',
    'dashboard': 'gauge',
    # `fa-hand-holding-usd` ("Receive Payment") has no line-weight form. A palm
    # is a wide shallow curve; put a disc above one and you have drawn `user`,
    # which is what all three attempts turned into at 16px — head over
    # shoulders, indistinguishable in a nav row. Adding fingers to break the
    # symmetry makes it a squiggle instead. Same shape of answer as
    # `file-invoice`: the mark that reads wins, and the FAB's own "Receive
    # Payment" label is what names the action.
    'hand-holding-usd': 'dollar-sign',
    'hand-holding-dollar': 'dollar-sign',
}


def resolve(name):
    """Return the inner markup for `name`, or None if the set has no such icon.

    Accepts an alias, and tolerates a leading `fa-` so that pasting a Font
    Awesome class name from an old surface does the obvious thing.
    """
    if not name:
        return None
    key = str(name).strip().lower()
    if key.startswith('fa-'):
        key = key[3:]
    key = ALIASES.get(key, key)
    return ICONS.get(key)
