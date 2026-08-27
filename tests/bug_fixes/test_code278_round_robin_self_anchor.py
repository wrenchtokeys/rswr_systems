"""
CODE-278 Regression Test: round-robin sent every customer request to the same
technician, and smart auto-assign counted the job it was balancing.

Root cause (round-robin): ``_assign_round_robin`` anchored the rotation on the
most recently assigned job of the same type, but did not exclude the job it was
being asked to assign.  ``GlassService.technician`` is a non-null FK, so the
caller has to create the job with a *provisional* technician before handing it
over — which means that brand-new row is itself the most recent one.  The
rotation anchored on itself and returned "provisional pick + 1".

Impact: the customer portal picks the provisional tech with
``get_available_technician()``, a lowest-workload picker.  Round-robin then
moved every job off that tech, so they never accumulated any load, so they were
picked provisionally again next time — and the same neighbour received every
single customer request while the rest of the shop got none.  Measured before
the fix: 3 eligible techs, 6 requests, all 6 to one tech.

Secondary root cause: the anchor ordered by ``-service_date`` first.
``service_date`` is the date of service, editable from the job form as
``repair_date``, so backdating or forward-dating a job dragged the rotation
anchor with it.  Creation order (``-id``) is what "last assigned" means.

Third root cause (smart): ``_assign_smart`` counted active jobs including the
one being assigned — ``REQUESTED`` is in ``active_statuses`` — inflating the
provisional tech's workload by one and pushing the job away from the tech the
count was meant to favour.

Fix: exclude the job under assignment from both the round-robin anchor and the
smart workload count, and order the anchor by ``-id``.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import Tenant
from apps.tenants.services.assignment_service import (
    _assign_round_robin,
    _assign_smart,
    auto_assign_repair,
)
from core.models import Customer


class RoundRobinSelfAnchorTest(TestCase):

    def setUp(self):
        owner = User.objects.create_user('c278_owner', password='pw')
        self.tenant = Tenant.objects.create(
            name='C278 Shop', slug='c278-shop', plan='trial', owner=owner,
            assignment_strategy='round_robin',
        )
        self.techs = [self._make_tech(f'c278_t{i}') for i in range(3)]
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@c278.test')

    def _make_tech(self, username):
        user = User.objects.create_user(username, password='pw')
        return Technician.objects.create(
            user=user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True,
        )

    def _make_repair(self, tech, **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=tech,
            queue_status=kwargs.pop('queue_status', 'APPROVED'), **kwargs,
        )

    # ------------------------------------------------------------------
    def test_anchor_ignores_the_job_being_assigned(self):
        """The rotation reads the PREVIOUS job, not the one in hand."""
        self._make_repair(self.techs[0])
        # Provisionally on tech 0 as well — the old code anchored here and
        # answered "tech 1"; the previous job is the real anchor, so the
        # answer is the same. Provision on tech 2 to tell them apart.
        new_repair = self._make_repair(self.techs[2], queue_status='REQUESTED')

        assigned = _assign_round_robin(new_repair, self.tenant)

        new_repair.refresh_from_db()
        self.assertEqual(assigned, self.techs[1])
        self.assertEqual(new_repair.technician, self.techs[1])

    def test_rotation_reaches_every_technician(self):
        """Six customer-shaped requests must land 2/2/2, not 6/0/0.

        Mirrors the real caller: pick a provisional tech with the customer
        portal's own picker, create the job, then auto-assign.
        """
        from apps.customer_portal.views import get_available_technician

        for i in range(6):
            provisional = get_available_technician(
                tenant=self.tenant, service_type='repair')
            repair = self._make_repair(
                provisional, queue_status='REQUESTED', unit_number=f'U{i}')
            auto_assign_repair(repair)

        counts = [
            Repair.objects.filter(tenant=self.tenant, technician=t).count()
            for t in self.techs
        ]
        self.assertEqual(counts, [2, 2, 2], f'Uneven rotation: {counts}')

    def test_anchor_uses_creation_order_not_service_date(self):
        """A forward-dated older job must not hijack the rotation anchor."""
        # Created first, but dated a week out — the shop booked it ahead.
        stale = self._make_repair(self.techs[2])
        stale.service_date = timezone.now() + timedelta(days=7)
        stale.save(update_fields=['service_date'])
        # Created second: this is the genuine "last assigned".
        self._make_repair(self.techs[0])

        new_repair = self._make_repair(self.techs[0], queue_status='REQUESTED')
        assigned = _assign_round_robin(new_repair, self.tenant)

        # Anchor is tech 0 (last created), so next is tech 1. Ordering by
        # -service_date would have anchored on tech 2 and answered tech 0.
        self.assertEqual(assigned, self.techs[1])

    def test_replacement_rotation_ignores_the_replacement_in_hand(self):
        """Same guarantee on the replacement side."""
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[0], queue_status='APPROVED')
        new_replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[2], queue_status='REQUESTED')

        assigned = _assign_round_robin(
            new_replacement, self.tenant, service_type='replacement')

        self.assertEqual(assigned, self.techs[1])

    def test_first_ever_job_starts_at_the_first_eligible_tech(self):
        """No history to anchor on — start the rotation, don't crash."""
        new_repair = self._make_repair(self.techs[2], queue_status='REQUESTED')
        assigned = _assign_round_robin(new_repair, self.tenant)
        self.assertEqual(assigned, self.techs[0])


class SmartAssignSelfCountTest(TestCase):

    def setUp(self):
        owner = User.objects.create_user('c278s_owner', password='pw')
        self.tenant = Tenant.objects.create(
            name='C278S Shop', slug='c278s-shop', plan='trial', owner=owner,
            assignment_strategy='auto',
        )
        self.techs = []
        for i in range(3):
            user = User.objects.create_user(f'c278s_t{i}', password='pw')
            self.techs.append(Technician.objects.create(
                user=user, tenant=self.tenant, is_active=True,
                can_repair=True, can_replace=True,
            ))
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@c278s.test')

    def test_job_being_assigned_is_not_counted_against_its_own_tech(self):
        """Nobody has any work: the new job is the only one in the shop.

        Counting it made its own provisional tech look busier than the two
        idle ones, so smart assign bounced the job to tech 1 — away from the
        tech the workload count was meant to favour.  With the job excluded
        all three tie on zero and the tie-break (lowest id) leaves it put.
        """
        new_repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[0], queue_status='REQUESTED')

        assigned = _assign_smart(new_repair, self.tenant)
        self.assertEqual(assigned, self.techs[0])

    def test_real_workload_still_decides(self):
        """The exclusion must not blind the count to genuine load."""
        for _ in range(2):
            Repair.objects.create(
                tenant=self.tenant, customer=self.customer,
                technician=self.techs[0], queue_status='APPROVED')
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[1], queue_status='APPROVED')

        new_repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[0], queue_status='REQUESTED')

        # Tech 0 has 2, tech 1 has 1, tech 2 has 0 — tech 2 wins.
        assigned = _assign_smart(new_repair, self.tenant)
        self.assertEqual(assigned, self.techs[2])
