"""
CODE-280 Regression Test: the queue had no way to drain.

CODE-279 made "nobody has picked this job yet" a real state
(``GlassService.needs_assignment``).  What it did not do was give a manager a
one-motion way out of it, because every path that meant to ask "is this job
unassigned?" asked it of a non-null foreign key:

  * ``views/repairs.py`` bulk approve — ``if repair.queue_status == 'REQUESTED'
    and not repair.technician and technician`` — meant to hand a REQUESTED job
    to whoever approved it.  ``technician`` is NOT NULL, so it never fired and
    approving a queued job left it queued.
  * ``views/repairs.py`` update gate — ``if not repair.technician_id`` behind
    the message "This repair has not been assigned yet and cannot be edited by
    technicians."  Never fired either: the message described a state the
    schema could not hold.
  * ``views/repairs.py`` repair create and ``saas/views.py`` replacement
    create — both had an "auto-assign if none was chosen" call behind the same
    impossible condition.  Both are unreachable by construction (the technician
    is assigned unconditionally / is a required form field), so CODE-280
    removes them rather than reviving them.

The product decision behind the first one: **approving takes the job only if
the approver can actually do that kind of work.**  In a one-person shop the
owner approves and it is theirs in one motion.  In a shop where a dispatcher
approves everything, taking every job would quietly make the whole queue
theirs — the opposite of what the Manual strategy is for — so their approval
approves the work and leaves it queued for a real pick.

``services.assignments.can_perform`` is the shared rule; it was
``quick_job._can_perform`` until this session needed it in two places.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.technician_portal.models import (
    Repair, Replacement, Technician, TechnicianNotification,
)
from apps.technician_portal.services.assignments import can_perform
from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_shop(business_name, email):
    """A real shop: subscription plan, owner, membership.

    Not ``Tenant.objects.create`` — a tenant with no subscription sends the
    middleware into a redirect loop the moment a test hits a view.
    """
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'),
            'trial_days': 30, 'display_order': 0, 'is_active': True,
        },
    )
    result = create_tenant_with_owner(
        business_name=business_name, email=email, password='testpass123!',
        first_name='Test', last_name='Owner', services_offered='both',
    )
    return result['user'], result['tenant']


def login(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


@override_settings(**TEST_SETTINGS)
class ApproveQueuedJobTestBase(TestCase):
    """A shop on Manual, so customer requests land in the queue."""

    def setUp(self):
        self.client = Client()
        self.owner_user, self.tenant = make_shop('C280 Shop', 'c280@test.com')
        self.tenant.assignment_strategy = 'manual'
        self.tenant.save(update_fields=['assignment_strategy'])

        self.tech = self._make_tech('c280_tech')
        self.manager = self._make_tech('c280_mgr', is_manager=True)
        # A dispatcher: a real manager who does not turn wrenches.
        self.dispatcher = self._make_tech(
            'c280_dispatch', is_manager=True, can_repair=False,
            can_replace=False,
        )
        self.customer = Customer.objects.create(
            name='Fleet Co', tenant=self.tenant, email='fleet@c280.test')

    def _make_tech(self, username, **kwargs):
        user = User.objects.create_user(username, password='pw')
        TenantMembership.objects.create(
            user=user, tenant=self.tenant,
            role='manager' if kwargs.get('is_manager') else 'technician',
            is_active=True,
        )
        kwargs.setdefault('can_repair', True)
        kwargs.setdefault('can_replace', True)
        return Technician.objects.create(
            user=user, tenant=self.tenant, is_active=True,
            phone_number='555-0100', **kwargs,
        )

    def _queued_repair(self, provisional=None, **kwargs):
        """A repair as the queue leaves it: provisional tech + flag raised."""
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=provisional or self.tech,
            queue_status=kwargs.pop('queue_status', 'REQUESTED'), **kwargs,
        )
        Repair.objects.filter(pk=repair.pk).update(needs_assignment=True)
        repair.refresh_from_db()
        return repair

    def _approve(self, actor_tech, repair):
        login(self.client, actor_tech.user, self.tenant)
        return self.client.post(
            reverse('tech_bulk_repair_action'),
            {'action': 'approve', 'repair_ids': [str(repair.pk)]},
            follow=True,
        )


class ApprovingTakesTheJobTest(ApproveQueuedJobTestBase):
    """The one-motion path, and the guard that keeps it from over-reaching."""

    def test_a_tech_who_can_do_the_work_takes_it_by_approving(self):
        queued = self._queued_repair(provisional=self.tech)

        self._approve(self.manager, queued)

        queued.refresh_from_db()
        self.assertEqual(queued.technician_id, self.manager.id)
        self.assertFalse(
            queued.needs_assignment,
            'taking the job should clear it out of the queue',
        )
        self.assertEqual(queued.queue_status, 'APPROVED')

    def test_a_dispatcher_approves_without_taking_the_job(self):
        """can_repair=False: approve the work, leave the pick to someone else."""
        queued = self._queued_repair(provisional=self.tech)

        self._approve(self.dispatcher, queued)

        queued.refresh_from_db()
        self.assertEqual(queued.queue_status, 'APPROVED')
        self.assertNotEqual(queued.technician_id, self.dispatcher.id)
        self.assertTrue(
            queued.needs_assignment,
            'a dispatcher approving is not a dispatcher choosing',
        )

    def test_an_already_assigned_job_keeps_its_technician(self):
        """Not queued means somebody chose — approving must not overrule it."""
        assigned = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            queue_status='REQUESTED',
        )
        self.assertFalse(assigned.needs_assignment)

        self._approve(self.manager, assigned)

        assigned.refresh_from_db()
        self.assertEqual(assigned.technician_id, self.tech.id)
        self.assertEqual(assigned.queue_status, 'APPROVED')

    def test_an_inactive_approver_does_not_take_the_job(self):
        queued = self._queued_repair(provisional=self.tech)
        self.manager.is_active = False
        self.manager.save(update_fields=['is_active'])

        self._approve(self.manager, queued)

        queued.refresh_from_db()
        self.assertTrue(queued.needs_assignment)
        self.assertNotEqual(queued.technician_id, self.manager.id)

    def test_taking_the_job_does_not_notify_the_taker(self):
        """You know you took it — you just clicked approve."""
        queued = self._queued_repair(provisional=self.tech)
        before = TechnicianNotification.objects.filter(
            technician=self.manager).count()

        self._approve(self.manager, queued)

        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.manager).count(),
            before,
        )

    def test_the_provisional_tech_is_not_told_they_lost_it(self):
        """They were never told it was theirs (CODE-279); no reassigned-away."""
        queued = self._queued_repair(provisional=self.tech)
        before = TechnicianNotification.objects.filter(
            technician=self.tech).count()

        self._approve(self.manager, queued)

        self.assertEqual(
            TechnicianNotification.objects.filter(
                technician=self.tech).count(),
            before,
        )


class QueuedJobsAreNotEditableYetTest(ApproveQueuedJobTestBase):
    """The update gate whose message finally describes a state that exists."""

    def _post_edit(self, actor_tech, repair):
        login(self.client, actor_tech.user, self.tenant)
        return self.client.get(
            reverse('update_repair', args=[repair.pk]), follow=True)

    def test_the_provisional_tech_cannot_edit_a_queued_job(self):
        queued = self._queued_repair(provisional=self.tech)

        resp = self._post_edit(self.tech, queued)

        self.assertContains(resp, 'waiting to be assigned')

    def test_the_same_tech_can_edit_it_once_it_is_really_theirs(self):
        queued = self._queued_repair(provisional=self.tech)
        queued.technician = self.manager
        queued.save()            # clears the flag (CODE-279)
        queued.technician = self.tech
        queued.save()

        resp = self._post_edit(self.tech, queued)

        self.assertNotContains(resp, 'waiting to be assigned')

    def test_a_manager_is_not_locked_out_of_the_queue(self):
        """Managers are who the queue is waiting on."""
        queued = self._queued_repair(provisional=self.manager)

        resp = self._post_edit(self.manager, queued)

        self.assertNotContains(resp, 'waiting to be assigned')


class CanPerformTest(TestCase):
    """The shared ability rule, extracted from quick_job for the approve path."""

    def setUp(self):
        _owner, self.tenant = make_shop('C280 CP', 'c280cp@test.com')
        self.user = User.objects.create_user('c280_cp_tech', password='pw')
        self.tech = Technician.objects.create(
            user=self.user, tenant=self.tenant, is_active=True,
            can_repair=True, can_replace=False,
        )

    def test_none_cannot_perform(self):
        """An admin-only user has no Technician row — not a crash, a False."""
        self.assertFalse(can_perform(None, 'repair'))

    def test_ability_is_read_per_service_type(self):
        self.assertTrue(can_perform(self.tech, 'repair'))
        self.assertFalse(can_perform(self.tech, 'replacement'))

    def test_an_inactive_tech_cannot_perform(self):
        self.tech.is_active = False
        self.tech.save(update_fields=['is_active'])
        self.assertFalse(can_perform(self.tech, 'repair'))


class RemovedDeadBranchesStillCreateJobsTest(ApproveQueuedJobTestBase):
    """The two branches CODE-280 deleted were unreachable — prove creation works."""

    def test_a_replacement_keeps_the_technician_the_form_chose(self):
        """saas.replacement_create's auto-assign call could never fire:
        technician is a required field, so a valid form always has a pick."""
        replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
        )
        replacement.refresh_from_db()
        self.assertEqual(replacement.technician_id, self.tech.id)
        self.assertFalse(replacement.needs_assignment)
