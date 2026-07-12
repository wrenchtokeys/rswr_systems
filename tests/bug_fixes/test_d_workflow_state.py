"""
Regression tests for Workstream D (Remediation Plan 2026-07-09):
workflow & state machine.

D1 — No status state machine: any status could transition to any other.
     A COMPLETED -> APPROVED -> COMPLETED cycle re-fired the completion
     hooks each round (original_status refreshes on every save), letting
     loyalty points and the unit repair counter be inflated at will.
     Now enforced in Repair.save(): COMPLETED is terminal; DENIED must be
     re-approved; forward jumps stay permissive.
D2 — Batch sibling propagation used queryset .update(), skipping
     Repair.save() and post_save signals — siblings changed status with
     no customer notification. Now per-repair save() in a transaction.
D3 — Quiet hours: log no longer claims a "delay" that never resolves
     (behavior documented as suppression; in-app notification remains).
D4 — Stripe 'unpaid' (terminal, retries exhausted) mapped to past_due,
     which only warns — the tenant kept full access for free. Now maps
     to 'expired' with the standard 30-day grace. Biweekly batch
     schedule anchored to a fixed epoch instead of ISO week parity.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingConfig
from apps.billing.tasks import _should_run_batch_today
from apps.rewards_referrals.models import PointTransaction
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants import webhooks
from apps.technician_portal.models import Repair, Technician, UnitRepairCount
from core.models import Customer


class WorkflowTestBase(TestCase):
    def setUp(self):
        self.client = Client()
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='D Test Shop',
            email='owner_d@test.com',
            password='testpass123!',
            first_name='DOwner',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='D Fleet', customer_type='FLEET',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _make_repair(self, status='COMPLETED', unit='D-UNIT'):
        return Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number=unit,
            queue_status=status,
        )


class D1StateMachineTests(WorkflowTestBase):
    def test_completed_is_terminal_at_model_layer(self):
        repair = self._make_repair('COMPLETED')
        reloaded = Repair.objects.get(pk=repair.pk)
        reloaded.queue_status = 'APPROVED'
        with self.assertRaises(ValidationError):
            reloaded.save()

    def test_denied_cannot_jump_to_completed(self):
        repair = self._make_repair('DENIED')
        reloaded = Repair.objects.get(pk=repair.pk)
        reloaded.queue_status = 'COMPLETED'
        with self.assertRaises(ValidationError):
            reloaded.save()

    def test_forward_flow_still_works(self):
        repair = self._make_repair('PENDING')
        for status in ('APPROVED', 'IN_PROGRESS', 'COMPLETED'):
            repair = Repair.objects.get(pk=repair.pk)
            repair.queue_status = status
            repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'COMPLETED')

    def test_view_rejects_cycle_and_awards_no_points(self):
        """The exploit: cycle COMPLETED->APPROVED->COMPLETED to farm points."""
        repair = self._make_repair('COMPLETED')
        baseline_points = PointTransaction.objects.count()
        baseline_count = UnitRepairCount.objects.get(
            tenant=self.tenant, customer=self.customer, unit_number='D-UNIT'
        ).repair_count

        response = self.client.post(
            reverse('update_queue_status', args=[repair.id]),
            data={'status': 'APPROVED'},
        )
        self.assertEqual(response.status_code, 302, "view redirects with an error message")

        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'COMPLETED', "status must not change")
        self.assertEqual(
            PointTransaction.objects.count(), baseline_points,
            "no loyalty points may be re-awarded via status cycling",
        )
        self.assertEqual(
            UnitRepairCount.objects.get(
                tenant=self.tenant, customer=self.customer, unit_number='D-UNIT'
            ).repair_count,
            baseline_count,
            "unit counter must not move",
        )


class D2SiblingPropagationTests(WorkflowTestBase):
    def test_sibling_approval_goes_through_save(self):
        import uuid
        batch_id = uuid.uuid4()
        repairs = []
        for i in (1, 2, 3):
            repairs.append(Repair.objects.create(
                tenant=self.tenant,
                customer=self.customer,
                technician=self.technician,
                unit_number='D2-UNIT',
                queue_status='PENDING',
                repair_batch_id=batch_id,
                break_number=i,
                total_breaks_in_batch=3,
            ))

        response = self.client.post(
            reverse('update_queue_status', args=[repairs[0].id]),
            data={'status': 'APPROVED'},
        )
        self.assertEqual(response.status_code, 302)

        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'APPROVED')

        # save()-based propagation refreshes preview pricing on siblings —
        # a queryset .update() would have left cost untouched/None.
        for r in repairs[1:]:
            self.assertIsNotNone(r.cost, "sibling went through Repair.save()")


class D4SubscriptionGapsTests(WorkflowTestBase):
    def test_unpaid_maps_to_expired_with_grace(self):
        self.tenant.stripe_customer_id = 'cus_d4'
        self.tenant.stripe_subscription_id = 'sub_d4'
        self.tenant.subscription_status = 'active'
        self.tenant.save()

        webhooks._handle_subscription_updated({
            'id': 'sub_d4',
            'customer': 'cus_d4',
            'status': 'unpaid',
            'items': {'data': []},
        })
        self.tenant.refresh_from_db()
        self.assertEqual(
            self.tenant.subscription_status, 'expired',
            "'unpaid' (retries exhausted) must block, not warn",
        )
        self.assertIsNotNone(
            self.tenant.grace_period_end,
            "the owner gets the standard read-only grace, not a hard lockout",
        )

    def test_biweekly_schedule_is_epoch_anchored(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.batch_invoice_frequency = 'biweekly'
        config.batch_invoice_day = 0  # Monday
        config.save()

        # The 2026/2027 ISO-week boundary: 2026-12-28 is ISO week 53 (odd),
        # 2027-01-04 is ISO week 1 (odd) — the old parity logic would skip
        # both or run both depending on parity; epoch anchoring alternates.
        mondays = [date(2026, 12, 21), date(2026, 12, 28),
                   date(2027, 1, 4), date(2027, 1, 11)]
        runs = [_should_run_batch_today(config, d) for d in mondays]
        self.assertIn(
            runs, ([True, False, True, False], [False, True, False, True]),
            f"biweekly must alternate cleanly across the year boundary "
            f"(old ISO-parity logic gave a double-run or 3-week gap), got {runs}",
        )
