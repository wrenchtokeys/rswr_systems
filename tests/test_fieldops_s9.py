"""
Fieldops S9 — "leave it blank" means unscheduled.

Covers docs/strategy/FIELD_OPS_SESSIONS.md §S9.

The bug this locks down was entirely client-side, which is why S1's
server-side tests passed the whole time it was live: `templates/base_app.html`
pre-filled EVERY empty `input[type="datetime-local"]` on EVERY page with the
current time before attaching flatpickr. So `job_form.html`'s own label --
"Optional -- leave blank to keep this job unscheduled" -- could not be
honoured. Unchecking "Job is already done" revealed a field that was already
filled in, and a job nobody scheduled was born with a booking time.

The fix makes the default OPT-IN via `data-default-now`. These tests assert
both halves: the two required "when did the work happen" fields still carry
the attribute, and the three optional `scheduled_for` fields still do not.
"""

import io
import re
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.saas.forms import ReplacementForm
from apps.technician_portal.forms import QuickJobForm, RepairForm
from apps.technician_portal.models import Repair
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

SHELLS = (
    'templates/base_app.html',
    'templates/customer_portal/base_customer.html',
)


def make_shop(business_name, email, services='both'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'),
            'trial_days': 30, 'display_order': 0, 'is_active': True,
        },
    )
    result = create_tenant_with_owner(
        business_name=business_name, email=email, password='testpass123!',
        first_name='Test', last_name='Owner', services_offered=services,
    )
    return result['user'], result['tenant']


def login(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


def read(path):
    return io.open(path, encoding='utf-8').read()


class PrefillIsOptInTests(TestCase):
    """The shells must not default a datetime-local nobody opted in."""

    def test_shells_gate_the_prefill_on_the_attribute(self):
        for path in SHELLS:
            source = read(path)
            self.assertIn(
                'data-default-now', source,
                f'{path} no longer gates its datetime-local prefill; an '
                'unguarded prefill is the S9 bug exactly.',
            )
            # The assignment must sit behind the attribute check, not merely
            # mention it somewhere in a comment.
            guarded = re.search(
                r'if\s*\(\s*!input\.value\s*&&\s*input\.hasAttribute\('
                r'[\'"]data-default-now[\'"]\s*\)\s*\)',
                source,
            )
            self.assertIsNotNone(
                guarded,
                f'{path}: the `input.value = ...` prefill must be guarded by '
                'input.hasAttribute("data-default-now").',
            )

    def test_shells_do_not_pass_defaultdate_to_flatpickr(self):
        # flatpickr's config.defaultDate WINS over the input's own value and
        # writes itself into the field, so `defaultDate: input.value || new
        # Date()` re-creates the bug through the picker even with the prefill
        # guarded. flatpickr already falls back to input.value on its own.
        for path in SHELLS:
            # Match the config key (`defaultDate:`), not the bare word — the
            # comment above the block explains why it was removed and would
            # otherwise fail this test while the code is correct. Asserting on
            # a boolean keeps a failure from dumping the whole shell template.
            configured = re.search(r'defaultDate\s*:', read(path)) is not None
            self.assertFalse(
                configured,
                f'{path}: passing defaultDate re-fills the very inputs this '
                'change exists to leave blank — flatpickr\'s config.defaultDate '
                'wins over the input\'s own value and writes itself into the '
                'field.',
            )

    def test_prefill_runs_before_flatpickr_attaches(self):
        # altInput hides the real input behind a formatted one, so a value
        # assigned after init lands on the hidden field and the visible box
        # still reads empty. Order is load-bearing, not cosmetic.
        for path in SHELLS:
            source = read(path)
            assign = source.index('input.value = `${year}')
            attach = source.index('flatpickr(input, {')
            self.assertLess(
                assign, attach,
                f'{path}: the prefill must run before flatpickr(input, ...).',
            )


@override_settings(**TEST_SETTINGS)
class WhichFieldsOptInTests(TestCase):
    """Required 'when did it happen' opts in; optional 'when will we go' does not."""

    def setUp(self):
        self.user, self.tenant = make_shop('S9 Shop', 's9@test.com')

    def _attrs(self, form, field):
        return form.fields[field].widget.attrs

    def test_repair_date_opts_in(self):
        form = RepairForm(user=self.user, tenant=self.tenant)
        self.assertIn(
            'data-default-now', self._attrs(form, 'repair_date'),
            'repair_date is required and means "when the work happened" — an '
            'empty box should still read as now.',
        )

    def test_repair_form_scheduled_for_does_not_opt_in(self):
        form = RepairForm(user=self.user, tenant=self.tenant)
        self.assertNotIn(
            'data-default-now', self._attrs(form, 'scheduled_for'),
            'scheduled_for is an optional booking time. It shares the '
            'CustomDateTimeInput widget class with repair_date, which is '
            'exactly how it got defaulted in the first place.',
        )

    def test_quick_job_form_scheduled_for_does_not_opt_in(self):
        form = QuickJobForm(tenant=self.tenant)
        self.assertNotIn(
            'data-default-now', self._attrs(form, 'scheduled_for'),
        )

    def test_replacement_form_scheduled_for_does_not_opt_in(self):
        form = ReplacementForm(tenant=self.tenant)
        self.assertNotIn(
            'data-default-now', self._attrs(form, 'scheduled_for'),
        )

    def test_multi_break_repair_date_opts_in(self):
        # Hand-written input, not a Django widget — guard the template.
        source = read('templates/technician_portal/multi_break_repair_form.html')
        block = source[source.index('id="repair_date"'):]
        block = block[:block.index('>')]
        self.assertIn(
            'data-default-now', block,
            'The multi-break form\'s repair_date is required and wants now.',
        )


@override_settings(**TEST_SETTINGS)
class RenderedJobFormTests(TestCase):
    """The page a shop actually opens must ship an un-defaulted booking field."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S9 Render Shop', 's9render@test.com')
        login(self.client, self.user, self.tenant)

    def test_job_form_scheduled_for_has_no_default(self):
        resp = self.client.get(reverse('job_create'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="scheduled_for"', html)
        tag = html[html.index('name="scheduled_for"'):]
        tag = tag[:tag.index('>')]
        self.assertNotIn('data-default-now', tag)
        # And Django must not be rendering a server-side value either.
        self.assertNotIn('value="20', tag)


@override_settings(**TEST_SETTINGS)
class BlankStaysNullTests(TestCase):
    """The behaviour the label promises, end to end."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('S9 Blank Shop', 's9blank@test.com')
        self.customer = Customer.objects.create(
            name='Smith Trucking', tenant=self.tenant, email='s9smith@test.com',
        )
        login(self.client, self.user, self.tenant)

    def test_job_created_without_a_time_is_unscheduled(self):
        resp = self.client.post(reverse('job_create'), {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'T-900',
            'work_done': 'Windshield repair',
            'already_completed': '',
            'scheduled_for': '',
        })
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant)
        self.assertIsNone(
            repair.scheduled_for,
            'A job created with an empty booking field must land in the '
            'unscheduled backlog, not on today at the minute it was typed.',
        )

    def test_a_supplied_time_still_round_trips(self):
        when = timezone.now() + timedelta(days=1)
        resp = self.client.post(reverse('job_create'), {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'T-901',
            'work_done': 'Windshield repair',
            'already_completed': '',
            'scheduled_for': timezone.localtime(when).strftime('%Y-%m-%dT%H:%M'),
        })
        self.assertEqual(resp.status_code, 302)
        repair = Repair.objects.get(tenant=self.tenant, unit_number='T-901')
        self.assertIsNotNone(repair.scheduled_for)
