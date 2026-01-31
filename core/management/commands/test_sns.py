"""
Management command to test AWS SNS SMS configuration.

Usage:
    python manage.py test_sns +12025551234

This command sends a test SMS using AWS SNS to verify that SMS
configuration is properly set up. Phone number must be in E.164 format.
"""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


class Command(BaseCommand):
    help = 'Test AWS SNS SMS configuration by sending a test SMS'

    def add_arguments(self, parser):
        parser.add_argument(
            'phone',
            type=str,
            help='Phone number in E.164 format (e.g., +12025551234)'
        )

    def handle(self, *args, **options):
        phone = options['phone']

        # Validate E.164 format
        if not phone.startswith('+'):
            raise CommandError(
                'Phone number must be in E.164 format starting with +\n'
                'Example: +12025551234 (for US number 202-555-1234)'
            )

        if not phone[1:].isdigit():
            raise CommandError('Phone number must contain only digits after the + sign')

        if len(phone) < 11 or len(phone) > 15:
            raise CommandError('Phone number length must be between 11-15 characters (including +)')

        self.stdout.write('=' * 70)
        self.stdout.write(self.style.WARNING('AWS SNS SMS Test'))
        self.stdout.write('=' * 70)
        self.stdout.write(f'Recipient: {phone}')
        self.stdout.write(f'AWS Region: {settings.AWS_SNS_REGION_NAME}')

        if hasattr(settings, 'SMS_ENABLED'):
            self.stdout.write(f'SMS Enabled: {settings.SMS_ENABLED}')

        self.stdout.write('=' * 70)
        self.stdout.write('')

        # Check if SMS is enabled
        if hasattr(settings, 'SMS_ENABLED') and not settings.SMS_ENABLED:
            self.stdout.write(self.style.WARNING(
                '⚠️  SMS_ENABLED is set to False in settings\n'
                'Set SMS_ENABLED=true in .env to enable SMS sending'
            ))
            raise CommandError('SMS is disabled in settings')

        try:
            # Initialize SNS client
            self.stdout.write(self.style.WARNING('Initializing AWS SNS client...'))

            sns_client = boto3.client(
                'sns',
                region_name=settings.AWS_SNS_REGION_NAME,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )

            # Send test SMS
            self.stdout.write(self.style.WARNING('Sending test SMS...'))

            response = sns_client.publish(
                PhoneNumber=phone,
                Message='''RS Systems SMS Test

This is a test SMS from the RS Systems notification system.

If you received this message, your AWS SNS configuration is working correctly!

RS Systems - Phase 2''',
                MessageAttributes={
                    'AWS.SNS.SMS.SMSType': {
                        'DataType': 'String',
                        'StringValue': 'Transactional'  # Higher priority, higher cost
                    }
                }
            )

            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.SUCCESS('✅ SMS sent successfully!'))
            self.stdout.write('')
            self.stdout.write(f'Message ID: {response.get("MessageId", "N/A")}')
            self.stdout.write(f'Region: {settings.AWS_SNS_REGION_NAME}')
            self.stdout.write('')
            self.stdout.write('Next steps:')
            self.stdout.write('1. Verify the SMS arrived at: {}'.format(phone))
            self.stdout.write('2. Check AWS SNS console for delivery status')
            self.stdout.write('3. Monitor AWS SNS spending in billing dashboard')
            self.stdout.write('4. Review spending limits in SNS console')
            self.stdout.write('')
            self.stdout.write('Cost Information:')
            self.stdout.write('- US SMS cost: ~$0.00645 per message')
            self.stdout.write('- International rates vary ($0.02 - $0.50)')
            self.stdout.write('- Check billing dashboard for exact costs')

        except NoCredentialsError:
            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.ERROR('❌ AWS credentials not found'))
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                'Missing AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY\n'
                'Set these in your .env file'
            ))
            raise CommandError('AWS credentials not configured')

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']

            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.ERROR('❌ AWS SNS Error'))
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(f'Error Code: {error_code}'))
            self.stdout.write(self.style.ERROR(f'Error Message: {error_message}'))
            self.stdout.write('')

            # Provide specific troubleshooting based on error
            self.stdout.write(self.style.WARNING('Troubleshooting Tips:'))

            if 'InvalidParameter' in error_code:
                self.stdout.write('1. Verify phone number is in E.164 format (+12025551234)')
                self.stdout.write('2. Check that the country code is valid')
            elif 'AuthorizationError' in error_code or 'AccessDenied' in error_code:
                self.stdout.write('1. Verify IAM user has sns:Publish permissions')
                self.stdout.write('2. Check AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY')
            elif 'Throttling' in error_code:
                self.stdout.write('1. You are sending too many SMS too quickly')
                self.stdout.write('2. Wait a few seconds and try again')
            elif 'OptedOut' in error_code:
                self.stdout.write('1. This phone number has opted out of SMS')
                self.stdout.write('2. Try a different number or check opt-out list')
            else:
                self.stdout.write('1. Verify AWS_SNS_REGION is correct')
                self.stdout.write('2. Check SNS spending limits haven\'t been exceeded')
                self.stdout.write('3. Verify IAM user has sns:Publish permission')
                self.stdout.write('4. Check that SMS is enabled in SNS console')

            self.stdout.write('')
            self.stdout.write('For detailed setup instructions, see:')
            self.stdout.write('docs/development/notifications/AWS_SETUP_GUIDE.md')

            raise CommandError(f'SMS test failed: {error_code}')

        except AttributeError as e:
            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.ERROR('❌ Configuration Error'))
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Missing required settings:'))
            self.stdout.write('Ensure the following are set in your settings (base.py / production.py):')
            self.stdout.write('- AWS_SNS_REGION_NAME')
            self.stdout.write('- AWS_ACCESS_KEY_ID')
            self.stdout.write('- AWS_SECRET_ACCESS_KEY')
            raise CommandError('SNS configuration incomplete')

        except Exception as e:
            self.stdout.write('')
            self.stdout.write('=' * 70)
            self.stdout.write(self.style.ERROR('❌ Unexpected Error'))
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            self.stdout.write(f'Error Type: {type(e).__name__}')
            raise CommandError('SMS test failed with unexpected error')

        self.stdout.write('=' * 70)
