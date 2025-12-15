"""
Management command to mark test accounts as email verified.

This is a development/testing helper to bypass the email verification flow
for test accounts. In production, users should verify via the email link.

Usage:
    python manage.py verify_test_emails email1@example.com email2@example.com

    # Verify all customer emails in the database (USE WITH CAUTION)
    python manage.py verify_test_emails --all
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from apps.customer_portal.models import CustomerUser
from core.models import CustomerNotificationPreference


class Command(BaseCommand):
    help = 'Mark test accounts as email verified for development testing'

    def add_arguments(self, parser):
        parser.add_argument(
            'emails',
            nargs='*',
            type=str,
            help='Email addresses to verify'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Verify all customer accounts (USE WITH CAUTION - development only)'
        )

    def handle(self, *args, **options):
        verified_count = 0
        failed_count = 0

        if options['all']:
            # Verify all customer accounts
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  WARNING: Verifying ALL customer accounts. '
                    'This should only be used in development!'
                )
            )

            prefs = CustomerNotificationPreference.objects.filter(email_verified=False)
            total = prefs.count()

            if total == 0:
                self.stdout.write(
                    self.style.SUCCESS('✅ All customer accounts already verified')
                )
                return

            # Ask for confirmation
            confirm = input(f'Verify {total} customer accounts? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR('❌ Aborted'))
                return

            prefs.update(email_verified=True)
            self.stdout.write(
                self.style.SUCCESS(f'✅ Verified {total} customer accounts')
            )
            return

        # Verify specific email addresses
        if not options['emails']:
            raise CommandError(
                'Please provide email addresses or use --all flag. '
                'Example: python manage.py verify_test_emails test@example.com'
            )

        for email in options['emails']:
            try:
                # Find the user by email
                user = User.objects.get(email=email)

                # Get the CustomerUser
                customer_user = CustomerUser.objects.get(user=user)

                # Get or create notification preferences
                prefs, created = CustomerNotificationPreference.objects.get_or_create(
                    customer=customer_user.customer
                )

                # Update email_verified flag
                if prefs.email_verified:
                    self.stdout.write(
                        self.style.WARNING(f'⚠️  Already verified: {email}')
                    )
                else:
                    prefs.email_verified = True
                    prefs.save()
                    self.stdout.write(
                        self.style.SUCCESS(f'✅ Verified: {email}')
                    )
                    verified_count += 1

            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ User not found: {email}')
                )
                failed_count += 1
            except CustomerUser.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f'❌ Customer account not found for user: {email}'
                    )
                )
                failed_count += 1
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'❌ Error for {email}: {str(e)}')
                )
                failed_count += 1

        # Print summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Verified: {verified_count}'))
        if failed_count > 0:
            self.stdout.write(self.style.ERROR(f'Failed: {failed_count}'))
