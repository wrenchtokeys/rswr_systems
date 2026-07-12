"""
Regression tests for A1 (Remediation Plan 2026-07-09):
Completed repairs were silently re-priced on any re-save.

Root cause:
    In Repair.save(), the first-transition guard
    (`if not self.pk or (self.pk and self.original_status != 'COMPLETED')`)
    protected only the UnitRepairCount increment. The cost recalculation below
    it ran on EVERY save of an already-COMPLETED repair, so re-saving repair #1
    of a unit with 3 completed repairs recomputed its cost at the CURRENT
    repair_count tier (e.g. $50 -> $35), silently diverging from the invoice
    line item already sent to the customer.

    Trigger paths: the edit form (update_repair view calls a full save()),
    a COMPLETED->COMPLETED status post, and the Django admin.

Fix:
    Price a repair exactly once, on the transition into COMPLETED. The pricing
    block is now guarded by the same first-completion check as the increment.
    cost_override still applies on any save (owners must be able to correct a
    price after completion).

Tests:
    A. Model-level re-save of an already-COMPLETED repair does not change cost
       and does not touch UnitRepairCount.
    B. The edit view (update_repair POST) does not change cost either.
    C. cost_override applies even on a re-save of a COMPLETED repair.
    D. First completion still prices correctly (progressive tiers intact).
"""

from datetime import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import TaxRate
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician, UnitRepairCount
from core.models import Customer


class NoRepricingOnResaveTests(TestCase):
    """A1: a COMPLETED repair must never be re-priced by a subsequent save()."""

    def setUp(self):
        self.client = Client()

        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='A1 Test Shop',
            email='owner_a1@test.com',
            password='testpass123!',
            first_name='AoneOwner',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        # Fleet customer -> progressive pricing applies
        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='A1 Fleet',
            customer_type='FLEET',
        )

        # Tax must be configured or TaxService silently sets 0 (per CLAUDE.md)
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

    def _complete_repair(self, unit_number='UNIT-A1'):
        return Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number=unit_number,
            queue_status='COMPLETED',
        )

    def _complete_three(self):
        r1 = self._complete_repair()
        r2 = self._complete_repair()
        r3 = self._complete_repair()
        return r1, r2, r3

    def test_a_model_resave_does_not_reprice(self):
        r1, r2, r3 = self._complete_three()

        self.assertEqual(r1.cost, Decimal('50.00'))
        self.assertEqual(r2.cost, Decimal('40.00'))
        self.assertEqual(r3.cost, Decimal('35.00'))

        count = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number='UNIT-A1'
        )
        self.assertEqual(count.repair_count, 3)

        # Reload from DB (fresh instance, original_status == 'COMPLETED'),
        # exactly what the edit view does before calling save().
        r1_reloaded = Repair.objects.get(pk=r1.pk)
        r1_reloaded.save()

        r1_reloaded.refresh_from_db()
        self.assertEqual(
            r1_reloaded.cost, Decimal('50.00'),
            "Re-saving an already-COMPLETED repair must not re-price it "
            "at the current repair_count tier",
        )
        count.refresh_from_db()
        self.assertEqual(count.repair_count, 3, "Re-save must not touch the unit counter")

    def test_b_edit_view_resave_does_not_reprice(self):
        r1, _, _ = self._complete_three()
        self.assertEqual(r1.cost, Decimal('50.00'))

        response = self.client.post(
            reverse('update_repair', args=[r1.id]),
            data={
                'customer': self.customer.id,
                'technician': self.technician.id,
                'unit_number': 'UNIT-A1',
                'queue_status': 'COMPLETED',
                'repair_date': timezone.now().strftime('%Y-%m-%dT%H:%M'),
                'technician_notes': 'attached after-photo (A1 regression)',
            },
        )
        self.assertIn(response.status_code, (200, 302), f"edit view failed: {response.status_code}")

        r1.refresh_from_db()
        self.assertEqual(
            r1.cost, Decimal('50.00'),
            "Editing a COMPLETED repair (e.g. to attach a photo) must not change its cost",
        )
        count = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number='UNIT-A1'
        )
        self.assertEqual(count.repair_count, 3)

    def test_c_cost_override_applies_on_resave(self):
        r1, _, _ = self._complete_three()

        r1_reloaded = Repair.objects.get(pk=r1.pk)
        r1_reloaded.cost_override = Decimal('99.00')
        r1_reloaded.override_reason = 'manager correction'
        r1_reloaded.save()

        r1_reloaded.refresh_from_db()
        self.assertEqual(
            r1_reloaded.cost, Decimal('99.00'),
            "cost_override must still apply on any save, including re-saves",
        )

    def test_d_first_completion_still_prices_progressively(self):
        # A repair completed via PENDING -> COMPLETED transition (not created
        # as COMPLETED) must still be priced at its tier on first completion.
        r1 = self._complete_repair()
        pending = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-A1',
            queue_status='PENDING',
        )
        pending_reloaded = Repair.objects.get(pk=pending.pk)
        pending_reloaded.queue_status = 'COMPLETED'
        pending_reloaded.save()
        pending_reloaded.refresh_from_db()
        self.assertEqual(
            pending_reloaded.cost, Decimal('40.00'),
            "First transition into COMPLETED must price at the next tier",
        )
