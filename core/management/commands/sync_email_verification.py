from django.core.management.base import BaseCommand
from apps.technician_portal.models import Technician
from core.models import TechnicianNotificationPreference, Customer, CustomerNotificationPreference


class Command(BaseCommand):
    help = 'Sync email verification status from Technician/Customer to NotificationPreferences'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually updating',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # ===== TECHNICIANS =====
        self.stdout.write(self.style.WARNING('\n=== TECHNICIAN EMAIL VERIFICATION ==='))
        verified_technicians = Technician.objects.filter(email_verified=True)
        total_verified = verified_technicians.count()

        self.stdout.write(self.style.WARNING(
            f'Found {total_verified} technician(s) with verified emails'
        ))

        tech_updated = 0
        tech_created = 0

        for tech in verified_technicians:
            prefs, was_created = TechnicianNotificationPreference.objects.get_or_create(
                technician=tech
            )

            if was_created:
                tech_created += 1
                self.stdout.write(
                    f'  Created preferences for {tech.user.get_full_name()}'
                )

            if not prefs.email_verified:
                if dry_run:
                    self.stdout.write(
                        f'  [DRY RUN] Would update preferences for {tech.user.get_full_name()}'
                    )
                else:
                    prefs.email_verified = True
                    prefs.email_verified_at = tech.email_verified_at
                    prefs.save()
                    self.stdout.write(
                        f'  ✓ Updated preferences for {tech.user.get_full_name()}'
                    )
                tech_updated += 1

        # ===== CUSTOMERS =====
        self.stdout.write(self.style.WARNING('\n=== CUSTOMER EMAIL VERIFICATION ==='))
        verified_customers = Customer.objects.filter(email_verified=True)
        total_customer_verified = verified_customers.count()

        self.stdout.write(self.style.WARNING(
            f'Found {total_customer_verified} customer(s) with verified emails'
        ))

        customer_updated = 0
        customer_created = 0

        for customer in verified_customers:
            prefs, was_created = CustomerNotificationPreference.objects.get_or_create(
                customer=customer
            )

            if was_created:
                customer_created += 1
                self.stdout.write(
                    f'  Created preferences for {customer.name}'
                )

            if not prefs.email_verified:
                if dry_run:
                    self.stdout.write(
                        f'  [DRY RUN] Would update preferences for {customer.name}'
                    )
                else:
                    prefs.email_verified = True
                    prefs.email_verified_at = customer.email_verified_at
                    prefs.save()
                    self.stdout.write(
                        f'  ✓ Updated preferences for {customer.name}'
                    )
                customer_updated += 1

        # ===== SUMMARY =====
        total_updated = tech_updated + customer_updated
        total_created = tech_created + customer_created

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\n[DRY RUN] Would update {total_updated} email verifications ({tech_updated} technicians, {customer_updated} customers)'
            ))
            self.stdout.write(self.style.WARNING(
                'Run without --dry-run to actually update the database'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Synced {total_updated} email verifications ({tech_updated} technicians, {customer_updated} customers)'
            ))
            if total_created > 0:
                self.stdout.write(self.style.SUCCESS(
                    f'✓ Created {total_created} new notification preference records ({tech_created} technicians, {customer_created} customers)'
                ))

        # Remaining unverified
        tech_remaining = Technician.objects.filter(email_verified=False).count()
        customer_remaining = Customer.objects.filter(email_verified=False).count()
        self.stdout.write(self.style.WARNING(
            f'\n{tech_remaining} technician(s) and {customer_remaining} customer(s) still have unverified emails'
        ))
