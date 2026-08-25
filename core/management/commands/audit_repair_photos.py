"""
Management command to audit and clean up orphaned repair photos in S3.

This command compares photo files in S3 against the database to identify:
1. Orphaned files (in S3 but not referenced in database)
2. Missing files (referenced in database but not in S3)
3. Size and cost estimates for orphaned files

Usage:
    python manage.py audit_repair_photos              # Audit only (dry run)
    python manage.py audit_repair_photos --delete     # Delete orphaned files
"""

from django.core.management.base import BaseCommand
from django.conf import settings
from apps.technician_portal.models import Repair, RepairPhotoCrop, Replacement
import boto3
import os


class Command(BaseCommand):
    help = 'Audit and optionally clean up orphaned repair photos in S3 storage'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Actually delete orphaned files (default is dry run)',
        )

    def handle(self, *args, **options):
        delete_mode = options['delete']

        if not settings.USE_S3:
            self.stdout.write(self.style.WARNING(
                'S3 storage is not enabled. This command only works with S3.'
            ))
            return

        self.stdout.write('Starting repair photo audit...\n')

        # Get S3 client
        try:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_S3_REGION_NAME
            )
            bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to connect to S3: {e}'))
            return

        # Get all photo files from S3
        self.stdout.write('Fetching files from S3...')
        s3_files = {}
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name, Prefix='media/repair_photos/'):
                if 'Contents' not in page:
                    continue
                for obj in page['Contents']:
                    key = obj['Key']
                    # Extract the filename from the full path (e.g., media/repair_photos/before/IMG_0433.jpeg -> IMG_0433.jpeg)
                    filename = os.path.basename(key)
                    s3_files[key] = {
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'],
                        'filename': filename
                    }
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to list S3 objects: {e}'))
            return

        self.stdout.write(f'Found {len(s3_files)} files in S3\n')

        # Get all photo references from database
        self.stdout.write('Fetching photo references from database...')
        db_photos = set()

        # all_objects: soft-deleted jobs are restorable for 30 days, so their
        # photos are NOT orphans. Replacements share the same photo fields and
        # upload paths, so they must be enumerated too, or --delete eats them.
        for service in list(Repair.all_objects.all()) + list(Replacement.all_objects.all()):
            if service.customer_submitted_photo:
                # Extract just the S3 key from the field
                db_photos.add(service.customer_submitted_photo.name)
            if service.damage_photo_before:
                db_photos.add(service.damage_photo_before.name)
            if service.damage_photo_after:
                db_photos.add(service.damage_photo_after.name)

        # Tap-to-crop derivatives live under repair_photos/crops/.
        for crop in RepairPhotoCrop.objects.all():
            if crop.cropped_image:
                db_photos.add(crop.cropped_image.name)

        self.stdout.write(f'Found {len(db_photos)} photo references in database\n')

        # Find orphaned files (in S3 but not in database)
        orphaned_files = []
        for s3_key, file_info in s3_files.items():
            # Check if this S3 key is referenced in the database
            # Need to match both with and without 'media/' prefix
            s3_key_without_media = s3_key.replace('media/', '', 1) if s3_key.startswith('media/') else s3_key

            if s3_key not in db_photos and s3_key_without_media not in db_photos:
                orphaned_files.append((s3_key, file_info))

        # Find missing files (in database but not in S3)
        missing_files = []
        for db_photo in db_photos:
            # Check both with and without media/ prefix
            db_photo_with_media = f"media/{db_photo}" if not db_photo.startswith('media/') else db_photo

            if db_photo not in s3_files and db_photo_with_media not in s3_files:
                missing_files.append(db_photo)

        # Display results
        self.stdout.write('\n' + '='*80)
        self.stdout.write('AUDIT RESULTS')
        self.stdout.write('='*80 + '\n')

        # Orphaned files
        if orphaned_files:
            total_size = sum(info['size'] for _, info in orphaned_files)
            total_size_mb = total_size / (1024 * 1024)
            # S3 storage costs approximately $0.023 per GB per month
            monthly_cost = (total_size / (1024 * 1024 * 1024)) * 0.023

            self.stdout.write(self.style.WARNING(
                f'\nFound {len(orphaned_files)} ORPHANED files (in S3 but not in database):'
            ))
            self.stdout.write(f'Total size: {total_size_mb:.2f} MB')
            self.stdout.write(f'Estimated monthly cost: ${monthly_cost:.4f}\n')

            for s3_key, info in orphaned_files:
                size_mb = info['size'] / (1024 * 1024)
                self.stdout.write(f"  - {s3_key} ({size_mb:.2f} MB, modified: {info['last_modified']})")
        else:
            self.stdout.write(self.style.SUCCESS('\nNo orphaned files found!'))

        # Missing files
        if missing_files:
            self.stdout.write(self.style.ERROR(
                f'\n\nFound {len(missing_files)} MISSING files (in database but not in S3):'
            ))
            for db_photo in missing_files:
                self.stdout.write(f"  - {db_photo}")
        else:
            self.stdout.write(self.style.SUCCESS('\nNo missing files!'))

        # Delete orphaned files if requested
        if orphaned_files and delete_mode:
            self.stdout.write('\n' + '='*80)
            self.stdout.write(self.style.WARNING('DELETING ORPHANED FILES'))
            self.stdout.write('='*80 + '\n')

            deleted_count = 0
            failed_count = 0

            for s3_key, info in orphaned_files:
                try:
                    s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
                    self.stdout.write(self.style.SUCCESS(f'Deleted: {s3_key}'))
                    deleted_count += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Failed to delete {s3_key}: {e}'))
                    failed_count += 1

            self.stdout.write(f'\n\nDeleted {deleted_count} files')
            if failed_count > 0:
                self.stdout.write(self.style.WARNING(f'Failed to delete {failed_count} files'))
        elif orphaned_files and not delete_mode:
            self.stdout.write('\n' + '='*80)
            self.stdout.write(self.style.WARNING(
                'DRY RUN MODE: No files were deleted. Use --delete to actually remove orphaned files.'
            ))
            self.stdout.write('='*80)

        self.stdout.write('\n\nAudit complete!')
