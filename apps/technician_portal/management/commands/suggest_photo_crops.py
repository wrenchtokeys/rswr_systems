"""
Mark the breaks in photos nobody ever tapped.

Tap-to-crop only labels a photo if someone taps it, and most of the backlog
predates the feature. This sweeps unmarked repair *and replacement* photos, runs the local
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
    python manage.py suggest_photo_crops --kind replacement
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.technician_portal.models import Repair, Replacement
from apps.technician_portal.services.photo_crops import (
    SOURCE_FIELDS, apply_suggestion,
)
from apps.technician_portal.services.photo_suggest import (
    SUGGESTER_VERSION, is_enabled, suggest_for,
)


class Command(BaseCommand):
    help = ("Suggest and save crops for repair and replacement photos that "
            "nobody has marked. Never modifies the original photos.")

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
        parser.add_argument(
            '--kind', choices=('repair', 'replacement'), default=None,
            help="Only repairs or only replacements. Default: both.",
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

        # Any job carrying at least one of the photo fields we care about.
        has_photo = Q()
        for field in fields:
            has_photo |= ~Q(**{field: ''}) & Q(**{f'{field}__isnull': False})

        models = {'repair': Repair, 'replacement': Replacement}
        if options['kind']:
            models = {options['kind']: models[options['kind']]}

        counts = {'examined': 0, 'marked': 0, 'declined': 0, 'skipped': 0}

        for kind, model in models.items():
            jobs = (model.objects.filter(has_photo)
                    .prefetch_related('photo_crops')
                    .order_by('-id'))
            if options['tenant'] is not None:
                jobs = jobs.filter(tenant_id=options['tenant'])

            # chunk_size is required alongside prefetch_related, and it also
            # keeps a shop-wide backlog off the heap.
            for job in jobs.iterator(chunk_size=200):
                for field in fields:
                    # A replacement's "after" photo is new glass — there is
                    # no damage in it to mark, and a suggestion there would
                    # be pure noise in the dataset.
                    if kind == 'replacement' and field == 'damage_photo_after':
                        continue
                    if limit is not None and counts['examined'] >= limit:
                        return self._report(counts, dry_run,
                                            stopped_at_limit=True)
                    if not getattr(job, field, None):
                        continue
                    if any(c.source_field == field
                           for c in job.photo_crops.all()):
                        counts['skipped'] += 1
                        continue

                    counts['examined'] += 1
                    if dry_run:
                        suggestion = suggest_for(job, field)
                        if suggestion is None:
                            counts['declined'] += 1
                            continue
                        counts['marked'] += 1
                        self.stdout.write(
                            f"  would mark {kind} #{job.pk} {field} at "
                            f"({suggestion.x_pct:.1f}%, {suggestion.y_pct:.1f}%) "
                            f"score {suggestion.score:.2f}"
                        )
                        continue

                    try:
                        crop = apply_suggestion(job, field)
                    except Exception as exc:  # one bad photo can't stop the sweep
                        crop = None
                        self.stderr.write(f"  {kind} #{job.pk} {field}: {exc}")
                    if crop is None:
                        counts['declined'] += 1
                        continue
                    counts['marked'] += 1
                    self.stdout.write(
                        f"  marked {kind} #{job.pk} {field} at "
                        f"({crop.center_x_pct:.1f}%, {crop.center_y_pct:.1f}%) "
                        f"score {crop.suggestion_score:.2f}"
                    )

        self._report(counts, dry_run)

    def _report(self, counts, dry_run, stopped_at_limit=False):
        if stopped_at_limit:
            self.stdout.write(self.style.WARNING(
                "Stopped at --limit; there is more backlog."
            ))
        self.stdout.write(
            f"Examined {counts['examined']} unmarked photo(s) with "
            f"{SUGGESTER_VERSION}; {counts['skipped']} already marked and "
            f"left alone."
        )
        verb = "would mark" if dry_run else "Marked"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {counts['marked']}; declined to guess on "
            f"{counts['declined']}."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING(
                "Dry run — no crops written. Originals are never modified."
            ))
        elif counts['marked']:
            self.stdout.write(
                "These are unconfirmed suggestions. A technician can confirm "
                "or correct each one from the job's detail page."
            )
