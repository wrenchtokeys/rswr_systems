"""
Retry tap-to-crop close-ups that only ever recorded the tap.

save_crop_for() fails open by design: if the original photo can't be opened
when the tech taps it (a truncated upload, an S3 write still settling, a
format Pillow choked on), the RepairPhotoCrop row is still written with the
tap coordinates and no image. That is deliberate — the tech's knowledge of
where the break is exists only at capture time, so it gets recorded even
when the crop can't be produced yet.

This command sweeps those rows and tries again. Coordinates are percentages
of the photo's natural size, so a retry lands in exactly the same place no
matter how long it waited. See docs/strategy/PHOTO_ML_SESSIONS.md.

    python manage.py retry_photo_crops --dry-run
    python manage.py retry_photo_crops --tenant 15 --limit 100
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.technician_portal.models import RepairPhotoCrop
from apps.technician_portal.services.photo_crops import retry_crop


class Command(BaseCommand):
    help = "Retry tap-to-crop close-ups whose source photo could not be read."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="List what would be retried without touching anything.",
        )
        parser.add_argument(
            '--tenant', type=int, default=None,
            help="Only this tenant's crops (id).",
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help="Stop after this many rows.",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Rows with no derived image. natural_width is the other tell — a row
        # can hold a stale file reference from a crop that later failed.
        pending = RepairPhotoCrop.objects.filter(
            Q(cropped_image='') | Q(cropped_image__isnull=True)
            | Q(natural_width__isnull=True)
        ).select_related('repair', 'created_by').order_by('id')

        if options['tenant'] is not None:
            pending = pending.filter(tenant_id=options['tenant'])
        if options['limit']:
            pending = pending[:options['limit']]

        total = len(pending)
        if not total:
            self.stdout.write(self.style.SUCCESS("No crops are waiting to be retried."))
            return

        self.stdout.write(f"{total} crop(s) waiting on a readable original.")
        if dry_run:
            for crop in pending:
                self.stdout.write(
                    f"  would retry crop {crop.pk}: repair #{crop.repair_id} "
                    f"{crop.source_field} at ({crop.center_x_pct:.1f}%, "
                    f"{crop.center_y_pct:.1f}%)"
                )
            self.stdout.write(self.style.WARNING("Dry run — nothing changed."))
            return

        fixed = 0
        still_failing = 0
        for crop in pending:
            try:
                ok = retry_crop(crop)
            except Exception as exc:  # never let one bad row stop the sweep
                ok = False
                self.stderr.write(f"  crop {crop.pk}: {exc}")
            if ok:
                fixed += 1
                self.stdout.write(
                    f"  cropped repair #{crop.repair_id} {crop.source_field}"
                )
            else:
                still_failing += 1

        self.stdout.write(self.style.SUCCESS(f"Produced {fixed} close-up(s)."))
        if still_failing:
            self.stdout.write(self.style.WARNING(
                f"{still_failing} still unreadable — the tap stays on record "
                f"for the next run."
            ))
