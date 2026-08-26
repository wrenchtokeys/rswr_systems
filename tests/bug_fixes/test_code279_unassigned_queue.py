"""
CODE-279 Regression Test: the Job Assignment setting made four promises and
kept two of them.

Root cause 1 — nothing could be unassigned.  ``GlassService.technician`` is a
non-null FK, so every caller creates the job with a *provisional* technician
before consulting the strategy.  When the strategy declined to assign —
``manual`` always, ``primary_first`` whenever the customer has no eligible
primary tech — ``auto_assign_*`` returned None and the provisional pick simply
stayed on the row.  The settings page said "a manager must manually assign
every repair"; in fact every customer request was assigned immediately, to
whoever ``get_available_technician()`` happened to return, and that tech was
notified it was theirs.  The manager was never told anything, and the job list's
"Unassigned" filter (``technician__isnull=True``) matched nothing, ever.

Root cause 2 — in-app job creation never read the setting.  The comment at the
``quick_job.create_job`` call site said "otherwise fall back to the shop's
assignment strategy", but ``resolve_technician`` never looked at
``tenant.assignment_strategy``: it returned the actor's own profile, or an
arbitrary ``.first()`` for an admin without one.  A shop set to Round Robin got
round robin on customer requests and something else entirely at the counter.

Fix: a ``needs_assignment`` flag — the row keeps its provisional technician,
the flag says nobody picked them.  It drives the Unassigned queue, suppresses
the "you have been assigned" notification, alerts the managers instead, and is
cleared automatically the moment anyone actually assigns the job.
``resolve_technician`` now consults the strategy, after the actor's own
profile (a tech's own walk-in stays theirs) and before the arbitrary fallback.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.technician_portal.models import (
    Repair, Replacement, Technician, TechnicianNotification,
)
from apps.tenants.models import Tenant
from apps.tenants.services.assignment_service import (
    auto_assign_repair,
    auto_assign_replacement,
    select_technician,
)
from core.models import Customer


class UnassignedQueueTestBase(TestCase):
    """Three eligible techs, one of them a manager, and a fleet customer."""

    strategy = 'manual'

    def setUp(self):
        owner = User.objects.create_user('c279_owner', password='pw')
        self.tenant = Tenant.objects.create(
            name='C279 Shop', slug='c279-shop', plan='trial', owner=owner,
            assignment_strategy=self.strategy,
        )
        self.manager = self._make_tech('c279_mgr', is_manager=True)
        self.techs = [self._make_tech(f'c279_t{i}') for i in range(2)]
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@c279.test')

    def _make_tech(self, username, **kwargs):
        user = User.objects.create_user(username, password='pw')
        return Technician.objects.create(
            user=user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=True, **kwargs,
        )

    def _make_repair(self, tech, **kwargs):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=tech,
            queue_status=kwargs.pop('queue_status', 'REQUESTED'), **kwargs,
        )


class ManualQueuesInsteadOfAssigningTest(UnassignedQueueTestBase):

    def test_manual_flags_the_job_instead_of_keeping_the_provisional_tech(self):
        """Manual means waiting on a manager, not silently assigned."""
        repair = self._make_repair(self.techs[0])

        assigned = auto_assign_repair(repair)

        repair.refresh_from_db()
        self.assertIsNone(assigned)
        self.assertTrue(repair.needs_assignment)
        # The provisional tech stays on the row — the column is NOT NULL.
        self.assertEqual(repair.technician, self.techs[0])

    def test_manual_replacements_queue_too(self):
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.techs[0], queue_status='REQUESTED',
        )

        self.assertIsNone(auto_assign_replacement(replacement))
        replacement.refresh_from_db()
        self.assertTrue(replacement.needs_assignment)

    def test_queued_job_appears_in_the_unassigned_filter(self):
        """The filter the job list runs — it matched nothing before the flag."""
        queued = self._make_repair(self.techs[0])
        auto_assign_repair(queued)
        assigned = self._make_repair(self.techs[1], queue_status='APPROVED')

        waiting = Repair.objects.filter(
            tenant=self.tenant, needs_assignment=True)

        self.assertEqual(list(waiting), [queued])
        self.assertNotIn(assigned, waiting)

    def test_provisional_tech_is_not_told_the_job_is_theirs(self):
        """Crossing REQUESTED → APPROVED used to notify the provisional tech."""
        repair = self._make_repair(self.techs[0])
        auto_assign_repair(repair)
        TechnicianNotification.objects.all().delete()

        repair.refresh_from_db()
        repair.queue_status = 'APPROVED'
        repair.save()

        self.assertFalse(
            TechnicianNotification.objects.filter(
                technician=self.techs[0]).exists(),
            'The provisional tech was told a job nobody assigned is theirs.',
        )

    def test_managers_are_told_the_job_is_waiting(self):
        """Suppressing the tech's notification must not silence everyone."""
        repair = self._make_repair(self.techs[0])

        auto_assign_repair(repair)

        notes = TechnicianNotification.objects.filter(technician=self.manager)
        self.assertEqual(notes.count(), 1)
        self.assertIn('waiting to be assigned', notes.first().message)
        self.assertFalse(
            TechnicianNotification.objects.filter(
                technician__in=self.techs).exists())

    def test_a_batch_alerts_the_managers_once(self):
        """Six breaks are one customer request, not six decisions."""
        import uuid
        batch_id = uuid.uuid4()
        breaks = [
            self._make_repair(
                self.techs[0], repair_batch_id=batch_id,
                break_number=i + 1, total_breaks_in_batch=3, unit_number='B-1',
            )
            for i in range(3)
        ]

        for repair in breaks:
            auto_assign_repair(repair)

        self.assertTrue(all(
            Repair.objects.get(pk=r.pk).needs_assignment for r in breaks))
        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.manager).count(),
            1,
        )

    def test_assigning_the_job_clears_the_flag(self):
        """Any surface that sets a technician settles the queue entry."""
        repair = self._make_repair(self.techs[0])
        auto_assign_repair(repair)
        repair.refresh_from_db()
        self.assertTrue(repair.needs_assignment)

        repair.technician = self.techs[1]
        repair.save()

        repair.refresh_from_db()
        self.assertFalse(repair.needs_assignment)

    def test_clearing_survives_a_narrow_update_fields_save(self):
        """assign_job-style saves pass update_fields; the clear must persist."""
        repair = self._make_repair(self.techs[0])
        auto_assign_repair(repair)

        repair.refresh_from_db()
        repair.technician = self.techs[1]
        repair.save(update_fields=['technician'])

        repair.refresh_from_db()
        self.assertFalse(repair.needs_assignment)

    def test_a_real_assignment_notifies_normally(self):
        """The suppression is for queued jobs only, not a permanent mute."""
        repair = self._make_repair(self.techs[0], queue_status='APPROVED')
        auto_assign_repair(repair)
        TechnicianNotification.objects.all().delete()

        repair.refresh_from_db()
        repair.technician = self.techs[1]
        repair.save()

        self.assertTrue(
            TechnicianNotification.objects.filter(
                technician=self.techs[1]).exists())


class DispatchBoardConfirmsThePlaceholderTest(UnassignedQueueTestBase):
    """The board is where the badge sends managers — it has to accept them."""

    def test_leaving_the_picker_alone_assigns_rather_than_refusing(self):
        from apps.technician_portal.services.dispatch import apply_dispatch

        repair = self._make_repair(self.techs[0])
        auto_assign_repair(repair)
        repair.refresh_from_db()
        self.assertTrue(repair.needs_assignment)

        result = apply_dispatch(
            tenant=self.tenant, service_type='repair', pk=repair.pk,
            technician_id=self.techs[0].pk, actor_user=self.manager.user,
        )

        repair.refresh_from_db()
        self.assertFalse(repair.needs_assignment)
        self.assertEqual(repair.technician, self.techs[0])
        self.assertIn('assigned to', result['message'])

    def test_an_ordinary_no_op_is_still_refused(self):
        """The guard only bends for jobs nobody had picked."""
        from apps.technician_portal.services.dispatch import (
            DispatchError, apply_dispatch,
        )

        repair = self._make_repair(self.techs[0], queue_status='APPROVED')

        with self.assertRaises(DispatchError) as caught:
            apply_dispatch(
                tenant=self.tenant, service_type='repair', pk=repair.pk,
                technician_id=self.techs[0].pk, actor_user=self.manager.user,
            )

        self.assertIn('Nothing to change', caught.exception.message)


class PrimaryFirstWithoutAPrimaryTest(UnassignedQueueTestBase):

    strategy = 'primary_first'

    def test_no_primary_tech_queues_the_job(self):
        repair = self._make_repair(self.techs[0])

        self.assertIsNone(auto_assign_repair(repair))
        repair.refresh_from_db()
        self.assertTrue(repair.needs_assignment)

    def test_an_ineligible_primary_tech_queues_the_job(self):
        """A deactivated primary is not a fallback to somebody else."""
        self.techs[1].is_active = False
        self.techs[1].save()
        self.customer.primary_technician = self.techs[1]
        self.customer.save()
        repair = self._make_repair(self.techs[0])

        self.assertIsNone(auto_assign_repair(repair))
        repair.refresh_from_db()
        self.assertTrue(repair.needs_assignment)

    def test_an_eligible_primary_tech_is_assigned_and_not_flagged(self):
        self.customer.primary_technician = self.techs[1]
        self.customer.save()
        repair = self._make_repair(self.techs[0])

        assigned = auto_assign_repair(repair)

        repair.refresh_from_db()
        self.assertEqual(assigned, self.techs[1])
        self.assertFalse(repair.needs_assignment)


class RoundRobinIgnoresQueuedJobsTest(UnassignedQueueTestBase):

    strategy = 'round_robin'

    def test_a_queued_job_does_not_move_the_rotation_anchor(self):
        """Its technician is a placeholder nobody chose — not a turn taken."""
        self.tenant.assignment_strategy = 'manual'
        self.tenant.save()
        queued = self._make_repair(self.techs[0])
        auto_assign_repair(queued)

        self.tenant.assignment_strategy = 'round_robin'
        self.tenant.save()
        following = self._make_repair(self.techs[1])
        assigned = auto_assign_repair(following)

        # With no real assignment on file the rotation starts at the top,
        # rather than treating the queued job's placeholder as tech 0's turn.
        self.assertEqual(assigned, self.manager)


class SelectTechnicianTest(UnassignedQueueTestBase):
    """The read-only entry point in-app creation uses, before a row exists."""

    def test_manual_declines(self):
        self.assertIsNone(
            select_technician(self.tenant, customer=self.customer))

    def test_round_robin_picks_without_writing_anything(self):
        self.tenant.assignment_strategy = 'round_robin'
        self.tenant.save()

        picked = select_technician(self.tenant, customer=self.customer)

        self.assertIsNotNone(picked)
        self.assertEqual(Repair.objects.count(), 0)

    def test_primary_first_reads_the_customer_it_is_given(self):
        self.tenant.assignment_strategy = 'primary_first'
        self.tenant.save()
        self.customer.primary_technician = self.techs[1]
        self.customer.save()

        self.assertEqual(
            select_technician(self.tenant, customer=self.customer),
            self.techs[1],
        )

    def test_no_tenant_declines(self):
        self.assertIsNone(select_technician(None))


class InAppCreationConsultsTheStrategyTest(UnassignedQueueTestBase):
    """Root cause 2: quick job creation never read assignment_strategy."""

    strategy = 'round_robin'

    def setUp(self):
        super().setUp()
        self.dispatcher = User.objects.create_user('c279_dispatch', password='pw')

    def _resolve(self, actor_user, service_type='repair'):
        from apps.technician_portal.services.quick_job import resolve_technician
        return resolve_technician(
            self.tenant, actor_user, service_type, customer=self.customer)

    def test_a_techs_own_job_stays_theirs(self):
        """The walk-in they just handled is not rotated away to a colleague."""
        tech, needs_assignment = self._resolve(self.techs[0].user)

        self.assertEqual(tech, self.techs[0])
        self.assertFalse(needs_assignment)

    def test_an_actor_without_a_profile_gets_the_shops_strategy(self):
        """A dispatcher used to get an arbitrary .first(); now: round robin."""
        self._make_repair(self.manager, queue_status='APPROVED')

        tech, needs_assignment = self._resolve(self.dispatcher)

        # Manager was last, so the rotation moves on rather than picking by id.
        self.assertEqual(tech, self.techs[0])
        self.assertFalse(needs_assignment)

    def test_primary_first_applies_in_app_too(self):
        self.tenant.assignment_strategy = 'primary_first'
        self.tenant.save()
        self.customer.primary_technician = self.techs[1]
        self.customer.save()

        tech, needs_assignment = self._resolve(self.dispatcher)

        self.assertEqual(tech, self.techs[1])
        self.assertFalse(needs_assignment)

    def test_manual_falls_through_to_a_flagged_placeholder(self):
        """Somebody has to go on a NOT NULL column; the flag says nobody chose."""
        self.tenant.assignment_strategy = 'manual'
        self.tenant.save()

        tech, needs_assignment = self._resolve(self.dispatcher)

        self.assertIsNotNone(tech)
        self.assertTrue(needs_assignment)

    def test_an_actor_who_cannot_do_the_work_defers_to_the_strategy(self):
        """A can_replace=False profile must not take a replacement (CODE-160)."""
        self.techs[0].can_replace = False
        self.techs[0].save()

        tech, needs_assignment = self._resolve(
            self.techs[0].user, service_type='replacement')

        self.assertNotEqual(tech, self.techs[0])
        self.assertFalse(needs_assignment)

    def test_create_job_flags_what_the_strategy_declined(self):
        from apps.technician_portal.services.quick_job import create_job

        self.tenant.assignment_strategy = 'manual'
        self.tenant.save()

        job = create_job(
            tenant=self.tenant, actor_user=self.dispatcher,
            data={'service_type': 'repair', 'customer': self.customer,
                  'unit_number': 'T-279'},
        )

        job.refresh_from_db()
        self.assertTrue(job.needs_assignment)
        self.assertTrue(
            TechnicianNotification.objects.filter(
                technician=self.manager,
                message__contains='waiting to be assigned').exists())

    def test_create_job_does_not_flag_a_strategy_pick(self):
        from apps.technician_portal.services.quick_job import create_job

        job = create_job(
            tenant=self.tenant, actor_user=self.dispatcher,
            data={'service_type': 'repair', 'customer': self.customer,
                  'unit_number': 'T-280'},
        )

        job.refresh_from_db()
        self.assertFalse(job.needs_assignment)

    def test_an_explicit_pick_still_wins(self):
        from apps.technician_portal.services.quick_job import create_job

        self.tenant.assignment_strategy = 'manual'
        self.tenant.save()

        job = create_job(
            tenant=self.tenant, actor_user=self.dispatcher,
            data={'service_type': 'repair', 'customer': self.customer,
                  'unit_number': 'T-281', 'technician': self.techs[1]},
        )

        job.refresh_from_db()
        self.assertEqual(job.technician, self.techs[1])
        self.assertFalse(job.needs_assignment)
