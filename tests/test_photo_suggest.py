"""
Auto-suggested crop marks (P3 of the photo-ML arc).

P1/P2 made every damage photo tappable. P3 opens the modal with the marker
already placed, so marking a photo is a confirmation instead of a hunt, and
sweeps the backlog of photos nobody ever tapped.

Two things are load-bearing and tested hard here:

  1. **Nothing leaves this server.** The suggester is pure Pillow. If anyone
     ever reaches for a hosted vision API, test_suggester_makes_no_network_calls
     fails — that was an explicit product decision, not an implementation
     detail.
  2. **A guess is never mistaken for a technician's tap.** confirmed_by_human
     is what P4's export weights labels by; a sweep must not trample a real
     tap, and a retry must not quietly demote one.

See docs/strategy/PHOTO_ML_SESSIONS.md.
"""
import json
import math
import socket
from io import BytesIO, StringIO

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from PIL import Image, ImageDraw

from apps.technician_portal.models import Repair, RepairPhotoCrop
from apps.technician_portal.services import photo_suggest
from apps.technician_portal.services.photo_crops import (
    apply_suggestion, retry_crop, save_crop_for,
)
from apps.technician_portal.services.photo_suggest import (
    Suggestion, suggest_for, suggest_point,
)

from tests.test_photo_tap_crop import TapCropTestCase, fake_photo, real_jpeg


# ---------------------------------------------------------------------------
# Fixtures: photos that look enough like windshields to exercise the maths.
# ---------------------------------------------------------------------------

def glass_photo(width=800, height=600, seed=7):
    """Smooth sky-through-glass gradient with faint sensor noise."""
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)],
                  fill=(int(150 + 60 * t), int(170 + 55 * t), int(200 + 40 * t)))
    pixels = img.load()
    value = seed
    for i in range(0, width * height // 60):
        # A cheap deterministic scatter — random.seed() would be shared state.
        value = (value * 1103515245 + 12345) % 2147483648
        x = value % width
        y = (value // width) % height
        r, g, b = pixels[x, y]
        n = (value % 13) - 6
        pixels[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)),
                        max(0, min(255, b + n)))
    return img


def add_chip(img, cx, cy, size=26):
    """A star-shaped rock chip: bright centre with legs, like the real thing."""
    draw = ImageDraw.Draw(img)
    draw.ellipse([cx - size // 3, cy - size // 3, cx + size // 3, cy + size // 3],
                 fill=(245, 245, 250))
    for i in range(9):
        angle = i * (2 * math.pi / 9) + 0.3
        draw.line([(cx, cy), (cx + math.cos(angle) * size,
                              cy + math.sin(angle) * size)],
                  fill=(235, 238, 245), width=3)
    return img


def as_upload(img, name='damage.jpg', exif_orientation=None):
    from django.core.files.uploadedfile import SimpleUploadedFile
    buf = BytesIO()
    kwargs = {'format': 'JPEG', 'quality': 90}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        kwargs['exif'] = exif
    img.save(buf, **kwargs)
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


def as_stream(img):
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=90)
    buf.seek(0)
    return buf


class SuggesterTests(TapCropTestCase):
    """The maths, in isolation from any request."""

    def test_finds_a_chip_near_where_it_actually_is(self):
        img = add_chip(glass_photo(), 400, 300)
        result = suggest_point(as_stream(img))
        self.assertIsNotNone(result, "should have found a centred chip")
        # 400/800 and 300/600 are both 50%.
        self.assertLess(abs(result.x_pct - 50.0), 6.0)
        self.assertLess(abs(result.y_pct - 50.0), 6.0)
        self.assertGreater(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertEqual(result.engine, photo_suggest.SUGGESTER_VERSION)

    def test_finds_an_off_centre_chip(self):
        """The centre prior must be a nudge, not a magnet — a break in the
        corner of the glass is still the break."""
        img = add_chip(glass_photo(), 260, 190)
        result = suggest_point(as_stream(img))
        self.assertIsNotNone(result)
        self.assertLess(abs(result.x_pct - 32.5), 8.0)
        self.assertLess(abs(result.y_pct - 31.7), 8.0)

    def test_declines_on_undamaged_glass(self):
        """No answer beats a confident marker on a reflection."""
        self.assertIsNone(suggest_point(as_stream(glass_photo())))

    def test_declines_when_the_frame_is_busy_all_over(self):
        """Foliage or gravel behind the glass is bright everywhere at once.
        That is the case a peak-height score gets wrong and the spread test
        catches — see _locate."""
        img = glass_photo()
        draw = ImageDraw.Draw(img)
        value = 3
        for _ in range(2000):
            value = (value * 1103515245 + 12345) % 2147483648
            x = value % 800
            y = 250 + (value // 800) % 350
            draw.ellipse([x, y, x + 4 + value % 10, y + 4 + value % 8],
                         fill=(20 + value % 70, 60 + value % 70, 20 + value % 60))
        self.assertIsNone(suggest_point(as_stream(img)))

    def test_respects_exif_orientation(self):
        """Coordinates must be in the same upright space a tap lands in, or
        every portrait iPhone photo gets marked in the wrong place — the trap
        P1 already hit once."""
        img = add_chip(glass_photo(800, 600), 600, 150)
        upright = suggest_point(as_stream(img))
        self.assertIsNotNone(upright)

        buf = BytesIO()
        exif = Image.Exif()
        exif[274] = 6  # rotate 90° CW on display
        # Store the pixels pre-rotated so that display-upright == `img`.
        img.rotate(90, expand=True).save(buf, format='JPEG', quality=90, exif=exif)
        buf.seek(0)
        rotated = suggest_point(buf)
        self.assertIsNotNone(rotated)
        self.assertLess(abs(rotated.x_pct - upright.x_pct), 8.0)
        self.assertLess(abs(rotated.y_pct - upright.y_pct), 8.0)

    def test_unreadable_bytes_are_declined_not_raised(self):
        """The suite is full of b'fake image content' uploads."""
        self.assertIsNone(suggest_point(BytesIO(b'fake image content')))

    def test_tiny_image_is_declined(self):
        self.assertIsNone(suggest_point(as_stream(Image.new('RGB', (12, 12)))))

    def test_coordinates_are_always_in_range(self):
        """A mark outside 0-100% would crop somewhere that isn't the photo."""
        for cx, cy in ((20, 20), (780, 20), (20, 580), (780, 580), (400, 300)):
            result = suggest_point(as_stream(add_chip(glass_photo(), cx, cy)))
            if result is None:
                continue
            self.assertGreaterEqual(result.x_pct, 0.0)
            self.assertLessEqual(result.x_pct, 100.0)
            self.assertGreaterEqual(result.y_pct, 0.0)
            self.assertLessEqual(result.y_pct, 100.0)

    def test_suggester_makes_no_network_calls(self):
        """The whole design rests on this: customer photos stay on our
        infrastructure. A hosted vision model was considered and rejected.
        If this test starts failing, that decision has been reversed by
        accident — do not just delete it."""
        real_socket = socket.socket

        def forbidden(*args, **kwargs):
            raise AssertionError(
                "The crop suggester opened a network socket. Damage photos "
                "must never leave this server — see photo_suggest.py."
            )

        socket.socket = forbidden
        try:
            suggest_point(as_stream(add_chip(glass_photo(), 400, 300)))
        finally:
            socket.socket = real_socket

    @override_settings(PHOTO_SUGGEST_ENABLED=False)
    def test_kill_switch_stops_suggestions(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-OFF',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)),
        )
        self.assertFalse(photo_suggest.is_enabled())
        self.assertIsNone(suggest_for(repair, 'damage_photo_before'))

    def test_suggest_for_returns_none_when_there_is_no_photo(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-NOPHOTO',
        )
        self.assertIsNone(suggest_for(repair, 'damage_photo_before'))

    def test_suggest_for_swallows_unreadable_originals(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-FAKE', damage_photo_before=fake_photo(),
        )
        self.assertIsNone(suggest_for(repair, 'damage_photo_before'))


class SuggestEndpointTests(TapCropTestCase):
    """The detail page's non-blocking ask."""

    def make_repair(self, **fields):
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-S1', **fields,
        )

    def ask(self, repair, source_field='damage_photo_before'):
        return self.client.post(
            reverse('suggest_photo_crop', args=[repair.id]),
            {'source_field': source_field},
        )

    def test_returns_a_point_for_a_damaged_photo(self):
        repair = self.make_repair(
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        response = self.ask(repair)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertTrue(body['success'])
        self.assertTrue(body['found'])
        self.assertLess(abs(body['x_pct'] - 50.0), 8.0)
        self.assertLess(abs(body['y_pct'] - 50.0), 8.0)
        self.assertEqual(body['engine'], photo_suggest.SUGGESTER_VERSION)

    def test_no_guess_is_a_success_not_an_error(self):
        """The client treats found=False as 'you tap it', which is the
        pre-P3 experience. It must not look like a failure."""
        repair = self.make_repair(damage_photo_before=as_upload(glass_photo()))
        body = json.loads(self.ask(repair).content)
        self.assertTrue(body['success'])
        self.assertFalse(body['found'])

    def test_suggesting_writes_nothing(self):
        """Asking is idempotent and free — the row appears only when a
        technician confirms."""
        repair = self.make_repair(
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        self.ask(repair)
        self.assertEqual(repair.photo_crops.count(), 0)

    def test_originals_are_never_modified(self):
        photo = as_upload(add_chip(glass_photo(), 400, 300))
        repair = self.make_repair(damage_photo_before=photo)
        with repair.damage_photo_before.open('rb'):
            before = repair.damage_photo_before.read()
        self.ask(repair)
        repair.refresh_from_db()
        with repair.damage_photo_before.open('rb'):
            self.assertEqual(repair.damage_photo_before.read(), before)

    def test_get_is_rejected(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.client.get(
            reverse('suggest_photo_crop', args=[repair.id]))
        self.assertEqual(response.status_code, 405)

    def test_unknown_field_is_rejected(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.ask(repair, source_field='invoice_pdf')
        self.assertEqual(response.status_code, 400)

    def test_another_shops_repair_is_not_found(self):
        """The suggest endpoint must be no laxer than the save endpoint, or
        it becomes a way to read another shop's photos."""
        from django.contrib.auth.models import User
        from apps.tenants.models import Tenant, TenantMembership
        from core.models import Customer

        from apps.technician_portal.models import Technician

        other_user = User.objects.create_user('other_sug', password='pw')
        other = Tenant.objects.create(
            name='Other Glass', slug='other-glass-sug', plan='trial',
            is_active=True, owner=other_user,
        )
        TenantMembership.objects.create(
            tenant=other, user=other_user, role='owner')
        other_tech = Technician.objects.create(
            tenant=other, user=other_user, is_active=True, can_repair=True)
        other_customer = Customer.objects.create(tenant=other, name='Theirs')
        theirs = Repair.objects.create(
            tenant=other, technician=other_tech, customer=other_customer,
            unit_number='U-X', damage_photo_before=real_jpeg(),
        )
        response = self.ask(theirs)
        self.assertEqual(response.status_code, 404)


class ProvenanceTests(TapCropTestCase):
    """confirmed_by_human is what P4 weights labels by. Guard it."""

    def make_repair(self, unit='U-P1', **fields):
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number=unit, **fields,
        )

    def test_a_tap_is_confirmed(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 40.0, 60.0,
                             technician=self.tech)
        self.assertTrue(crop.confirmed_by_human)
        self.assertEqual(crop.suggested_by, '')
        self.assertIsNone(crop.suggested_x_pct)

    def test_a_sweep_suggestion_is_not_confirmed(self):
        repair = self.make_repair(
            unit='U-P2',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        crop = apply_suggestion(repair, 'damage_photo_before')
        self.assertIsNotNone(crop)
        self.assertFalse(crop.confirmed_by_human)
        self.assertEqual(crop.suggested_by, photo_suggest.SUGGESTER_VERSION)
        self.assertIsNone(crop.created_by)
        # It records where it guessed as well as where the mark sits, so the
        # two stay comparable after a technician moves it.
        self.assertEqual(crop.suggested_x_pct, crop.center_x_pct)
        self.assertEqual(crop.suggested_y_pct, crop.center_y_pct)

    def test_a_sweep_never_overwrites_a_technicians_tap(self):
        repair = self.make_repair(
            unit='U-P3',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        save_crop_for(repair, 'damage_photo_before', 10.0, 90.0,
                      technician=self.tech)
        self.assertIsNone(apply_suggestion(repair, 'damage_photo_before'))
        crop = repair.photo_crops.get()
        self.assertTrue(crop.confirmed_by_human)
        self.assertEqual(crop.center_x_pct, 10.0)

    def test_confirming_a_suggestion_keeps_what_was_suggested(self):
        """The gap between the guess and the correction is the only honest
        measure of whether the suggester works."""
        repair = self.make_repair(
            unit='U-P4',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        response = self.client.post(
            reverse('save_photo_crop', args=[repair.id]),
            {
                'source_field': 'damage_photo_before',
                'center_x_pct': '52.0', 'center_y_pct': '48.0',
                'suggested_x_pct': '50.0', 'suggested_y_pct': '50.0',
                'suggested_by': photo_suggest.SUGGESTER_VERSION,
                'suggestion_score': '0.91',
            },
        )
        self.assertEqual(response.status_code, 200)
        crop = repair.photo_crops.get()
        self.assertTrue(crop.confirmed_by_human)
        self.assertEqual(crop.center_x_pct, 52.0)
        self.assertEqual(crop.suggested_x_pct, 50.0)
        self.assertEqual(crop.suggested_y_pct, 50.0)
        self.assertAlmostEqual(crop.suggestion_score, 0.91)

    def test_a_malformed_suggestion_echo_does_not_lose_the_tap(self):
        repair = self.make_repair(unit='U-P5', damage_photo_before=real_jpeg())
        response = self.client.post(
            reverse('save_photo_crop', args=[repair.id]),
            {
                'source_field': 'damage_photo_before',
                'center_x_pct': '30', 'center_y_pct': '30',
                'suggested_x_pct': 'banana',
                'suggested_by': 'saliency-v1',
            },
        )
        self.assertEqual(response.status_code, 200)
        crop = repair.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 30.0)
        self.assertTrue(crop.confirmed_by_human)

    def test_retry_does_not_demote_a_confirmed_crop(self):
        """retry_crop re-derives the image; it must not re-label the photo."""
        repair = self.make_repair(unit='U-P6', damage_photo_before=fake_photo())
        crop = save_crop_for(repair, 'damage_photo_before', 45.0, 45.0,
                             technician=self.tech)
        self.assertFalse(crop.cropped_image)
        self.assertTrue(crop.confirmed_by_human)

        repair.damage_photo_before = real_jpeg()
        repair.save()
        self.assertTrue(retry_crop(crop))
        crop.refresh_from_db()
        self.assertTrue(crop.cropped_image)
        self.assertTrue(crop.confirmed_by_human)

    def test_retry_keeps_a_suggestion_unconfirmed(self):
        repair = self.make_repair(unit='U-P7', damage_photo_before=fake_photo())
        crop = save_crop_for(
            repair, 'damage_photo_before', 45.0, 45.0, technician=None,
            confirmed_by_human=False,
            suggestion=Suggestion(45.0, 45.0, 0.8),
        )
        repair.damage_photo_before = real_jpeg()
        repair.save()
        self.assertTrue(retry_crop(crop))
        crop.refresh_from_db()
        self.assertFalse(crop.confirmed_by_human)
        self.assertEqual(crop.suggested_by, photo_suggest.SUGGESTER_VERSION)
        self.assertAlmostEqual(crop.suggestion_score, 0.8)


class SweepCommandTests(TapCropTestCase):
    """manage.py suggest_photo_crops."""

    def make_repair(self, unit, **fields):
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number=unit, **fields,
        )

    def run_sweep(self, *args):
        out = StringIO()
        call_command('suggest_photo_crops', *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        self.make_repair(
            'U-C1',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        output = self.run_sweep('--dry-run')
        self.assertIn('would mark', output)
        self.assertEqual(RepairPhotoCrop.objects.count(), 0)

    def test_sweep_marks_an_unmarked_photo(self):
        repair = self.make_repair(
            'U-C2',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        self.run_sweep()
        crop = repair.photo_crops.get()
        self.assertFalse(crop.confirmed_by_human)
        self.assertTrue(crop.cropped_image)

    def test_sweep_leaves_the_original_photo_alone(self):
        """Drake's condition for running this at all."""
        photo = as_upload(add_chip(glass_photo(), 400, 300))
        repair = self.make_repair('U-C3', damage_photo_before=photo)
        with repair.damage_photo_before.open('rb'):
            before = repair.damage_photo_before.read()
        name = repair.damage_photo_before.name
        self.run_sweep()
        repair.refresh_from_db()
        self.assertEqual(repair.damage_photo_before.name, name)
        with repair.damage_photo_before.open('rb'):
            self.assertEqual(repair.damage_photo_before.read(), before)

    def test_sweep_skips_photos_that_already_have_a_crop(self):
        repair = self.make_repair(
            'U-C4',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        save_crop_for(repair, 'damage_photo_before', 11.0, 22.0,
                      technician=self.tech)
        self.run_sweep()
        crop = repair.photo_crops.get()
        self.assertEqual(crop.center_x_pct, 11.0)
        self.assertTrue(crop.confirmed_by_human)

    def test_running_the_sweep_twice_changes_nothing_the_second_time(self):
        repair = self.make_repair(
            'U-C5',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        self.run_sweep()
        first = repair.photo_crops.get()
        stamp = first.updated_at
        self.run_sweep()
        first.refresh_from_db()
        self.assertEqual(first.updated_at, stamp)
        self.assertEqual(repair.photo_crops.count(), 1)

    def test_sweep_declines_rather_than_guessing_on_clean_glass(self):
        repair = self.make_repair(
            'U-C6', damage_photo_before=as_upload(glass_photo()))
        output = self.run_sweep()
        self.assertEqual(repair.photo_crops.count(), 0)
        self.assertIn('declined to guess on 1', output)

    def test_sweep_is_tenant_scoped(self):
        from django.contrib.auth.models import User
        from apps.tenants.models import Tenant, TenantMembership
        from core.models import Customer

        from apps.technician_portal.models import Technician

        other_user = User.objects.create_user('other_sweep', password='pw')
        other = Tenant.objects.create(
            name='Other Sweep', slug='other-sweep', plan='trial',
            is_active=True, owner=other_user,
        )
        TenantMembership.objects.create(
            tenant=other, user=other_user, role='owner')
        other_tech = Technician.objects.create(
            tenant=other, user=other_user, is_active=True, can_repair=True)
        theirs = Repair.objects.create(
            tenant=other, technician=other_tech,
            customer=Customer.objects.create(tenant=other, name='Theirs'),
            unit_number='U-X',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)),
        )
        mine = self.make_repair(
            'U-C7',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        self.run_sweep('--tenant', str(self.shop.id))
        self.assertEqual(mine.photo_crops.count(), 1)
        self.assertEqual(theirs.photo_crops.count(), 0)

    def test_field_filter_only_touches_that_field(self):
        repair = self.make_repair(
            'U-C8',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)),
            damage_photo_after=as_upload(add_chip(glass_photo(), 400, 300)),
        )
        self.run_sweep('--field', 'damage_photo_before')
        self.assertEqual(
            [c.source_field for c in repair.photo_crops.all()],
            ['damage_photo_before'],
        )

    def test_unreadable_photos_do_not_stop_the_sweep(self):
        self.make_repair('U-C9', damage_photo_before=fake_photo())
        good = self.make_repair(
            'U-C10',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        self.run_sweep()
        self.assertEqual(good.photo_crops.count(), 1)

    @override_settings(PHOTO_SUGGEST_ENABLED=False)
    def test_kill_switch_stops_the_sweep(self):
        repair = self.make_repair(
            'U-C11',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        output = self.run_sweep()
        self.assertIn('off', output)
        self.assertEqual(repair.photo_crops.count(), 0)


class DetailPageMarkupTests(TapCropTestCase):
    """What the tech sees for a mark a machine placed."""

    def make_repair(self, unit, **fields):
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number=unit, **fields,
        )

    def test_unmarked_photo_offers_to_mark_and_exposes_the_suggest_endpoint(self):
        repair = self.make_repair('U-M1', damage_photo_before=real_jpeg())
        html = self.client.get(
            reverse('repair_detail', args=[repair.id])).content.decode()
        self.assertIn('Mark the break', html)
        self.assertIn(
            reverse('suggest_photo_crop', args=[repair.id]), html)

    def test_an_unconfirmed_suggestion_says_so(self):
        repair = self.make_repair(
            'U-M2',
            damage_photo_before=as_upload(add_chip(glass_photo(), 400, 300)))
        apply_suggestion(repair, 'damage_photo_before')
        html = self.client.get(
            reverse('repair_detail', args=[repair.id])).content.decode()
        self.assertIn('Check the mark', html)
        self.assertIn('We guessed this one', html)

    def test_a_technicians_tap_does_not_say_we_guessed(self):
        repair = self.make_repair('U-M3', damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 40.0, 60.0,
                      technician=self.tech)
        html = self.client.get(
            reverse('repair_detail', args=[repair.id])).content.decode()
        self.assertIn('Move the mark', html)
        self.assertNotIn('We guessed this one', html)
