"""
The customer can KEEP the photos, not just look at them (P7 of the photo-ML arc).

P6/P6.1/P6.2 made the damage photo legible on the invoice. None of them made
it keepable: the only way to save one was right-click, one photo at a time,
landing in Downloads as `IMG_4686.jpg` — no invoice, no unit, no date. A
fleet manager's record is a file in a folder, per unit, per date, and that is
what these tests describe.

The three things worth breaking a build over:

  1. **The filename says what the file is** — and never says "Unit" about an
     individual's car (the individual-vs-fleet rule in CLAUDE.md applies to a
     filename exactly as it does to an invoice line).
  2. **Bytes come from storage, not from the photo's public URL.** The
     server must not make an anonymous HTTP round trip to S3 for a file it
     already has; that also breaks the day the media bucket is closed.
  3. **The public route is gated exactly like /pdf/**, and one unreadable
     photo does not cost the customer the rest of the archive.
"""
import zipfile
from io import BytesIO
from unittest.mock import patch

from django.urls import reverse

from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Replacement
from apps.technician_portal.services import photo_archive
from apps.technician_portal.services.photo_archive import (
    build_photo_zip, entries_for_job, entries_for_jobs, zip_name_for_job,
)
from core.models import Customer
from django.contrib.auth.models import User
from rs_systems.views import generate_payment_token

from tests.test_photo_closeup_visible import PhotoInvoiceTestCase
from tests.test_photo_tap_crop import real_jpeg


class PhotoDownloadTestCase(PhotoInvoiceTestCase):
    """`make_repair` in the shared mixin always uses `self.customer`; these
    tests need jobs on other accounts too."""

    def repair_for(self, customer, **fields):
        fields.setdefault('queue_status', 'COMPLETED')
        return Repair.objects.create(
            tenant=self.shop, technician=self.tech, customer=customer, **fields)


def zip_names(response):
    """The entry names inside a ZIP response."""
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        return archive.namelist()


class FilenameTests(PhotoDownloadTestCase):
    """A file called IMG_4686.jpg is not a record. These names are."""

    def test_fleet_photo_is_named_for_invoice_unit_and_date(self):
        repair = self.make_repair(unit_number='4521')
        repair.damage_photo_before = real_jpeg(name='IMG_4686.jpg')
        repair.save()

        names = [name for name, _field in
                 entries_for_job(repair, invoice_number='INV-1042')]
        date = repair.service_date.strftime('%Y-%m-%d')
        self.assertEqual(names, [f'INV-1042_Unit-4521_{date}_Before.jpg'])

    def test_individual_gets_their_vehicle_and_never_the_word_unit(self):
        """`Unit_.jpg` is the filename version of the 'Unit  — Before' bug."""
        person = Customer.objects.create(
            tenant=self.shop, name='Dana Reyes', customer_type='RETAIL')
        repair = self.repair_for(
            person, vehicle_year='2019', vehicle_make='Ford',
            vehicle_model='F-150', unit_number='',
            damage_photo_before=real_jpeg())

        name = entries_for_job(repair, invoice_number='INV-1042')[0][0]
        self.assertIn('2019-Ford-F-150', name)
        self.assertNotIn('Unit', name)

    def test_a_job_with_nothing_on_record_still_names_the_photo(self):
        """No invoice, no vehicle: the label alone, never a bare separator."""
        repair = self.make_repair(
            unit_number='', damage_photo_before=real_jpeg())
        repair.service_date = None  # a job the shop never dated

        name = entries_for_job(repair)[0][0]
        self.assertEqual(name, 'Before.jpg')

    def test_vehicle_label_is_sanitized_for_a_filesystem(self):
        """A vehicle box is free text and can hold a slash."""
        person = Customer.objects.create(
            tenant=self.shop, name='Slash Co', customer_type='RETAIL')
        repair = self.repair_for(
            person, vehicle_make='Ford', vehicle_model='F-150 / spare',
            unit_number='', damage_photo_before=real_jpeg())

        name = entries_for_job(repair)[0][0]
        self.assertNotIn('/', name)

    def test_two_breaks_on_one_unit_do_not_collide(self):
        """A multi-break session is a normal ticket, and a ZIP will happily
        hold the same name twice while the customer's unzipper keeps one."""
        jobs = []
        for _ in range(2):
            repair = self.make_repair(unit_number='4521')
            repair.damage_photo_before = real_jpeg()
            repair.save()
            jobs.append(repair)

        names = [name for name, _f in entries_for_jobs(jobs, invoice_number='INV-1')]
        self.assertEqual(len(names), 2)
        self.assertEqual(len(set(names)), 2)

    def test_extension_follows_the_stored_file(self):
        repair = self.make_repair(unit_number='7')
        repair.damage_photo_before = real_jpeg(name='shot.PNG')
        repair.save()
        self.assertTrue(entries_for_job(repair)[0][0].endswith('.png'))


class ZipBuildingTests(PhotoDownloadTestCase):
    """The archive itself: read from storage, tolerate a missing file."""

    def test_photos_are_read_through_storage_not_over_http(self):
        """Re-fetching our own public URL would be an anonymous round trip
        to S3 for a file we already have — and it breaks the day the bucket
        is closed."""
        repair = self.make_repair(unit_number='4521')
        repair.damage_photo_before = real_jpeg()
        repair.save()

        def refuse(self):
            raise AssertionError('photo bytes must not be fetched over HTTP')

        entries = entries_for_job(repair)
        with patch.object(type(repair.damage_photo_before), 'url',
                          property(refuse)):
            payload, written = build_photo_zip(entries)
        self.assertEqual(len(written), 1)
        self.assertTrue(payload)

    def test_a_photo_missing_from_storage_does_not_lose_the_others(self):
        repair = self.make_repair(unit_number='4521')
        repair.damage_photo_before = real_jpeg()
        repair.damage_photo_after = real_jpeg()
        repair.save()

        entries = entries_for_job(repair)
        broken, good = entries[0], entries[1]

        def explode(*args, **kwargs):
            raise OSError('gone from the bucket')

        with patch.object(broken[1], 'open', side_effect=explode):
            payload, written = build_photo_zip([broken, good])

        self.assertEqual(written, [good[0]])
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = archive.namelist()
            # A partial archive says so rather than looking complete.
            self.assertIn('README.txt', names)
            self.assertIn(broken[0], archive.read('README.txt').decode())

    def test_nothing_readable_yields_no_response_at_all(self):
        """The caller's cue to 404 rather than hand over an empty archive."""
        self.assertIsNone(photo_archive.photo_zip_response([], 'x.zip'))

    def test_the_zip_holds_the_original_bytes(self):
        repair = self.make_repair(unit_number='4521')
        upload = real_jpeg()
        raw = upload.read()
        upload.seek(0)
        repair.damage_photo_before = upload
        repair.save()

        payload, written = build_photo_zip(entries_for_job(repair))
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            self.assertEqual(archive.read(written[0]), raw)


class PublicInvoiceZipTests(PhotoDownloadTestCase):
    """The fleet answer: one control, every photo on the invoice."""

    def zip_url(self, invoice, token=None):
        return (f'/invoice/{invoice.id}/'
                f'{token or generate_payment_token(invoice.id)}/photos.zip')

    def make_invoiced_repair(self, invoice, unit_number='4521'):
        repair = self.make_repair(unit_number=unit_number)
        repair.damage_photo_before = real_jpeg()
        repair.damage_photo_after = real_jpeg()
        repair.save()
        self.add_line(invoice, repair)
        return repair

    def test_one_request_returns_every_photo_on_the_invoice(self):
        invoice = self.make_invoice()
        self.make_invoiced_repair(invoice, unit_number='4521')
        self.make_invoiced_repair(invoice, unit_number='4522')

        response = self.client.get(self.zip_url(invoice))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertEqual(len(zip_names(response)), 4)

    def test_the_download_is_an_attachment_named_for_the_invoice(self):
        invoice = self.make_invoice()
        self.make_invoiced_repair(invoice)
        response = self.client.get(self.zip_url(invoice))
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn(f'Invoice_{invoice.invoice_number}_Photos.zip',
                      response['Content-Disposition'])

    def test_a_wrong_token_is_refused_exactly_like_the_pdf(self):
        invoice = self.make_invoice()
        self.make_invoiced_repair(invoice)
        self.assertEqual(
            self.client.get(self.zip_url(invoice, token='nope')).status_code, 404)

    def test_an_invoice_with_no_photos_404s_rather_than_shipping_an_empty_zip(self):
        invoice = self.make_invoice()
        repair = self.make_repair(unit_number='4521')
        self.add_line(invoice, repair)
        self.assertEqual(self.client.get(self.zip_url(invoice)).status_code, 404)

    def test_the_page_offers_the_download_and_only_when_there_is_one(self):
        invoice = self.make_invoice()
        with_photos = self.get_public_invoice(invoice)
        self.assertNotContains(with_photos, 'photos.zip')

        self.make_invoiced_repair(invoice)
        self.assertContains(self.get_public_invoice(invoice), 'photos.zip')

    def test_the_zip_carries_the_same_jobs_the_page_shows(self):
        """A ZIP that misses a photo the page showed is worse than no ZIP."""
        invoice = self.make_invoice()
        self.make_invoiced_repair(invoice)
        replacement = self.make_replacement(unit_number='9001')
        replacement.damage_photo_before = real_jpeg()
        replacement.save()
        self.add_line(invoice, replacement)

        page_photos = len(self.all_photos(invoice))
        self.assertEqual(len(zip_names(self.client.get(self.zip_url(invoice)))),
                         page_photos)

    def test_a_job_billed_on_two_lines_contributes_its_photos_once(self):
        invoice = self.make_invoice()
        repair = self.make_invoiced_repair(invoice)
        self.add_line(invoice, repair)
        self.assertEqual(len(zip_names(self.client.get(self.zip_url(invoice)))), 2)


class CustomerPortalZipTests(PhotoDownloadTestCase):
    """Per job, session-gated — a fleet files by unit and date, and an
    uninvoiced job still has photos worth keeping."""

    def setUp(self):
        super().setUp()
        self.portal_user = User.objects.create_user(
            'fleet_portal', password='pw', email='fleet@portal.test')
        CustomerUser.objects.create(
            user=self.portal_user, customer=self.customer)
        self.client.force_login(self.portal_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def test_a_customer_downloads_one_repairs_photos(self):
        repair = self.make_repair(unit_number='4521')
        repair.damage_photo_before = real_jpeg()
        repair.save()

        response = self.client.get(
            reverse('customer_repair_photos_zip', args=[repair.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(zip_names(response)), 1)
        self.assertIn(zip_name_for_job(repair), response['Content-Disposition'])

    def test_the_customers_own_photo_is_in_the_archive(self):
        """They took it and sent it in; it is theirs (Drake's call, 2026-09-01)."""
        repair = self.make_repair(unit_number='4521')
        repair.customer_submitted_photo = real_jpeg()
        repair.save()

        names = zip_names(self.client.get(
            reverse('customer_repair_photos_zip', args=[repair.id])))
        self.assertEqual(len(names), 1)
        self.assertIn('Customer-submitted', names[0])

    def test_a_replacement_downloads_the_same_way(self):
        replacement = self.make_replacement(unit_number='9001')
        replacement.damage_photo_before = real_jpeg()
        replacement.save()

        response = self.client.get(
            reverse('customer_replacement_photos_zip', args=[replacement.id]))
        self.assertEqual(response.status_code, 200)

    def test_another_companys_job_is_not_downloadable(self):
        """The portal gate is per customer; the public one is per invoice."""
        stranger = Customer.objects.create(tenant=self.shop, name='Other Fleet')
        repair = self.repair_for(stranger, unit_number='1',
                                 damage_photo_before=real_jpeg())

        self.assertEqual(self.client.get(
            reverse('customer_repair_photos_zip', args=[repair.id])).status_code,
            404)

    def test_a_job_with_no_photos_404s(self):
        repair = self.make_repair(unit_number='4521')
        self.assertEqual(self.client.get(
            reverse('customer_repair_photos_zip', args=[repair.id])).status_code,
            404)


class ShopZipTests(PhotoDownloadTestCase):
    """The shop is who a customer phones asking for the photos."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def test_the_shop_downloads_a_repairs_photos(self):
        repair = self.make_repair(unit_number='4521')
        repair.damage_photo_before = real_jpeg()
        repair.save()

        response = self.client.get(
            reverse('repair_photos_zip', args=[repair.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(zip_names(response)), 1)

    def test_the_shop_downloads_a_replacements_photos(self):
        replacement = self.make_replacement(unit_number='9001')
        replacement.damage_photo_before = real_jpeg()
        replacement.save()

        response = self.client.get(
            reverse('replacement_photos_zip', args=[replacement.id]))
        self.assertEqual(response.status_code, 200)

    def test_another_shops_job_is_not_downloadable(self):
        other_owner = User.objects.create_user('other_shop_owner', password='pw')
        from apps.tenants.models import Tenant
        other = Tenant.objects.create(
            name='Other Shop', slug='other-shop-p7', plan='trial',
            is_active=True, owner=other_owner, services_offered='both')
        other_customer = Customer.objects.create(tenant=other, name='Theirs')
        from apps.technician_portal.models import Technician
        other_tech = Technician.objects.create(
            tenant=other, user=other_owner, is_active=True, is_manager=True)
        repair = Repair.objects.create(
            tenant=other, technician=other_tech, customer=other_customer,
            unit_number='1', damage_photo_before=real_jpeg(),
        )
        self.assertEqual(self.client.get(
            reverse('repair_photos_zip', args=[repair.id])).status_code, 404)


class DownloadControlRenderTests(PhotoDownloadTestCase):
    """The control has to be ON the page, on every surface that shows photos.

    A `{% url %}` typo here is a 500 on a detail page, not a missing button,
    so these render the real templates rather than trusting the routes.
    """

    def setUp(self):
        super().setUp()
        self.portal_user = User.objects.create_user(
            'render_portal', password='pw', email='render@portal.test')
        CustomerUser.objects.create(
            user=self.portal_user, customer=self.customer)

    def as_customer(self):
        self.client.force_login(self.portal_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def as_shop(self):
        self.client.force_login(self.owner_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def test_customer_repair_detail_offers_the_download(self):
        repair = self.make_repair(
            unit_number='4521', damage_photo_before=real_jpeg())
        self.as_customer()
        response = self.client.get(
            reverse('customer_repair_detail', args=[repair.id]))
        self.assertContains(
            response, reverse('customer_repair_photos_zip', args=[repair.id]))

    def test_customer_replacement_detail_offers_the_download(self):
        replacement = self.make_replacement(
            unit_number='9001', damage_photo_before=real_jpeg())
        self.as_customer()
        response = self.client.get(
            reverse('customer_replacement_detail', args=[replacement.id]))
        self.assertContains(
            response,
            reverse('customer_replacement_photos_zip', args=[replacement.id]))

    def test_shop_repair_detail_offers_the_download(self):
        repair = self.make_repair(
            unit_number='4521', damage_photo_before=real_jpeg())
        self.as_shop()
        response = self.client.get(reverse('repair_detail', args=[repair.id]))
        self.assertContains(
            response, reverse('repair_photos_zip', args=[repair.id]))

    def test_shop_replacement_detail_offers_the_download(self):
        replacement = self.make_replacement(
            unit_number='9001', damage_photo_before=real_jpeg())
        self.as_shop()
        response = self.client.get(
            reverse('replacement_detail', args=[replacement.id]))
        self.assertContains(
            response, reverse('replacement_photos_zip', args=[replacement.id]))
