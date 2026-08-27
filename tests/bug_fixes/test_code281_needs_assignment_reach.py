"""
CODE-281 Regression Test: the Unassigned queue could only be found by
someone already looking at it.

CODE-279 gave the shop a real "nobody has picked this yet" state and told
the managers about it by writing a ``TechnicianNotification`` row — the
dashboard's unread list, and nowhere else.  No bell, no email, because
``NotificationService`` renders from a ``NotificationTemplate`` and there
was no row for this event.  A shop that did not open the dashboard on a
given afternoon never learned that a customer request was sitting
unassigned, which is the single thing Manual assignment depends on
somebody noticing.  The setting promised "a manager must manually assign
every repair"; what it delivered was "a manager must manually go looking".

Fix: a ``needs_assignment`` template (core migration 0034) and a
``NotificationService`` send alongside the dashboard row.  Named for the
event rather than the audience — the call site decides who hears it.

The rules this file guards:

* The alert reaches a manager who never opens the app.
* Exactly once per customer request — a six-break batch is one decision,
  and an email, unlike a dashboard row, cannot be unsent.
* It never names the provisional technician.  The name on the row is the
  placeholder the non-null FK forced onto it; printing it in a manager's
  inbox would read as "assigned to Marcus", the exact lie the queue
  exists to stop telling.
* The technician who did not get the job is not told anything at all.
* The dashboard row survives an email failure.  It is the floor this
  event has always had; the reach is additive.
"""

import uuid

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from apps.technician_portal.models import (
    Repair, Replacement, Technician, TechnicianNotification,
)
from apps.tenants.models import Tenant
from apps.tenants.services.assignment_service import (
    auto_assign_repair,
    auto_assign_replacement,
)
from core.models import Customer
from core.models.notification import Notification
from core.models.notification_template import NotificationTemplate


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class NeedsAssignmentReachBase(TestCase):
    """A manual shop, one manager with an inbox, and two ordinary techs."""

    strategy = 'manual'

    def setUp(self):
        owner = User.objects.create_user('c281_owner', password='pw')
        self.tenant = Tenant.objects.create(
            name='C281 Shop', slug='c281-shop', plan='trial', owner=owner,
            assignment_strategy=self.strategy,
        )
        self.manager = self._make_tech(
            'c281_mgr', 'mgr@c281.test', is_manager=True)
        self.techs = [
            self._make_tech(f'c281_t{i}', f't{i}@c281.test') for i in range(2)
        ]
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@c281.test')
        mail.outbox = []

    def _make_tech(self, username, email, **kwargs):
        user = User.objects.create_user(username, email, 'pw')
        return Technician.objects.create(
            user=user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True, **kwargs,
        )

    def _make_repair(self, tech=None, **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=tech or self.techs[0],
            queue_status=kwargs.pop('queue_status', 'REQUESTED'),
            unit_number=kwargs.pop('unit_number', '4417'),
            **kwargs,
        )

    def _mail_to(self, address):
        return [m for m in mail.outbox if address in m.to]

    @staticmethod
    def _bodies(message):
        """Subject, plain text and the HTML alternative, as one string."""
        parts = [message.subject, message.body]
        parts += [content for content, mime in message.alternatives]
        return '\n'.join(parts)


class TheAlertLeavesTheDashboardTest(NeedsAssignmentReachBase):

    def test_the_manager_is_emailed(self):
        """The point of the session: reach someone who never opens the app."""
        self._make_repair()

        repair = Repair.objects.first()
        auto_assign_repair(repair)

        self.assertEqual(len(self._mail_to('mgr@c281.test')), 1)

    def test_the_bell_row_is_written_too(self):
        """The email is a channel of a Notification, not a bare send."""
        auto_assign_repair(self._make_repair())

        notes = Notification.objects.filter(
            template__name='needs_assignment',
            recipient_id=self.manager.pk,
        )
        self.assertEqual(notes.count(), 1)
        self.assertIn('waiting to be assigned', notes.first().message)

    def test_the_dashboard_row_still_happens(self):
        """CODE-279's floor is additive-to, not replaced."""
        auto_assign_repair(self._make_repair())

        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.manager).count(),
            1,
        )

    def test_the_email_links_to_the_job(self):
        repair = self._make_repair()
        auto_assign_repair(repair)

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertIn(f'/tech/repairs/{repair.pk}/', body)

    def test_the_technician_nobody_picked_hears_nothing_about_assignment(self):
        """The provisional tech gets no assignment notification of any kind.

        They do still get `repair_request_submitted` — every technician in
        the shop is told a customer asked for work, and that is a different
        event with a different meaning.  What must not reach them is
        anything saying the job is theirs.
        """
        auto_assign_repair(self._make_repair(self.techs[0]))

        assignment_mail = [
            m for m in mail.outbox
            if 't0@c281.test' in m.to or 't1@c281.test' in m.to
            if 'assign' in m.subject.lower()
        ]
        self.assertEqual(assignment_mail, [])
        self.assertFalse(Notification.objects.filter(
            recipient_id__in=[t.pk for t in self.techs],
            template__name__in=['repair_assigned', 'needs_assignment'],
        ).exists())


class TheEmailDoesNotNameThePlaceholderTest(NeedsAssignmentReachBase):
    """The name on the row is not a decision, so it is not in the alert."""

    def setUp(self):
        super().setUp()
        placeholder = self.techs[0].user
        placeholder.first_name = 'Zephyrine'
        placeholder.last_name = 'Quillfeather'
        placeholder.save()

    def test_the_provisional_technician_is_absent_from_the_email(self):
        auto_assign_repair(self._make_repair(self.techs[0]))

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertNotIn('Zephyrine', body)
        self.assertNotIn('Quillfeather', body)

    def test_the_bell_row_does_not_name_them_either(self):
        auto_assign_repair(self._make_repair(self.techs[0]))

        note = Notification.objects.get(template__name='needs_assignment')
        self.assertNotIn('Zephyrine', f'{note.title} {note.message}')


class TheEmailSaysWhyItIsQueuedTest(NeedsAssignmentReachBase):
    """"Waiting to be assigned" alone cannot tell policy from breakage."""

    def test_manual_says_the_shop_assigns_by_hand(self):
        auto_assign_repair(self._make_repair())

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertIn('assigns every job by hand', body)


class PrimaryFirstSaysSomethingElseTest(NeedsAssignmentReachBase):

    strategy = 'primary_first'

    def test_primary_first_names_the_missing_primary(self):
        auto_assign_repair(self._make_repair())

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertIn('no primary technician', body)


class OneRequestIsOneEmailTest(NeedsAssignmentReachBase):
    """A six-break windshield is one decision, and so is one inbox line."""

    def _batch(self, count):
        batch_id = uuid.uuid4()
        return [
            self._make_repair(
                repair_batch_id=batch_id, break_number=i + 1,
                total_breaks_in_batch=count, unit_number='B-1',
            )
            for i in range(count)
        ]

    def test_a_three_break_batch_emails_once(self):
        breaks = self._batch(3)

        for repair in breaks:
            auto_assign_repair(repair)

        self.assertTrue(all(
            Repair.objects.get(pk=r.pk).needs_assignment for r in breaks))
        self.assertEqual(len(self._mail_to('mgr@c281.test')), 1)

    def test_the_one_email_says_how_many_breaks(self):
        """One alert for three breaks has to say it stands for three."""
        for repair in self._batch(3):
            auto_assign_repair(repair)

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertIn('Breaks', body)

    def test_two_separate_requests_are_two_emails(self):
        """The de-dup is per batch, not a mute on the whole event."""
        auto_assign_repair(self._make_repair(unit_number='A-1'))
        auto_assign_repair(self._make_repair(unit_number='A-2'))

        self.assertEqual(len(self._mail_to('mgr@c281.test')), 2)


class EveryManagerHearsTest(NeedsAssignmentReachBase):

    def setUp(self):
        super().setUp()
        self.second = self._make_tech(
            'c281_mgr2', 'mgr2@c281.test', is_manager=True)
        self.retired = self._make_tech(
            'c281_mgr3', 'mgr3@c281.test', is_manager=True)
        self.retired.is_active = False
        self.retired.save()
        mail.outbox = []

    def test_both_active_managers_are_emailed(self):
        auto_assign_repair(self._make_repair())

        self.assertEqual(len(self._mail_to('mgr@c281.test')), 1)
        self.assertEqual(len(self._mail_to('mgr2@c281.test')), 1)

    def test_a_deactivated_manager_is_not(self):
        auto_assign_repair(self._make_repair())

        self.assertEqual(self._mail_to('mgr3@c281.test'), [])


class QueuedReplacementsReachManagersTest(NeedsAssignmentReachBase):
    """Replacements queue too, and their alert has to carry a real link.

    ``Notification.repair`` is a Repair-only FK, so a replacement cannot be
    attached to the notification and its job facts have to be merged at the
    call site.  The dashboard row's missing deep link is a known gap that
    JOB_QUEUE_SESSIONS Q5 owns; the email's is not, because ``action_url``
    is a plain string the sender controls.
    """

    def _make_replacement(self):
        return Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[0], queue_status='REQUESTED',
            unit_number='4417',
        )

    def test_a_queued_replacement_emails_the_manager(self):
        auto_assign_replacement(self._make_replacement())

        self.assertEqual(len(self._mail_to('mgr@c281.test')), 1)

    def test_the_replacement_email_links_to_the_replacement(self):
        replacement = self._make_replacement()
        auto_assign_replacement(replacement)

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertIn(f'/tech/replacement/{replacement.pk}/', body)

    def test_the_replacement_email_says_replacement(self):
        auto_assign_replacement(self._make_replacement())

        body = self._bodies(self._mail_to('mgr@c281.test')[0])
        self.assertIn('replacement', body.lower())


class TheTemplateCanActuallySendTest(NeedsAssignmentReachBase):
    """HIGH maps to ['in_app', 'sms'], and SMS is dark until fieldops N2.

    Without an explicit override this template would render an email body
    that no channel delivers — the trap N3 found in three other rows.
    """

    def test_email_is_one_of_the_channels(self):
        template = NotificationTemplate.objects.get(name='needs_assignment')
        self.assertIn('email', template.channels_override)

    def test_it_has_a_body_to_send(self):
        template = NotificationTemplate.objects.get(name='needs_assignment')
        self.assertTrue(template.email_html_template)
        self.assertTrue(template.email_text_template)
        self.assertTrue(template.email_subject_template)


class TheDashboardRowSurvivesTest(NeedsAssignmentReachBase):
    """The reach is additive: losing it must not lose what CODE-279 had."""

    def test_an_unusable_template_does_not_cost_us_the_dashboard_row(self):
        NotificationTemplate.objects.filter(
            name='needs_assignment').update(active=False)

        auto_assign_repair(self._make_repair())

        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.manager).count(),
            1,
        )
        self.assertEqual(self._mail_to('mgr@c281.test'), [])


class AnOptedOutManagerTest(NeedsAssignmentReachBase):
    """The opt-out is honored, and the dashboard still holds the job."""

    def test_turning_off_assignment_email_silences_the_send_not_the_queue(self):
        from core.models.notification_preferences import (
            TechnicianNotificationPreference,
        )
        prefs, _ = TechnicianNotificationPreference.objects.get_or_create(
            technician=self.manager)
        prefs.receive_email_notifications = False
        prefs.save()

        auto_assign_repair(self._make_repair())

        self.assertEqual(self._mail_to('mgr@c281.test'), [])
        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.manager).count(),
            1,
        )
        self.assertTrue(Notification.objects.filter(
            template__name='needs_assignment').exists())
