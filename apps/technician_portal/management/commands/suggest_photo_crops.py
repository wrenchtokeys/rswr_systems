"""
Mark the breaks in photos nobody ever tapped.

Tap-to-crop only labels a photo if someone taps it, and most of the backlog
predates the feature. This sweeps unmarked repair photos, runs the local
suggester over each one, and saves a crop where it is confident enough.

**Originals are never touched.** A crop is a separate derived JPEG stored
next to the untouched photo, exactly as a technician's tap produces — this
command reads the originals and writes new files, nothing else. That was
Drake's condition for running it at all.

Suggested crops are stored with ``confirmed_by_human=False``. They are a
weaker label than a tap and P4's export must be able to weight them
differently; the repair detail page shows them as "Check the mark" so a
technician can confirm or correct one in a second. Existing crops are never
overwritten, so a sweep cannot trample anybody's work — and re-running it is
therefore safe.

No photo leaves this server: see services/photo_suggest.py.

    python manage.py suggest_photo_crops --dry-run
    python manage.py suggest_photo_crops --tenant 15 --limit 200
    python manage.py suggest_photo_crops --field damage_photo_before
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.technician_portal.models import Repair
from apps.technician_portal.services.photo_crops import (
    SOURCE_FIELDS, apply_suggestion,
)
from apps.technician_portal.services.photo_suggest import (
    SUGGESTER_VERSION, is_enabled, suggest_for,
)


class Command(BaseCommand):
    help = ("Suggest and save crops for repair photos that nobody has "
            "marked. Never modifies the original photos.")

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Report what would be marked without writing anything.",
        )
        parser.add_argument(
            '--tenant', type=int, default=None,
            help="Only this tenant's repairs (id).",
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help="Stop after this many photos examined.",
        )
        parser.add_argument(
            '--field', choices=SOURCE_FIELDS, default=None,
            help="Only this photo field. Default: all three.",
        )

    def handle(self, *args, **options):
        if not is_enabled():
            self.stdout.write(self.style.WARNING(
                "PHOTO_SUGGEST_ENABLED is off — nothing to do."
            ))
            return

        dry_run = options['dry_run']
        fields = [options['field']] if options['field'] else list(SOURCE_FIELDS)
        limit = options['limit']

        # Any repair carrying at least one of the photo fields we care about.
        has_photo = Q()
        for field in fields:
            has_photo |= ~Q(**{field: ''}) & Q(**{f'{field}__isnull': False})
        repairs = (Repair.objects.filter(has_photo)
                   .prefetch_related('photo_crops')
                   .order_by('-id'))
        if options['tenant'] is not None:
            repairs = repairs.filter(tenant_id=options['tenant'])

        examined = marked = declined = skipped = 0

        # chunk_size is required alongside prefetch_related, and it also keeps
        # a shop-wide backlog off the heap.
        for repair in repairs.iterator(chunk_size=200):
            for field in fields:
                if limit is not None and examined >= limit:
                    return self._report(
                        examined, marked, declined, skipped, dry_run,
                        stopped_at_limit=True,
                    )
                if not getattr(repair, field, None):
                    continue
                if any(c.source_field == field for c in repair.photo_crops.all()):
                    skipped += 1
                    continue

                examined += 1
                if dry_run:
                    suggestion = suggest_for(repair, field)
                    if suggestion is None:
                        declined += 1
                        continue
                    marked += 1
                    self.stdout.write(
                        f"  would mark repair #{repair.pk} {field} at "
                        f"({suggestion.x_pct:.1f}%, {suggestion.y_pct:.1f}%) "
                        f"score {suggestion.score:.2f}"
                    )
                    continue

                try:
                    crop = apply_suggestion(repair, field)
                except Exception as exc:  # one bad photo must not stop the sweep
                    crop = None
                    self.stderr.write(f"  repair #{repair.pk} {field}: {exc}")
                if crop is None:
                    declined += 1
                    continue
                marked += 1
                self.stdout.write(
                    f"  marked repair #{repair.pk} {field} at "
                    f"({crop.center_x_pct:.1f}%, {crop.center_y_pct:.1f}%) "
                    f"score {crop.suggestion_score:.2f}"
                )

        self._report(examined, marked, declined, skipped, dry_run)

    def _report(self, examined, marked, declined, skipped, dry_run,
                stopped_at_limit=False):
        if stopped_at_limit:
            self.stdout.write(self.style.WARNING(
                "Stopped at --limit; there is more backlog."
            ))
        self.stdout.write(
            f"Examined {examined} unmarked photo(s) with {SUGGESTER_VERSION}; "
            f"{skipped} already marked and left alone."
        )
        verb = "would mark" if dry_run else "Marked"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {marked}; declined to guess on {declined}."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Dry run — no crops written. Originals are never modified."
            ))
        elif marked:
            self.stdout.write(
                "These are unconfirmed suggestions. A technician can confirm "
                "or correct each one from the repair's detail page."
            )
