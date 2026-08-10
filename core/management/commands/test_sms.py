"""
Management command to test AWS End User Messaging SMS configuration.

Usage:
    python manage.py test_sms +12025551234
    python manage.py test_sms 501-282-7129   # any common US format works

Sends a single test text through SMSService (the same path invoice and
review texts use), so it exercises the origination identity, IAM
permissions, and delivery logging end to end.
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from core.services.sms_service import SMSService


class Command(BaseCommand):
    help = 'Send a test SMS via AWS End User Messaging using SMSService'

    def add_arguments(self, parser):
        parser.add_argument(
            'phone',
            type=str,
            help='Recipient phone number (E.164 or common US format)'
        )
        parser.add_argument(
            '--message',
            type=str,
            default='RS Systems test message. Reply STOP to opt out.',
            help='Message body to send'
        )

    def handle(self, *args, **options):
        phone = SMSService.normalize_phone(options['phone'])
        if not phone:
            raise CommandError(
                f"Unusable phone number: {options['phone']!r}. "
                "Use E.164 (+12025551234) or a 10-digit US number."
            )

        self.stdout.write('=' * 70)
        self.stdout.write(self.style.WARNING('AWS End User Messaging SMS Test'))
        self.stdout.write('=' * 70)
        self.stdout.write(f'Recipient:            {phone}')
        self.stdout.write(f'Region:               {settings.AWS_SMS_REGION_NAME}')
        self.stdout.write(f'Origination identity: {settings.SMS_ORIGINATION_IDENTITY or "(not set)"}')
        self.stdout.write(f'Configuration set:    {settings.SMS_CONFIGURATION_SET or "(none)"}')
        self.stdout.write(f'SMS_ENABLED:          {settings.SMS_ENABLED}')
        self.stdout.write('=' * 70)

        if not SMSService.is_enabled():
            raise CommandError(
                'SMS is disabled. Set SMS_ENABLED=true and SMS_ORIGINATION_IDENTITY '
                'to the registered toll-free number (e.g. +18559394817).'
            )

        success, log = SMSService.send_notification_sms(
            notification_id=None,
            recipient_phone=phone,
            message=options['message'],
        )

        if success:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ SMS accepted by AWS (message id: {log.provider_message_id})\n'
                'Note: carrier delivery is asynchronous — check the handset.'
            ))
        else:
            detail = log.error_message if log else 'no delivery log created (see logs above)'
            raise CommandError(f'SMS send failed: {detail}')
