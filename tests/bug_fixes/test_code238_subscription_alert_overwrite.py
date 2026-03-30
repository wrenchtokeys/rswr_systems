"""
CODE-238: Subscription alert overwrite bug

Bug: _send_alert in check_subscription_alerts updated the DB via
Tenant.objects.filter().update() but did NOT update the in-memory
tenant.subscription_alerts_sent attribute. When a tenant qualified for
multiple alerts in a single run (e.g. trial_expiry_7_days AND
trial_expiry_1_day), the second alert's DB write would start from
`tenant.subscription_alerts_sent or {}` = {} again, overwriting the
first alert. Result: the first alert re-fires on every subsequent run
(duplicate emails forever).

Fix: After recording the alert in the DB, also update
tenant.subscription_alerts_sent on the in-memory object so subsequent
_send_alert calls within the same run see the full dict.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.tenants.models import Tenant


class SubscriptionAlertOverwriteTests(TestCase):
    """Verify multiple alerts in one run don't overwrite each other."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.owner = User.objects.create_user(
            username='alertowner', password='test', email='owner@test.com',
            first_name='Owner',
        )
        self.tenant = Tenant.objects.create(
            name='Alert Shop',
            slug='alert-shop',
            subdomain='alert-shop',
            owner=self.owner,
            plan='trial',
            trial_started_at=timezone.now() - timedelta(days=29),
            subscription_alerts_sent={},
        )

    @patch('core.email_utils.send_branded_email')
    def test_multiple_alerts_same_run_all_persist(self, mock_email):
        """
        A tenant with trial expiring in <1 day qualifies for both
        trial_expiry_7_days and trial_expiry_1_day in the same run.
        Both must be recorded in subscription_alerts_sent.
        """
        from apps.tenants.management.commands.check_subscription_alerts import (
            _send_alert, ALERT_TRIAL_7_DAYS, ALERT_TRIAL_1_DAY,
        )

        # Send first alert
        result1 = _send_alert(
            self.tenant, ALERT_TRIAL_7_DAYS,
            subject='Trial ends in 7 days',
            body='',
            headline='Trial Ending',
            paragraphs=['Test'],
        )
        self.assertTrue(result1, "First alert should send")

        # Send second alert — same tenant object, same run
        result2 = _send_alert(
            self.tenant, ALERT_TRIAL_1_DAY,
            subject='Trial expires tomorrow',
            body='',
            headline='Trial Tomorrow',
            paragraphs=['Test'],
        )
        self.assertTrue(result2, "Second alert should send")

        # Both alerts must be in the DB
        self.tenant.refresh_from_db()
        alerts = self.tenant.subscription_alerts_sent
        self.assertIn(ALERT_TRIAL_7_DAYS, alerts,
                       "7-day alert should persist in DB after second alert")
        self.assertIn(ALERT_TRIAL_1_DAY, alerts,
                       "1-day alert should persist in DB")

    @patch('core.email_utils.send_branded_email')
    def test_alert_not_sent_twice(self, mock_email):
        """An already-sent alert should not fire again."""
        from apps.tenants.management.commands.check_subscription_alerts import (
            _send_alert, ALERT_TRIAL_7_DAYS,
        )

        # Send once
        _send_alert(self.tenant, ALERT_TRIAL_7_DAYS, subject='Test', body='',
                     headline='Test', paragraphs=['Test'])

        # Send again — should return False (already sent)
        result = _send_alert(self.tenant, ALERT_TRIAL_7_DAYS, subject='Test', body='',
                             headline='Test', paragraphs=['Test'])
        self.assertFalse(result, "Alert should not re-send if already recorded")
        self.assertEqual(mock_email.call_count, 1, "Email should only be sent once")

    @patch('core.email_utils.send_branded_email')
    def test_in_memory_object_updated(self, mock_email):
        """
        After _send_alert, the in-memory tenant.subscription_alerts_sent
        must reflect the new alert (not just the DB row).
        """
        from apps.tenants.management.commands.check_subscription_alerts import (
            _send_alert, ALERT_TRIAL_7_DAYS,
        )

        # Start with empty dict to simulate a fresh tenant
        self.tenant.subscription_alerts_sent = {}
        self.tenant.save(update_fields=['subscription_alerts_sent'])

        _send_alert(self.tenant, ALERT_TRIAL_7_DAYS, subject='Test', body='',
                     headline='Test', paragraphs=['Test'])

        # In-memory object should have the alert (not still empty)
        self.assertIn(ALERT_TRIAL_7_DAYS, self.tenant.subscription_alerts_sent)
        # DB should also have it
        self.tenant.refresh_from_db()
        self.assertIn(ALERT_TRIAL_7_DAYS, self.tenant.subscription_alerts_sent)

    @patch('core.email_utils.send_branded_email')
    def test_full_command_multiple_alerts(self, mock_email):
        """
        End-to-end: run the full command on a tenant with trial expiring
        in <1 day. Both 7-day and 1-day alerts should fire and persist.
        """
        from django.core.management import call_command
        from apps.tenants.management.commands.check_subscription_alerts import (
            ALERT_TRIAL_7_DAYS, ALERT_TRIAL_1_DAY,
        )

        # Trial expires tomorrow
        self.tenant.trial_started_at = timezone.now() - timedelta(days=29)
        self.tenant.subscription_alerts_sent = {}
        self.tenant.save()

        call_command('check_subscription_alerts')

        self.tenant.refresh_from_db()
        alerts = self.tenant.subscription_alerts_sent
        self.assertIn(ALERT_TRIAL_7_DAYS, alerts)
        self.assertIn(ALERT_TRIAL_1_DAY, alerts)
