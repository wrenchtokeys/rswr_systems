"""
FIELD_OPS N3 — notification coverage audit.

Guards the defects the audit found. Each class maps to one row of the
inventory table in docs/strategy/FIELD_OPS_SESSIONS.md.
"""
import glob
import os
import uuid
from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer

from apps.technician_portal.review_service import _adjust_to_business_hours
from core.models.notification_template import NotificationTemplate

NOTIFICATION_DIR = os.path.join(
    settings.BASE_DIR, 'templates', 'emails', 'notifications'
)

MOCK_BRANDING = {
    'primary_color': '#0a0a0a', 'text_color': '#111', 'heading_font': 'Arial',
    'body_font': 'Arial', 'warning_color': '#f00', 'button_border_radius': 4,
    'logo_url': '', 'company_name': 'Test Shop',
}


def _bodies(ext):
    return sorted(
        os.path.basename(p)
        for p in glob.glob(os.path.join(NOTIFICATION_DIR, '*' + ext))
    )


class MissingActionUrlTests(TestCase):
    """A body without an action_url loses its button, never the whole email.

    Nineteen bodies built their CTA with `{% with url=base_url|add:action_url %}`,
    and `{% with %}` resolves filter arguments strictly: a context that omits
    the key raises VariableDoesNotExist and kills the render.
    """

    def test_every_html_body_renders_without_an_action_url(self):
        for name in _bodies('.html'):
            with self.subTest(template=name):
                html = render_to_string(
                    f'emails/notifications/{name}',
                    {'branding': MOCK_BRANDING, 'base_url': 'https://rssystems.io'},
                )
                self.assertIn('</html>', html)

    def test_every_text_body_renders_without_an_action_url(self):
        for name in _bodies('.txt'):
            with self.subTest(template=name):
                render_to_string(
                    f'emails/notifications/{name}',
                    {'branding': MOCK_BRANDING, 'base_url': 'https://rssystems.io'},
                )

    def test_no_body_offers_a_button_that_goes_nowhere(self):
        """Without an action_url the CTA is dropped, not pointed at the root."""
        for name in _bodies('.html'):
            with self.subTest(template=name):
                html = render_to_string(
                    f'emails/notifications/{name}',
                    {'branding': MOCK_BRANDING, 'base_url': 'https://rssystems.io'},
                )
                self.assertNotIn('href="https://rssystems.io"', html)

    def test_text_bodies_link_absolutely(self):
        """repair_in_progress/.txt and repair_pending_approval/.txt printed a
        bare relative path, which is not clickable in a mail client."""
        for name in _bodies('.txt'):
            with self.subTest(template=name):
                source = open(
                    os.path.join(NOTIFICATION_DIR, name), encoding='utf-8'
                ).read()
                self.assertNotRegex(
                    source, r'(?<!base_url \}\})\{\{ action_url \}\}',
                    f'{name} prints action_url without a base_url prefix',
                )


class ActionUrlResolutionTests(TestCase):
    """render() resolves the seeded action_url_template before the bodies."""

    def _template(self, **kw):
        defaults = dict(
            name='n3_probe', title_template='T', message_template='M',
            email_subject_template='S',
            email_html_template='emails/notifications/repair_assigned.html',
            email_text_template='emails/notifications/repair_assigned.txt',
            action_url_template='/tech/repairs/{{ repair_id }}/',
        )
        defaults.update(kw)
        return NotificationTemplate(**defaults)

    def test_seeded_action_url_reaches_the_email_body(self):
        rendered = self._template().render({
            'repair_id': 77, 'branding': MOCK_BRANDING,
        })
        self.assertEqual(rendered['action_url'], '/tech/repairs/77/')
        self.assertIn('https://rssystems.io/tech/repairs/77/', rendered['email_html'])
        self.assertIn('https://rssystems.io/tech/repairs/77/', rendered['email_text'])

    def test_caller_supplied_action_url_wins(self):
        rendered = self._template().render({
            'repair_id': 77, 'action_url': '/tech/jobs/', 'branding': MOCK_BRANDING,
        })
        self.assertEqual(rendered['action_url'], '/tech/jobs/')
        self.assertIn('https://rssystems.io/tech/jobs/', rendered['email_html'])

    def test_template_without_an_action_url_still_renders(self):
        rendered = self._template(action_url_template='').render({
            'repair_id': 77, 'branding': MOCK_BRANDING,
        })
        self.assertEqual(rendered['action_url'], '')
        self.assertIn('</html>', rendered['email_html'])


class BatchApprovedTests(TestCase):
    """The multi-break approval email, rendered with what its sender passes."""

    CONTEXT = {
        'batch_id': 'abc-123',
        'unit_number': '4417',
        'repair_count': 3,
        'repairs': [
            {'break_description': 'Star break, driver side', 'cost': 50.0},
            {'break_description': 'Chip, passenger side', 'cost': 40.0},
            {'break_description': 'Bullseye, center', 'cost': 25.0},
        ],
        'total_cost': 115.0,
        'customer_name': 'Penske',
        'technician_name': 'Ray',
        'action_url': '/tech/repairs/?batch=abc-123',
        'branding': MOCK_BRANDING,
        'base_url': 'https://rssystems.io',
    }

    def setUp(self):
        self.html = render_to_string(
            'emails/notifications/batch_approved.html', self.CONTEXT)
        self.text = render_to_string(
            'emails/notifications/batch_approved.txt', self.CONTEXT)

    def test_the_break_count_renders(self):
        """It read `repairs_count`; every sender and seed passes `repair_count`."""
        self.assertIn('3 breaks approved.', self.html)
        self.assertIn('3 breaks approved.', self.text)
        self.assertNotIn(' repair approved', self.html)

    def test_the_pricing_ladder_renders(self):
        """The per-break rows are the whole point of this email."""
        for label, cost in (('Star break, driver side', '$50.00'),
                            ('Chip, passenger side', '$40.00'),
                            ('Bullseye, center', '$25.00')):
            self.assertIn(label, self.html)
            self.assertIn(label, self.text)
            self.assertIn(cost, self.text)
        self.assertIn('$115.00', self.text)

    def test_the_button_has_a_destination(self):
        """It was built from `view_repairs_url`, which no sender ever passed."""
        self.assertIn('https://rssystems.io/tech/repairs/?batch=abc-123', self.html)
        self.assertIn('https://rssystems.io/tech/repairs/?batch=abc-123', self.text)

    def test_it_links_a_technician_to_the_technician_preferences(self):
        """Recipient is first_repair.technician, not the customer."""
        self.assertIn('https://rssystems.io/tech/notifications/preferences/', self.html)
        self.assertIn('https://rssystems.io/tech/notifications/preferences/', self.text)
        self.assertNotIn('/app/notifications/preferences/', self.html)
        self.assertNotIn('/app/notifications/preferences/', self.text)


class BusinessHoursAreLocalTests(TestCase):
    """Review requests are clamped in the shop's clock, not in UTC."""

    def test_pre_dawn_local_is_pushed_to_local_opening(self):
        with timezone.override('America/Chicago'):
            early = timezone.make_aware(
                timezone.datetime(2026, 8, 24, 3, 30), timezone.get_current_timezone())
            out = _adjust_to_business_hours(early, 9, 19)
            self.assertEqual(timezone.localtime(out).hour, 9)
            self.assertEqual(timezone.localtime(out).date(), early.date())

    def test_the_utc_hour_is_not_what_gets_compared(self):
        """09:00 UTC is 04:00 in Chicago -- inside the old check, and the
        exact hour review requests were going out at."""
        with timezone.override('America/Chicago'):
            four_am_local = timezone.make_aware(
                timezone.datetime(2026, 8, 24, 4, 0), timezone.get_current_timezone())
            self.assertEqual(four_am_local.astimezone(dt_timezone.utc).hour, 9)
            out = _adjust_to_business_hours(four_am_local, 9, 19)
            self.assertNotEqual(timezone.localtime(out).hour, 4)
            self.assertEqual(timezone.localtime(out).hour, 9)

    def test_after_close_local_moves_to_the_next_morning(self):
        with timezone.override('America/Chicago'):
            late = timezone.make_aware(
                timezone.datetime(2026, 8, 24, 21, 15), timezone.get_current_timezone())
            out = _adjust_to_business_hours(late, 9, 19)
            local = timezone.localtime(out)
            self.assertEqual(local.hour, 9)
            self.assertEqual(local.date(), late.date() + timedelta(days=1))

    def test_a_time_inside_the_window_is_untouched(self):
        with timezone.override('America/Chicago'):
            noon = timezone.make_aware(
                timezone.datetime(2026, 8, 24, 12, 0), timezone.get_current_timezone())
            self.assertEqual(_adjust_to_business_hours(noon, 9, 19), noon)


class DeliverableChannelTests(TestCase):
    """Every seeded template that has an email body can actually email it.

    Migration 0018 seeded the repair lifecycle with no email wiring at all,
    and 0027 backfilled only the two rows fieldops N1 needed. 0033 finishes
    the job.
    """

    LIFECYCLE = [
        'repair_pending_approval', 'repair_approved', 'repair_denied',
        'repair_in_progress', 'repair_completed', 'batch_approved',
        'repair_assigned', 'repair_reassigned_away',
    ]

    @staticmethod
    def _channels(template):
        if template.channels_override:
            channels = list(template.channels_override)
            if 'in_app' not in channels:
                channels.insert(0, 'in_app')
            return channels
        channels = ['in_app']
        priority = (template.default_priority or '').upper()
        if priority == 'URGENT':
            channels += ['email', 'sms']
        elif priority == 'HIGH':
            channels += ['sms']
        elif priority == 'MEDIUM':
            channels += ['email']
        return channels

    def test_lifecycle_templates_have_an_email_body(self):
        for name in self.LIFECYCLE:
            with self.subTest(template=name):
                template = NotificationTemplate.objects.filter(name=name).first()
                self.assertIsNotNone(template, f'{name} is not seeded')
                self.assertTrue(
                    template.email_html_template,
                    f'{name} has no email_html_template; its email goes out as '
                    f'bare plain text',
                )
                self.assertTrue(template.email_text_template)
                self.assertTrue(template.email_subject_template)

    def test_the_shop_hears_about_a_new_request_by_email(self):
        template = NotificationTemplate.objects.get(name='repair_request_submitted')
        self.assertIn('email', self._channels(template))

    def test_no_template_has_a_body_it_can_never_send(self):
        stranded = [
            t.name for t in NotificationTemplate.objects.filter(active=True)
            if t.email_html_template and 'email' not in self._channels(t)
        ]
        self.assertEqual(
            stranded, [],
            'these templates render an email body that no channel delivers',
        )

    def test_referenced_email_bodies_exist_on_disk(self):
        for template in NotificationTemplate.objects.filter(active=True):
            for field in ('email_html_template', 'email_text_template'):
                path = getattr(template, field)
                if not path:
                    continue
                with self.subTest(template=template.name, field=field):
                    render_to_string(path, {'branding': MOCK_BRANDING})


class AudienceConsistencyTests(TestCase):
    """A body's preferences link matches the portal its recipient can log into."""

    # Recipient per call site; see the N3 inventory table in FIELD_OPS_SESSIONS.md.
    TECH_FACING = [
        'repair_assigned', 'repair_reassigned_away', 'repair_approved',
        'repair_denied', 'repair_request_submitted', 'batch_approved',
        'job_rescheduled', 'jobs_bulk_assigned', 'jobs_bulk_reassigned_away',
        'replacement_approved', 'replacement_denied',
        'replacement_request_submitted',
    ]
    CUSTOMER_FACING = [
        'repair_pending_approval', 'repair_in_progress', 'repair_completed',
        'repair_request_received', 'payment_received',
        'replacement_request_received', 'replacement_pending_approval',
        'replacement_in_progress', 'replacement_completed',
    ]

    def _render(self, name):
        return render_to_string(
            f'emails/notifications/{name}.html',
            {'branding': MOCK_BRANDING, 'base_url': 'https://rssystems.io'},
        )

    def test_tech_bodies_link_the_tech_portal(self):
        for name in self.TECH_FACING:
            with self.subTest(template=name):
                self.assertIn(
                    'https://rssystems.io/tech/notifications/preferences/',
                    self._render(name),
                )

    def test_customer_bodies_link_the_customer_portal(self):
        for name in self.CUSTOMER_FACING:
            with self.subTest(template=name):
                self.assertIn(
                    'https://rssystems.io/app/notifications/preferences/',
                    self._render(name),
                )

    def test_every_notification_body_is_classified(self):
        """A new body must be added to one of the two lists above, so the
        next one cannot quietly inherit the wrong portal's link."""
        on_disk = {os.path.splitext(n)[0] for n in _bodies('.html')}
        classified = set(self.TECH_FACING) | set(self.CUSTOMER_FACING)
        self.assertEqual(
            on_disk - classified, set(),
            'unclassified notification bodies -- add them to the N3 inventory',
        )


@override_settings(
    ALLOWED_HOSTS=['*', 'testserver'],
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class BatchApprovalSpeaksOnceTests(TestCase):
    """Approving a multi-break batch emails the tech once, not once per break.

    `notify_batch_approved` had no callers at all -- the batch_approved
    template was unreachable. Meanwhile each `repair.save()` in the approval
    loop tripped the per-break `repair_approved` email, so the dashboard
    showed one grouped line while the tech's inbox got N.
    """

    def setUp(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        owner = User.objects.create_user(
            'n3_owner', 'n3_owner@test.com', 'testpass123',
            first_name='Test', last_name='Owner',
        )
        self.tenant = Tenant.objects.create(
            name='N3 Shop', slug='n3-shop', subdomain='n3-shop', owner=owner,
            subscription_plan=plan, plan='trial', subscription_status='trialing',
        )
        TenantMembership.objects.create(tenant=self.tenant, user=owner, role='owner')
        tech_user = User.objects.create_user(
            'n3_tech', 'n3_tech@test.com', 'testpass123',
            first_name='Ray', last_name='Tech',
        )
        self.tech = Technician.objects.create(
            user=tech_user, tenant=self.tenant, is_active=True, can_repair=True,
        )
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        self.batch_id = uuid.uuid4()

    def _pending_batch(self, count):
        repairs = []
        for i in range(count):
            repair = Repair.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number='4417', repair_batch_id=self.batch_id,
                description=f'Break {i + 1}', cost=Decimal('50.00'),
            )
            # Shop-created jobs auto-approve on save (resolve_initial_shop_status),
            # so PENDING has to be written past the model hook.
            Repair.objects.filter(pk=repair.pk).update(queue_status='PENDING')
            repairs.append(Repair.objects.get(pk=repair.pk))
        mail.outbox = []
        return repairs

    def _tech_mail(self):
        return [m for m in mail.outbox if 'n3_tech@test.com' in m.to]

    def test_a_batch_sends_one_email_not_one_per_break(self):
        from apps.technician_portal.signals import notify_batch_approved

        repairs = self._pending_batch(3)
        for repair in repairs:
            repair.queue_status = 'APPROVED'
            repair._batch_approval_notifications_handled = True
            repair.save()

        self.assertEqual(
            self._tech_mail(), [],
            'the per-break repair_approved email should be suppressed for a batch',
        )

        notify_batch_approved(repairs)
        sent = self._tech_mail()
        self.assertEqual(len(sent), 1)
        self.assertIn('3 repairs', sent[0].subject)

    def test_the_batch_email_carries_the_pricing_ladder(self):
        from apps.technician_portal.signals import notify_batch_approved

        repairs = self._pending_batch(3)
        for repair in repairs:
            repair.queue_status = 'APPROVED'
            repair._batch_approval_notifications_handled = True
            repair.save()
        notify_batch_approved(repairs)

        body = self._tech_mail()[0].body
        for i in range(3):
            self.assertIn(f'Break {i + 1}', body)
        self.assertIn('$150.00', body)  # 3 x $50 total

    def test_a_single_approval_still_emails_per_repair(self):
        """The guard must not silence the ordinary one-repair path."""
        repair = self._pending_batch(1)[0]
        repair.queue_status = 'APPROVED'
        repair.save()
        self.assertEqual(len(self._tech_mail()), 1)
        self.assertIn('Approved', self._tech_mail()[0].subject)
