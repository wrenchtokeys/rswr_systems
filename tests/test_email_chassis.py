"""Guards for the shared email chassis (templates/emails/).

RS Systems used to have two unrelated email systems — the Django
notification templates and an HTML builder in core/email_utils.py — that
shared no header, button, type scale or colour. They now both render
through templates/emails/base.html. These tests lock down the properties
that made unifying them worth doing, because each one regressed silently
before: an emoji nobody noticed for months, a bare "Unit #" printed to
retail customers, and a shop's brand colour on the platform's own
billing mail.
"""
import datetime
import glob
import os.path
import re
from decimal import Decimal
from types import SimpleNamespace as NS

from django.core import mail
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings

from core.email_utils import send_branded_email
from core.notification_text import on_vehicle

# Pictographs, dingbats and the geometric/misc-symbol blocks that carry the
# tick and cross this codebase used. Deliberately NOT a blanket ban on
# non-ASCII: em dashes and accented names are fine and wanted.
EMOJI = re.compile(
    '['
    '\U0001F300-\U0001FAFF'   # emoji proper
    '←-⇿'           # arrows
    '☀-➿'           # dingbats, incl. the tick and cross
    '⬀-⯿'           # misc symbols and arrows
    '️'                  # variation selector
    ']'
)


def _sample_context():
    """One context wide enough to render every notification template."""
    tech = NS(get_full_name=lambda: 'Dale Whitcomb')
    customer = NS(
        name='Penske Truck Leasing', company_name='Penske Truck Leasing',
        vehicle_column_label='Unit #', is_individual=False,
    )
    repair = NS(
        id=1842, break_description='Bullseye, passenger side',
        assigned_technician=tech, customer=customer, unit_number='4471',
        actual_repair_date=datetime.date(2026, 8, 19),
        requested_repair_date=datetime.date(2026, 8, 18),
        cost=Decimal('40.00'), has_warranty=True, warranty_expires_at=None,
        denial_reason='Damage is outside the repairable area.',
    )
    invoice = NS(
        invoice_number='INV-1043', total=Decimal('84.75'),
        amount_due=Decimal('0.00'), amount_paid=Decimal('84.75'),
        customer=customer, status='PAID', get_status_display=lambda: 'Paid',
    )
    payment = NS(
        amount=Decimal('84.75'), payment_date=datetime.date(2026, 8, 21),
        get_payment_method_display=lambda: 'Visa ending 4242',
        reference_number='ch_3PqL2b0z',
    )
    return {
        'repair': repair, 'repairs': [repair], 'repairs_count': 2,
        'invoice': invoice, 'payment': payment,
        'vehicle_identifier': '4471', 'vehicle_label': 'Unit #',
        'service_location': '1900 Bond St, North Little Rock, AR',
        'unit_number': '4471', 'customer_name': 'Penske Truck Leasing',
        'technician_name': 'Dale Whitcomb', 'new_technician_name': 'Ray Alvarez',
        'repair_id': 1842, 'job_id': 1842, 'job_type': 'Repair',
        'status': 'Approved', 'description': 'Bullseye, passenger side',
        'damage_type': 'Bullseye', 'estimated_cost': Decimal('50.00'),
        'total_cost': Decimal('90.00'), 'pricing_note': 'Your rate steps down.',
        'preferred_time': 'Thursday morning', 'job_count': 3,
        'job_summary': 'Unit 2210, Unit 4471', 'day': 'Thursday',
        'first_time': '9:00 AM', 'first_job': 'Unit 4471',
        'second_time': '1:30 PM', 'second_job': 'Erin Castillo',
        'action_url': '/tech/jobs/1842/',
        'view_repair_url': 'https://rssystems.io/app/repairs/1842/',
        'view_repairs_url': 'https://rssystems.io/app/batch/abc/',
        'pay_url': 'https://rssystems.io/pay/abc',
        'receipt_pdf_url': 'https://rssystems.io/pdf/abc',
        'base_url': 'https://rssystems.io',
        'branding': {
            'company_name': 'Glass Guy Auto Glass', 'primary_color': '#2563eb',
            'company_address': '4210 S University Ave, Little Rock, AR',
            'support_phone': '(501) 555-0142',
            'support_email': 'service@glassguy.example',
            'logo_url': '', 'footer_text': '', 'website_url': '',
        },
    }


class NotificationTemplateRenderTests(SimpleTestCase):
    """Every template in emails/notifications/ renders and stays clean."""

    def _templates(self):
        paths = sorted(glob.glob('templates/emails/notifications/*'))
        self.assertTrue(paths, 'no notification templates found')
        return [('emails/notifications/' + os.path.basename(p)) for p in paths]

    def test_every_template_renders(self):
        context = _sample_context()
        for name in self._templates():
            with self.subTest(template=name):
                render_to_string(name, context)

    def test_no_emoji_or_dingbats(self):
        """'✓ COMPLETED' shipped in six of these and rendered as a box."""
        context = _sample_context()
        for name in self._templates():
            with self.subTest(template=name):
                found = EMOJI.findall(render_to_string(name, context))
                self.assertEqual(found, [], f'{name} renders {found}')

    def test_plain_text_has_no_ascii_rulers(self):
        """The rows of '=' read as machine output and wrapped on phones."""
        context = _sample_context()
        for name in self._templates():
            if not name.endswith('.txt'):
                continue
            with self.subTest(template=name):
                self.assertNotIn('====', render_to_string(name, context))

    def test_html_templates_use_the_shared_chassis(self):
        """A template that stops extending base.html is a second design."""
        context = _sample_context()
        for name in self._templates():
            if not name.endswith('.html'):
                continue
            with self.subTest(template=name):
                html = render_to_string(name, context)
                self.assertIn('#f7f8fa', html, 'not rendered through the chassis')
                self.assertIn('Manage notification preferences', html)


class RealCallerContextTests(SimpleTestCase):
    """Render with only what the signal actually passes, not a wish list.

    The context reaching a notification template is flat and JSON-safe —
    NotificationService persists it and the retry path re-renders it, so the
    job object is never in there. Templates that reached for
    {{ repair.total_cost }} rendered a bare "$" and {{ repair.id }} rendered
    nothing, for months, because a generous test context hid it.

    Each context below is the one its sender in
    apps/technician_portal/signals.py builds, plus the values
    NotificationService derives.
    """

    BRANDING = {
        'company_name': 'Glass Guy Auto Glass', 'primary_color': '#2563eb',
        'company_address': '4210 S University Ave, Little Rock, AR',
        'support_phone': '(501) 555-0142', 'support_email': 'x@example.com',
        'logo_url': '', 'footer_text': '', 'website_url': '',
    }
    # What NotificationService.create_notification derives from the job.
    DERIVED = {
        'vehicle_identifier': '4471', 'vehicle_label': 'Unit #',
        'service_location': '1900 Bond St, North Little Rock, AR',
        'damage_description': 'Bullseye, passenger side',
        'job_cost_display': '$40.00', 'warranty_display': 'Lifetime',
        'denial_reason': 'Damage is outside the repairable area.',
        'completed_on': 'August 19, 2026', 'requested_on': 'August 18, 2026',
    }

    CASES = {
        # _notify_customer_completed
        'repair_completed': ({
            'repair_id': 1842, 'unit_number': '4471',
            'technician_name': 'Dale Whitcomb', 'final_cost': 40.0,
            'customer_name': 'Penske Truck Leasing',
            'action_url': '/app/repairs/1842/',
        }, ['1842', 'Dale Whitcomb', '$40.00', '4471', 'Lifetime']),
        # _notify_technician_approved
        'repair_approved': ({
            'repair_id': 1842, 'unit_number': '4471',
            'customer_name': 'Penske Truck Leasing',
            'action_url': '/tech/repairs/1842/',
        }, ['1842', 'Penske Truck Leasing', '$40.00']),
        # _notify_technician_denied
        'repair_denied': ({
            'repair_id': 1842, 'unit_number': '4471',
            'customer_name': 'Penske Truck Leasing',
            'action_url': '/tech/repairs/1842/',
        }, ['1842', 'Damage is outside the repairable area.']),
        # _notify_customer_in_progress
        'repair_in_progress': ({
            'repair_id': 1842, 'unit_number': '4471',
            'technician_name': 'Dale Whitcomb',
            'customer_name': 'Penske Truck Leasing',
            'action_url': '/app/repairs/1842/',
        }, ['1842', 'Dale Whitcomb', '4471']),
        # _notify_customer_approval_needed
        'repair_pending_approval': ({
            'repair_id': 1842, 'unit_number': '4471',
            'technician_name': 'Dale Whitcomb', 'estimated_cost': 50.0,
            'customer_name': 'Penske Truck Leasing',
            'action_url': '/app/repairs/1842/approve/',
        }, ['1842', 'Dale Whitcomb', '$50.00']),
    }

    def _context(self, extra):
        context = {'branding': self.BRANDING, 'base_url': 'https://rssystems.io'}
        context.update(self.DERIVED)
        context.update(extra)
        return context

    def test_key_facts_actually_render(self):
        for name, (caller_context, expected) in self.CASES.items():
            context = self._context(caller_context)
            for suffix in ('.html', '.txt'):
                template = f'emails/notifications/{name}{suffix}'
                out = render_to_string(template, context)
                for probe in expected:
                    with self.subTest(template=template, probe=probe):
                        self.assertIn(probe, out)

    def test_no_row_renders_with_an_empty_value(self):
        """'Repair ID: #' and a bare '$' are what this catches."""
        for name, (caller_context, _) in self.CASES.items():
            context = self._context(caller_context)
            text = render_to_string(f'emails/notifications/{name}.txt', context)
            for line in text.splitlines():
                if not line.startswith('  ') or not line.strip():
                    continue
                # A row is "  <padded label><value>"; the value must exist.
                with self.subTest(template=name, line=line):
                    self.assertTrue(
                        line.strip().rstrip('#$').strip() and len(line.split()) > 1,
                        f'{name}.txt row has a label but no value: {line!r}',
                    )

    def test_action_button_has_a_url(self):
        """view_repair_url was never in the context; the button had no href."""
        for name, (caller_context, _) in self.CASES.items():
            context = self._context(caller_context)
            html = render_to_string(f'emails/notifications/{name}.html', context)
            with self.subTest(template=name):
                self.assertIn(
                    f'href="https://rssystems.io{caller_context["action_url"]}"',
                    html,
                )


class VehicleRowTests(SimpleTestCase):
    """A fleet job names a unit; an individual's names their vehicle."""

    def _render_row(self, **overrides):
        context = _sample_context()
        context.update(overrides)
        return render_to_string('emails/components/vehicle_row.html', context)

    def test_fleet_job_labels_the_unit(self):
        out = self._render_row(vehicle_label='Unit #', vehicle_identifier='4471')
        self.assertIn('Unit #', out)
        self.assertIn('4471', out)

    def test_individual_job_labels_the_vehicle(self):
        out = self._render_row(vehicle_label='Vehicle',
                               vehicle_identifier='2022 Toyota Camry')
        self.assertIn('Vehicle', out)
        self.assertIn('2022 Toyota Camry', out)
        self.assertNotIn('Unit #', out)

    def test_nothing_on_record_prints_nothing(self):
        """Better an absent row than 'Unit #' with nothing after it."""
        out = self._render_row(vehicle_label='', vehicle_identifier='', unit_number='')
        self.assertEqual(out.strip(), '')


class OnVehiclePhrasingTests(SimpleTestCase):
    """The in-app message helper that replaced 'on Unit {blank}'."""

    def test_fleet_reads_as_a_unit(self):
        job = NS(get_vehicle_label=lambda: 'Unit #4471')
        self.assertEqual(on_vehicle(job), ' on Unit #4471')

    def test_individual_reads_as_prose(self):
        job = NS(get_vehicle_label=lambda: '2019 Ford F-150')
        self.assertEqual(on_vehicle(job), ' on a 2019 Ford F-150')

    def test_no_vehicle_closes_the_sentence(self):
        job = NS(get_vehicle_label=lambda: '')
        self.assertEqual(on_vehicle(job), '')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendBrandedEmailTests(TestCase):
    """send_branded_email renders the same chassis as the templates."""

    def setUp(self):
        mail.outbox = []

    def _send(self, **kwargs):
        defaults = dict(
            subject='Invoice INV-1043', recipient_list=['fleet@example.com'],
            headline='Invoice INV-1043', body_paragraphs=['Your invoice is ready.'],
        )
        defaults.update(kwargs)
        send_branded_email(**defaults)
        return mail.outbox[-1]

    def test_renders_through_the_chassis(self):
        html = self._send().alternatives[0][0]
        self.assertIn('#f7f8fa', html)
        self.assertIn('Manage notification preferences', html)

    def test_no_emoji_in_either_half(self):
        message = self._send()
        self.assertEqual(EMOJI.findall(message.alternatives[0][0]), [])
        self.assertEqual(EMOJI.findall(message.body), [])

    def test_plain_text_has_no_ascii_rulers(self):
        self.assertNotIn('====', self._send().body)

    def test_detail_row_flags_are_accepted(self):
        """2-tuples are what every existing caller passes and must keep working."""
        message = self._send(detail_rows=[
            ('Invoice #', 'INV-1043'),
            ('Total', '$84.75', 'strong'),
            ('Balance', '$0.00', 'strong money'),
        ])
        html = message.alternatives[0][0]
        for probe in ('INV-1043', '$84.75', '$0.00'):
            self.assertIn(probe, html)
            self.assertIn(probe, message.body)
        # money flag paints the value green; nothing else in the email does.
        self.assertIn('#166534', html)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PlatformVersusShopIdentityTests(TestCase):
    """Billing mail is RS Systems' voice; job mail is the shop's."""

    def setUp(self):
        mail.outbox = []
        from apps.tenants.models import SubscriptionPlan
        from apps.tenants.services.signup_service import create_tenant_with_owner

        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0,
                      'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Glass Guy Auto Glass', email='owner@glassguy.example',
            password='testpass123!', first_name='Ray', last_name='Duncan',
        )
        self.tenant = result['tenant']
        # branding_enabled is a read-only property gated on the plan
        # (custom_branding, Pro and up), so the tier is what turns the shop's
        # colour on — it is not a field you can set.
        self.tenant.plan = 'pro'
        self.tenant.brand_color = '#b91c1c'
        self.tenant.business_email = 'service@glassguy.example'
        self.tenant.save(update_fields=['plan', 'brand_color', 'business_email'])
        self.assertTrue(
            self.tenant.branding_enabled,
            'test needs a tenant whose plan applies its brand colour',
        )

    def _send(self, **kwargs):
        send_branded_email(
            subject='Payment failed', recipient_list=['owner@example.com'],
            headline='We could not process your payment.',
            body_paragraphs=['Your card was declined.'],
            tenant=self.tenant, **kwargs
        )
        return mail.outbox[-1]

    def test_shop_email_wears_the_shop_brand_colour(self):
        message = self._send()
        html = message.alternatives[0][0]
        self.assertIn('#b91c1c', html)
        self.assertIn('Glass Guy Auto Glass', html)
        self.assertIn('Glass Guy Auto Glass via RS Systems', message.from_email)

    def test_platform_email_never_wears_it(self):
        """An owner must be able to tell who is asking them for money."""
        message = self._send(platform=True)
        html = message.alternatives[0][0]
        self.assertNotIn('#b91c1c', html)
        self.assertIn('RS Systems', html)
        # The shop is still named — on the right of the header, so an owner
        # running two shops can tell which one is in trouble.
        self.assertIn('Glass Guy Auto Glass', html)
        self.assertNotIn('via RS Systems', message.from_email)
        # Replies about a subscription must not land in the shop's inbox.
        self.assertNotIn('service@glassguy.example', message.reply_to or [])
