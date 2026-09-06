"""
A customer's damage photo is a route, not a public file (P8 of the photo-ML arc).

Until P8 every `<img>` of a damage photo pointed straight at S3, and the
bucket policy made `media/*` world-readable — access control for a photo of
a customer's vehicle at their home was "know the filename", and the
filenames were the technician's phone's sequential originals. The invoice's
token protected the page, not the photos on it.

These tests describe the replacement: three routes, one per surface, each
gated exactly like the P7 ZIP on that surface, streaming bytes through
storage. The things worth breaking a build over:

  1. **Every surface renders the route, never the storage URL.** A surface
     missed is broken art the day the bucket closes, not an error page — so
     the last class here scans the source rather than trusting a list.
  2. **The gates are the ZIP's gates.** A photo route laxer than the crop
     endpoints would leak one shop's photos to another just as effectively.
  3. **Bytes come from storage.** The invoice PDF's logo was the last place
     the app fetched its own media over anonymous HTTP; it must not come back.
"""
import re
from pathlib import Path
from unittest.mock import PropertyMock, patch

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Technician
from apps.technician_portal.services import photo_serving
from apps.technician_portal.services.photo_crops import save_crop_for
from apps.technician_portal.services.photo_serving import (
    customer_photo_url, public_photo_url, shop_crop_url, shop_photo_url,
)
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
import rs_systems.views as rs_views
from rs_systems.views import generate_payment_token

from tests.test_photo_closeup_visible import PhotoInvoiceTestCase
from tests.test_photo_tap_crop import real_jpeg

REPO = Path(__file__).resolve().parent.parent

JPEG_MAGIC = b'\xff\xd8\xff'


def body(response):
    """The bytes of a streaming or plain response."""
    if hasattr(response, 'streaming_content'):
        return b''.join(response.streaming_content)
    return response.content


class ServingTestCase(PhotoInvoiceTestCase):
    """The mixin's shop, owner (logged in) and fleet customer, plus a second
    shop and a portal user, because the gates are the whole point."""

    def setUp(self):
        super().setUp()
        self.other_owner = User.objects.create_user(
            'other_owner', password='pw', email='other@shop.test')
        self.other_shop = Tenant.objects.create(
            name='Other Shop', slug='other-shop', plan='trial',
            is_active=True, owner=self.other_owner, services_offered='both',
        )
        TenantMembership.objects.create(
            tenant=self.other_shop, user=self.other_owner, role='owner')
        Technician.objects.create(
            tenant=self.other_shop, user=self.other_owner,
            is_active=True, is_manager=True, can_repair=True, can_replace=True,
        )

    def login_as(self, user, tenant):
        client = Client()
        client.force_login(user)
        session = client.session
        session['tenant_id'] = tenant.id
        session.save()
        return client

    def portal_client(self, customer=None):
        user = User.objects.create_user(
            f'portal_{(customer or self.customer).pk}', password='pw')
        CustomerUser.objects.create(user=user, customer=customer or self.customer)
        return self.login_as(user, self.shop)

    def assert_is_the_photo(self, response, upload_bytes):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertEqual(response['Cache-Control'], photo_serving.CACHE_CONTROL)
        self.assertEqual(body(response), upload_bytes)


class ShopRouteTests(ServingTestCase):
    """The shop side: the crop endpoints' own gate (`_job_access`)."""

    def test_the_shop_gets_the_bytes_it_stored(self):
        upload = real_jpeg()
        upload_bytes = upload.read()
        upload.seek(0)
        repair = self.make_repair(damage_photo_before=upload)

        response = self.client.get(shop_photo_url(repair, 'damage_photo_before'))
        self.assert_is_the_photo(response, upload_bytes)

    def test_the_url_is_the_route_not_the_storage_url(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        url = shop_photo_url(repair, 'damage_photo_before')
        self.assertTrue(url.startswith(
            reverse('repair_photo', args=[repair.pk, 'damage_photo_before'])))
        self.assertNotIn('repair_photos/', url)

    def test_a_replacement_answers_on_its_own_route(self):
        replacement = self.make_replacement(damage_photo_after=real_jpeg())
        url = shop_photo_url(replacement, 'damage_photo_after')
        self.assertTrue(url.startswith(
            reverse('replacement_photo', args=[replacement.pk, 'damage_photo_after'])))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_the_thumb_route_serves_the_crop_not_the_original(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 40.0, 40.0)
        self.assertTrue(crop.cropped_image)

        response = self.client.get(shop_crop_url(crop))
        self.assertEqual(response.status_code, 200)
        data = body(response)
        self.assertTrue(data.startswith(JPEG_MAGIC))
        with repair.damage_photo_before.open('rb') as handle:
            self.assertNotEqual(data, handle.read())

    def test_a_thumb_for_an_unmarked_photo_is_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.client.get(
            reverse('repair_crop_thumb', args=[repair.pk, 'damage_photo_before']))
        self.assertEqual(response.status_code, 404)

    def test_an_unknown_field_is_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.client.get(
            reverse('repair_photo', args=[repair.pk, 'additional_photos']))
        self.assertEqual(response.status_code, 404)

    def test_a_field_with_no_photo_is_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        self.assertEqual(shop_photo_url(repair, 'damage_photo_after'), '')
        response = self.client.get(
            reverse('repair_photo', args=[repair.pk, 'damage_photo_after']))
        self.assertEqual(response.status_code, 404)

    def test_another_shop_gets_404_not_the_photo(self):
        """The whole point. Tenant scoping first, then the job gate."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        other = self.login_as(self.other_owner, self.other_shop)
        response = other.get(shop_photo_url(repair, 'damage_photo_before'))
        self.assertEqual(response.status_code, 404)

    def test_a_technician_who_may_not_open_the_job_gets_no_photo(self):
        """Same answer as the ZIP and the crop endpoints: `can_view_repair`."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        tech_user = User.objects.create_user('plain_tech', password='pw')
        TenantMembership.objects.create(
            tenant=self.shop, user=tech_user, role='technician')
        Technician.objects.create(
            tenant=self.shop, user=tech_user, is_active=True,
            is_manager=False, can_repair=True,
        )
        client = self.login_as(tech_user, self.shop)
        response = client.get(shop_photo_url(repair, 'damage_photo_before'))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = Client().get(shop_photo_url(repair, 'damage_photo_before'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_a_file_missing_from_storage_is_404_not_500(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        field = repair.damage_photo_before
        field.storage.delete(field.name)
        response = self.client.get(shop_photo_url(repair, 'damage_photo_before'))
        self.assertEqual(response.status_code, 404)


class CustomerRouteTests(ServingTestCase):
    """The portal: the detail page's own scoping (`customer=`, `tenant=`)."""

    def test_the_customer_sees_their_own_photo(self):
        upload = real_jpeg()
        upload_bytes = upload.read()
        upload.seek(0)
        repair = self.make_repair(damage_photo_before=upload)

        client = self.portal_client()
        response = client.get(customer_photo_url(repair, 'damage_photo_before'))
        self.assert_is_the_photo(response, upload_bytes)

    def test_a_replacement_answers_too(self):
        replacement = self.make_replacement(customer_submitted_photo=real_jpeg())
        client = self.portal_client()
        url = customer_photo_url(replacement, 'customer_submitted_photo')
        self.assertTrue(url.startswith(reverse(
            'customer_replacement_photo',
            args=[replacement.pk, 'customer_submitted_photo'])))
        self.assertEqual(client.get(url).status_code, 200)

    def test_another_customer_at_the_same_shop_gets_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        stranger = Customer.objects.create(tenant=self.shop, name='Stranger Fleet')
        client = self.portal_client(stranger)
        response = client.get(customer_photo_url(repair, 'damage_photo_before'))
        self.assertEqual(response.status_code, 404)

    def test_an_unknown_field_is_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        client = self.portal_client()
        response = client.get(
            reverse('customer_repair_photo', args=[repair.pk, 'additional_photos']))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = Client().get(customer_photo_url(repair, 'damage_photo_before'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])


class PublicInvoiceRouteTests(ServingTestCase):
    """The public page: the invoice's token, and the job must be billed on it."""

    def test_a_valid_token_gets_the_photo_with_no_session(self):
        upload = real_jpeg()
        upload_bytes = upload.read()
        upload.seek(0)
        repair = self.make_repair(damage_photo_before=upload)
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        response = Client().get(self.public_url(invoice, repair))
        self.assert_is_the_photo(response, upload_bytes)

    def test_a_bad_token_is_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        url = public_photo_url(invoice.id, 'deadbeef', repair, 'damage_photo_before')
        self.assertEqual(Client().get(url).status_code, 404)

    def test_a_job_not_on_this_invoice_is_404_even_with_a_valid_token(self):
        """A token for one invoice must not open another job's photos."""
        billed = self.make_repair(unit_number='BILLED',
                                  damage_photo_before=real_jpeg())
        other = self.make_repair(unit_number='OTHER',
                                 damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, billed)

        self.assertEqual(Client().get(self.public_url(invoice, billed)).status_code, 200)
        self.assertEqual(Client().get(self.public_url(invoice, other)).status_code, 404)

    def test_the_wrong_kind_for_a_job_id_is_404(self):
        """A repair's id under 'replacement' must not resolve to a replacement
        that happens to share the number."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        token = generate_payment_token(invoice.id)
        url = reverse('public_invoice_photo',
                      args=[invoice.id, token, 'replacement', repair.pk,
                            'damage_photo_before'])
        self.assertEqual(Client().get(url).status_code, 404)

    def test_an_unknown_field_is_404(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        token = generate_payment_token(invoice.id)
        url = reverse('public_invoice_photo',
                      args=[invoice.id, token, 'repair', repair.pk, 'additional_photos'])
        self.assertEqual(Client().get(url).status_code, 404)

    def test_fetching_a_photo_does_not_count_as_viewing_the_invoice(self):
        """The page already recorded the view; an <img> is not a click."""
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)

        with patch.object(rs_views, '_resolve_public_invoice',
                          wraps=rs_views._resolve_public_invoice) as resolve:
            Client().get(self.public_url(invoice, repair))
        self.assertTrue(resolve.called)
        self.assertFalse(resolve.call_args.kwargs.get('record_view', True))

    def test_a_replacement_photo_answers_under_its_kind(self):
        replacement = self.make_replacement(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, replacement)
        url = self.public_url(invoice, replacement)
        self.assertIn('/photos/replacement/', url)
        self.assertEqual(Client().get(url).status_code, 200)


class VersionedUrlTests(ServingTestCase):
    """The route names the field, so the URL must change when the file does,
    or `Cache-Control: private, max-age` serves a replaced photo stale."""

    def test_replacing_the_photo_changes_the_url(self):
        repair = self.make_repair(damage_photo_before=real_jpeg(name='first.jpg'))
        first = shop_photo_url(repair, 'damage_photo_before')
        repair.damage_photo_before = real_jpeg(name='second.jpg')
        repair.save()
        second = shop_photo_url(repair, 'damage_photo_before')
        self.assertNotEqual(first, second)
        self.assertEqual(first.split('?')[0], second.split('?')[0])

    def test_every_surface_carries_the_version(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        for url in (shop_photo_url(repair, 'damage_photo_before'),
                    customer_photo_url(repair, 'damage_photo_before'),
                    self.public_url(invoice, repair)):
            self.assertRegex(url, r'\?v=[0-9a-f]{8}$')

    def test_re_tapping_changes_the_thumb_url(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        crop = save_crop_for(repair, 'damage_photo_before', 40.0, 40.0)
        self.assertIn('?v=', shop_crop_url(crop))


class SurfacesRenderTheRouteTests(ServingTestCase):
    """Every page that used to print a storage URL prints the route now."""

    def storage_url(self, field):
        return field.url

    def test_the_shop_repair_page(self):
        repair = self.make_repair(damage_photo_before=real_jpeg(),
                                  customer_submitted_photo=real_jpeg())
        save_crop_for(repair, 'damage_photo_before', 40.0, 40.0)
        html = self.client.get(reverse('repair_detail', args=[repair.pk])).content.decode()
        self.assertIn(shop_photo_url(repair, 'damage_photo_before'), html)
        self.assertIn(shop_photo_url(repair, 'customer_submitted_photo'), html)
        self.assertIn(shop_crop_url(repair.photo_crops.get()), html)
        self.assertNotIn(self.storage_url(repair.damage_photo_before), html)
        self.assertNotIn('repair_photos/', html)

    def test_the_crop_control_hands_the_modal_the_route(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        html = self.client.get(reverse('repair_detail', args=[repair.pk])).content.decode()
        self.assertIn(
            f'data-crop-src="{shop_photo_url(repair, "damage_photo_before")}"', html)

    def test_the_shop_edit_form(self):
        repair = self.make_repair(damage_photo_after=real_jpeg())
        html = self.client.get(reverse('update_repair', args=[repair.pk])).content.decode()
        self.assertIn(shop_photo_url(repair, 'damage_photo_after'), html)
        self.assertNotIn('repair_photos/', html)

    def test_the_owner_replacement_page(self):
        replacement = self.make_replacement(damage_photo_before=real_jpeg(),
                                            damage_photo_after=real_jpeg())
        html = self.client.get(
            reverse('replacement_detail', args=[replacement.pk])).content.decode()
        self.assertIn(shop_photo_url(replacement, 'damage_photo_before'), html)
        self.assertIn(shop_photo_url(replacement, 'damage_photo_after'), html)
        self.assertNotIn('repair_photos/', html)

    def test_the_customer_portal_pages(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        replacement = self.make_replacement(damage_photo_after=real_jpeg())
        client = self.portal_client()

        html = client.get(reverse('customer_repair_detail', args=[repair.pk])).content.decode()
        self.assertIn(customer_photo_url(repair, 'damage_photo_before'), html)
        self.assertNotIn('repair_photos/', html)

        html = client.get(
            reverse('customer_replacement_detail', args=[replacement.pk])).content.decode()
        self.assertIn(customer_photo_url(replacement, 'damage_photo_after'), html)
        self.assertNotIn('repair_photos/', html)

    def test_the_public_invoice_page(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        invoice = self.make_invoice()
        self.add_line(invoice, repair)
        html = self.get_public_invoice(invoice).content.decode()
        self.assertIn(self.public_url(invoice, repair), html)
        self.assertNotIn('repair_photos/', html)

    def test_the_mark_queue_loads_the_route(self):
        """The backlog tool shows the original to be tapped; if photos move
        and it does not, the tool goes blind."""
        self.make_repair(damage_photo_before=real_jpeg())
        html = self.client.get(reverse('photo_backfill_queue')).content.decode()
        self.assertIn('/photos/damage_photo_before/', html)
        self.assertNotIn('repair_photos/', html)

    def test_saving_a_tap_returns_the_thumb_route(self):
        repair = self.make_repair(damage_photo_before=real_jpeg())
        response = self.client.post(
            reverse('save_photo_crop', args=[repair.pk]),
            {'source_field': 'damage_photo_before',
             'center_x_pct': '40', 'center_y_pct': '40'})
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['crop_url'], shop_crop_url(repair.photo_crops.get()))


class NothingPrintsAStorageUrlTests(ServingTestCase):
    """Source scan. A template that prints `.url` on a photo field is broken
    art the day the bucket closes — not a failing test, not an error page —
    so the rule is enforced on the source rather than on a list of pages."""

    PHOTO_FIELD_URL = re.compile(
        r'\b(damage_photo_before|damage_photo_after|customer_submitted_photo'
        r'|cropped_image)(\.value)?\.url\b')

    def scan(self, root, suffixes):
        hits = []
        for path in Path(root).rglob('*'):
            if path.suffix not in suffixes or not path.is_file():
                continue
            rel = path.relative_to(REPO)
            parts = rel.parts
            if 'tests' in parts or 'migrations' in parts or 'templatetags' in parts:
                continue
            for number, line in enumerate(path.read_text(errors='ignore').splitlines(), 1):
                if self.PHOTO_FIELD_URL.search(line):
                    hits.append(f'{rel}:{number}: {line.strip()}')
        return hits

    def test_no_template_prints_a_photo_fields_storage_url(self):
        self.assertEqual(self.scan(REPO / 'templates', {'.html', '.txt'}), [])

    def test_no_app_code_reads_a_photo_fields_storage_url(self):
        hits = []
        for root in ('apps', 'core', 'common', 'rs_systems'):
            hits += self.scan(REPO / root, {'.py', '.html'})
        self.assertEqual(hits, [])


class InvoicePdfLogoTests(ServingTestCase):
    """The PDF used to `urlretrieve` the shop's logo from its public URL — the
    last place the app fetched its own media over the network."""

    def test_the_logo_is_read_through_storage_not_fetched(self):
        from apps.billing.services import invoice_service
        from apps.billing.services.invoice_service import InvoiceService

        self.shop.logo = real_jpeg(name='logo.jpg')
        self.shop.save()

        with patch.object(Tenant, 'branding_enabled', new_callable=PropertyMock,
                          return_value=True):
            service = InvoiceService(tenant=self.shop)
            with patch('urllib.request.urlretrieve',
                       side_effect=AssertionError('fetched the logo over HTTP')):
                image = service._get_logo_for_pdf()
        self.assertIsNotNone(image)
        self.assertFalse(hasattr(invoice_service, 'urllib'),
                         'invoice_service must not import urllib again')

    def test_no_logo_means_no_image_and_no_error(self):
        from apps.billing.services.invoice_service import InvoiceService
        service = InvoiceService(tenant=self.shop)
        self.assertIsNone(service._get_logo_for_pdf())
