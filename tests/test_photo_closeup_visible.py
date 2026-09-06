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

from django.urls import reverse

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Replacement
from apps.technician_portal.services.photo_crops import (
    focus_position, focus_positions_for, save_crop_for,
)
from core.models import Customer
from django.contrib.auth.models import User
from apps.technician_portal.services.photo_serving import (
    customer_photo_url, public_photo_url,
)
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

    def public_url(self, invoice, job, field='damage_photo_before'):
        """The app route the public page renders for one of a job's photos.

        Since P8 the page never prints a storage URL: the media bucket is
        private and every photo is served by the app under the invoice's
        own token.
        """
        return public_photo_url(
            invoice.id, generate_payment_token(invoice.id), job, field)

    # P6.2 split the flat photo list into (pairs, tiles): a job with both a
    # before and an after photo is one exhibit, everything else is a tile in
    # the grid it always rendered in. These three keep the older tests
    # reading the half they are actually about.

    def photo_tiles(self, invoice):
        """The loose tiles — every photo that is not half of a pair."""
        return _public_invoice_photos(invoice)[1]

    def photo_pairs(self, invoice):
        """The before/after exhibits."""
        return _public_invoice_photos(invoice)[0]

    def all_photos(self, invoice):
        """Every photo the page renders, pair members included."""
        pairs, tiles = _public_invoice_photos(invoice)
        return [photo for pair in pairs for photo in pair['photos']] + tiles


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

        photos = self.photo_tiles(invoice)
        self.assertEqual(len(photos), 1)
        self.assertEqual(photos[0]['focus'], '')
        self.assertTrue(photos[0]['reframe'])

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn(self.public_url(invoice, repair), html)
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

        photos = self.photo_tiles(invoice)
        self.assertEqual(photos[0]['url'], self.public_url(invoice, repair))

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

        photos = self.photo_tiles(invoice)
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

        urls = {p['url'] for p in self.photo_tiles(invoice)}
        self.assertEqual(urls, {self.public_url(invoice, repair),
                                self.public_url(invoice, replacement)})

    def test_a_job_billed_on_two_lines_is_still_one_job(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        self.add_line(invoice, repair)

        self.assertEqual(len(self.photo_tiles(invoice)), 1)

    def test_a_free_form_charge_line_contributes_nothing(self):
        invoice = self.make_invoice()
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Mobile service fee',
            quantity=1, unit_price=Decimal('25.00'), amount=Decimal('25.00'),
        )
        self.assertEqual(self.photo_tiles(invoice), [])


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

        photos = self.photo_tiles(invoice)
        self.assertEqual(photos[0]['caption'], 'Unit #4521 — Before')

    def test_an_individual_gets_their_car_not_a_unit_number(self):
        person = self.make_individual()
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=person,
            unit_number='', vehicle_year=2019, vehicle_make='Ford',
            vehicle_model='F-150', damage_photo_before=real_jpeg())
        invoice = self.make_invoice(customer=person)
        self.add_line(invoice, repair)

        photos = self.photo_tiles(invoice)
        self.assertEqual(photos[0]['caption'], '2019 Ford F-150 — Before')

    def test_nothing_on_record_prints_no_noun_at_all(self):
        """Better a bare 'Before' than 'Unit  — Before'."""
        person = self.make_individual()
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=person,
            unit_number='', damage_photo_before=real_jpeg())
        invoice = self.make_invoice(customer=person)
        self.add_line(invoice, repair)

        photos = self.photo_tiles(invoice)
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

        urls = {p['url'] for p in self.photo_tiles(invoice)}
        self.assertEqual(urls, {self.public_url(invoice, mine)})
        self.assertNotIn(self.public_url(invoice, theirs), urls)

    def test_a_photo_whose_storage_is_broken_is_a_404_not_a_500(self):
        """Since P8 the page links the app route, so a file the shop deleted
        out of storage is a broken tile on the customer's screen — never a
        500 on the invoice, and never a 500 on the photo route either."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        field = repair.damage_photo_before
        field.storage.delete(field.name)

        self.assertEqual(self.get_public_invoice(invoice).status_code, 200)
        response = self.client.get(self.public_url(invoice, repair))
        self.assertEqual(response.status_code, 404)


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
        self.assertIn(customer_photo_url(repair, 'damage_photo_before'), html)
        self.assertNotIn('style="object-position', html)
        self.assertIn('photo-blind-focus', html)


class InvoiceBeforeAfterPairTests(PhotoInvoiceTestCase):
    """P6.2: two photos of the same glass become one exhibit.

    A glass repair's product is invisible when the work is good — the chip
    becomes a faint blemish and the customer drives away with nothing to show
    anyone. Both photos were already on the model, already uploaded by the
    same technician, and already on this page, rendered as two tiles in a
    flat grid that never said they were the same spot an hour apart.
    """

    def test_both_photos_become_one_pair_and_no_loose_tiles(self):
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pairs, tiles = _public_invoice_photos(invoice)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(tiles, [])
        self.assertEqual(pairs[0]['before']['url'],
                         self.public_url(invoice, repair))
        self.assertEqual(pairs[0]['after']['url'],
                         self.public_url(invoice, repair, 'damage_photo_after'))
        self.assertEqual(pairs[0]['before']['label'], 'Before')
        self.assertEqual(pairs[0]['after']['label'], 'After')

    def test_the_pair_renders_side_by_side_in_one_figure(self):
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('class="photo-pair"', html)
        self.assertIn('class="photo-pair-frames"', html)
        self.assertIn(self.public_url(invoice, repair), html)
        self.assertIn(self.public_url(invoice, repair, 'damage_photo_after'), html)
        self.assertIn('>Before</span>', html)
        self.assertIn('>After</span>', html)

    def test_the_pair_is_captioned_once_not_once_per_photo(self):
        """One row, one mention: the vehicle is named for the exhibit, not
        for each half of it."""
        repair = self.make_repair(unit_number='4521',
                                  damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pairs = self.photo_pairs(invoice)
        self.assertEqual(pairs[0]['caption'],
                         'Unit #4521 — before and after the repair')

        html = self.get_public_invoice(invoice).content.decode()
        # <figcaption> appears nowhere on this page but the photo block.
        self.assertEqual(html.count('<figcaption>'), 1)
        self.assertEqual(
            html.count('Unit #4521 — before and after the repair'), 1)

    def test_each_half_still_names_itself_to_a_screen_reader(self):
        """The visible caption is shared; the alt text is not — a blind
        reader needs to know which image is which."""
        repair = self.make_repair(unit_number='4521',
                                  damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('alt="Unit #4521 — Before"', html)
        self.assertIn('alt="Unit #4521 — After"', html)

    def test_an_individual_gets_their_car_in_the_pair_caption(self):
        person = Customer.objects.create(
            tenant=self.shop, name='Dana Reyes', customer_type='RETAIL')
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=person,
            unit_number='', vehicle_year=2019, vehicle_make='Ford',
            vehicle_model='F-150', damage_photo_before=real_jpeg(),
            damage_photo_after=real_jpeg())
        invoice = self.make_invoice(customer=person)
        self.add_line(invoice, repair)

        self.assertEqual(self.photo_pairs(invoice)[0]['caption'],
                         '2019 Ford F-150 — before and after the repair')

    def test_nothing_on_record_still_prints_no_bare_noun(self):
        person = Customer.objects.create(
            tenant=self.shop, name='Sam Okoro', customer_type='RETAIL')
        repair = Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=person,
            unit_number='', damage_photo_before=real_jpeg(),
            damage_photo_after=real_jpeg())
        invoice = self.make_invoice(customer=person)
        self.add_line(invoice, repair)

        self.assertEqual(self.photo_pairs(invoice)[0]['caption'],
                         'Before and after the repair')
        html = self.get_public_invoice(invoice).content.decode()
        self.assertNotIn('Unit  —', html)


class InvoicePairFramingTests(PhotoInvoiceTestCase):
    """The pair inherits P6/P6.1 framing — and the after photo's exemption."""

    def test_a_marked_before_frames_on_its_tap_inside_the_pair(self):
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 63.0, 22.5)
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pair = self.photo_pairs(invoice)[0]
        self.assertEqual(pair['before']['focus'], '63.00% 22.50%')
        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('style="object-position: 63.00% 22.50%', html)

    def test_an_unmarked_before_keeps_the_measured_blind_default(self):
        """The P6.1 class has to survive the move out of the flat grid —
        losing it would silently put every unmarked pair back on dead
        centre, with nothing in any console to say so."""
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pair = self.photo_pairs(invoice)[0]
        self.assertEqual(pair['before']['focus'], '')
        self.assertTrue(pair['before']['reframe'])

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('class="blind-focus"', html)
        self.assertNotIn('style="object-position', html)

    def test_the_after_photo_is_never_reframed_in_a_pair_either(self):
        """A resin repair leaves a blemish. Zooming the after photo — by tap
        or by blind default — shows the customer the scar instead of the fix,
        which is the exact opposite of what the pair is for.

        The tap on the after photo IS collected at capture; matched framing
        would have to come from that, never from the before photo's
        coordinates, which describe a different shot from a different angle.
        """
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        save_crop_for(repair, 'damage_photo_after', 70.0, 70.0)
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pair = self.photo_pairs(invoice)[0]
        self.assertEqual(pair['after']['focus'], '')
        self.assertFalse(pair['after']['reframe'])

        html = self.get_public_invoice(invoice).content.decode()
        self.assertNotIn('70.00% 70.00%', html)
        # One image is aimed, the other is not: exactly one class attribute.
        self.assertEqual(html.count('class="blind-focus"'), 1)


class InvoicePairCompositionTests(PhotoInvoiceTestCase):
    """What is a pair, what is a tile, and what is neither."""

    def test_a_job_with_only_a_before_photo_renders_exactly_as_before(self):
        """No pair, and above all no empty 'After' slot — a placeholder
        shames the shop on its own invoice for a photo nobody took."""
        repair = self.make_repair(unit_number='4521',
                                  damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pairs, tiles = _public_invoice_photos(invoice)
        self.assertEqual(pairs, [])
        self.assertEqual(len(tiles), 1)
        self.assertEqual(tiles[0]['caption'], 'Unit #4521 — Before')

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('class="photo-grid"', html)
        # The class attribute, not the bare word: the page's own <style>
        # block names .photo-pair whether or not one is rendered.
        self.assertNotIn('class="photo-pair"', html)
        self.assertNotIn('>After</span>', html)

    def test_a_job_with_only_an_after_photo_is_a_tile_too(self):
        repair = self.make_repair(damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pairs, tiles = _public_invoice_photos(invoice)
        self.assertEqual(pairs, [])
        self.assertEqual([t['label'] for t in tiles], ['After'])

    def test_the_customer_photo_stays_its_own_tile_beside_the_pair(self):
        """It is a different camera on a different day — pairing it with the
        after shot would claim a comparison that was never taken."""
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg(),
                                  customer_submitted_photo=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        pairs, tiles = _public_invoice_photos(invoice)
        self.assertEqual(len(pairs), 1)
        self.assertEqual([t['label'] for t in tiles], ['Customer submitted'])

    def test_an_invoice_with_no_photos_renders_no_photo_block(self):
        invoice = self.make_invoice()
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Mobile service fee',
            quantity=1, unit_price=Decimal('25.00'), amount=Decimal('25.00'))

        self.assertEqual(_public_invoice_photos(invoice), ([], []))
        html = self.get_public_invoice(invoice).content.decode()
        self.assertNotIn('class="photos"', html)

    def test_two_jobs_with_pairs_are_two_exhibits(self):
        first = self.make_repair(unit_number='A-1',
                                 damage_photo_before=real_jpeg(),
                                 damage_photo_after=real_jpeg())
        second = self.make_repair(unit_number='B-2',
                                  damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, first)
        self.add_line(invoice, second)

        pairs, tiles = _public_invoice_photos(invoice)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(tiles, [])
        self.assertEqual({p['caption'] for p in pairs},
                         {'Unit #A-1 — before and after the repair',
                          'Unit #B-2 — before and after the repair'})

    def test_a_job_billed_on_two_lines_is_still_one_pair(self):
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        self.add_line(invoice, repair)

        self.assertEqual(len(self.photo_pairs(invoice)), 1)

    def test_broken_storage_is_still_not_fatal(self):
        """Building the page links the photos; it does not read them (P8).
        A pair whose files are gone still renders, and each photo is a 404
        on its own route rather than a 500 anywhere."""
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        for field in (repair.damage_photo_before, repair.damage_photo_after):
            field.storage.delete(field.name)

        self.assertEqual(len(self.photo_pairs(invoice)), 1)
        self.assertEqual(self.get_public_invoice(invoice).status_code, 200)
        for field in ('damage_photo_before', 'damage_photo_after'):
            response = self.client.get(self.public_url(invoice, repair, field))
            self.assertEqual(response.status_code, 404)


class InvoiceReplacementPairLanguageTests(PhotoInvoiceTestCase):
    """A replacement did not repair anything, and must not say it did."""

    def test_a_replacement_pair_reads_as_damage_and_new_glass(self):
        replacement = self.make_replacement(
            unit_number='7788',
            damage_photo_before=real_jpeg(),
            damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, replacement)

        pair = self.photo_pairs(invoice)[0]
        self.assertEqual(pair['before']['label'], 'Damage')
        self.assertEqual(pair['after']['label'], 'New glass')
        self.assertEqual(pair['caption'],
                         'Unit #7788 — the damage, and the new glass')

        html = self.get_public_invoice(invoice).content.decode()
        self.assertNotIn('before and after the repair', html)
        self.assertIn('>New glass</span>', html)

    def test_a_replacements_damage_photo_still_frames_on_its_tap(self):
        replacement = self.make_replacement(
            damage_photo_before=real_jpeg(), damage_photo_after=real_jpeg())
        save_crop_for(replacement, 'damage_photo_before', 18.0, 44.0)
        invoice = self.make_invoice()
        self.add_line(invoice, replacement)

        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn('style="object-position: 18.00% 44.00%', html)

    def test_a_mixed_invoice_pairs_each_job_in_its_own_language(self):
        repair = self.make_repair(unit_number='A-1',
                                  damage_photo_before=real_jpeg(),
                                  damage_photo_after=real_jpeg())
        replacement = self.make_replacement(
            unit_number='B-2',
            damage_photo_before=real_jpeg(), damage_photo_after=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        self.add_line(invoice, replacement)

        captions = {p['caption'] for p in self.photo_pairs(invoice)}
        self.assertEqual(captions,
                         {'Unit #A-1 — before and after the repair',
                          'Unit #B-2 — the damage, and the new glass'})
