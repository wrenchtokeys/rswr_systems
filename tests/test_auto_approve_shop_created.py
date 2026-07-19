"""
Tests for auto-approval of shop-created repairs and replacements.

Shop-created work (entered as PENDING) auto-approves via
resolve_initial_shop_status unless the customer's CustomerRepairPreference
explicitly requires approval. Customer-portal requests enter as REQUESTED
and are unaffected.
"""

from decimal import Decimal

from django.test import TestCase

from apps.customer_portal.models import CustomerRepairPreference
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer, Notification


def make_tenant_with_owner(email='approveowner@test.com', first_name='App'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name='Approve Test Shop', email=email,
        password='testpass123!', first_name=first_name, last_name='Owner',
    )


class AutoApproveBase(TestCase):
    def setUp(self):
        result = make_tenant_with_owner()
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(tenant=self.tenant, user=self.user)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', email='fleet@test.com',
        )

    def make_repair(self, status='PENDING', **kwargs):
        defaults = dict(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='U-1',
            damage_type='chip',
            queue_status=status,
        )
        defaults.update(kwargs)
        return Repair.objects.create(**defaults)

    def make_replacement(self, status='PENDING', **kwargs):
        defaults = dict(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='R-1',
            glass_position='WINDSHIELD',
            parts_cost=Decimal('250.00'),
            labor_cost=Decimal('150.00'),
            queue_status=status,
        )
        defaults.update(kwargs)
        return Replacement.objects.create(**defaults)


class ShopCreatedAutoApproveTests(AutoApproveBase):
    def test_repair_auto_approves_without_preferences(self):
        repair = self.make_repair()
        self.assertEqual(repair.queue_status, 'APPROVED')

    def test_replacement_auto_approves_without_preferences(self):
        replacement = self.make_replacement()
        self.assertEqual(replacement.queue_status, 'APPROVED')

    def test_no_pending_approval_notification_sent(self):
        self.make_repair()
        self.assertFalse(
            Notification.objects.filter(
                template__name='repair_pending_approval').exists()
        )

    def test_technician_still_notified_of_assignment(self):
        self.make_repair()
        self.assertTrue(
            Notification.objects.filter(
                template__name='repair_assigned').exists()
        )

    def test_default_preference_row_auto_approves(self):
        # New rows get the flipped AUTO_APPROVE default
        prefs = CustomerRepairPreference.objects.create(customer=self.customer)
        self.assertEqual(prefs.field_repair_approval_mode, 'AUTO_APPROVE')
        repair = self.make_repair()
        self.assertEqual(repair.queue_status, 'APPROVED')


class ExplicitRequireApprovalTests(AutoApproveBase):
    def setUp(self):
        super().setUp()
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )

    def test_repair_stays_pending(self):
        repair = self.make_repair()
        self.assertEqual(repair.queue_status, 'PENDING')

    def test_replacement_stays_pending(self):
        replacement = self.make_replacement()
        self.assertEqual(replacement.queue_status, 'PENDING')

    def test_pending_approval_notification_sent(self):
        self.make_repair()
        self.assertTrue(
            Notification.objects.filter(
                template__name='repair_pending_approval').exists()
        )

    def test_pending_to_approved_transition_still_works(self):
        repair = self.make_repair()
        repair.queue_status = 'APPROVED'
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')


class UnitThresholdTests(AutoApproveBase):
    def setUp(self):
        super().setUp()
        CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='UNIT_THRESHOLD',
            units_per_visit_threshold=1,
        )

    def test_over_threshold_stays_pending(self):
        # Pin service_date to midday UTC so .date() and the __date lookup
        # (local time) agree regardless of when the test runs
        from datetime import datetime, timezone as dt_tz
        visit = datetime(2026, 7, 15, 18, 0, tzinfo=dt_tz.utc)
        first = self.make_repair(unit_number='U-1', service_date=visit)
        self.assertEqual(first.queue_status, 'APPROVED')
        second = self.make_repair(unit_number='U-2', service_date=visit)
        self.assertEqual(second.queue_status, 'PENDING')


class CustomerRequestedWorkUnaffectedTests(AutoApproveBase):
    def test_requested_repair_stays_requested(self):
        repair = self.make_repair(status='REQUESTED')
        self.assertEqual(repair.queue_status, 'REQUESTED')

    def test_requested_replacement_stays_requested(self):
        replacement = self.make_replacement(status='REQUESTED')
        self.assertEqual(replacement.queue_status, 'REQUESTED')

    def test_requested_to_pending_transition_survives(self):
        # Shop accepting a portal request moves it to PENDING and it stays
        # there (the auto-approve gate only applies on create)
        repair = self.make_repair(status='REQUESTED')
        repair.queue_status = 'PENDING'
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'PENDING')


class OwnerReplacementCreateViewTests(AutoApproveBase):
    def test_owner_created_replacement_is_approved(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        resp = self.client.post('/tech/replacement/new/', {
            'customer': self.customer.id,
            'technician': self.technician.id,
            'unit_number': 'R-9',
            'glass_position': 'WINDSHIELD',
            'parts_cost': '250.00',
            'labor_cost': '150.00',
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, 'context', None) and resp.context.get('form') and resp.context['form'].errors)
        replacement = Replacement.objects.get(unit_number='R-9')
        self.assertEqual(replacement.queue_status, 'APPROVED')
