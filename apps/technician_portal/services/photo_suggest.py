"""
Guess where the break is in a damage photo, locally.

P3 of docs/strategy/PHOTO_ML_SESSIONS.md. The point is not to be right every
time — it is to make marking a photo a confirmation instead of a hunt, so
more photos end up labeled. The technician always overrides, and a
suggestion nobody confirmed is recorded as such.

**No photo ever leaves this server.** That was Drake's call when the arc was
planned: the obvious implementation was a hosted vision model, and it was
rejected because these are real customers' photos. So this is pure Pillow —
no numpy, no OpenCV, no network, no API key, no per-photo cost, and nothing
to train before it works.

How it works. A chip or crack is a small patch of sharp structure sitting in
glass that is otherwise smooth, and the technician pointed the camera at it.
So:

  detail   = |image - blur(image)|      high-pass; edges and texture
  energy   = blur(detail, small)        gather detail into blobs
  context  = blur(detail, large)        how busy this neighbourhood is anyway
  salience = max(0, energy - context)   structure that stands out from its
                                        surroundings, so uniformly busy
                                        regions (foliage through the glass,
                                        a gravel driveway) score near zero
  weighted = salience * centre_prior    the camera was aimed at the break

The mark is the centroid of the brightest patch of `weighted`, and the score
is how *compact* that patch is. Compactness, not height, is the useful
signal: a chip is a few adjacent pixels, a crack is a short line, and busy
background is bright everywhere at once. When the patch is too spread out we
return nothing at all, because an empty modal is better than a marker
pointing confidently at a tree.

Everything fails open: any error means no suggestion, which is exactly the
pre-P3 behaviour.

Replacing this with a trained detector later means swapping `suggest_point`
and bumping SUGGESTER_VERSION — the stored `suggested_by` on every row says
which engine produced it, so the two can be compared on the same photos.
"""
import logging

from django.conf import settings

from PIL import Image, ImageChops, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

# Bump when the algorithm changes — it is stored per row so a later engine
# can be scored against this one on the same photos.
SUGGESTER_VERSION = 'saliency-v1'

# Analysis runs on a thumbnail: a break big enough to matter survives the
# downscale, and it keeps the pure-Python argmax scan to ~30k pixels.
ANALYSIS_LONG_EDGE = 192

DETAIL_RADIUS = 1.5     # high-pass cut-off
BLOB_RADIUS = 3.0       # gather detail into break-sized blobs
CONTEXT_RADIUS = 18.0   # "how busy is this whole area anyway"

# Ignore the outer frame: lens vignetting, the dash, the edge of the glass
# and the frame of the photo itself all light up a high-pass filter, and a
# break is almost never in the last few percent of the shot.
BORDER_MARGIN = 0.08

# The technician aimed at the break. Corners are damped to
# (1 - CENTRE_PRIOR) of their salience; the centre is untouched.
CENTRE_PRIOR = 0.45

# What counts as part of the winning patch, as a fraction of the peak.
HOT_FRACTION = 0.6

# How far that patch may be spread across the frame (RMS distance from its
# own centroid, over the image diagonal) before we decline to guess. A chip
# measures ~0.01 and a crack ~0.07 on test images; scattered background
# texture measures ~0.14.
#
# This threshold is a starting guess, not a tuned constant — deliberately.
# Every row records the suggestion next to whatever the technician finally
# marked (RepairPhotoCrop.suggested_x_pct), so the first few hundred real
# corrections will say where it actually belongs. Do not hand-tune it
# against synthetic images; read the corrections.
MAX_SPREAD = 0.12


class Suggestion:
    """Where the suggester thinks the break is, in tap coordinates."""

    __slots__ = ('x_pct', 'y_pct', 'score', 'engine')

    def __init__(self, x_pct, y_pct, score, engine=SUGGESTER_VERSION):
        self.x_pct = x_pct
        self.y_pct = y_pct
        self.score = score
        self.engine = engine

    def __repr__(self):
        return (f'<Suggestion {self.engine} ({self.x_pct:.1f}%, '
                f'{self.y_pct:.1f}%) score={self.score:.2f}>')


def is_enabled():
    """Master switch. Local and free, so it defaults on; still killable."""
    return bool(getattr(settings, 'PHOTO_SUGGEST_ENABLED', True))


def suggest_point(fp):
    """Analyse one open image file. Returns a Suggestion or None.

    Coordinates come back as percent of the EXIF-upright natural size — the
    same convention a technician's tap uses, which is what lets a suggestion
    be dropped straight into the modal's marker and stored in the same
    columns. See photo_crops.save_crop_for.
    """
    try:
        img = Image.open(fp)
        # The tap convention is upright space; measure in upright space.
        img = ImageOps.exif_transpose(img).convert('L')
        img.thumbnail((ANALYSIS_LONG_EDGE, ANALYSIS_LONG_EDGE), Image.BILINEAR)
    except Exception:
        logger.exception("Could not open a photo to suggest a crop point")
        return None

    width, height = img.size
    if width < 24 or height < 24:
        return None

    try:
        detail = ImageChops.difference(
            img, img.filter(ImageFilter.GaussianBlur(DETAIL_RADIUS)),
        )
        energy = list(
            detail.filter(ImageFilter.GaussianBlur(BLOB_RADIUS)).getdata()
        )
        context = list(
            detail.filter(ImageFilter.GaussianBlur(CONTEXT_RADIUS)).getdata()
        )
    except Exception:
        logger.exception("Salience pass failed while suggesting a crop point")
        return None

    return _locate(energy, context, width, height)


def _locate(energy, context, width, height):
    """Find the compact bright patch, and say how sure we are.

    Two passes over the salience map. The first finds the peak; the second
    collects everything within HOT_FRACTION of it and measures how spread out
    that hot region is, as a fraction of the image diagonal.

    Spread is the confidence signal, and it is the one that matters. A chip
    lights up a handful of adjacent pixels (spread ~0.01); a crack lights up
    a short line (~0.07); foliage or gravel behind the glass lights up
    scattered patches all over the frame (~0.14) — and *that* case is the one
    a plain "how tall is the peak" score cannot catch, because a texture
    boundary has a perfectly tall peak. It is just not alone.

    The mark is the hot region's weighted centroid, not the peak pixel. On a
    crack the peak lands wherever the contrast happens to be highest, often
    near one end; the centroid lands on the crack's middle, which is what a
    technician would have tapped.
    """
    x_lo, x_hi = int(width * BORDER_MARGIN), int(width * (1 - BORDER_MARGIN))
    y_lo, y_hi = int(height * BORDER_MARGIN), int(height * (1 - BORDER_MARGIN))
    if x_hi <= x_lo or y_hi <= y_lo:
        x_lo, x_hi, y_lo, y_hi = 0, width, 0, height

    half_w = width / 2.0
    half_h = height / 2.0
    # Normalising by the corner distance puts the prior at 1.0 in the centre
    # and (1 - CENTRE_PRIOR) in the corners whatever the aspect ratio.
    corner = (half_w ** 2 + half_h ** 2) ** 0.5 or 1.0
    diagonal = (width ** 2 + height ** 2) ** 0.5 or 1.0

    salience = []
    best = 0.0
    for y in range(y_lo, y_hi):
        row = y * width
        dy = y + 0.5 - half_h
        for x in range(x_lo, x_hi):
            raw = energy[row + x] - context[row + x]
            value = 0.0
            if raw > 0:
                dx = x + 0.5 - half_w
                prior = 1.0 - CENTRE_PRIOR * (
                    (dx * dx + dy * dy) ** 0.5 / corner
                )
                value = raw * prior
                if value > best:
                    best = value
            salience.append((value, x, y))

    # Nothing stood out from its surroundings at all: clean glass, a blank
    # wall, an out-of-focus shot. No answer is the right answer.
    if best <= 0.0:
        return None

    cut = HOT_FRACTION * best
    weight = 0.0
    sum_x = sum_y = 0.0
    hot = []
    for value, x, y in salience:
        if value < cut:
            continue
        hot.append((value, x, y))
        weight += value
        sum_x += value * x
        sum_y += value * y
    if weight <= 0.0:
        return None

    centre_x = sum_x / weight
    centre_y = sum_y / weight
    variance = sum(
        value * ((x - centre_x) ** 2 + (y - centre_y) ** 2)
        for value, x, y in hot
    ) / weight
    spread = (variance ** 0.5) / diagonal

    if spread > MAX_SPREAD:
        # Bright structure scattered across the frame — the photo is busy,
        # not damaged. Guessing here is worse than not guessing: the
        # technician gets the plain modal and taps, exactly as before P3.
        return None

    return Suggestion(
        x_pct=min(max((centre_x + 0.5) / width * 100.0, 0.0), 100.0),
        y_pct=min(max((centre_y + 0.5) / height * 100.0, 0.0), 100.0),
        score=max(0.0, min(1.0, 1.0 - spread / MAX_SPREAD)),
    )


def suggest_for(job, source_field):
    """Suggest a break point for one photo field on a job, or None.

    ``job`` is a Repair or a Replacement — this only ever reads a photo
    field, so it never needed to care which.

    Never raises: no suggestion is always an acceptable answer, and the
    caller's fallback is the plain empty modal.
    """
    if not is_enabled():
        return None
    photo = getattr(job, source_field, None)
    if not photo:
        return None
    try:
        with photo.open('rb'):
            return suggest_point(photo)
    except Exception:
        logger.exception(
            "Crop suggestion failed for %s %s %s",
            job._meta.model_name, job.pk, source_field,
        )
        return None
