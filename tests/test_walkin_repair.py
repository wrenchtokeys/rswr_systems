"""Tests for the walk-in / individual repair creation toggle."""
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

    def test_walkin_creates_customer_and_auto_approves(self):
        resp = self.client.post(reverse('create_repair'), self._base_post())
        self.assertIn(resp.status_code, (302, 200), msg=resp.content[:500])

        cust = Customer.objects.filter(tenant=self.tenant, customer_type='WALK_IN').first()
        self.assertIsNotNone(cust, "Walk-in customer should have been created")
        self.assertEqual(cust.name, 'John Walkin')
        self.assertEqual(cust.phone, '5551234567')

        repair = Repair.objects.filter(tenant=self.tenant, customer=cust).first()
        self.assertIsNotNone(repair, "Repair should have been created")
        self.assertEqual(repair.queue_status, 'APPROVED', "Walk-in repair should auto-approve")
        self.assertEqual(repair.vehicle_make, 'Ford')
        self.assertEqual(repair.vehicle_model, 'F-150')

    def test_walkin_requires_name(self):
        data = self._base_post(walkin_name='')
        resp = self.client.post(reverse('create_repair'), data)
        # Form invalid -> re-render, no repair created
        self.assertFalse(Repair.objects.filter(tenant=self.tenant).exists())

    def test_duplicate_walkin_names_get_unique_suffix(self):
        self.client.post(reverse('create_repair'), self._base_post())
        self.client.post(reverse('create_repair'), self._base_post())
        walkins = Customer.objects.filter(tenant=self.tenant, customer_type='WALK_IN')
        self.assertEqual(walkins.count(), 2, "Two distinct walk-in customers expected")
        names = set(walkins.values_list('name', flat=True))
        self.assertIn('John Walkin', names)
        self.assertIn('John Walkin (2)', names)

    def test_normal_customer_still_required_without_walkin(self):
        data = self._base_post(is_walkin='', walkin_name='', walkin_phone='')
        resp = self.client.post(reverse('create_repair'), data)
        self.assertFalse(
            Repair.objects.filter(tenant=self.tenant).exists(),
            "Repair should not be created without a customer when not a walk-in",
        )
