"""
One door for creating a job.

There used to be five: /tech/jobs/new/ (quick), /tech/repairs/create/ (full
repair), the full replacement form, the multi-break form, and convert-to-batch.
A tech had to pick one before knowing what the job was, and the quick form
carried "Full repair form" / "Full replacement form" escape hatches for the
fields it lacked — click one and everything typed so far was gone.

The per-type forms still exist and still back the edit flows; the UI simply
stopped asking anyone to choose. /tech/jobs/new/ now carries the optional
fields behind a "More details" disclosure.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class UnifiedJobCreateTests(TestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user('owner_ujc', password='pw', email='owner@ujc.test')
        self.shop = Tenant.objects.create(
            name='Unified Shop', slug='unified-shop', plan='trial',
            is_active=True, owner=self.owner_user,
            # offers_repairs/offers_replacements are properties derived from this.
            services_offered='both',
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')
        self.owner_tech = Technician.objects.create(
            tenant=self.shop, user=self.owner_user,
            is_active=True, is_manager=True, can_repair=True, can_replace=True,
        )
        self.mate_user = User.objects.create_user('mate_ujc', password='pw', email='mate@ujc.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.mate_user, role='technician')
        self.mate = Technician.objects.create(
            tenant=self.shop, user=self.mate_user,
            is_active=True, is_manager=False, can_repair=True, can_replace=True,
        )
        self.customer = Customer.objects.create(tenant=self.shop, name='Unified Fleet')

        self.client = Client()
        self.client.force_login(self.owner_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def _post(self, **overrides):
        payload = {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-900',
            'work_done': 'Chip repair',
            'price': '55.00',
        }
        payload.update(overrides)
        return self.client.post(reverse('job_create'), payload)

    # --- the advanced fields actually persist ------------------------------

    def test_repair_accepts_advanced_fields(self):
        self._post(
            vehicle_year='2019', vehicle_make='Toyota', vehicle_model='Camry',
            windshield_temperature='72.5', resin_viscosity='Medium',
            drilled_before_repair='on',
            insurance_claim='on', insurance_company='Acme Mutual',
            claim_number='CLM-1', deductible='100.00',
            customer_notes='Park round the back',
        )
        repair = Repair.objects.get(tenant=self.shop, unit_number='U-900')
        self.assertEqual(repair.vehicle_year, 2019)
        self.assertEqual(repair.vehicle_make, 'Toyota')
        self.assertEqual(repair.vehicle_model, 'Camry')
        self.assertEqual(repair.windshield_temperature, Decimal('72.5'))
        self.assertEqual(repair.resin_viscosity, 'Medium')
        self.assertTrue(repair.drilled_before_repair)
        self.assertTrue(repair.insurance_claim)
        self.assertEqual(repair.insurance_company, 'Acme Mutual')
        self.assertEqual(repair.claim_number, 'CLM-1')
        self.assertEqual(repair.deductible, Decimal('100.00'))
        self.assertEqual(repair.customer_notes, 'Park round the back')

    def test_replacement_accepts_adas_fields(self):
        self._post(
            service_type='replacement', unit_number='U-901',
            requires_adas_calibration='on', adas_calibration_cost='250.00',
        )
        replacement = Replacement.objects.get(tenant=self.shop, unit_number='U-901')
        self.assertTrue(replacement.requires_adas_calibration)
        self.assertEqual(replacement.adas_calibration_cost, Decimal('250.00'))

    def test_explicit_technician_wins_over_auto_assignment(self):
        self._post(technician=self.mate.id)
        repair = Repair.objects.get(tenant=self.shop, unit_number='U-900')
        self.assertEqual(repair.technician_id, self.mate.id)

    def test_blank_technician_still_auto_assigns(self):
        self._post(technician='')
        repair = Repair.objects.get(tenant=self.shop, unit_number='U-900')
        self.assertIsNotNone(repair.technician_id)

    def test_technician_dropdown_is_tenant_scoped(self):
        """A tech from another shop must never be assignable here."""
        rival_user = User.objects.create_user('rival_ujc', password='pw', email='rival@ujc.test')
        rival = Tenant.objects.create(
            name='Rival', slug='rival-ujc', plan='trial',
            is_active=True, owner=rival_user,
        )
        rival_tech = Technician.objects.create(
            tenant=rival, user=rival_user, is_active=True, can_repair=True,
        )
        response = self.client.get(reverse('job_create'))
        choices = response.context['form'].fields['technician'].queryset
        self.assertIn(self.mate, choices)
        self.assertNotIn(rival_tech, choices)

    # --- the escape hatches are gone --------------------------------------

    def test_form_no_longer_sends_users_to_a_different_form(self):
        response = self.client.get(reverse('job_create'))
        content = response.content.decode()
        self.assertNotIn('Full repair form', content)
        self.assertNotIn('Full replacement form', content)

    def test_form_posts_multipart_so_photos_can_be_attached(self):
        response = self.client.get(reverse('job_create'))
        self.assertContains(response, 'enctype="multipart/form-data"')

    def test_advanced_panel_opens_when_it_holds_the_error(self):
        """An error hidden inside a collapsed <details> reads as no error."""
        response = self._post(vehicle_year='1200')  # below the min
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['advanced_has_errors'])

    def test_advanced_panel_stays_shut_for_errors_outside_it(self):
        response = self._post(customer='', new_customer_name='')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['advanced_has_errors'])
