"""
Crop coverage beyond the upload forms (P2 of the photo-ML arc).

P1 captured the tap on two of four surfaces, at upload time only. This
covers the rest: the repair detail page (crop or re-crop any photo already
on the job, including a customer-submitted one), the multi-break form (one
tap per break), and the sweep that finishes crops whose original wouldn't
open the first time. See docs/strategy/PHOTO_ML_SESSIONS.md.
"""
import json
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from PIL import Image

from apps.technician_portal.models import Repair, RepairPhotoCrop, Technician
from apps.technician_portal.services.photo_crops import save_crop_for
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer

from tests.test_photo_tap_crop import TapCropTestCase, fake_photo, real_jpeg


class DetailPageCropEndpointTests(TapCropTestCase):
    """The detail-page tap: its own POST, no form around it."""

    def make_repair(self, **fields):
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-D1', **fields,
        )

    def tap(self, repair, source_field='damage_photo_before', x='40', y='60'):
        return self.client.post(
            reverse('save_photo_crop', args=[repair.id]),
            {'source_field': source_field, 'center_x_pct': x, 'center_y_pct': y},
        )

    def test_tap_from_the_detail_page_creates_the_crop(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.tap(repair)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertTrue(body['success'])
        self.assertTrue(body['cropped'])
        self.assertTrue(body['crop_url'])

        crop = repair.photo_crops.get()
        self.assertEqual(crop.source_field, 'damage_photo_before')
        self.assertEqual(crop.tenant, self.shop)
        self.assertEqual(crop.created_by, self.tech)
        self.assertEqual(crop.center_x_pct, 40.0)
        self.assertEqual(crop.center_y_pct, 60.0)
        self.assertTrue(crop.cropped_image)
        # The original is untouched — the crop is a separate derived file.
        repair.refresh_from_db()
        self.assertTrue(repair.damage_photo_before)

    def test_customer_submitted_photo_is_croppable_by_the_shop(self):
        """P2's decision: customers are never asked to tap. Their photos get
        marked by the shop from here — and they are the best source of the
        'not repairable' class the classifier needs."""
        repair = self.make_repair(customer_submitted_photo=real_jpeg())
        response = self.tap(repair, source_field='customer_submitted_photo')
        self.assertEqual(response.status_code, 200)
        crop = repair.photo_crops.get()
        self.assertEqual(crop.source_field, 'customer_submitted_photo')
        self.assertTrue(crop.cropped_image)

    def test_re_tap_moves_the_mark_without_stacking_rows(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        self.tap(repair, x='20', y='20')
        first = repair.photo_crops.get()
        first_box = (first.crop_left, first.crop_top)

        self.tap(repair, x='75', y='30')
        self.assertEqual(repair.photo_crops.count(), 1)
        second = repair.photo_crops.get()
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(second.center_x_pct, 75.0)
        self.assertTrue(second.cropped_image)
        # The correction has to reach the pixels, not just the coordinates.
        self.assertNotEqual((second.crop_left, second.crop_top), first_box)

    def test_tap_on_an_unreadable_original_is_still_recorded(self):
        """Fail open, exactly like the upload path: the tech's knowledge of
        where the break is only exists now, so keep it and retry the image."""
        repair = self.make_repair(damage_photo_before=fake_photo())
        response = self.tap(repair)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertTrue(body['success'])
        self.assertFalse(body['cropped'])
        crop = repair.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 40.0)
        self.assertFalse(crop.cropped_image)

    def test_unknown_source_field_is_rejected(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.tap(repair, source_field='technician_notes')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_field_with_no_photo_is_rejected(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.tap(repair, source_field='damage_photo_after')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_bad_coordinates_are_rejected(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.tap(repair, x='over there')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_coordinates_are_clamped_to_the_photo(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        self.tap(repair, x='250', y='-40')
        crop = repair.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 100.0)
        self.assertEqual(crop.center_y_pct, 0.0)

    def test_get_is_not_allowed(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.client.get(reverse('save_photo_crop', args=[repair.id]))
        self.assertEqual(response.status_code, 405)

    def test_another_shops_repair_is_invisible(self):
        other_user = User.objects.create_user(
            'other_crop', password='pw', email='other@crop.test')
        other_shop = Tenant.objects.create(
            name='Other Shop', slug='other-crop-shop', plan='trial',
            is_active=True, owner=other_user, services_offered='both',
        )
        TenantMembership.objects.create(
            tenant=other_shop, user=other_user, role='owner')
        other_tech = Technician.objects.create(
            tenant=other_shop, user=other_user, is_active=True, is_manager=True)
        other_customer = Customer.objects.create(
            tenant=other_shop, name='Other Fleet')
        their_repair = Repair.objects.create(
            tenant=other_shop, technician=other_tech, customer=other_customer,
            unit_number='X-1', damage_photo_before=real_jpeg(),
        )
        response = self.tap(their_repair)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_a_tech_cannot_mark_someone_elses_job(self):
        stranger = User.objects.create_user(
            'stranger_crop', password='pw', email='stranger@crop.test')
        TenantMembership.objects.create(
            tenant=self.shop, user=stranger, role='technician')
        Technician.objects.create(
            tenant=self.shop, user=stranger, is_active=True, is_manager=False)
        repair = self.make_repair(damage_photo_before=real_jpeg())

        client = Client()
        client.force_login(stranger)
        session = client.session
        session['tenant_id'] = self.shop.id
        session.save()
        response = client.post(
            reverse('save_photo_crop', args=[repair.id]),
            {'source_field': 'damage_photo_before',
             'center_x_pct': '50', 'center_y_pct': '50'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)


class DetailPageCropUiTests(TapCropTestCase):
    def test_every_photo_gets_the_offer(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-D2',
            damage_photo_before=real_jpeg(),
            damage_photo_after=real_jpeg(),
            customer_submitted_photo=real_jpeg(),
        )
        content = self.client.get(
            reverse('repair_detail', args=[repair.id])).content.decode()
        self.assertIn('photoCropModal', content)
        self.assertIn('photo_crop_detail.js', content)
        self.assertIn(reverse('save_photo_crop', args=[repair.id]), content)
        for field in ('damage_photo_before', 'damage_photo_after',
                      'customer_submitted_photo'):
            self.assertIn(f'data-crop-field="{field}"', content)

    def test_an_existing_crop_shows_and_offers_a_correction(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-D3', damage_photo_before=real_jpeg(),
        )
        crop = save_crop_for(repair, 'damage_photo_before', 33.0, 66.0)
        content = self.client.get(
            reverse('repair_detail', args=[repair.id])).content.decode()
        self.assertIn(crop.cropped_image.url, content)
        self.assertIn('data-crop-at-x="33.00"', content)
        self.assertIn('data-crop-at-y="66.00"', content)
        self.assertIn('Move the mark', content)

    def test_a_repair_with_no_photos_ships_no_crop_ui(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-D4',
        )
        content = self.client.get(
            reverse('repair_detail', args=[repair.id])).content.decode()
        self.assertNotIn('data-crop-field', content)
        self.assertNotIn('photoCropModal', content)


class MultiBreakTapCropTests(TapCropTestCase):
    """Several breaks per windshield is several labeled examples per job —
    the reason multi-break coverage was worth the bespoke plumbing."""

    def post_breaks(self, breaks):
        payload = {
            'customer': self.customer.id,
            'unit_number': 'MB-1',
            'repair_date': '2026-08-25T10:00',
            'breaks_count': len(breaks),
        }
        for i, fields in enumerate(breaks):
            payload.setdefault(f'breaks[{i}][damage_type]', 'CHIP')
            for key, value in fields.items():
                payload[f'breaks[{i}][{key}]'] = value
        return self.client.post(
            reverse('create_multi_break_repair'), payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

    def test_each_break_gets_its_own_crop(self):
        self.post_breaks([
            {'damage_type': 'CHIP',
             'photo_before': real_jpeg(name='b1.jpg'),
             'crop_x_damage_photo_before': '25',
             'crop_y_damage_photo_before': '35'},
            {'damage_type': 'CHIP',
             'photo_before': real_jpeg(name='b2.jpg'),
             'crop_x_damage_photo_before': '70',
             'crop_y_damage_photo_before': '80'},
        ])
        repairs = Repair.objects.filter(
            tenant=self.shop, unit_number='MB-1').order_by('break_number')
        self.assertEqual(repairs.count(), 2)
        self.assertEqual(RepairPhotoCrop.objects.count(), 2)

        first, second = repairs[0].photo_crops.get(), repairs[1].photo_crops.get()
        self.assertEqual((first.center_x_pct, first.center_y_pct), (25.0, 35.0))
        self.assertEqual((second.center_x_pct, second.center_y_pct), (70.0, 80.0))
        self.assertTrue(first.cropped_image)
        self.assertTrue(second.cropped_image)
        self.assertEqual(first.created_by, self.tech)

    def test_before_and_after_taps_on_one_break(self):
        self.post_breaks([
            {'damage_type': 'CHIP',
             'photo_before': real_jpeg(name='b.jpg'),
             'photo_after': real_jpeg(name='a.jpg'),
             'crop_x_damage_photo_before': '10',
             'crop_y_damage_photo_before': '10',
             'crop_x_damage_photo_after': '90',
             'crop_y_damage_photo_after': '90'},
        ])
        repair = Repair.objects.get(tenant=self.shop, unit_number='MB-1')
        fields = {c.source_field: c for c in repair.photo_crops.all()}
        self.assertEqual(set(fields), {'damage_photo_before', 'damage_photo_after'})
        self.assertEqual(fields['damage_photo_after'].center_x_pct, 90.0)

    def test_a_break_whose_tap_was_skipped_gets_no_crop(self):
        self.post_breaks([
            {'damage_type': 'CHIP',
             'photo_before': real_jpeg(name='b1.jpg'),
             'crop_x_damage_photo_before': '25',
             'crop_y_damage_photo_before': '35'},
            {'damage_type': 'CHIP', 'photo_before': real_jpeg(name='b2.jpg')},
        ])
        repairs = Repair.objects.filter(
            tenant=self.shop, unit_number='MB-1').order_by('break_number')
        self.assertEqual(repairs.count(), 2)
        self.assertEqual(repairs[0].photo_crops.count(), 1)
        self.assertEqual(repairs[1].photo_crops.count(), 0)

    def test_a_batch_with_no_taps_at_all_still_saves(self):
        response = self.post_breaks([
            {'damage_type': 'CHIP', 'photo_before': real_jpeg(name='b1.jpg')},
        ])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Repair.objects.filter(tenant=self.shop, unit_number='MB-1').count(), 1)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_form_ships_the_crop_modal(self):
        content = self.client.get(
            reverse('create_multi_break_repair')).content.decode()
        self.assertIn('photoCropModal', content)
        self.assertIn('photo_crop_modal.js', content)


class RetryPhotoCropsCommandTests(TapCropTestCase):
    def stranded_crop(self, unit='U-R1'):
        """A tap on record whose image never got made, then a readable
        original underneath it — the state the sweep exists to resolve."""
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number=unit, damage_photo_before=fake_photo(),
        )
        crop = save_crop_for(repair, 'damage_photo_before', 45.0, 55.0,
                             technician=self.tech)
        self.assertFalse(crop.cropped_image)
        repair.damage_photo_before = real_jpeg()
        repair.save(update_fields=['damage_photo_before'])
        return repair, crop

    def run_command(self, *args):
        out = StringIO()
        call_command('retry_photo_crops', *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_the_sweep_finishes_a_stranded_crop(self):
        repair, crop = self.stranded_crop()
        output = self.run_command()
        crop.refresh_from_db()
        self.assertTrue(crop.cropped_image)
        self.assertEqual(crop.natural_width, 800)
        # The tap is unchanged — that's the point of storing percentages.
        self.assertEqual(crop.center_x_pct, 45.0)
        self.assertEqual(crop.center_y_pct, 55.0)
        self.assertIn('Produced 1', output)
        with crop.cropped_image.open('rb') as f:
            self.assertEqual(
                Image.open(f).size,
                (crop.crop_right - crop.crop_left, crop.crop_bottom - crop.crop_top),
            )

    def test_dry_run_changes_nothing(self):
        repair, crop = self.stranded_crop()
        output = self.run_command('--dry-run')
        crop.refresh_from_db()
        self.assertFalse(crop.cropped_image)
        self.assertIn('would retry', output)

    def test_finished_crops_are_left_alone(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-R2', damage_photo_before=real_jpeg(),
        )
        crop = save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        name = crop.cropped_image.name
        self.run_command()
        crop.refresh_from_db()
        self.assertEqual(crop.cropped_image.name, name)

    def test_a_still_unreadable_original_keeps_its_tap_for_next_time(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-R3', damage_photo_before=fake_photo(),
        )
        crop = save_crop_for(repair, 'damage_photo_before', 60.0, 60.0)
        output = self.run_command()
        crop.refresh_from_db()
        self.assertFalse(crop.cropped_image)
        self.assertEqual(crop.center_x_pct, 60.0)
        self.assertIn('still unreadable', output)

    def test_the_tenant_filter_scopes_the_sweep(self):
        repair, crop = self.stranded_crop()
        self.run_command('--tenant', str(self.shop.id + 999))
        crop.refresh_from_db()
        self.assertFalse(crop.cropped_image)
