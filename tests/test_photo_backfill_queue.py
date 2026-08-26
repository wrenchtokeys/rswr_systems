"""
The unmarked-photo burn-down queue (P4a.1 of the photo-ML arc).

Production holds seventy-seven completed repairs carrying a damage photo and
exactly one of them has ever had the break marked. Marking them one job at a
time works and has worked since P2; nobody was going to open seventy-seven
jobs to do it. This is the page that puts them in a row.

What the tests are actually protecting, in order of how much it would hurt
to get wrong:

1. **The queue only ever offers what the save endpoint will accept.** It
   filters with the same two permission helpers the endpoint uses; a queue
   that hands a technician a 403 for doing what it asked is worse than no
   queue.
2. **A marked photo leaves the queue.** The worklist is a live question, not
   stored state — that is what makes the page safe to reload, to run from
   two devices, or to abandon halfway.
3. **After-photos are never in it.** They label `not_applicable`, and P6
   deliberately does not zoom them for the customer either, so a tap there
   is worth nothing at both ends.
4. **Originals are untouched.** Same promise as the rest of the arc.

See docs/strategy/PHOTO_ML_SESSIONS.md.
"""
import json

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.technician_portal.models import (
    Repair, RepairPhotoCrop, Replacement, Technician,
)
from apps.technician_portal.services.photo_backlog import (
    MARKABLE_FIELDS, backlog_for, backlog_size,
)
from apps.technician_portal.services.photo_dataset import (
    NOT_REPAIRABLE, REPAIRABLE, UNKNOWN, label_for_photo,
)
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer

from tests.test_photo_tap_crop import TapCropTestCase, fake_photo, real_jpeg


QUEUE_URL = '/tech/photos/mark/'


class BackfillQueueTestCase(TapCropTestCase):
    """Jobs to mark, and the helpers to make them."""

    def make_repair(self, status='COMPLETED', **fields):
        fields.setdefault('damage_photo_before', real_jpeg())
        fields.setdefault('unit_number', 'U-B1')
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            queue_status=status, **fields,
        )

    def make_replacement(self, status='COMPLETED', **fields):
        fields.setdefault('damage_photo_before', real_jpeg())
        fields.setdefault('unit_number', 'U-B2')
        return Replacement.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            queue_status=status, **fields,
        )

    def entries(self):
        response = self.client.get(QUEUE_URL)
        self.assertEqual(response.status_code, 200)
        return response.context['queue']

    def mark(self, entry, x='40', y='60'):
        """Tap one queue entry exactly the way the page does."""
        return self.client.post(entry['save_url'], {
            'source_field': entry['field'],
            'center_x_pct': x,
            'center_y_pct': y,
        })


class WhatIsInTheQueueTests(BackfillQueueTestCase):

    def test_an_unmarked_before_photo_is_in_the_queue(self):
        repair = self.make_repair()
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['kind'], 'repair')
        self.assertEqual(entry['id'], repair.pk)
        self.assertEqual(entry['field'], 'damage_photo_before')
        self.assertTrue(entry['src'])
        self.assertEqual(entry['save_url'],
                         reverse('save_photo_crop', args=[repair.pk]))

    def test_a_customer_submitted_photo_is_in_the_queue(self):
        """The shop marks the customer's photo — customers are never asked
        to tap (P2's standing decision)."""
        self.make_repair(damage_photo_before=None,
                         customer_submitted_photo=real_jpeg())
        fields = [entry['field'] for entry in self.entries()]
        self.assertEqual(fields, ['customer_submitted_photo'])

    def test_an_after_photo_is_never_in_the_queue(self):
        """It labels not_applicable and P6 won't zoom it for the customer
        either, so a tap on it is worth nothing at either end."""
        self.make_repair(damage_photo_before=None,
                         damage_photo_after=real_jpeg())
        self.assertEqual(self.entries(), [])
        self.assertNotIn('damage_photo_after', MARKABLE_FIELDS)

    def test_a_job_with_no_photo_is_not_in_the_queue(self):
        self.make_repair(damage_photo_before=None)
        self.assertEqual(self.entries(), [])

    def test_both_photos_on_one_job_are_two_entries(self):
        """The unit of work is a photo, not a job — a job can owe two marks."""
        self.make_repair(customer_submitted_photo=real_jpeg())
        fields = sorted(entry['field'] for entry in self.entries())
        self.assertEqual(
            fields, ['customer_submitted_photo', 'damage_photo_before'])

    def test_replacements_are_in_the_queue_too(self):
        """They are the only source of the negative class (P4a), so leaving
        them out would rebuild the sampling fault P4a existed to fix."""
        replacement = self.make_replacement(glass_position='WINDSHIELD')
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['kind'], 'replacement')
        self.assertEqual(entries[0]['id'], replacement.pk)
        self.assertEqual(
            entries[0]['save_url'],
            reverse('save_replacement_photo_crop', args=[replacement.pk]))

    def test_another_shops_photos_are_never_offered(self):
        other_user = User.objects.create_user(
            'other_backfill', password='pw', email='other@backfill.test')
        other = Tenant.objects.create(
            name='Other Shop', slug='other-backfill', plan='trial',
            is_active=True, owner=other_user, services_offered='both')
        TenantMembership.objects.create(
            tenant=other, user=other_user, role='owner')
        other_tech = Technician.objects.create(
            tenant=other, user=other_user, is_active=True, is_manager=True)
        other_customer = Customer.objects.create(tenant=other, name='Theirs')
        Repair.objects.create(
            tenant=other, technician=other_tech, customer=other_customer,
            unit_number='U-X', queue_status='COMPLETED',
            damage_photo_before=real_jpeg(),
        )
        self.assertEqual(self.entries(), [])

    def test_a_trashed_job_is_not_in_the_queue(self):
        """Soft delete is the shop saying they are done with the job; the
        default manager already excludes it and the queue inherits that."""
        repair = self.make_repair()
        self.assertEqual(len(self.entries()), 1)
        repair.delete()
        self.assertEqual(self.entries(), [])


class MarkedMeansMarkedByAHumanTests(BackfillQueueTestCase):

    def test_marking_a_photo_removes_it_from_the_queue(self):
        self.make_repair()
        entries = self.entries()
        self.assertEqual(len(entries), 1)

        response = self.mark(entries[0])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['success'])

        # The worklist is a live question, which is what makes reloading,
        # resuming and running from two devices all safe.
        self.assertEqual(self.entries(), [])

    def test_a_machine_guess_nobody_confirmed_stays_in_the_queue(self):
        """P3's sweep writes confirmed_by_human=False. Those rows are
        excluded from the dataset export by design, so they still need a
        person — and the queue opens on the guess so confirming is a
        glance."""
        repair = self.make_repair()
        RepairPhotoCrop.objects.create(
            tenant=self.shop, repair=repair,
            source_field='damage_photo_before',
            center_x_pct=30.0, center_y_pct=40.0,
            confirmed_by_human=False, suggested_x_pct=30.0,
            suggested_y_pct=40.0, suggested_by='saliency_v1',
            suggestion_score=0.42,
        )
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['at'], {'x': 30.0, 'y': 40.0})
        self.assertEqual(entries[0]['suggested']['by'], 'saliency_v1')

    def test_confirming_a_guess_posts_the_guess_back(self):
        """The distance between the guess and the human's mark is the only
        honest measure of the suggester (P4a), so the page must not drop it
        on the way through."""
        repair = self.make_repair()
        RepairPhotoCrop.objects.create(
            tenant=self.shop, repair=repair,
            source_field='damage_photo_before',
            center_x_pct=30.0, center_y_pct=40.0,
            confirmed_by_human=False, suggested_x_pct=30.0,
            suggested_y_pct=40.0, suggested_by='saliency_v1',
            suggestion_score=0.42,
        )
        entry = self.entries()[0]
        self.client.post(entry['save_url'], {
            'source_field': entry['field'],
            'center_x_pct': '55', 'center_y_pct': '65',
            'suggested_x_pct': entry['suggested']['x'],
            'suggested_y_pct': entry['suggested']['y'],
            'suggested_by': entry['suggested']['by'],
            'suggestion_score': entry['suggested']['score'],
        })
        crop = repair.photo_crops.get()
        self.assertTrue(crop.confirmed_by_human)
        self.assertEqual(crop.center_x_pct, 55.0)
        self.assertEqual(crop.suggested_x_pct, 30.0)
        self.assertEqual(crop.suggested_by, 'saliency_v1')
        self.assertEqual(self.entries(), [])

    def test_a_human_marked_photo_on_another_field_does_not_hide_this_one(self):
        """The crop row is unique per (job, field); the queue must key on
        the same pair or one mark would silence a job's other photo."""
        repair = self.make_repair(customer_submitted_photo=real_jpeg())
        entries = self.entries()
        before = next(e for e in entries if e['field'] == 'damage_photo_before')
        self.mark(before)
        fields = [entry['field'] for entry in self.entries()]
        self.assertEqual(fields, ['customer_submitted_photo'])


class OrderingTests(BackfillQueueTestCase):

    def test_completed_jobs_come_before_open_ones(self):
        """A completed job's photo carries a label today; an open one's is
        `unknown` until somebody finishes the work."""
        self.make_repair(status='IN_PROGRESS', unit_number='U-OPEN')
        self.make_repair(status='COMPLETED', unit_number='U-DONE')
        entries = self.entries()
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0]['trainable'])
        self.assertFalse(entries[1]['trainable'])

    def test_the_page_counts_the_trainable_ones_out_loud(self):
        self.make_repair(status='COMPLETED')
        self.make_repair(status='PENDING', unit_number='U-P')
        response = self.client.get(QUEUE_URL)
        self.assertEqual(response.context['queue_count'], 2)
        self.assertEqual(response.context['trainable_count'], 1)

    def test_tempered_glass_sorts_last(self):
        """A door window is always replaced no matter what hit it, so its
        photo is no evidence of anything — still worth marking for the
        customer's invoice, just not first."""
        self.make_replacement(glass_position='DRIVER_FRONT')
        self.make_repair()
        entries = self.entries()
        self.assertEqual([entry['kind'] for entry in entries],
                         ['repair', 'replacement'])
        self.assertFalse(entries[1]['trainable'])


class PermissionTests(BackfillQueueTestCase):
    """The queue and the endpoint must agree about who may mark what."""

    def make_plain_tech(self):
        user = User.objects.create_user(
            'plain_backfill', password='pw', email='plain@backfill.test')
        TenantMembership.objects.create(
            tenant=self.shop, user=user, role='technician')
        tech = Technician.objects.create(
            tenant=self.shop, user=user, is_active=True, is_manager=False,
            can_repair=True, can_replace=True,
        )
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = self.shop.id
        session.save()
        return tech, client

    def test_a_tech_is_not_offered_another_techs_job(self):
        """Anything the queue lists, the save endpoint must accept — so the
        queue runs the endpoint's own permission check, not a looser one of
        its own."""
        self.make_repair()  # assigned to self.tech
        _tech, client = self.make_plain_tech()
        response = client.get(QUEUE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['queue'], [])

    def test_a_tech_is_offered_their_own_job(self):
        tech, client = self.make_plain_tech()
        Repair.objects.create(
            tenant=self.shop, technician=tech, customer=self.customer,
            unit_number='U-MINE', queue_status='COMPLETED',
            damage_photo_before=real_jpeg(),
        )
        response = client.get(QUEUE_URL)
        self.assertEqual(len(response.context['queue']), 1)

    def test_everything_the_queue_offers_the_endpoint_accepts(self):
        """The invariant, stated directly: walk the whole queue and mark
        every entry. None may be refused."""
        self.make_repair()
        self.make_repair(status='IN_PROGRESS', unit_number='U-2',
                         customer_submitted_photo=real_jpeg())
        self.make_replacement(glass_position='WINDSHIELD')
        entries = self.entries()
        self.assertGreaterEqual(len(entries), 4)
        for entry in entries:
            response = self.mark(entry)
            self.assertEqual(
                response.status_code, 200,
                f"queue offered {entry['kind']} #{entry['id']} "
                f"{entry['field']} but the endpoint refused it",
            )
            self.assertTrue(json.loads(response.content)['success'])
        self.assertEqual(self.entries(), [])

    def test_the_page_needs_a_technician(self):
        client = Client()
        response = client.get(QUEUE_URL)
        self.assertIn(response.status_code, (302, 403))


class PayloadTests(BackfillQueueTestCase):

    def test_an_individuals_photo_is_never_captioned_unit_blank(self):
        """The documented fleet-vs-individual trap: an individual has no
        unit number, and printing 'Unit #' with nothing after it is how
        invoices came to read 'Unit #Silver Camry'."""
        individual = Customer.objects.create(
            tenant=self.shop, name='Jane Doe', customer_type='RETAIL')
        Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=individual,
            unit_number='', vehicle_year='2019', vehicle_make='Ford',
            vehicle_model='F-150',
            queue_status='COMPLETED', damage_photo_before=real_jpeg(),
        )
        subtitle = self.entries()[0]['subtitle']
        self.assertIn('Jane Doe', subtitle)
        self.assertIn('2019 Ford F-150', subtitle)
        self.assertNotIn('Unit #', subtitle)

    def test_a_fleet_photo_says_unit(self):
        self.make_repair(unit_number='4021')
        self.assertIn('Unit #4021', self.entries()[0]['subtitle'])

    def test_a_customer_with_no_vehicle_on_record_prints_no_bare_noun(self):
        Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='', queue_status='COMPLETED',
            damage_photo_before=real_jpeg(),
        )
        subtitle = self.entries()[0]['subtitle']
        self.assertEqual(subtitle, self.customer.name)

    def test_the_entry_links_back_to_the_job(self):
        repair = self.make_repair()
        self.assertEqual(self.entries()[0]['detail_url'],
                         reverse('repair_detail', args=[repair.pk]))

    def test_the_payload_is_escaped_into_the_page_not_interpolated(self):
        """It carries customer names and free-text vehicle descriptions
        into a <script> block, so it goes through json_script."""
        hostile = Customer.objects.create(
            tenant=self.shop, name='</script><img src=x onerror=alert(1)>',
            customer_type='RETAIL')
        Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=hostile,
            unit_number='', queue_status='COMPLETED',
            damage_photo_before=real_jpeg(),
        )
        html = self.client.get(QUEUE_URL).content.decode()
        self.assertIn('photoBackfillQueue', html)
        self.assertNotIn('<img src=x onerror=alert(1)>', html)


class EmptyAndDegradeTests(BackfillQueueTestCase):

    def test_an_empty_queue_says_so_and_loads_no_driver(self):
        response = self.client.get(QUEUE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['queue'], [])
        html = response.content.decode()
        self.assertIn('Nothing to mark', html)
        self.assertNotIn('photo_backfill.js', html)

    def test_a_fake_bytes_photo_is_still_offered(self):
        """The suite is full of b'fake image content' uploads and so is the
        wild (model-level writes skip ImageField validation). The queue
        offers them; the endpoint records the tap and retry_photo_crops
        finishes the image later. Never a crash, never a silent drop."""
        repair = self.make_repair(damage_photo_before=fake_photo())
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        response = self.mark(entries[0])
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertTrue(body['success'])
        self.assertFalse(body['cropped'])
        crop = repair.photo_crops.get()
        self.assertTrue(crop.confirmed_by_human)
        self.assertFalse(crop.cropped_image)

    def test_marking_never_touches_the_original(self):
        """The standing promise of the whole arc."""
        repair = self.make_repair()
        original = repair.damage_photo_before.name
        with repair.damage_photo_before.open('rb') as fh:
            before_bytes = fh.read()

        self.mark(self.entries()[0])

        repair.refresh_from_db()
        self.assertEqual(repair.damage_photo_before.name, original)
        with repair.damage_photo_before.open('rb') as fh:
            self.assertEqual(fh.read(), before_bytes)


class EntryPointTests(BackfillQueueTestCase):
    """The job list is the only door to this page."""

    def test_the_job_list_counts_the_backlog(self):
        self.make_repair()
        self.make_repair(unit_number='U-3')
        response = self.client.get(reverse('job_list'))
        self.assertEqual(response.context['unmarked_photo_count'], 2)
        self.assertIn('photos to mark', response.content.decode())

    def test_the_link_disappears_when_there_is_nothing_to_mark(self):
        response = self.client.get(reverse('job_list'))
        self.assertEqual(response.context['unmarked_photo_count'], 0)
        self.assertNotIn('photo to mark', response.content.decode())
        self.assertNotIn('photos to mark', response.content.decode())

    def test_the_count_matches_what_the_queue_will_show(self):
        """A number that promises more than the page delivers is worse than
        no number — so both go through the same permission filter."""
        self.make_repair()
        _tech, client = self.make_plain_tech_for(client_only=True)
        listed = client.get(reverse('job_list')).context['unmarked_photo_count']
        queued = len(client.get(QUEUE_URL).context['queue'])
        self.assertEqual(listed, queued)

    def make_plain_tech_for(self, client_only=False):
        user = User.objects.create_user(
            'plain_entry', password='pw', email='plain@entry.test')
        TenantMembership.objects.create(
            tenant=self.shop, user=user, role='technician')
        tech = Technician.objects.create(
            tenant=self.shop, user=user, is_active=True, is_manager=False,
            can_repair=True,
        )
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = self.shop.id
        session.save()
        return tech, client


class LabelRuleReuseTests(BackfillQueueTestCase):
    """label_for_photo is the same rule set label_for uses, reached before
    a crop row exists. One copy, or the queue and the export would disagree
    about what a photo is worth."""

    def test_a_completed_repair_is_repairable(self):
        repair = self.make_repair()
        self.assertEqual(
            label_for_photo(repair, 'damage_photo_before')[0], REPAIRABLE)

    def test_a_completed_windshield_replacement_is_not_repairable(self):
        replacement = self.make_replacement(glass_position='WINDSHIELD')
        self.assertEqual(
            label_for_photo(replacement, 'damage_photo_before')[0],
            NOT_REPAIRABLE)

    def test_an_open_job_is_unknown(self):
        repair = self.make_repair(status='IN_PROGRESS')
        self.assertEqual(
            label_for_photo(repair, 'damage_photo_before')[0], UNKNOWN)

    def test_the_crop_flavoured_entry_point_still_agrees(self):
        """label_for(crop) must keep answering exactly what it did before
        the refactor — the export depends on it."""
        from apps.technician_portal.services.photo_dataset import label_for

        repair = self.make_repair()
        crop = RepairPhotoCrop.objects.create(
            tenant=self.shop, repair=repair,
            source_field='damage_photo_before',
            center_x_pct=10.0, center_y_pct=10.0, confirmed_by_human=True,
        )
        self.assertEqual(label_for(crop), ('repairable', 'repair_completed'))


class ServiceApiTests(BackfillQueueTestCase):
    """backlog_for / backlog_size, without going through the view."""

    def request_for(self, user):
        from django.test import RequestFactory
        request = RequestFactory().get(QUEUE_URL)
        request.user = user
        request.tenant = self.shop
        return request

    def test_backlog_size_matches_backlog_for(self):
        self.make_repair()
        self.make_repair(unit_number='U-9', customer_submitted_photo=real_jpeg())
        request = self.request_for(self.owner_user)
        self.assertEqual(backlog_size(request, self.shop),
                         len(backlog_for(request, self.shop)))

    def test_no_tenant_means_no_backlog(self):
        self.make_repair()
        request = self.request_for(self.owner_user)
        self.assertEqual(backlog_for(request, None), [])
        self.assertEqual(backlog_size(request, None), 0)

    def test_the_limit_is_honoured(self):
        for index in range(4):
            self.make_repair(unit_number=f'U-L{index}')
        request = self.request_for(self.owner_user)
        self.assertEqual(len(backlog_for(request, self.shop, limit=2)), 2)
