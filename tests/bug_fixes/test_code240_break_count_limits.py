"""
CODE-240: Unbounded break_count in batch repair creation

Both the customer portal (handle_batch_repair_request) and technician portal
(create_multi_break_repair, convert_to_batch) accepted arbitrary break_count
values from user-submitted POST data without any upper bound.  A malicious
request with breakCount=10000 would create 10,000 Repair rows in a single
atomic transaction — exhausting DB connections and disk.

Fix: Cap break count to 20 per unit and units per request to 50 in the
customer portal batch handler; cap breaks_count to 20 in the technician
portal batch creation and convert_to_batch views.
"""

import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser


def _add_messages(request):
    """Attach messages middleware to a RequestFactory-built request."""
    setattr(request, 'session', 'session')
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)
    return request


class BreakCountLimitsTestBase(TestCase):
    """Shared setup for break-count limit tests."""

    @classmethod
    def setUpTestData(cls):
        cls.owner_user = User.objects.create_user(
            username='owner240', password='pass', email='owner240@test.com',
            first_name='Owner', last_name='Test',
        )
        cls.tenant = Tenant.objects.create(
            name='Test Shop 240',
            slug='test-shop-240',
            is_active=True,
            owner=cls.owner_user,
        )
        TenantMembership.objects.create(
            user=cls.owner_user, tenant=cls.tenant, role='owner', is_active=True,
        )
        cls.tech_user = User.objects.create_user(
            username='tech240', password='pass', email='tech240@test.com',
            first_name='Tech', last_name='Test',
        )
        TenantMembership.objects.create(
            user=cls.tech_user, tenant=cls.tenant, role='technician', is_active=True,
        )
        cls.technician = Technician.objects.create(
            user=cls.tech_user, tenant=cls.tenant, is_active=True,
            can_repair=True,
        )
        cls.customer = Customer.objects.create(
            name='Fleet 240', tenant=cls.tenant,
        )
        cls.cust_user_django = User.objects.create_user(
            username='cust240', password='pass', email='cust240@test.com',
        )
        TenantMembership.objects.create(
            user=cls.cust_user_django, tenant=cls.tenant, role='viewer', is_active=True,
        )
        cls.customer_user = CustomerUser.objects.create(
            user=cls.cust_user_django, customer=cls.customer,
        )
        cls.factory = RequestFactory()


class TestCustomerBatchBreakCountCap(BreakCountLimitsTestBase):
    """Customer portal: handle_batch_repair_request caps break count."""

    def _call_view(self, units_data):
        from apps.customer_portal.views import handle_batch_repair_request
        from urllib.parse import urlencode
        body = urlencode({'units_data': json.dumps(units_data)})
        request = self.factory.post(
            '/', data=body, content_type='application/x-www-form-urlencoded',
        )
        request.user = self.cust_user_django
        request.tenant = self.tenant
        # Override content_type so the view takes the form (not AJAX) path
        request.content_type = 'application/x-www-form-urlencoded'
        _add_messages(request)
        return handle_batch_repair_request(request, self.customer, self.customer_user)

    @patch('apps.tenants.services.assignment_service.auto_assign_repair', return_value=None)
    @patch('apps.customer_portal.views.get_available_technician')
    def test_break_count_capped_at_20(self, mock_get_tech, _mock_assign):
        """Submitting breakCount=100 should only create 20 repairs, not 100."""
        mock_get_tech.return_value = self.technician
        units_data = [{
            'unitNumber': 'UNIT-CAP-100',
            'damageType': 'Chip',
            'notes': '',
            'hasPhoto': False,
            'hasMultipleBreaks': True,
            'breakCount': 100,
        }]
        self._call_view(units_data)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='UNIT-CAP-100',
        )
        self.assertLessEqual(repairs.count(), 20,
                             "Break count must be capped at 20 per unit (CODE-240)")
        self.assertGreater(repairs.count(), 0,
                           "Capped break count should still create repairs")

    @patch('apps.tenants.services.assignment_service.auto_assign_repair', return_value=None)
    @patch('apps.customer_portal.views.get_available_technician')
    def test_break_count_exactly_20_allowed(self, mock_get_tech, _mock_assign):
        """breakCount=20 is the maximum and should work."""
        mock_get_tech.return_value = self.technician
        units_data = [{
            'unitNumber': 'UNIT-EXACT-20',
            'damageType': 'Chip',
            'notes': '',
            'hasPhoto': False,
            'hasMultipleBreaks': True,
            'breakCount': 20,
        }]
        self._call_view(units_data)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='UNIT-EXACT-20',
        )
        self.assertEqual(repairs.count(), 20)

    @patch('apps.tenants.services.assignment_service.auto_assign_repair', return_value=None)
    @patch('apps.customer_portal.views.get_available_technician')
    def test_break_count_within_limit_works_normally(self, mock_get_tech, _mock_assign):
        """breakCount=5 should create exactly 5 repairs."""
        mock_get_tech.return_value = self.technician
        units_data = [{
            'unitNumber': 'UNIT-NORMAL-5',
            'damageType': 'Chip',
            'notes': '',
            'hasPhoto': False,
            'hasMultipleBreaks': True,
            'breakCount': 5,
        }]
        self._call_view(units_data)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='UNIT-NORMAL-5',
        )
        self.assertEqual(repairs.count(), 5)

    def test_too_many_units_rejected(self):
        """Submitting > 50 units should be rejected outright."""
        units_data = [
            {'unitNumber': f'UNIT-{i}', 'damageType': 'Chip', 'notes': '',
             'hasPhoto': False, 'hasMultipleBreaks': False, 'breakCount': None}
            for i in range(51)
        ]
        response = self._call_view(units_data)
        repair_count = Repair.objects.filter(customer=self.customer).count()
        self.assertEqual(repair_count, 0,
                         "Submitting > 50 units must be rejected, no repairs created (CODE-240)")

    @patch('apps.tenants.services.assignment_service.auto_assign_repair', return_value=None)
    @patch('apps.customer_portal.views.get_available_technician')
    def test_50_units_accepted(self, mock_get_tech, _mock_assign):
        """Exactly 50 units should be accepted."""
        mock_get_tech.return_value = self.technician
        units_data = [
            {'unitNumber': f'UNIT50-{i}', 'damageType': 'Chip', 'notes': '',
             'hasPhoto': False, 'hasMultipleBreaks': False, 'breakCount': None}
            for i in range(50)
        ]
        self._call_view(units_data)
        repair_count = Repair.objects.filter(
            customer=self.customer,
            unit_number__startswith='UNIT50-',
        ).count()
        self.assertEqual(repair_count, 50)

    def test_negative_break_count_treated_as_single(self):
        """Negative breakCount should be treated as None (single repair path)."""
        units_data = [{
            'unitNumber': 'UNIT-NEG',
            'damageType': 'Chip',
            'notes': '',
            'hasPhoto': False,
            'hasMultipleBreaks': True,
            'breakCount': -5,
        }]
        self._call_view(units_data)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='UNIT-NEG',
        )
        self.assertLessEqual(repairs.count(), 1,
                             "Negative break count must not create multiple repairs (CODE-240)")

    def test_non_numeric_break_count_handled(self):
        """Non-numeric breakCount should not crash."""
        units_data = [{
            'unitNumber': 'UNIT-NAN',
            'damageType': 'Chip',
            'notes': '',
            'hasPhoto': False,
            'hasMultipleBreaks': True,
            'breakCount': 'abc',
        }]
        self._call_view(units_data)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='UNIT-NAN',
        )
        self.assertLessEqual(repairs.count(), 1,
                             "Non-numeric break count must be handled gracefully (CODE-240)")


class TestTechBatchBreakCountCap(BreakCountLimitsTestBase):
    """Technician portal: create_multi_break_repair caps breaks_count."""

    def _make_request(self, data):
        from apps.technician_portal.views.batch import create_multi_break_repair
        request = self.factory.post('/', data=data)
        request.user = self.tech_user
        request.tenant = self.tenant
        _add_messages(request)
        # Add XMLHttpRequest header for JSON response path
        request.META['HTTP_X_REQUESTED_WITH'] = 'XMLHttpRequest'
        return request

    def test_breaks_count_over_limit_rejected(self):
        """POST with breaks_count=25 should be rejected."""
        from apps.technician_portal.views.batch import create_multi_break_repair
        request = self._make_request({
            'customer': str(self.customer.id),
            'unit_number': 'TECH-OVER-25',
            'repair_date': '2026-03-30',
            'breaks_count': '25',
        })
        response = create_multi_break_repair(request)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='TECH-OVER-25',
        )
        self.assertEqual(repairs.count(), 0,
                         "breaks_count > 20 must be rejected outright in tech portal (CODE-240)")

    def test_breaks_count_at_limit_accepted(self):
        """POST with breaks_count=20 should be accepted (boundary)."""
        from apps.technician_portal.views.batch import create_multi_break_repair
        data = {
            'customer': str(self.customer.id),
            'unit_number': 'TECH-LIMIT-20',
            'repair_date': '2026-03-30',
            'breaks_count': '20',
        }
        # Add per-break fields
        for i in range(20):
            data[f'breaks[{i}][damage_type]'] = 'Chip'
            data[f'breaks[{i}][notes]'] = ''
        request = self._make_request(data)
        response = create_multi_break_repair(request)
        repairs = Repair.objects.filter(
            customer=self.customer, unit_number='TECH-LIMIT-20',
        )
        self.assertEqual(repairs.count(), 20,
                         "breaks_count=20 at the limit should create 20 repairs")


class TestConvertToBatchBreakCap(BreakCountLimitsTestBase):
    """Technician portal: convert_to_batch caps additional_breaks."""

    def test_additional_breaks_over_limit_rejected(self):
        """POST with additional_breaks=25 should be rejected."""
        repair = Repair.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='CONV-OVER',
            damage_type='Chip',
            queue_status='APPROVED',
        )
        from apps.technician_portal.views.batch import convert_to_batch
        request = self.factory.post('/', data={'additional_breaks': '25'})
        request.user = self.tech_user
        request.tenant = self.tenant
        _add_messages(request)
        response = convert_to_batch(request, repair.id)
        repair.refresh_from_db()
        self.assertIsNone(repair.repair_batch_id,
                          "additional_breaks > 19 must be rejected (CODE-240)")

    def test_additional_breaks_at_limit_accepted(self):
        """POST with additional_breaks=19 should work (total 20 = 1 + 19)."""
        repair = Repair.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='CONV-LIMIT',
            damage_type='Chip',
            queue_status='APPROVED',
        )
        from apps.technician_portal.views.batch import convert_to_batch
        data = {'additional_breaks': '19'}
        for i in range(19):
            data[f'damage_type_{i}'] = 'Chip'
        request = self.factory.post('/', data=data)
        request.user = self.tech_user
        request.tenant = self.tenant
        _add_messages(request)
        response = convert_to_batch(request, repair.id)
        repair.refresh_from_db()
        self.assertIsNotNone(repair.repair_batch_id,
                             "additional_breaks=19 at limit should create batch")
        batch_count = Repair.objects.filter(
            repair_batch_id=repair.repair_batch_id,
        ).count()
        self.assertEqual(batch_count, 20, "1 original + 19 additional = 20 total")

    def test_additional_breaks_2_works(self):
        """POST with additional_breaks=2 should work (total 3)."""
        repair = Repair.objects.create(
            tenant=self.tenant,
            technician=self.technician,
            customer=self.customer,
            unit_number='CONV-OK',
            damage_type='Chip',
            queue_status='APPROVED',
        )
        from apps.technician_portal.views.batch import convert_to_batch
        request = self.factory.post('/', data={
            'additional_breaks': '2',
            'damage_type_0': 'Chip',
            'damage_type_1': 'Chip',
        })
        request.user = self.tech_user
        request.tenant = self.tenant
        _add_messages(request)
        response = convert_to_batch(request, repair.id)
        repair.refresh_from_db()
        self.assertIsNotNone(repair.repair_batch_id,
                             "additional_breaks=2 within limit should create batch")
        batch_count = Repair.objects.filter(
            repair_batch_id=repair.repair_batch_id,
        ).count()
        self.assertEqual(batch_count, 3, "1 original + 2 additional = 3 total")
