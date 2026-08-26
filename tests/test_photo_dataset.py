"""
Both classes, and the export that proves it (P4a of the photo-ML arc).

Two things this session fixes, both structural:

  1. A RepairPhotoCrop could only hang off a Repair. A crop of a repair is
     by definition a photo of damage that WAS repaired, so the corpus was
     100% positive class and no amount of waiting would have made it
     trainable. Replacements now carry crops too.
  2. Nothing had ever counted what the corpus contains. The export command
     reports the class balance and the suggester's real correction distance
     every run, out loud.

See docs/strategy/PHOTO_ML_SESSIONS.md.
"""
import json
import os
import shutil
import tempfile
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, override_settings
from django.urls import reverse

from apps.technician_portal.models import (
    Repair, RepairPhotoCrop, Replacement, Technician,
)
from apps.technician_portal.services.photo_crops import (
    delete_crops_for, save_crop_for,
)
from apps.technician_portal.services.photo_dataset import (
    label_for, phase_of, record_for, suggestion_error_pct,
)
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from django.contrib.auth.models import User

from tests.test_photo_tap_crop import TapCropTestCase, fake_photo, real_jpeg


class ReplacementCropMixin:
    def make_replacement(self, **fields):
        fields.setdefault('queue_status', 'COMPLETED')
        fields.setdefault('glass_position', 'WINDSHIELD')
        fields.setdefault('unit_number', 'R-1')
        return Replacement.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            **fields,
        )

    def make_repair(self, **fields):
        fields.setdefault('queue_status', 'COMPLETED')
        fields.setdefault('unit_number', 'U-1')
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            **fields,
        )


class ReplacementCropModelTests(ReplacementCropMixin, TapCropTestCase):
    """The FK pair, and the constraint that keeps it honest."""

    def test_a_crop_can_hang_off_a_replacement(self):
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        crop = save_crop_for(replacement, 'damage_photo_before', 50.0, 50.0)
        self.assertIsNotNone(crop)
        self.assertIsNone(crop.repair)
        self.assertEqual(crop.replacement, replacement)
        self.assertEqual(crop.service, replacement)
        self.assertEqual(crop.service_kind, 'replacement')
        self.assertEqual(crop.tenant, self.shop)
        self.assertTrue(crop.cropped_image)
        # The original is untouched, exactly as on a repair.
        replacement.refresh_from_db()
        self.assertTrue(replacement.damage_photo_before)

    def test_a_row_with_neither_job_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RepairPhotoCrop.objects.create(
                tenant=self.shop, source_field='damage_photo_before',
                center_x_pct=50.0, center_y_pct=50.0,
            )

    def test_a_row_with_both_jobs_is_rejected(self):
        """Both FKs set would make .service ambiguous and double-count the
        row in an export — one photo, two labels."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        with self.assertRaises(IntegrityError), transaction.atomic():
            RepairPhotoCrop.objects.create(
                tenant=self.shop, repair=repair, replacement=replacement,
                source_field='damage_photo_before',
                center_x_pct=50.0, center_y_pct=50.0,
            )

    def test_re_tapping_a_replacement_replaces_rather_than_stacks(self):
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        save_crop_for(replacement, 'damage_photo_before', 20.0, 20.0)
        save_crop_for(replacement, 'damage_photo_before', 70.0, 40.0)
        crop = replacement.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 70.0)

    def test_a_repair_and_a_replacement_do_not_share_a_crop_row(self):
        """The unique constraints are per-FK; nothing about a repair's crop
        may leak onto a replacement that happens to share its id."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 10.0, 10.0)
        save_crop_for(replacement, 'damage_photo_before', 90.0, 90.0)

        self.assertEqual(RepairPhotoCrop.objects.count(), 2)
        self.assertEqual(repair.photo_crops.get().center_x_pct, 10.0)
        self.assertEqual(replacement.photo_crops.get().center_x_pct, 90.0)
        # Distinct derived files — the crop filename is namespaced by kind,
        # so a repair and a replacement can't overwrite each other.
        self.assertNotEqual(repair.photo_crops.get().cropped_image.name,
                            replacement.photo_crops.get().cropped_image.name)

    def test_deleting_a_replacement_photo_deletes_its_crop(self):
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        save_crop_for(replacement, 'damage_photo_before', 50.0, 50.0)
        delete_crops_for(replacement, 'damage_photo_before')
        self.assertEqual(replacement.photo_crops.count(), 0)

    def test_an_unreadable_replacement_photo_still_records_the_tap(self):
        """Fails open on a replacement the same way it does on a repair."""
        replacement = self.make_replacement(damage_photo_before=fake_photo())
        crop = save_crop_for(replacement, 'damage_photo_before', 33.0, 66.0)
        self.assertEqual(crop.center_x_pct, 33.0)
        self.assertFalse(crop.cropped_image)
        self.assertIsNone(crop.natural_width)


class ReplacementCropEndpointTests(ReplacementCropMixin, TapCropTestCase):
    """The detail-page endpoints, under the replacement's own permission."""

    def tap(self, replacement, source_field='customer_submitted_photo',
            x='40', y='60'):
        return self.client.post(
            reverse('save_replacement_photo_crop', args=[replacement.id]),
            {'source_field': source_field,
             'center_x_pct': x, 'center_y_pct': y},
        )

    def test_the_shop_can_mark_a_customers_replacement_photo(self):
        """The highest-value photo in the whole arc: a customer photographs
        damage, the shop quotes a replacement, and that is a labeled
        negative example nobody had to stage."""
        replacement = self.make_replacement(customer_submitted_photo=real_jpeg())
        response = self.tap(replacement)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertTrue(body['success'])
        self.assertTrue(body['cropped'])

        crop = replacement.photo_crops.get()
        self.assertEqual(crop.source_field, 'customer_submitted_photo')
        self.assertTrue(crop.confirmed_by_human)
        self.assertEqual(crop.created_by, self.tech)

    def test_another_shops_replacement_is_not_reachable(self):
        other_user = User.objects.create_user('other_p4a', password='pw')
        other = Tenant.objects.create(
            name='Other Shop', slug='other-shop-p4a', plan='trial',
            is_active=True, owner=other_user, services_offered='both')
        TenantMembership.objects.create(
            tenant=other, user=other_user, role='owner')
        # Replacement.technician is NOT NULL, so a second-tenant fixture
        # needs its own Technician (trap from P3).
        other_tech = Technician.objects.create(
            tenant=other, user=other_user, is_active=True,
            is_manager=True, can_replace=True)
        other_customer = Customer.objects.create(tenant=other, name='Theirs')
        theirs = Replacement.objects.create(
            tenant=other, technician=other_tech, customer=other_customer,
            unit_number='X-1', customer_submitted_photo=real_jpeg(),
        )
        response = self.tap(theirs)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_marking_a_photo_the_replacement_does_not_have_is_rejected(self):
        replacement = self.make_replacement()
        response = self.tap(replacement)
        self.assertEqual(response.status_code, 400)

    def test_get_is_rejected(self):
        replacement = self.make_replacement(customer_submitted_photo=real_jpeg())
        response = self.client.get(
            reverse('save_replacement_photo_crop', args=[replacement.id]))
        self.assertEqual(response.status_code, 405)

    def test_the_suggest_endpoint_answers_for_replacements_too(self):
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        response = self.client.post(
            reverse('suggest_replacement_photo_crop', args=[replacement.id]),
            {'source_field': 'damage_photo_before'},
        )
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        # 'found' depends on PHOTO_SUGGEST_ENABLED and on the image; either
        # answer is a success. Declining to guess is a normal outcome.
        self.assertTrue(body['success'])
        self.assertIn('found', body)

    def test_the_detail_page_offers_the_mark(self):
        replacement = self.make_replacement(customer_submitted_photo=real_jpeg())
        response = self.client.get(
            reverse('replacement_detail', args=[replacement.id]))
        content = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('photoCropEndpoint', content)
        self.assertIn('Mark the break', content)
        self.assertIn(
            reverse('save_replacement_photo_crop', args=[replacement.id]),
            content,
        )


class LabelTests(ReplacementCropMixin, TapCropTestCase):
    """What the shop did is the label. These are the rules that read it."""

    def crop_on(self, job, field='damage_photo_before'):
        return save_crop_for(job, field, 50.0, 50.0)

    def test_a_completed_repair_is_the_positive_class(self):
        crop = self.crop_on(self.make_repair(damage_photo_before=real_jpeg()))
        self.assertEqual(label_for(crop), ('repairable', 'repair_completed'))

    def test_a_completed_windshield_replacement_is_the_negative_class(self):
        crop = self.crop_on(
            self.make_replacement(damage_photo_before=real_jpeg()))
        self.assertEqual(
            label_for(crop),
            ('not_repairable', 'replacement_completed_windshield'))

    def test_side_glass_is_not_evidence_of_anything(self):
        """Tempered side and rear glass shatters and is always replaced.
        Labeling it 'not repairable' would teach the model that a door
        window full of holes is what unrepairable windshield damage looks
        like."""
        crop = self.crop_on(self.make_replacement(
            glass_position='FRONT_LEFT', damage_photo_before=real_jpeg()))
        label, source = label_for(crop)
        self.assertEqual(label, 'not_applicable')
        self.assertEqual(source, 'replacement_non_windshield')

    def test_an_unfinished_job_has_no_label_yet(self):
        crop = self.crop_on(self.make_repair(
            queue_status='IN_PROGRESS', damage_photo_before=real_jpeg()))
        self.assertEqual(label_for(crop), ('unknown', 'repair_in_progress'))

    def test_a_denied_job_is_unknown_not_negative(self):
        """A customer who declined the work said nothing about whether the
        glass could have been repaired."""
        crop = self.crop_on(self.make_repair(
            queue_status='DENIED', damage_photo_before=real_jpeg()))
        label, _ = label_for(crop)
        self.assertEqual(label, 'unknown')

    def test_an_after_photo_is_not_a_training_example(self):
        crop = self.crop_on(
            self.make_repair(damage_photo_after=real_jpeg()),
            field='damage_photo_after')
        self.assertEqual(label_for(crop), ('not_applicable', 'after_photo'))
        self.assertEqual(phase_of('damage_photo_after'), 'after')

    def test_unspecified_glass_is_negative_but_flagged(self):
        crop = self.crop_on(self.make_replacement(
            glass_position='', damage_photo_before=real_jpeg()))
        label, source = label_for(crop)
        self.assertEqual(label, 'not_repairable')
        self.assertEqual(source, 'replacement_completed_glass_unspecified')


class SuggestionErrorTests(ReplacementCropMixin, TapCropTestCase):
    def test_the_correction_distance_is_the_gap_between_guess_and_mark(self):
        from apps.technician_portal.services.photo_suggest import Suggestion

        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(
            repair, 'damage_photo_before', 50.0, 50.0,
            confirmed_by_human=True,
            suggestion=Suggestion(53.0, 54.0, 0.9, engine='test'),
        )
        self.assertAlmostEqual(suggestion_error_pct(crop), 5.0, places=3)

    def test_an_unconfirmed_row_reports_no_error(self):
        """A machine suggestion nobody looked at sits exactly on itself.
        Counting those would report the suggester as pixel-perfect."""
        from apps.technician_portal.services.photo_suggest import Suggestion

        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(
            repair, 'damage_photo_before', 50.0, 50.0,
            confirmed_by_human=False,
            suggestion=Suggestion(50.0, 50.0, 0.9, engine='test'),
        )
        self.assertIsNone(suggestion_error_pct(crop))

    def test_a_hand_tapped_row_reports_no_error(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        self.assertIsNone(suggestion_error_pct(crop))


class ExportTests(ReplacementCropMixin, TapCropTestCase):
    def setUp(self):
        super().setUp()
        self.out = tempfile.mkdtemp(prefix='photoml-export-')
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def export(self, **kwargs):
        out = StringIO()
        call_command('export_photo_dataset', stdout=out, stderr=StringIO(),
                     **kwargs)
        return out.getvalue()

    def read_jsonl(self):
        path = os.path.join(self.out, 'dataset.jsonl')
        with open(path, encoding='utf-8') as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def seed_both_classes(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 40.0, 40.0)
        replacement = self.make_replacement(
            customer_submitted_photo=real_jpeg())
        save_crop_for(replacement, 'customer_submitted_photo', 60.0, 60.0)
        return repair, replacement

    def test_the_bundle_has_an_image_and_a_row_per_crop(self):
        self.seed_both_classes()
        self.export(out=self.out)
        rows = self.read_jsonl()
        self.assertEqual(len(rows), 2)
        for row in rows:
            path = os.path.join(self.out, row['image'])
            self.assertTrue(os.path.exists(path), row['image'])
            self.assertGreater(os.path.getsize(path), 0)
        self.assertEqual(
            {row['label'] for row in rows},
            {'repairable', 'not_repairable'},
        )

    def test_the_bundle_names_nobody(self):
        """These are a real shop's real customers. Ids travel; names don't."""
        self.customer.name = 'Penske Truck Leasing'
        self.customer.save()
        self.seed_both_classes()
        self.export(out=self.out)
        with open(os.path.join(self.out, 'dataset.jsonl'), encoding='utf-8') as fh:
            blob = fh.read()
        self.assertNotIn('Penske', blob)
        self.assertNotIn('R-1', blob)
        self.assertNotIn('U-1', blob)

    def test_unconfirmed_suggestions_are_left_out_by_default(self):
        from apps.technician_portal.services.photo_suggest import Suggestion

        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 50.0, 50.0,
                      confirmed_by_human=False,
                      suggestion=Suggestion(50.0, 50.0, 0.9, engine='test'))
        self.export(out=self.out)
        self.assertEqual(self.read_jsonl(), [])

        self.export(out=self.out, include_unconfirmed=True)
        rows = self.read_jsonl()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]['confirmed_by_human'])

    def test_trainable_only_drops_the_undecided(self):
        self.seed_both_classes()
        pending = self.make_repair(
            queue_status='IN_PROGRESS', unit_number='U-2',
            damage_photo_before=real_jpeg())
        save_crop_for(pending, 'damage_photo_before', 50.0, 50.0)

        self.export(out=self.out)
        self.assertEqual(len(self.read_jsonl()), 3)

        self.export(out=self.out, trainable_only=True)
        rows = self.read_jsonl()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['trainable'] for row in rows))

    def test_the_crops_regenerate_byte_identically_from_the_originals(self):
        """The acceptance criterion for the export: the derived files are
        disposable. Coordinates plus the untouched original are enough to
        rebuild the whole dataset."""
        self.seed_both_classes()
        self.export(out=self.out)
        stored = {}
        for row in self.read_jsonl():
            with open(os.path.join(self.out, row['image']), 'rb') as fh:
                stored[row['crop_id']] = fh.read()

        regen_dir = tempfile.mkdtemp(prefix='photoml-regen-')
        self.addCleanup(shutil.rmtree, regen_dir, ignore_errors=True)
        self.export(out=regen_dir, from_originals=True)
        for row in json.loads('[' + ','.join(
                open(os.path.join(regen_dir, 'dataset.jsonl'),
                     encoding='utf-8').read().strip().splitlines()) + ']'):
            with open(os.path.join(regen_dir, row['image']), 'rb') as fh:
                self.assertEqual(fh.read(), stored[row['crop_id']],
                                 f"crop {row['crop_id']} did not regenerate")

    def test_stats_only_writes_nothing(self):
        self.seed_both_classes()
        output = self.export(stats_only=True)
        self.assertFalse(os.path.exists(os.path.join(self.out, 'dataset.jsonl')))
        self.assertIn('by label', output)

    def test_a_single_class_corpus_is_called_out_loudly(self):
        """The failure this whole session exists to make visible. Before
        P4a every corpus looked like this and nothing said so."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        output = self.export(out=self.out)
        self.assertIn('Only one class present', output)
        self.assertIn('not_repairable', output)

    def test_a_balanced_corpus_is_not_called_out(self):
        self.seed_both_classes()
        output = self.export(out=self.out)
        self.assertNotIn('Only one class present', output)
        self.assertIn('Trainable: 2', output)

    def test_an_empty_corpus_says_so_rather_than_failing(self):
        output = self.export(out=self.out)
        self.assertIn('Nothing to export', output)
        self.assertEqual(self.read_jsonl(), [])

    def test_the_summary_measures_the_suggester(self):
        from apps.technician_portal.services.photo_suggest import Suggestion

        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 50.0, 50.0,
                      confirmed_by_human=True,
                      suggestion=Suggestion(53.0, 54.0, 0.9, engine='test'))
        output = self.export(out=self.out)
        self.assertIn('median correction 5.0pp', output)
        row = self.read_jsonl()[0]
        self.assertEqual(row['suggestion_error_pct'], 5.0)
        self.assertEqual(row['suggested_by'], 'test')

    def test_the_summary_admits_when_it_cannot_measure_the_suggester(self):
        self.seed_both_classes()
        output = self.export(out=self.out)
        self.assertIn('nothing to say about the suggester', output)

    def test_a_row_awaiting_its_close_up_is_reported_not_silently_dropped(self):
        repair = self.make_repair(damage_photo_before=fake_photo())
        save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        output = self.export(out=self.out)
        self.assertEqual(self.read_jsonl(), [])
        self.assertIn('retry_photo_crops', output)

    def test_the_export_is_tenant_scoped(self):
        self.seed_both_classes()
        other_user = User.objects.create_user('other_export', password='pw')
        other = Tenant.objects.create(
            name='Other Export Shop', slug='other-export-p4a', plan='trial',
            is_active=True, owner=other_user, services_offered='both')
        other_tech = Technician.objects.create(
            tenant=other, user=other_user, is_active=True, is_manager=True)
        other_customer = Customer.objects.create(tenant=other, name='Theirs')
        theirs = Repair.objects.create(
            tenant=other, technician=other_tech, customer=other_customer,
            unit_number='X-9', queue_status='COMPLETED',
            damage_photo_before=real_jpeg())
        save_crop_for(theirs, 'damage_photo_before', 50.0, 50.0)

        self.export(out=self.out, tenant=self.shop.id)
        rows = self.read_jsonl()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row['tenant_id'] for row in rows}, {self.shop.id})

    def test_the_record_carries_the_box_needed_to_rebuild_it(self):
        repair, _ = self.seed_both_classes()
        self.export(out=self.out)
        row = next(r for r in self.read_jsonl() if r['job_kind'] == 'repair')
        crop = repair.photo_crops.get()
        self.assertEqual(row['crop_box'],
                         [crop.crop_left, crop.crop_top,
                          crop.crop_right, crop.crop_bottom])
        self.assertEqual(row['natural_width'], 800)
        self.assertEqual(row['natural_height'], 600)


@override_settings(PHOTO_SUGGEST_ENABLED=True)
class SweepCoversReplacementsTests(ReplacementCropMixin, TapCropTestCase):
    """manage.py suggest_photo_crops, over replacements.

    The switch is flipped with override_settings, never by patching
    ``is_enabled``. Patching it is a trap: the command module binds
    ``is_enabled`` at import, Django imports that module lazily inside
    call_command, and if that first import happens while photo_suggest is
    patched, the command keeps the mock for the rest of the process — long
    after the patch exits. It cost an afternoon; see PHOTO_ML_SESSIONS.md.
    """

    def sweep(self, **kwargs):
        out = StringIO()
        call_command('suggest_photo_crops', stdout=out, stderr=StringIO(),
                     **kwargs)
        return out.getvalue()

    def test_the_sweep_examines_replacements(self):
        from unittest.mock import patch
        from apps.technician_portal.services.photo_suggest import Suggestion

        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        with patch('apps.technician_portal.services.photo_suggest.suggest_for',
                   return_value=Suggestion(45.0, 55.0, 0.8, engine='test')):
            output = self.sweep(kind='replacement')

        crop = replacement.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 45.0)
        self.assertFalse(crop.confirmed_by_human)
        self.assertIn('replacement #', output)

    def test_the_sweep_leaves_a_replacements_after_photo_alone(self):
        """New glass. There is nothing in it to mark."""
        from unittest.mock import patch
        from apps.technician_portal.services.photo_suggest import Suggestion

        replacement = self.make_replacement(damage_photo_after=real_jpeg())
        with patch('apps.technician_portal.services.photo_suggest.suggest_for',
                   return_value=Suggestion(45.0, 55.0, 0.8, engine='test')):
            self.sweep(kind='replacement')
        self.assertEqual(replacement.photo_crops.count(), 0)

    def test_the_sweep_still_leaves_a_technicians_mark_alone(self):
        """A replacement's tap is as untouchable as a repair's."""
        from unittest.mock import patch
        from apps.technician_portal.services.photo_suggest import Suggestion

        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        save_crop_for(replacement, 'damage_photo_before', 12.0, 34.0)
        with patch('apps.technician_portal.services.photo_suggest.suggest_for',
                   return_value=Suggestion(90.0, 90.0, 0.9, engine='test')):
            self.sweep(kind='replacement')
        crop = replacement.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 12.0)
        self.assertTrue(crop.confirmed_by_human)
