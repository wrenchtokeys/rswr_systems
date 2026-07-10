"""
SES migration: welcome email must not be gated on a provider credential.

Bug:
- _send_welcome_email() returned early unless os.environ['SENDGRID_API_KEY'] was set.
- Retiring SendGrid means unsetting that variable, which would have silently
  stopped every welcome email in production — no exception, just a log line.

Fix:
- _send_welcome_email() now always delegates to the configured email backend.
  A missing/incorrect SES credential surfaces as a logged warning from the
  backend instead of a silent no-op.
"""

import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from apps.tenants.models import Tenant
from apps.tenants.views import _send_welcome_email


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TestWelcomeEmailNotGatedOnProviderCredential(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='Ses', email='owner-ses@example.com',
            password='testpass', first_name='Ses', last_name='Owner',
        )
        self.tenant = Tenant.objects.create(
            name='SES Shop', slug='ses-shop', plan='trial', is_active=True,
            owner=self.owner,
        )
        mail.outbox = []

    def test_sends_with_no_sendgrid_api_key_in_environ(self):
        """The retired SENDGRID_API_KEY var must not gate delivery."""
        env = {k: v for k, v in os.environ.items() if k != 'SENDGRID_API_KEY'}
        with patch.dict(os.environ, env, clear=True):
            _send_welcome_email(self.owner, self.tenant, trial_days=30)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.owner.email, mail.outbox[0].to)
        self.assertIn('Welcome', mail.outbox[0].subject)

    def test_backend_failure_is_swallowed_but_logged(self):
        """fail_silently keeps signup working if SES rejects the send."""
        with patch('core.email_utils.send_branded_email', side_effect=Exception('SES down')):
            _send_welcome_email(self.owner, self.tenant, trial_days=30)  # must not raise
