"""
Tap-to-crop for repair damage photos (P1 of the photo-ML arc).

The technician taps the break on the photo they just attached; the server
crops a square around the tap and stores it on a RepairPhotoCrop row next
to the untouched original. See docs/strategy/PHOTO_ML_SESSIONS.md.

The suite-compat tests matter most: the rest of the test suite uploads
b"fake image content" photos, so the crop path must only open an image
when tap coordinates were actually posted, and must fail open when the
bytes aren't an image.
"""
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from PIL import Image

from apps.technician_portal.models import Repair, RepairPhotoCrop, Technician
from apps.technician_portal.services.photo_crops import (
    MIN_CROP_PX, save_crop_for,
)
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


def real_jpeg(width=800, height=600, name='photo.jpg', exif_orientation=None):
    """An actual decodable JPEG upload, unlike the suite's fake-bytes ones."""
    img = Image.new('RGB', (width, height), color=(120, 30, 30))
    buf = BytesIO()
    save_kwargs = {'format': 'JPEG'}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation  # 274 = Orientation tag
        save_kwargs['exif'] = exif
    img.save(buf, **save_kwargs)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


def fake_photo(name='fake.jpg'):
    return SimpleUploadedFile(name, b'fake image content', content_type='image/jpeg')


class TapCropTestCase(TestCase):
    def setUp(self):
        self.owner_user = User.objects.create_user(
            'owner_crop', password='pw', email='owner@crop.test')
        self.shop = Tenant.objects.create(
            name='Crop Shop', slug='crop-shop', plan='trial',
            is_active=True, owner=self.owner_user, services_offered='both',
        )
        TenantMembership.objects.create(
            tenant=self.shop, user=self.owner_user, role='owner')
        self.tech = Technician.objects.create(
            tenant=self.shop, user=self.owner_user,
            is_active=True, is_manager=True, can_repair=True, can_replace=True,
        )
        self.customer = Customer.objects.create(tenant=self.shop, name='Crop Fleet')

        self.client = Client()
        self.client.force_login(self.owner_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def post_job(self, **overrides):
        payload = {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'U-1',
            'work_done': 'Chip repair',
            'price': '55.00',
        }
        payload.update(overrides)
        return self.client.post(reverse('job_create'), payload)


class JobFormTapCropTests(TapCropTestCase):
    def test_tap_creates_crop_row_and_file(self):
        self.post_job(
            damage_photo_before=real_jpeg(),
            crop_x_damage_photo_before='40',
            crop_y_damage_photo_before='55',
        )
        repair = Repair.objects.get(tenant=self.shop, unit_number='U-1')
        crop = repair.photo_crops.get()
        self.assertEqual(crop.source_field, 'damage_photo_before')
        self.assertEqual(crop.tenant, self.shop)
        self.assertEqual(crop.center_x_pct, 40.0)
        self.assertEqual(crop.center_y_pct, 55.0)
        self.assertEqual(crop.natural_width, 800)
        self.assertEqual(crop.natural_height, 600)
        self.assertTrue(crop.cropped_image)
        # Square box, inside the image
        self.assertEqual(crop.crop_right - crop.crop_left,
                         crop.crop_bottom - crop.crop_top)
        self.assertGreaterEqual(crop.crop_left, 0)
        self.assertLessEqual(crop.crop_right, 800)
        self.assertLessEqual(crop.crop_bottom, 600)
        # The derived file is a real JPEG of the box's size
        with crop.cropped_image.open('rb') as f:
            derived = Image.open(f)
            self.assertEqual(derived.size,
                             (crop.crop_right - crop.crop_left,
                              crop.crop_bottom - crop.crop_top))
        # The original is untouched on the repair
        self.assertTrue(repair.damage_photo_before)

    def test_photo_without_coords_never_attempts_a_crop(self):
        """The rest of the suite posts photos with no coords — the crop
        path must not even try to open those. (save_crop_for is the only
        thing that opens the image.)"""
        with patch('apps.technician_portal.services.photo_crops.save_crop_for') as mock_crop:
            self.post_job(damage_photo_before=real_jpeg())
        mock_crop.assert_not_called()
        repair = Repair.objects.get(tenant=self.shop, unit_number='U-1')
        self.assertEqual(repair.photo_crops.count(), 0)

    def test_empty_coord_fields_are_a_skip(self):
        self.post_job(
            damage_photo_before=real_jpeg(),
            crop_x_damage_photo_before='',
            crop_y_damage_photo_before='',
        )
        repair = Repair.objects.get(tenant=self.shop, unit_number='U-1')
        self.assertEqual(repair.photo_crops.count(), 0)

    def test_unreadable_image_fails_open_and_records_the_tap(self):
        """Fake bytes can't get past QuickJobForm's ImageField, but they DO
        exist on the model in the wider suite (create-multi-break and the
        customer portal write request.FILES straight to the field), so the
        crop service must swallow them and keep the tap."""
        from apps.technician_portal.services.photo_crops import (
            process_tap_coordinates,
        )
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-1', damage_photo_before=fake_photo(),
        )
        process_tap_coordinates(
            repair,
            {'crop_x_damage_photo_before': '50',
             'crop_y_damage_photo_before': '50'},
        )
        crop = repair.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 50.0)
        self.assertFalse(crop.cropped_image)
        self.assertIsNone(crop.natural_width)

    def test_replacement_posts_are_ignored(self):
        self.post_job(
            service_type='replacement',
            damage_photo_before=real_jpeg(),
            crop_x_damage_photo_before='50',
            crop_y_damage_photo_before='50',
        )
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_heic_conversion_now_runs_on_the_job_form_path(self):
        """job_create was the one tech upload path storing raw HEIC."""
        with patch('common.utils.convert_heic_to_jpeg',
                   side_effect=lambda f: f) as mock_convert:
            self.post_job(damage_photo_before=fake_photo(name='shot.heic'))
        mock_convert.assert_called_once()

    def test_form_renders_crop_inputs_and_modal(self):
        response = self.client.get(reverse('job_create'))
        content = response.content.decode()
        self.assertIn('crop_x_damage_photo_before', content)
        self.assertIn('crop_y_damage_photo_after', content)
        self.assertIn('photoCropModal', content)
        self.assertIn('data-tap-crop', content)
        self.assertIn('photo_tap_crop.js', content)


class CropServiceTests(TapCropTestCase):
    def make_repair(self, photo):
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-2', damage_photo_before=photo,
        )

    def test_exif_orientation_is_applied_before_cropping(self):
        """Browsers render EXIF-upright and the tap happens on that
        rendering; the crop has to happen in the same frame."""
        repair = self.make_repair(
            real_jpeg(width=800, height=600, exif_orientation=6))
        crop = save_crop_for(repair, 'damage_photo_before', 90.0, 90.0)
        # Orientation 6 = 90° rotation: the upright image is 600x800
        self.assertEqual(crop.natural_width, 600)
        self.assertEqual(crop.natural_height, 800)
        self.assertLessEqual(crop.crop_right, 600)
        self.assertLessEqual(crop.crop_bottom, 800)

    def test_edge_tap_is_shifted_into_bounds(self):
        repair = self.make_repair(real_jpeg(width=900, height=900))
        crop = save_crop_for(repair, 'damage_photo_before', 1.0, 1.0)
        self.assertEqual(crop.crop_left, 0)
        self.assertEqual(crop.crop_top, 0)
        side = crop.crop_right - crop.crop_left
        self.assertGreaterEqual(side, MIN_CROP_PX)
        self.assertEqual(side, int(0.35 * 900))

    def test_tiny_image_crop_is_clamped_to_the_image(self):
        repair = self.make_repair(real_jpeg(width=200, height=150))
        crop = save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        # MIN_CROP_PX exceeds the image, so the box clamps to min(w, h)
        self.assertEqual(crop.crop_right - crop.crop_left, 150)
        self.assertLessEqual(crop.crop_right, 200)
        self.assertLessEqual(crop.crop_bottom, 150)

    def test_retap_replaces_the_previous_crop(self):
        repair = self.make_repair(real_jpeg())
        first = save_crop_for(repair, 'damage_photo_before', 20.0, 20.0)
        first_name = first.cropped_image.name
        first_storage = first.cropped_image.storage
        second = save_crop_for(repair, 'damage_photo_before', 80.0, 80.0)
        self.assertEqual(repair.photo_crops.count(), 1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.center_x_pct, 80.0)
        self.assertNotEqual(second.cropped_image.name, first_name)
        self.assertFalse(first_storage.exists(first_name))

    def test_missing_photo_is_a_noop(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-3',
        )
        self.assertIsNone(save_crop_for(repair, 'damage_photo_before', 50.0, 50.0))
        self.assertEqual(repair.photo_crops.count(), 0)


class UpdateRepairTapCropTests(TapCropTestCase):
    def test_deleting_the_photo_deletes_its_crop(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-4', damage_photo_before=real_jpeg(),
        )
        crop = save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        crop_name = crop.cropped_image.name
        storage = crop.cropped_image.storage

        self.client.post(
            reverse('update_repair', args=[repair.id]),
            {
                'customer': self.customer.id,
                'technician': self.tech.id,
                'unit_number': 'U-4',
                'queue_status': repair.queue_status,
                'repair_date': '2026-08-25 10:00',
                'damage_photo_before-DELETE': 'true',
            },
        )
        repair.refresh_from_db()
        self.assertFalse(repair.damage_photo_before)
        self.assertEqual(repair.photo_crops.count(), 0)
        self.assertFalse(storage.exists(crop_name))
