"""
Features the unified job form lost when it replaced the old repair form.

`technician_portal/repair_form.html` (+ static/js/repair_form.js) grew a set of
behaviours over time: a resin-viscosity suggestion, in-browser photo
compression, a duplicate-job warning. Each was hand-copied per form rather than
shared, so when every "New job" entry point moved to
`technician_portal/job_form.html`, that page inherited the *inputs* and none of
the *behaviour*. The APIs behind all three kept working the whole time, which is
why nothing looked broken.

These tests pin the wiring in place on every form that has the inputs, and pin
the two shared modules that now own the logic so it cannot be copy-pasted apart
again.
"""

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician, ViscosityRecommendation
from core.models import Customer

STATIC = Path(settings.BASE_DIR) / 'static' / 'js'


class JobFormShopMixin:
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0,
                      'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Parity Shop', email='owner@parity.test',
            password='testpass123!', first_name='Pat', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.tenant.services_offered = 'both'
        self.tenant.save()

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def job_form_html(self):
        return self.client.get(reverse('job_create'), {'type': 'repair'}).content.decode()


class ViscositySuggestionParityTests(JobFormShopMixin, TestCase):
    """Every form with a windshield-temperature box asks for the shop's rule."""

    def test_job_form_wires_the_shared_module(self):
        html = self.job_form_html()
        self.assertIn('id="viscositySuggestion"', html)
        self.assertIn('js/viscosity_suggestion.js', html)
        self.assertIn('data-viscosity-input="id_windshield_temperature"', html)
        self.assertIn('/tech/api/viscosity-suggestion/', html)

    def test_multi_break_modal_wires_the_shared_module(self):
        html = self.client.get(reverse('create_multi_break_repair')).content.decode()
        self.assertIn('id="modalViscositySuggestion"', html)
        self.assertIn('js/viscosity_suggestion.js', html)
        self.assertIn('data-viscosity-input="modal_windshield_temperature"', html)

    def test_convert_to_batch_rows_wire_the_shared_module(self):
        """These break cards are built in JS, so the row template carries it."""
        customer = Customer.objects.create(tenant=self.tenant, name='Fleet Co')
        technician = Technician.objects.get(user=self.user, tenant=self.tenant)
        repair = Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=technician,
            unit_number='77', damage_type='CHIP',
        )
        html = self.client.get(
            reverse('convert_to_batch', args=[repair.id])
        ).content.decode()
        self.assertIn('js/viscosity_suggestion.js', html)
        self.assertIn('id="viscositySuggestion_${i}"', html)
        # The temperature input needs an id for the module to bind to it.
        self.assertIn('id="windshield_temperature_${i}"', html)

    def test_repair_form_still_wires_it(self):
        """The old form keeps the feature; it is still the edit-a-repair page."""
        customer = Customer.objects.create(tenant=self.tenant, name='Fleet Co')
        technician = Technician.objects.get(user=self.user, tenant=self.tenant)
        repair = Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=technician,
            unit_number='88', damage_type='CHIP',
        )
        html = self.client.get(
            reverse('update_repair', args=[repair.id])
        ).content.decode()
        self.assertIn('id="viscositySuggestion"', html)
        self.assertIn('js/viscosity_suggestion.js', html)


class ViscosityModuleTests(TestCase):
    """The shared module is the only copy of this logic left."""

    def test_module_exists(self):
        self.assertTrue((STATIC / 'viscosity_suggestion.js').exists())

    def test_shop_authored_text_is_not_rendered_as_html(self):
        """suggestion_text is free text an owner typed; a tech renders it."""
        source = (STATIC / 'viscosity_suggestion.js').read_text()
        self.assertIn('createTextNode', source)
        # Nothing may be *assigned* into innerHTML (the word itself still
        # appears in the comment explaining why).
        self.assertNotRegex(source, r'\.innerHTML\s*=')

    def test_every_badge_color_has_a_tone(self):
        """The old copies stopped at five and rendered orange/purple gray."""
        source = (STATIC / 'viscosity_suggestion.js').read_text()
        for color in ['blue', 'green', 'yellow', 'orange', 'red', 'purple', 'gray']:
            self.assertIn("bg-%s-50" % color, source)

    def test_the_old_per_form_copies_are_gone(self):
        for name in ['repair_form.js', 'multi_break.js']:
            source = (STATIC / name).read_text()
            self.assertNotIn('/tech/api/viscosity-suggestion/', source,
                             '%s still has its own copy of the fetch' % name)

    def test_multi_break_modal_resyncs_the_suggestion(self):
        """One dialog serves every break, so the value moves under the box."""
        source = (STATIC / 'multi_break.js').read_text()
        # Cleared when the modal is reset, refetched when a break is loaded.
        self.assertGreaterEqual(source.count('syncModalViscositySuggestion()'), 3)


class PhotoCompressionParityTests(JobFormShopMixin, TestCase):
    """
    Both photos post in one request against a 10MB nginx/Django cap. The old
    form always resized first; the job form posted raw and died on a 413.
    """

    def test_job_form_photo_inputs_opt_into_compression(self):
        html = self.job_form_html()
        self.assertIn('js/image_compress.js', html)
        self.assertEqual(html.count('data-compress'), 2)
        self.assertIn('id="id_damage_photo_before_preview"', html)
        self.assertIn('id="id_damage_photo_after_preview"', html)

    def test_module_exists_and_stays_under_the_request_cap(self):
        source = (STATIC / 'image_compress.js').read_text()
        self.assertIn('MAX_DIMENSION: 2048', source)
        self.assertIn('QUALITY: 0.85', source)

    def test_the_old_per_form_copies_are_gone(self):
        for name in ['repair_form.js', 'multi_break.js']:
            source = (STATIC / name).read_text()
            self.assertNotIn('const ImageCompressor = {', source,
                             '%s still defines its own compressor' % name)

    def test_forms_that_use_the_compressor_load_it(self):
        """Both legacy forms lost their inline copy — they must load the module."""
        html = self.client.get(reverse('create_multi_break_repair')).content.decode()
        self.assertIn('js/image_compress.js', html)

    def test_the_client_cap_matches_the_server_cap(self):
        source = (STATIC / 'image_compress.js').read_text()
        self.assertIn('10 * 1024 * 1024', source)
        self.assertEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 10 * 1024 * 1024)


class DuplicateJobWarningTests(JobFormShopMixin, TestCase):
    """The check-existing-repair endpoint had no caller on the new form."""

    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(tenant=self.tenant, name='Fleet Co')
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)

    def test_job_form_wires_the_endpoint(self):
        html = self.job_form_html()
        self.assertIn('id="duplicate-job-warning"', html)
        self.assertIn(reverse('check_existing_repair'), html)

    def test_endpoint_reports_an_open_job_on_the_same_unit(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='4021', damage_type='CHIP', queue_status='IN_PROGRESS',
        )
        data = self.client.get(
            reverse('check_existing_repair'),
            {'customer': self.customer.id, 'unit_number': '4021'},
        ).json()
        self.assertTrue(data['existing_repair'])
        self.assertEqual(data['repair_id'], repair.id)

    def test_a_different_unit_is_not_flagged(self):
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='4021', damage_type='CHIP', queue_status='IN_PROGRESS',
        )
        data = self.client.get(
            reverse('check_existing_repair'),
            {'customer': self.customer.id, 'unit_number': '4022'},
        ).json()
        self.assertFalse(data['existing_repair'])

    def test_another_shops_job_is_never_flagged(self):
        other = create_tenant_with_owner(
            business_name='Other Shop', email='owner@otherparity.test',
            password='testpass123!', first_name='Odie', last_name='Owner',
        )['tenant']
        other_customer = Customer.objects.create(tenant=other, name='Fleet Co')
        other_tech = Technician.objects.filter(tenant=other).first()
        Repair.objects.create(
            tenant=other, customer=other_customer, technician=other_tech,
            unit_number='4021', damage_type='CHIP', queue_status='IN_PROGRESS',
        )
        data = self.client.get(
            reverse('check_existing_repair'),
            {'customer': other_customer.id, 'unit_number': '4021'},
        ).json()
        self.assertFalse(data['existing_repair'])
