"""
The marked break becomes something the customer sees (P6 of the photo-ML arc).

Four sessions built tap-to-crop and the only place a crop had ever appeared
was an internal technician page. Production's marking rate was 1 photo out of
77 — a capture pipeline whose payoff is a future model does not capture. This
session puts the mark on the surfaces a customer already looks at, and fixes
the three bugs sitting on that path:

  1. The invoice tile was a blind centre-crop (`object-fit: cover` with no
     `object-position`) while a human-marked point sat unused in the database.
  2. Replacement line items contributed no photos at all, so the invoices
     where a close-up matters most had none.
  3. The caption was built from the raw `unit_number` column, so an
     individual's invoice read "Unit  — Before" with nothing after the noun.

The original file is what gets served in every case: this changes framing,
never assets. See docs/strategy/PHOTO_ML_SESSIONS.md.
"""
import uuid
from decimal import Decimal

from django.test import override_settings
from django.urls import reverse

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Replacement
from apps.technician_portal.services.photo_crops import (
    focus_position, focus_positions_for, save_crop_for,
)
from core.models import Customer
from django.contrib.auth.models import User
from rs_systems.views import _public_invoice_photos, generate_payment_token

from tests.test_photo_dataset import ReplacementCropMixin
from tests.test_photo_tap_crop import TapCropTestCase, real_jpeg


class PhotoInvoiceTestCase(ReplacementCropMixin, TapCropTestCase):
    """A tenant, a customer, and an invoice that can carry job line items."""

    def make_invoice(self, customer=None):
        BillingConfig.objects.get_or_create(tenant=self.shop)
        return Invoice.objects.create(
            tenant=self.shop,
            customer=customer or self.customer,
            invoice_number=f'INV-P6-{uuid.uuid4().hex[:8]}',
            status='SENT',
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
        )

    def add_line(self, invoice, job):
        kind = 'replacement' if isinstance(job, Replacement) else 'repair'
        return InvoiceLineItem.objects.create(
            invoice=invoice,
            description='Glass work',
            quantity=1,
            unit_price=Decimal('100.00'),
            amount=Decimal('100.00'),
            **{kind: job},
        )

    def get_public_invoice(self, invoice):
        token = generate_payment_token(invoice.id)
        return self.client.get(f'/invoice/{invoice.id}/{token}/')


class FocusPositionTests(TapCropTestCase):
    """The one function that turns a tap into a CSS crop origin."""

    def test_no_crop_is_no_position(self):
        self.assertEqual(focus_position(None), '')

    def test_a_tap_becomes_an_object_position(self):
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-1', damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 68.0, 41.0)
        self.assertEqual(focus_position(crop), '68.00% 41.00%')

    def test_a_tap_whose_crop_could_not_be_rendered_still_frames(self):
        """A null box means Pillow could not open the original. The tap is
        still the best information anyone has about where the break is, and
        framing needs only the tap."""
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-2', damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 20.0, 80.0)
        crop.crop_left = crop.crop_top = None
        crop.crop_right = crop.crop_bottom = None
        crop.cropped_image = None
        crop.save()
        self.assertEqual(focus_position(crop), '20.00% 80.00%')

    def test_out_of_range_coordinates_are_clamped(self):
        """CSS accepts values outside 0-100% and slides the image off the
        box; a bad row must degrade to an edge, never to a blank tile."""
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-3', damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        crop.center_x_pct, crop.center_y_pct = 140.0, -12.0
        crop.save()
        self.assertEqual(focus_position(crop), '100.00% 0.00%')

    def test_the_after_photo_is_never_reframed(self):
        """A resin repair leaves a visible blemish. Zooming the after photo
        shows the customer the scar instead of the fix."""
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=self.customer,
            unit_number='U-4',
            damage_photo_before=real_jpeg(), damage_photo_after=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 30.0, 30.0)
        save_crop_for(repair, 'damage_photo_after', 60.0, 60.0)
        positions = focus_positions_for(repair)
        self.assertIn('damage_photo_before', positions)
        self.assertNotIn('damage_photo_after', positions)


class InvoicePhotoFramingTests(PhotoInvoiceTestCase):
    """Bug 1: the tile was cropped on the middle of the frame."""

    def test_an_unmarked_photo_falls_back_to_the_measured_default(self):
        """No tap means no inline position — but not dead centre either.

        P6.1: an unmarked tile is aimed at (41%, 61%) by `.blind-focus`,
        because that is where technicians who DO mark actually tap. The data
        still records the photo as unmarked (`focus` stays '').
        """
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        photos = _public_invoice_photos(invoice)
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]['focus'], '')
        self.assertTrue(photos[0]['reframe'])

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn(repair.damage_photo_before.url, html)
        # No tap, so no inline attribute — the default comes from the sheet.
        self.assertNotIn('style="object-position', html)
        self.assertIn('class="blind-focus"', html)

    def test_a_marked_photo_is_framed_on_the_break(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 72.5, 33.25)
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('style="object-position: 72.50% 33.25%', html)

    def test_the_original_is_what_gets_served(self):
        """Framing changes the crop origin, not the asset. The customer can
        still open the whole photo, and no crop file is linked."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 40.0, 40.0)
        self.assertTrue(crop.cropped_image)
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        photos = _public_invoice_photos(invoice)
        self.assertEqual(photos[0]['url'], repair.damage_photo_before.url)

        html = self.get_public_invoice(invoice).content.decode()
        self.assertNotIn('repair_photos/crops/', html)

    def test_marking_a_photo_does_not_touch_the_original(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        before = repair.damage_photo_before.name
        save_crop_for(repair, 'damage_photo_before', 10.0, 90.0)
        repair.refresh_from_db()
        self.assertEqual(repair.damage_photo_before.name, before)


class InvoiceReplacementPhotoTests(PhotoInvoiceTestCase):
    """Bug 2: replacement line items contributed no photos at all."""

    def test_a_replacement_invoice_shows_its_photos(self):
        replacement = self.make_replacement(
            damage_photo_before=real_jpeg(),
            customer_submitted_photo=real_jpeg(),
        )
        invoice = self.make_invoice()
        self.add_line(invoice, replacement)

        photos = _public_invoice_photos(invoice)
        self.assertEqual({p['label'] for p in photos},
                         {'Before', 'Customer submitted'})

    def test_a_replacements_marked_break_is_framed_too(self):
        """The customer's own photo on a replacement is the one that answers
        'why couldn't you just repair it?'."""
        replacement = self.make_replacement(customer_submitted_photo=real_jpeg())
        save_crop_for(replacement, 'customer_submitted_photo', 15.0, 62.0)
        invoice = self.make_invoice()
        self.add_line(invoice, replacement)

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('style="object-position: 15.00% 62.00%', html)

    def test_a_mixed_invoice_shows_both_jobs(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        self.add_line(invoice, replacement)

        urls = {p['url'] for p in _public_invoice_photos(invoice)}
        self.assertEqual(urls, {repair.damage_photo_before.url,
                                replacement.damage_photo_before.url})

    def test_a_job_billed_on_two_lines_is_still_one_job(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        self.add_line(invoice, repair)

        self.assertEqual(len(_public_invoice_photos(invoice)), 1)

    def test_a_free_form_charge_line_contributes_nothing(self):
        invoice = self.make_invoice()
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Mobile service fee',
            quantity=1, unit_price=Decimal('25.00'), amount=Decimal('25.00'),
        )
        self.assertEqual(_public_invoice_photos(invoice), [])


class InvoicePhotoCaptionTests(PhotoInvoiceTestCase):
    """Bug 3: 'Unit  — Before', the individual-vs-fleet trap in CLAUDE.md."""

    def make_individual(self):
        return Customer.objects.create(
            tenant=self.shop, name='Dana Reyes', customer_type='RETAIL')

    def test_a_fleet_caption_still_names_the_unit(self):
        repair = self.make_repair(unit_number='4521',
                                  damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        photos = _public_invoice_photos(invoice)
        self.assertEqual(photos[0]['caption'], 'Unit #4521 — Before')

    def test_an_individual_gets_their_car_not_a_unit_number(self):
        person = self.make_individual()
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=person,
            unit_number='', vehicle_year=2019, vehicle_make='Ford',
            vehicle_model='F-150', damage_photo_before=real_jpeg())
        invoice = self.make_invoice(customer=person)
        self.add_line(invoice, repair)

        photos = _public_invoice_photos(invoice)
        self.assertEqual(photos[0]['caption'], '2019 Ford F-150 — Before')

    def test_nothing_on_record_prints_no_noun_at_all(self):
        """Better a bare 'Before' than 'Unit  — Before'."""
        person = self.make_individual()
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=person,
            unit_number='', damage_photo_before=real_jpeg())
        invoice = self.make_invoice(customer=person)
        self.add_line(invoice, repair)

        photos = _public_invoice_photos(invoice)
        self.assertEqual(photos[0]['caption'], 'Before')

        html = self.get_public_invoice(invoice).content.decode()
        self.assertNotIn('Unit  —', html)
        self.assertNotIn('Unit #  —', html)


class InvoicePhotoIsolationTests(PhotoInvoiceTestCase):
    """The page is public and tokened — it must leak nothing it did not
    already serve."""

    def test_a_bad_token_still_404s_with_photos_present(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 50.0, 50.0)
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        response = self.client.get(f'/invoice/{invoice.id}/deadbeef/')
        self.assertEqual(response.status_code, 404)

    def test_only_this_invoices_jobs_contribute(self):
        mine = self.make_repair(unit_number='MINE',
                                damage_photo_before=real_jpeg())
        theirs = self.make_repair(unit_number='THEIRS',
                                  damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, mine)

        urls = {p['url'] for p in _public_invoice_photos(invoice)}
        self.assertEqual(urls, {mine.damage_photo_before.url})
        self.assertNotIn(theirs.damage_photo_before.url, urls)

    def test_a_photo_whose_storage_is_broken_is_skipped_not_fatal(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        with override_settings(MEDIA_URL=None):
            photos = _public_invoice_photos(invoice)
        self.assertEqual(photos, [])
        self.assertEqual(self.get_public_invoice(invoice).status_code, 200)


class PortalRepairDetailFramingTests(PhotoInvoiceTestCase):
    """The portal's before photo sits in a 4:3 object-cover box — it was
    blind-cropped for exactly the same reason the invoice was."""

    def setUp(self):
        super().setUp()
        self.portal_user = User.objects.create_user(
            'portal_p6', password='pw', email='portal@p6.test')
        CustomerUser.objects.create(
            user=self.portal_user, customer=self.customer,
            is_primary_contact=True,
        )

    def portal_get(self, repair):
        self.client.force_login(self.portal_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()
        return self.client.get(
            reverse('customer_repair_detail', args=[repair.id]))

    def test_the_portal_frames_a_marked_break(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 25.0, 75.0)
        html = self.portal_get(repair).content.decode()
        self.assertIn('style="object-position: 25.00% 75.00%', html)

    def test_an_unmarked_portal_photo_falls_back_to_the_measured_default(self):
        """Same as the invoice tile: no tap, no inline style, but the box is
        aimed at (41%, 61%) by `.photo-blind-focus` rather than dead centre."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        html = self.portal_get(repair).content.decode()
        self.assertIn(repair.damage_photo_before.url, html)
        self.assertNotIn('style="object-position', html)
        self.assertIn('photo-blind-focus', html)
