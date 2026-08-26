"""
Export the tap-to-crop corpus as an images + JSONL bundle.

    python manage.py export_photo_dataset --out ~/photoml/run1
    python manage.py export_photo_dataset --out /tmp/x --tenant 15 --from-originals
    python manage.py export_photo_dataset --stats-only

This is P4's export step (docs/strategy/PHOTO_ML_SESSIONS.md). Training
happens outside this codebase; the app's job is to hand over a bundle and
an honest count of what is in it.

Two things it is deliberately built to tell you, out loud, every run:

  * **The class balance.** Techs photograph what they already know is
    repairable, so the negative class is the scarce one and a corpus that
    is 95% positive is not a training set. The summary says so rather than
    leaving it to be discovered after a model is trained.
  * **How wrong the suggester was.** Every row carries the P3 guess beside
    the mark a human settled on. The median correction distance is the
    first measurement of the suggester that isn't synthetic — see P3's
    Notes on MAX_SPREAD.

**Originals are never modified.** Crops are copied (or re-derived) into the
output directory; nothing is written back to the database or to media
storage. ``--from-originals`` re-derives each crop from the untouched
original using only the stored box, which is the standing proof that the
metadata alone can regenerate the dataset.

The bundle is anonymised — ids only, no customer names or unit numbers.
"""
import json
import os
from io import BytesIO

from django.core.management.base import BaseCommand, CommandError

from apps.technician_portal.models import RepairPhotoCrop
from apps.technician_portal.services.photo_crops import CROP_JPEG_QUALITY
from apps.technician_portal.services.photo_dataset import (
    TRAINABLE_LABELS, record_for, suggestion_error_pct,
)


class Command(BaseCommand):
    help = ("Export tap-to-crop close-ups and their labels as an "
            "images + JSONL training bundle. Reads only; never modifies "
            "an original photo.")

    def add_arguments(self, parser):
        parser.add_argument(
            '--out', default=None,
            help="Directory to write into (created if missing). Required "
                 "unless --stats-only.",
        )
        parser.add_argument(
            '--tenant', type=int, default=None,
            help="Only this tenant's crops (id).",
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help="Stop after this many rows.",
        )
        parser.add_argument(
            '--include-unconfirmed', action='store_true',
            help="Include machine suggestions nobody has confirmed. Off by "
                 "default: training on the suggester's own unreviewed "
                 "output only teaches the next model to imitate it.",
        )
        parser.add_argument(
            '--trainable-only', action='store_true',
            help="Drop rows whose outcome isn't decided (and 'after' "
                 "photos), leaving only repairable/not_repairable.",
        )
        parser.add_argument(
            '--from-originals', action='store_true',
            help="Re-derive each crop from the untouched original using the "
                 "stored box instead of copying the saved close-up. Proves "
                 "the bundle is reproducible from metadata alone.",
        )
        parser.add_argument(
            '--stats-only', action='store_true',
            help="Print the summary and write nothing.",
        )

    def handle(self, *args, **options):
        out = options['out']
        stats_only = options['stats_only']
        if not stats_only and not out:
            raise CommandError("--out is required (or pass --stats-only).")

        crops = (RepairPhotoCrop.objects
                 .select_related('repair', 'replacement')
                 .order_by('id'))
        if options['tenant'] is not None:
            crops = crops.filter(tenant_id=options['tenant'])
        if not options['include_unconfirmed']:
            crops = crops.filter(confirmed_by_human=True)
        if options['limit']:
            crops = crops[:options['limit']]

        if not stats_only:
            os.makedirs(os.path.join(out, 'images'), exist_ok=True)

        labels = {}
        sources = {}
        kinds = {}
        errors = []
        written = 0
        no_image = 0
        records = []

        for crop in crops:
            record = record_for(crop, f'images/crop{crop.pk}.jpg')
            labels[record['label']] = labels.get(record['label'], 0) + 1
            sources[record['label_source']] = sources.get(record['label_source'], 0) + 1
            kinds[record['job_kind']] = kinds.get(record['job_kind'], 0) + 1
            error = suggestion_error_pct(crop)
            if error is not None:
                errors.append(error)

            if options['trainable_only'] and record['label'] not in TRAINABLE_LABELS:
                continue

            if stats_only:
                records.append(record)
                continue

            data = self._image_bytes(crop, options['from_originals'])
            if data is None:
                # A row with no derived image yet (retry_photo_crops hasn't
                # got to it). The label is still real, so it is reported —
                # but a bundle entry pointing at a missing file is not.
                no_image += 1
                continue
            with open(os.path.join(out, record['image']), 'wb') as fh:
                fh.write(data)
            records.append(record)
            written += 1

        if not stats_only:
            path = os.path.join(out, 'dataset.jsonl')
            with open(path, 'w', encoding='utf-8') as fh:
                for record in records:
                    fh.write(json.dumps(record) + '\n')
            self.stdout.write(self.style.SUCCESS(
                f"Wrote {written} crop(s) + {path}"
            ))
            if no_image:
                self.stdout.write(self.style.WARNING(
                    f"{no_image} row(s) had no close-up yet and were left "
                    f"out — run retry_photo_crops, then export again."
                ))

        self._summarise(labels, sources, kinds, errors)

    def _image_bytes(self, crop, from_originals):
        """The crop's JPEG bytes, or None if it hasn't been derived yet."""
        if from_originals:
            return self._rederive(crop)
        if not crop.cropped_image:
            return None
        try:
            with crop.cropped_image.open('rb') as fh:
                return fh.read()
        except Exception:
            return None

    def _rederive(self, crop):
        """Rebuild the close-up from the original using only stored metadata.

        Same Pillow settings as save_crop_for, so this comes out
        byte-identical to the stored file — which is the point: it proves
        the dataset survives losing every derived file, as long as the
        originals and the coordinates are intact.
        """
        from PIL import Image, ImageOps

        if crop.crop_left is None:
            return None
        job = crop.service
        photo = getattr(job, crop.source_field, None) if job else None
        if not photo:
            return None
        try:
            with photo.open('rb'):
                img = ImageOps.exif_transpose(Image.open(photo))
                box = (crop.crop_left, crop.crop_top,
                       crop.crop_right, crop.crop_bottom)
                buffer = BytesIO()
                img.crop(box).convert('RGB').save(
                    buffer, format='JPEG',
                    quality=CROP_JPEG_QUALITY, optimize=True,
                )
                return buffer.getvalue()
        except Exception:
            return None

    def _summarise(self, labels, sources, kinds, errors):
        total = sum(labels.values())
        self.stdout.write("")
        self.stdout.write(f"{total} crop(s) considered.")
        if not total:
            self.stdout.write(self.style.WARNING(
                "Nothing to export. Crops accumulate as technicians tap "
                "breaks; there is no shortcut."
            ))
            return

        self.stdout.write("  by job:    " + ", ".join(
            f"{k}={v}" for k, v in sorted(kinds.items())))
        self.stdout.write("  by label:  " + ", ".join(
            f"{k}={v}" for k, v in sorted(labels.items())))
        self.stdout.write("  by rule:   " + ", ".join(
            f"{k}={v}" for k, v in sorted(sources.items())))

        positives = labels.get('repairable', 0)
        negatives = labels.get('not_repairable', 0)
        trainable = positives + negatives
        self.stdout.write("")
        if not trainable:
            self.stdout.write(self.style.WARNING(
                "No trainable rows: every outcome is still undecided."
            ))
        elif not negatives or not positives:
            missing = 'not_repairable' if not negatives else 'repairable'
            self.stdout.write(self.style.ERROR(
                f"Only one class present ({trainable} rows, no {missing}). "
                f"A classifier cannot be trained on this."
            ))
        else:
            minority = min(positives, negatives) / trainable
            line = (f"Trainable: {trainable} "
                    f"({positives} repairable / {negatives} not) — "
                    f"minority class {minority:.0%}.")
            if minority < 0.20:
                self.stdout.write(self.style.WARNING(
                    line + " Too skewed to train on as-is."))
            else:
                self.stdout.write(self.style.SUCCESS(line))

        self.stdout.write("")
        if not errors:
            self.stdout.write(
                "No confirmed rows carry a machine suggestion, so there is "
                "still nothing to say about the suggester's accuracy."
            )
            return
        errors.sort()
        median = errors[len(errors) // 2]
        self.stdout.write(
            f"Suggester vs human, over {len(errors)} confirmed mark(s): "
            f"median correction {median:.1f}pp, "
            f"worst {errors[-1]:.1f}pp, best {errors[0]:.1f}pp."
        )
        self.stdout.write(
            "  (percentage points of the image; its diagonal is ~141. "
            "This is the number that should move MAX_SPREAD — not more "
            "synthetic fixtures.)"
        )
