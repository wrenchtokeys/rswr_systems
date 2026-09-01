"""
Regression tests for CODE-282 — editing an individual's repair was impossible.

Field report: "Created individual ticket and then went to edit for new photo.
Car type became unit number, many errors flagged when I tried to save."

Two root causes, one page:

1. update_repair's context omitted customer_types_json /
   customer_primary_tech_json, which repair_form.html interpolates directly
   into `const customerTypes = ...;`. The missing key rendered a JS
   SyntaxError that killed the whole script block, so the fleet/individual
   field toggle never ran: the individual's vehicle text sat under a
   fleet-styled "Unit Number *" label and the vehicle fields (with their
   errors) stayed hidden.

2. RepairForm.clean() demanded vehicle make+model for every non-FLEET
   customer with empty year/make/model — but a quick-job-created
   individual's vehicle legitimately lives as free text in unit_number
   (Repair.get_vehicle_identifier falls back to it), so every edit-save was
   rejected on fields the page wasn't even showing. Adding a photo goes
   through this same full edit form.
"""

import json

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.forms import RepairForm
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


def make_shop(business_name, email):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name='Test', last_name='Owner',
    )
    return result['user'], result['tenant']


class IndividualRepairEditTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Edit Fix Shop', 'editfix@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Jane Driver', customer_type='RETAIL',
        )
        # Shape a quick-job individual repair: vehicle as free text in
        # unit_number, no structured vehicle fields.
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Silver Camry', queue_status='COMPLETED',
            service_date=timezone.now(),
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_edit_page_has_customer_types_json(self):
        """The context the field-toggle script needs must be present on edit,
        not just create — its absence rendered `const customerTypes = ;`."""
        response = self.client.get(reverse('update_repair', args=[self.repair.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('customer_types_json', response.context)
        types = json.loads(response.context['customer_types_json'])
        self.assertEqual(types[str(self.customer.id)], 'RETAIL')
        self.assertIn('customer_primary_tech_json', response.context)
        self.assertNotContains(response, 'const customerTypes = ;')

    def test_edit_page_shows_vehicle_label_not_unit_number(self):
        """An individual whose vehicle lives in unit_number sees that input
        server-rendered as "Vehicle", visible without JS."""
        response = self.client.get(reverse('update_repair', args=[self.repair.id]))
        self.assertTrue(response.context['customer_is_individual'])
        self.assertTrue(response.context['repair_vehicle_in_unit'])
        self.assertContains(response, '<span id="unit-label-text">Vehicle</span>', html=True)

    def test_fleet_edit_page_keeps_unit_number_label(self):
        fleet = Customer.objects.create(
            tenant=self.tenant, name='Penske', customer_type='FLEET',
        )
        repair = Repair.objects.create(
            tenant=self.tenant, customer=fleet, technician=self.tech,
            unit_number='TRUCK-7', queue_status='COMPLETED',
            service_date=timezone.now(),
        )
        response = self.client.get(reverse('update_repair', args=[repair.id]))
        self.assertFalse(response.context['customer_is_individual'])
        self.assertContains(response, '<span id="unit-label-text">Unit Number</span>', html=True)

    def test_edit_save_succeeds_with_vehicle_in_unit_number(self):
        """The field-reported failure: re-saving an individual's quick-job
        repair (e.g. to add a photo) must not demand vehicle make/model."""
        response = self.client.post(
            reverse('update_repair', args=[self.repair.id]),
            data={
                'customer': self.customer.id,
                'technician': self.tech.id,
                'unit_number': 'Silver Camry',
                'queue_status': 'COMPLETED',
                'repair_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
                'technician_notes': 'added after-photo',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.unit_number, 'Silver Camry')
        self.assertEqual(self.repair.get_vehicle_identifier(), 'Silver Camry')
        self.assertEqual(self.repair.technician_notes, 'added after-photo')

    def test_individual_with_no_vehicle_at_all_still_errors(self):
        """Relaxing the rule must not drop it: an individual repair with no
        vehicle info anywhere is still invalid."""
        form = RepairForm(
            data={
                'customer': self.customer.id,
                'technician': self.tech.id,
                'unit_number': '',
                'queue_status': 'APPROVED',
                'repair_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
            },
            instance=self.repair, user=self.user, tenant=self.tenant,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('vehicle_make', form.errors)
        self.assertIn('vehicle_model', form.errors)

    def test_fleet_still_requires_unit_number(self):
        fleet = Customer.objects.create(
            tenant=self.tenant, name='Penske', customer_type='FLEET',
        )
        form = RepairForm(
            data={
                'customer': fleet.id,
                'technician': self.tech.id,
                'unit_number': '',
                'queue_status': 'APPROVED',
                'repair_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
            },
            user=self.user, tenant=self.tenant,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('unit_number', form.errors)
