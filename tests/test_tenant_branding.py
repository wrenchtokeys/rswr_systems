"""
Tests for per-shop branding: Tenant.brand_color, shop-branded email senders
(From display name + Reply-To), invoice PDF branding from the tenant instead
of the platform EmailBrandingConfig singleton, and the customer portal
brand-palette override.
"""
from django.core import mail
from django.template import Context, Template
from django.test import TestCase

from apps.tenants.branding import brand_shades
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.email_utils import send_branded_email, shop_sender
from core.models.email_branding import EmailBrandingConfig


def make_tenant(business_name='Test Shop', email='owner@test.com', first_name='Test'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name=first_name, last_name='Owner',
    )


class BrandShadesTests(TestCase):
    def test_base_color_is_shade_500(self):
        shades = brand_shades('#3b82f6')
        self.assertEqual(shades[500], '59 130 246')
        self.assertEqual(len(shades), 10)

    def test_light_shades_lighter_and_dark_shades_darker(self):
        shades = brand_shades('#3b82f6')
        r50 = int(shades[50].split()[0])
        r900 = int(shades[900].split()[0])
        self.assertGreater(r50, 59)
        self.assertLess(r900, 59)

    def test_malformed_color_returns_empty(self):
        self.assertEqual(brand_shades(''), {})
        self.assertEqual(brand_shades(None), {})
        self.assertEqual(brand_shades('#12'), {})
        self.assertEqual(brand_shades('#zzzzzz'), {})


class ShopSenderTests(TestCase):
    def test_from_shows_shop_name_over_platform_address(self):
        from_email, reply_to = shop_sender('Duncan Glass', 'dad@duncanglass.com')
        self.assertIn('Duncan Glass', from_email)
        self.assertIn('@', from_email)
        self.assertEqual(reply_to, ['dad@duncanglass.com'])

    def test_no_shop_falls_back_to_platform_default(self):
        from django.conf import settings
        from_email, reply_to = shop_sender()
        self.assertEqual(from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(reply_to, [])


class SendBrandedEmailTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.tenant = result['tenant']
        self.tenant.business_email = 'shop@duncanglass.com'
        self.tenant.brand_color = '#8b0000'
        self.tenant.save()

    def test_shop_name_from_reply_to_and_brand_color(self):
        send_branded_email(
            subject='Hello',
            recipient_list=['customer@example.com'],
            headline='Hi there',
            body_paragraphs=['Your repair is done.'],
            tenant=self.tenant,
            button_text='View', button_url='https://example.com/x',
        )
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn(self.tenant.name, msg.from_email)
        self.assertEqual(msg.reply_to, ['shop@duncanglass.com'])
        html = msg.alternatives[0][0]
        self.assertIn('#8b0000', html)

    def test_no_tenant_keeps_platform_sender(self):
        send_branded_email(
            subject='Hello',
            recipient_list=['x@example.com'],
            headline='Hi',
            body_paragraphs=['p'],
        )
        from django.conf import settings
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(mail.outbox[0].reply_to, [])


class EmailBrandingContextTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.tenant = result['tenant']

    def test_brand_color_overrides_platform_colors(self):
        self.tenant.brand_color = '#112233'
        self.tenant.save()
        context = EmailBrandingConfig.get_tenant_context(self.tenant)
        self.assertEqual(context['primary_color'], '#112233')
        self.assertEqual(context['secondary_color'], '#112233')

    def test_without_brand_color_platform_colors_stay(self):
        config = EmailBrandingConfig.get_instance()
        context = EmailBrandingConfig.get_tenant_context(self.tenant)
        self.assertEqual(context['primary_color'], config.primary_color)


class InvoiceBrandingTests(TestCase):
    """Invoice PDF branding must come from the tenant, never the platform
    singleton — that's how every shop's invoices got the platform owner's
    logo and colors."""

    def setUp(self):
        result = make_tenant()
        self.tenant = result['tenant']
        # Give the platform singleton loud colors so a leak is detectable.
        config = EmailBrandingConfig.get_instance()
        config.primary_color = '#ff0000'
        config.secondary_color = '#00ff00'
        config.save()

    def test_tenant_brand_color_used_on_invoice(self):
        from apps.billing.services.invoice_service import InvoiceService
        self.tenant.brand_color = '#123456'
        self.tenant.save()
        service = InvoiceService(tenant=self.tenant)
        self.assertEqual(service.HEADER_COLOR, '#123456')
        self.assertEqual(service.PRIMARY_COLOR, '#123456')

    def test_singleton_colors_never_leak_onto_shop_invoice(self):
        from apps.billing.services.invoice_service import InvoiceService
        service = InvoiceService(tenant=self.tenant)
        self.assertNotIn(service.HEADER_COLOR, ('#00ff00', '#ff0000'))
        self.assertNotIn(service.PRIMARY_COLOR, ('#00ff00', '#ff0000'))

    def test_singleton_logo_never_leaks_onto_shop_invoice(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.billing.services.invoice_service import InvoiceService
        # 1x1 transparent GIF — enough for an ImageField
        gif = (b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff'
               b'!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01'
               b'\x00\x00\x02\x02D\x01\x00;')
        config = EmailBrandingConfig.get_instance()
        config.logo = SimpleUploadedFile('platform.gif', gif, content_type='image/gif')
        config.save()
        service = InvoiceService(tenant=self.tenant)
        self.assertFalse(getattr(service, 'logo_url', None))


class OwnerBrandingSettingsTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_save_brand_color(self):
        response = self.client.post('/owner/settings/', {
            'form_type': 'branding', 'brand_color': '#aabbcc',
        })
        self.assertEqual(response.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.brand_color, '#aabbcc')

    def test_invalid_color_rejected(self):
        self.client.post('/owner/settings/', {
            'form_type': 'branding', 'brand_color': 'red',
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.brand_color, '')

    def test_reset_brand_color(self):
        self.tenant.brand_color = '#aabbcc'
        self.tenant.save()
        self.client.post('/owner/settings/', {
            'form_type': 'branding', 'brand_color': '#aabbcc', 'reset_brand': '1',
        })
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.brand_color, '')

    def test_branding_card_renders(self):
        response = self.client.get('/owner/settings/')
        self.assertContains(response, 'Brand Color')


class PortalBrandCssTests(TestCase):
    def setUp(self):
        result = make_tenant()
        self.tenant = result['tenant']

    def _render(self):
        class Req:
            pass
        req = Req()
        req.tenant = self.tenant
        return Template('{% load branding_tags %}{% tenant_brand_css %}').render(
            Context({'request': req})
        )

    def test_emits_overrides_when_brand_color_set(self):
        self.tenant.brand_color = '#3b82f6'
        html = self._render()
        self.assertIn('--brand-500: 59 130 246;', html)
        self.assertIn('<style>', html)

    def test_renders_nothing_without_brand_color(self):
        self.assertEqual(self._render(), '')
