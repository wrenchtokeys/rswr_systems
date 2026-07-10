"""
Regression tests for A2 (Remediation Plan 2026-07-09):
convert_to_batch double-incremented UnitRepairCount.

Root cause:
    convert_to_batch (apps/technician_portal/views/batch.py) manually ran
    `unit_count.repair_count += 1; unit_count.save()` after creating each
    additional break — and then Repair.save() incremented the counter AGAIN
    when each break transitioned into COMPLETED (whether via the
    mark_completed checkbox in the same request, or later through the normal
    completion flow). Converting 1 repair + 2 breaks on a fresh unit ended
    with repair_count=5 instead of 3, so the next real repair on that unit
    was priced at the $25 floor instead of $30 — permanent, compounding
    underbilling.

    create_multi_break_repair correctly relies on completion-time increments
    only; the two batch flows disagreed.

Fix:
    Delete the manual increment; Repair.save() owns the counter. Batch
    pricing is still computed from the pre-increment count at creation.

Tests:
    A. Convert 1+2 breaks with mark_completed on -> repair_count == 3,
       costs are 50/40/35, and a 4th completed repair prices at $30.
    B. Convert 1+2 breaks WITHOUT mark_completed -> counter unchanged at
       creation; completing all three later yields repair_count == 3.
"""

from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from apps.billing.models import TaxRate
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician, UnitRepairCount
from core.models import Customer


class ConvertToBatchCountTests(TestCase):
    """A2: convert_to_batch must not pre-increment UnitRepairCount."""

    def setUp(self):
        self.client = Client()

        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='A2 Test Shop',
            email='owner_a2@test.com',
            password='testpass123!',
            first_name='AtwoOwner',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='A2 Fleet',
            customer_type='FLEET',
        )
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

    def _make_approved_repair(self, unit_number):
        return Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number=unit_number,
            queue_status='APPROVED',
        )

    def _convert(self, repair, mark_completed=True):
        data = {
            'additional_breaks': '2',
            'damage_type_0': 'Chip',
            'damage_type_1': 'Crack',
            'notes_0': 'break 2',
            'notes_1': 'break 3',
        }
        if mark_completed:
            data['mark_completed'] = 'on'
        response = self.client.post(
            reverse('convert_to_batch', args=[repair.id]), data=data
        )
        self.assertEqual(response.status_code, 302, "convert_to_batch should redirect on success")
        self.assertIn('/batch/', response['Location'], f"unexpected redirect: {response['Location']}")
        return response

    def _unit_count(self, unit_number):
        return UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number=unit_number
        )

    def test_a_convert_with_mark_completed_counts_once(self):
        repair = self._make_approved_repair('UNIT-A2')
        self._convert(repair, mark_completed=True)

        batch_repairs = Repair.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number='UNIT-A2'
        ).order_by('break_number')
        self.assertEqual(batch_repairs.count(), 3)
        self.assertTrue(all(r.queue_status == 'COMPLETED' for r in batch_repairs))

        count = self._unit_count('UNIT-A2')
        self.assertEqual(
            count.repair_count, 3,
            "Counter must equal the number of completed repairs (was double-counted to 5)",
        )

        costs = [r.cost for r in batch_repairs]
        self.assertEqual(
            costs, [Decimal('50.00'), Decimal('40.00'), Decimal('35.00')],
            "Batch breaks must be priced at progressive tiers 1/2/3",
        )

        # A 4th repair on this unit must price as repair #4 ($30), not #6 ($25).
        r4 = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-A2',
            queue_status='COMPLETED',
        )
        self.assertEqual(
            r4.cost, Decimal('30.00'),
            "Next repair must be priced as #4 ($30); $25 means the counter was inflated",
        )
        self.assertEqual(self._unit_count('UNIT-A2').repair_count, 4)

    def test_b_convert_without_mark_completed_counts_on_completion(self):
        repair = self._make_approved_repair('UNIT-A2B')
        self._convert(repair, mark_completed=False)

        # Nothing is COMPLETED yet, so the counter must still be 0.
        count = self._unit_count('UNIT-A2B')
        self.assertEqual(
            count.repair_count, 0,
            "Creating batch breaks must not touch the counter before completion",
        )

        # Complete all three through the normal model flow.
        for r in Repair.objects.filter(
            tenant=self.tenant, customer=self.customer, unit_number='UNIT-A2B'
        ):
            r.queue_status = 'COMPLETED'
            r.save()

        count.refresh_from_db()
        self.assertEqual(count.repair_count, 3)
