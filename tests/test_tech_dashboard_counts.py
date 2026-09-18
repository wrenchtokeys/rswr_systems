"""The technician dashboard has to agree with itself.

Two numbers on that page contradicted the queue rendered directly above them:

  * "Ready to start" counted repairs with a `RepairApproval` row created in
    the last 24 hours. `RepairApproval` is written ONLY by the customer
    portal; shop-created jobs auto-approve through `resolve_initial_shop_status`
    and never write one. On a default AUTO_APPROVE shop -- which is every shop
    -- the tile was structurally always zero while the queue showed jobs
    badged Ready.
  * Every tile was `len()` of a display list capped at 5, taken from a slice
    already capped at 10 or 30, so a busy tech's numbers were simply wrong.
    "Jobs in progress" also folded in replacements while the card below it was
    repairs-only.

The tiles now count the work. The two legacy cards keep only multi-break
batches, which is the one thing Today's Queue cannot express.
"""

from decimal import Decimal
import uuid

from django.test import Client, TestCase, override_settings

from apps.technician_portal.models import Repair, Replacement, Technician
from core.models import Customer
from tests.test_unified_dashboard import login, make_shop

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


@override_settings(**TEST_SETTINGS)
class TileAccuracyTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Counts Shop', 'counts@test.com', 'both')
        self.customer = Customer.objects.create(name='Counts Fleet', tenant=self.tenant)
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        login(self.client, self.user, self.tenant)

    def repair(self, status, **kw):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=kw.pop('unit', 'U-1'), queue_status=status, **kw,
        )

    def stats(self):
        resp = self.client.get('/tech/')
        self.assertEqual(resp.status_code, 200)
        return resp.context['summary_stats'], resp

    def test_ready_to_start_counts_approved_work_on_an_auto_approve_shop(self):
        """The headline bug: no RepairApproval row exists, and none is needed."""
        self.repair('APPROVED', unit='A-1')
        self.repair('APPROVED', unit='A-2')
        stats, resp = self.stats()
        self.assertEqual(stats['pending_approval'], 2)
        # ...and the queue above agrees, which is the contradiction that
        # started this.
        ready_in_queue = [
            j for j in resp.context['todays_queue'] if j.queue_status == 'APPROVED'
        ]
        self.assertEqual(len(ready_in_queue), stats['pending_approval'])

    def test_the_tiles_are_not_capped_at_five(self):
        """Every tile used to be len() of a list sliced for display."""
        for i in range(8):
            self.repair('IN_PROGRESS', unit=f'P-{i}')
        for i in range(7):
            self.repair('APPROVED', unit=f'R-{i}')
        stats, _ = self.stats()
        self.assertEqual(stats['individual_in_progress'], 8)
        self.assertEqual(stats['pending_approval'], 7)
        self.assertEqual(stats['total_active_work'], 15)

    def test_completed_jobs_do_not_count_as_active(self):
        self.repair('COMPLETED', unit='C-1')
        stats, _ = self.stats()
        self.assertEqual(stats['individual_in_progress'], 0)
        self.assertEqual(stats['pending_approval'], 0)
        self.assertEqual(stats['total_active_work'], 0)

    def test_another_technicians_work_is_not_counted(self):
        from django.contrib.auth.models import User

        other_user = User.objects.create_user('other_tech', 'other@test.com', 'pw')
        other = Technician.objects.create(
            tenant=self.tenant, user=other_user, is_active=True,
        )
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=other,
            unit_number='X-1', queue_status='IN_PROGRESS',
        )
        stats, _ = self.stats()
        self.assertEqual(stats['individual_in_progress'], 0)

    def test_replacements_still_count(self):
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-1', glass_position='WINDSHIELD', queue_status='IN_PROGRESS',
        )
        Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Z-2', glass_position='WINDSHIELD', queue_status='APPROVED',
        )
        stats, _ = self.stats()
        self.assertEqual(stats['individual_in_progress'], 1)
        self.assertEqual(stats['pending_approval'], 1)
        self.assertEqual(stats['total_active_work'], 2)


@override_settings(**TEST_SETTINGS)
class BatchCountingTests(TestCase):
    """A multi-break windshield is one job, counted once."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Batch Shop', 'batch@test.com', 'repairs')
        self.customer = Customer.objects.create(name='Batch Fleet', tenant=self.tenant)
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        login(self.client, self.user, self.tenant)

    def batch(self, statuses, unit='B-1'):
        batch_id = uuid.uuid4()
        made = []
        for n, status in enumerate(statuses, start=1):
            made.append(Repair.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number=unit, queue_status=status,
                repair_batch_id=batch_id, break_number=n,
                total_breaks_in_batch=len(statuses),
            ))
        return batch_id, made

    def stats(self):
        resp = self.client.get('/tech/')
        self.assertEqual(resp.status_code, 200)
        return resp.context['summary_stats'], resp

    def test_a_three_break_batch_is_one_job_not_three(self):
        self.batch(['APPROVED', 'APPROVED', 'APPROVED'])
        stats, _ = self.stats()
        self.assertEqual(stats['pending_approval'], 1)
        self.assertEqual(stats['individual_in_progress'], 0)
        self.assertEqual(stats['total_active_work'], 1)

    def test_a_half_started_batch_counts_once_as_in_progress(self):
        """Never both, or Total active jobs would double-count it."""
        self.batch(['IN_PROGRESS', 'APPROVED', 'APPROVED'])
        stats, _ = self.stats()
        self.assertEqual(stats['batches_in_progress'], 1)
        self.assertEqual(stats['pending_approval'], 0)
        self.assertEqual(stats['total_active_work'], 1)

    def test_batches_and_solo_jobs_add_up(self):
        self.batch(['IN_PROGRESS', 'APPROVED'], unit='B-1')
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='S-1', queue_status='APPROVED',
        )
        stats, _ = self.stats()
        self.assertEqual(stats['batches_in_progress'], 1)
        self.assertEqual(stats['individual_in_progress'], 0)
        self.assertEqual(stats['pending_approval'], 1)
        self.assertEqual(stats['total_active_work'], 2)

    def test_a_stray_batch_id_on_a_single_repair_is_not_a_batch(self):
        """Repair.is_part_of_batch is the authority, not "has an id"."""
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='N-1', queue_status='APPROVED',
            repair_batch_id=uuid.uuid4(), break_number=1,
            total_breaks_in_batch=1,
        )
        stats, _ = self.stats()
        self.assertEqual(stats['batches_in_progress'], 0)
        self.assertEqual(stats['pending_approval'], 1)


@override_settings(**TEST_SETTINGS)
class LegacyCardTests(TestCase):
    """The cards keep batches and give up duplicating the queue."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Card Shop', 'card@test.com', 'repairs')
        self.customer = Customer.objects.create(name='Card Fleet', tenant=self.tenant)
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        login(self.client, self.user, self.tenant)

    def test_a_solo_job_is_actionable_once_not_twice(self):
        """Continue up top and Complete down below were the same job.

        Asserted on the ACTIONS, not on the unit number: assignment
        notifications legitimately name the unit several times elsewhere on
        the page.
        """
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='SOLO-1', queue_status='IN_PROGRESS', cost=Decimal('50'),
        )
        resp = self.client.get('/tech/')
        body = resp.content.decode()
        # Today's Queue offers it, once.
        self.assertEqual(body.count('>\n                                Continue\n'), 1)
        # The legacy card's own verb and its update_repair link are both gone.
        self.assertNotIn(f'/tech/repairs/{repair.id}/update/', body)
        self.assertNotIn('>\n                                Complete\n', body)
        # No batches exist, so neither card renders at all.
        self.assertNotContains(resp, "Batches you've started")
        self.assertNotContains(resp, 'Batches ready to start')

    def test_a_half_started_batch_is_not_filed_under_ready_to_start(self):
        """A windshield you have already started is not waiting to be started.

        The cards used to file any batch with an approved break under "Ready to
        Start" and explicitly exclude it from "In Progress" -- so a batch the
        tech was part-way through sat in the wrong card while the tile beside
        it counted the batch as in progress.
        """
        batch_id = uuid.uuid4()
        for n, status in enumerate(['IN_PROGRESS', 'APPROVED'], start=1):
            Repair.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number='HALF-1', queue_status=status,
                repair_batch_id=batch_id, break_number=n, total_breaks_in_batch=2,
            )
        resp = self.client.get('/tech/')
        # Context carries the summaries (dict .values()), not the ids.
        started = [b['batch_id'] for b in resp.context['batch_repairs_in_progress']]
        ready = [b['batch_id'] for b in resp.context['batch_repairs_approved']]
        self.assertEqual(started, [batch_id])
        self.assertEqual(ready, [])
        self.assertContains(resp, "Batches you've started")
        self.assertNotContains(resp, 'Batches ready to start')
        # ...and the tile agrees, which is the whole point.
        self.assertEqual(resp.context['summary_stats']['batches_in_progress'], 1)
        self.assertEqual(resp.context['summary_stats']['pending_approval'], 0)

    def test_a_batch_still_gets_its_card_and_start_all(self):
        batch_id = uuid.uuid4()
        for n in (1, 2):
            Repair.objects.create(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number='BATCH-1', queue_status='APPROVED',
                repair_batch_id=batch_id, break_number=n, total_breaks_in_batch=2,
            )
        resp = self.client.get('/tech/')
        self.assertContains(resp, 'Batches ready to start')
        self.assertContains(resp, 'Start All')

    def test_no_emoji_headings_survive(self):
        resp = self.client.get('/tech/')
        body = resp.content.decode()
        for glyph in ('🔧', '✅', '🎁'):
            self.assertNotIn(glyph, body, f'{glyph} heading is still on the dashboard')

    def test_the_page_names_itself(self):
        """Owner and portal both render "Dashboard | Shop | RS Systems"."""
        resp = self.client.get('/tech/')
        self.assertContains(resp, '<title>Dashboard | Card Shop | RS Systems</title>', html=False)
