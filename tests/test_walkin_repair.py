"""Tests for the new-individual repair creation toggle.

Rewritten for the fleet/individual separation: inline-created individuals are
RETAIL, duplicate names get a suggest-the-existing-record flow (never a
silent "John Walkin (2)" suffix, never a hard error), and a confirmed
resubmit may create a second person with the same name.
"""
from django.test import TestCase
from django.urls import reverse

from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants.models import SubscriptionPlan
from apps.technician_portal.models import Repair
from core.models import Customer


class WalkInRepairTests(TestCase):
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Walk-in Shop', email='owner@walkin.com',
            password='testpass123!', first_name='Wally', last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _base_post(self, **overrides):
        from apps.technician_portal.models import Technician
        tech = Technician.objects.filter(tenant=self.tenant).first()
        data = {
            'is_walkin': 'on',
            'walkin_name': 'John Walkin',
            'walkin_phone': '5551234567',
            'vehicle_year': '2019',
            'vehicle_make': 'Ford',
            'vehicle_model': 'F-150',
            'repair_date': '2026-07-25T10:00',
            'queue_status': 'PENDING',
            'technician': tech.id,
        }
        data.update(overrides)
        return data

    def _individuals(self):
        return Customer.objects.filter(
            tenant=self.tenant, customer_type__in=['RETAIL', 'WALK_IN'])

    def test_walkin_creates_individual_and_auto_approves(self):
        resp = self.client.post(reverse('create_repair'), self._base_post())
        self.assertIn(resp.status_code, (302, 200), msg=resp.content[:500])

        cust = self._individuals().first()
        self.assertIsNotNone(cust, "Individual customer should have been created")
        self.assertEqual(cust.customer_type, 'RETAIL')
        self.assertEqual(cust.name, 'John Walkin')
        self.assertEqual(cust.phone, '5551234567')

        repair = Repair.objects.filter(tenant=self.tenant, customer=cust).first()
        self.assertIsNotNone(repair, "Repair should have been created")
        self.assertEqual(repair.queue_status, 'APPROVED', "Walk-in repair should auto-approve")
        self.assertEqual(repair.vehicle_make, 'Ford')
        self.assertEqual(repair.vehicle_model, 'F-150')

    def test_walkin_captures_email(self):
        self.client.post(reverse('create_repair'),
                         self._base_post(walkin_email='john@walkin.test'))
        cust = self._individuals().first()
        self.assertEqual(cust.email, 'john@walkin.test')

    def test_walkin_requires_name(self):
        data = self._base_post(walkin_name='')
        self.client.post(reverse('create_repair'), data)
        self.assertFalse(Repair.objects.filter(tenant=self.tenant).exists())

    def test_duplicate_name_suggests_existing_instead_of_creating(self):
        self.client.post(reverse('create_repair'), self._base_post())
        resp = self.client.post(reverse('create_repair'), self._base_post())

        # Second submit is intercepted: no new customer, no second repair
        self.assertEqual(self._individuals().count(), 1)
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 1)
        self.assertContains(resp, 'already a customer')

    def test_confirmed_duplicate_creates_second_person_same_name(self):
        self.client.post(reverse('create_repair'), self._base_post())
        self.client.post(reverse('create_repair'),
                         self._base_post(confirmed_new_customer='on'))

        walkins = self._individuals()
        self.assertEqual(walkins.count(), 2, "Two distinct individuals expected")
        names = list(walkins.values_list('name', flat=True))
        # People share names — no "(2)" suffix hack anymore
        self.assertEqual(names, ['John Walkin', 'John Walkin'])
        self.assertEqual(Repair.objects.filter(tenant=self.tenant).count(), 2)

    def test_normal_customer_still_required_without_walkin(self):
        data = self._base_post(is_walkin='', walkin_name='', walkin_phone='')
        self.client.post(reverse('create_repair'), data)
        self.assertFalse(
            Repair.objects.filter(tenant=self.tenant).exists(),
            "Repair should not be created without a customer when not a walk-in",
        )
