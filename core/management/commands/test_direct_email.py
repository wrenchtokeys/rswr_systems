"""
Management command to test email sending directly via Amazon SES.

Sends a multipart (text + HTML) message through the configured backend,
which exercises a different path than `test_ses` (plain `send_mail`).

This helps diagnose whether email issues are due to:
1. SES configuration problems
2. Network/firewall issues

Usage:
    python manage.py test_direct_email your-email@example.com
"""

from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Test email sending directly via Amazon SES'

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
        self.stdout.write(f'SES SMTP password: {"SET" if settings.EMAIL_HOST_PASSWORD else "NOT SET"}')
        self.stdout.write('')

        try:
            # Create HTML email
            subject = 'Test Email from RS Systems (Direct Send)'
            from django.utils import timezone

            text_content = '''
This is a test email sent directly via Amazon SES.

If you receive this email, SES is configured correctly.

Timestamp: {timestamp}
Environment: Production
            '''.format(timestamp=str(timezone.now()))

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
    <p class="success">Amazon SES is configured correctly!</p>

    <div class="info">
        <p><strong>This email was sent directly via Amazon SES.</strong></p>
        <p>If you receive this, your email configuration is working correctly.</p>
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
                self.stdout.write('→ SES is working correctly')
                self.stdout.write('→ Check notification preferences and email verification settings')
            else:
                self.stdout.write(self.style.ERROR(f'\n❌ Email send returned 0 (no emails sent)'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ Email send failed: {str(e)}'))
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Common issues:'))
            self.stdout.write('1. Invalid EMAIL_HOST_USER / EMAIL_HOST_PASSWORD (SES SMTP credentials)')
            self.stdout.write('2. SES account paused, or sending disabled for the identity')
            self.stdout.write('3. Network/firewall blocking port 587')
            self.stdout.write('4. FROM address domain not verified in SES')

            import traceback
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('Full error:'))
            self.stdout.write(traceback.format_exc())
