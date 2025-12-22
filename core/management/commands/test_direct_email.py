"""
Management command to test email sending directly (bypassing Celery).

This helps diagnose whether email issues are due to:
1. SendGrid configuration problems
2. Celery workers not running
3. Network/firewall issues

Usage:
    python manage.py test_direct_email your-email@example.com
"""

from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test email sending directly via SendGrid (bypasses Celery queue)'

    def add_arguments(self, parser):
        parser.add_argument(
            'recipient_email',
            type=str,
            help='Email address to send test email to'
        )

    def handle(self, *args, **options):
        recipient_email = options['recipient_email']

        self.stdout.write(self.style.NOTICE(f'\n=== Direct Email Test ==='))
        self.stdout.write(f'Recipient: {recipient_email}')
        self.stdout.write(f'From: {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write(f'Email Backend: {settings.EMAIL_BACKEND}')
        self.stdout.write(f'Email Host: {settings.EMAIL_HOST}')
        self.stdout.write(f'Email Port: {settings.EMAIL_PORT}')
        self.stdout.write(f'Email User: {settings.EMAIL_HOST_USER}')
        self.stdout.write(f'SendGrid API Key: {"SET" if settings.EMAIL_HOST_PASSWORD else "NOT SET"}')
        self.stdout.write('')

        try:
            # Create HTML email
            subject = 'Test Email from RS Systems (Direct Send)'
            text_content = '''
This is a test email sent directly via SendGrid (bypassing Celery).

If you receive this email, SendGrid is configured correctly.
If emails still don't work, the issue is likely with Celery workers.

Timestamp: {timestamp}
Environment: Production
            '''.format(timestamp=str(__import__('django.utils.timezone', fromlist=['timezone']).timezone.now()))

            html_content = '''
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; }}
        .success {{ color: green; font-weight: bold; }}
        .info {{ background: #f0f0f0; padding: 15px; border-left: 4px solid #0066cc; }}
    </style>
</head>
<body>
    <h2>🎉 Test Email Received!</h2>
    <p class="success">SendGrid is configured correctly!</p>

    <div class="info">
        <p><strong>This email was sent directly</strong> (bypassing Celery queue).</p>
        <p>If you receive this but not notification emails, the issue is with Celery workers.</p>
    </div>

    <p><small>Sent from RS Systems Production</small></p>
</body>
</html>
            '''

            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient_email]
            )
            email.attach_alternative(html_content, "text/html")

            self.stdout.write(self.style.NOTICE('Sending email...'))

            # Send email (fail_silently=False so we see errors)
            result = email.send(fail_silently=False)

            if result == 1:
                self.stdout.write(self.style.SUCCESS(f'\n✅ Email sent successfully!'))
                self.stdout.write(self.style.SUCCESS(f'Check {recipient_email} for the test email.'))
                self.stdout.write('')
                self.stdout.write(self.style.WARNING('If you receive this email but NOT notification emails:'))
                self.stdout.write('→ SendGrid is working correctly')
                self.stdout.write('→ The issue is Celery workers not processing tasks')
                self.stdout.write('→ Check systemd status: sudo systemctl status celery-worker')
            else:
                self.stdout.write(self.style.ERROR(f'\n❌ Email send returned 0 (no emails sent)'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Email send failed: {str(e)}'))
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Common issues:'))
            self.stdout.write('1. Invalid SENDGRID_API_KEY environment variable')
            self.stdout.write('2. SendGrid account suspended or restricted')
            self.stdout.write('3. Network/firewall blocking port 587')
            self.stdout.write('4. FROM address not verified in SendGrid')

            import traceback
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('Full error:'))
            self.stdout.write(traceback.format_exc())
