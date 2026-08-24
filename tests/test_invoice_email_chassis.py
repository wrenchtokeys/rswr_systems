"""The invoice email renders through the shared chassis.

PR #200 unified `send_branded_email()` and the notification templates and
recorded that `templates/emails/base.html` was "the only email shell". It
was not. `InvoiceEmailService._build_html_email` still built a third one in
an f-string — hardcoded `#1e40af` header, `#2563eb` buttons, `#f3f4f6`
ground — so a shop that set its brand colour saw it on every email except
the one asking for money. It was found in production, on a real invoice
sent to a real customer, after #200 deployed.

These tests pin the things that made the move worth doing, and the two
live defects found on the way: a shop's custom invoice copy that reached
only the plain-text alternative, and a logo lookup that raised
RuntimeError on any tenant with a logo outside S3.
"""
import datetime
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from django.test import TestCase, override_settings

from apps.billing.services.invoice_email_service import InvoiceEmailService


def _item(unit_number, damage_type, final_cost, description=''):
    return NS(
        unit_number=unit_number, damage_type=damage_type,
        final_cost=final_cost, description=description,
        repair_obj=None, replacement_obj=None,
    )


def _invoice_data(**kwargs):
    """A duck-typed invoice-data object, the way the service is really called.

    `InvoiceData` is a dataclass but every caller path also hands the
    builders lighter objects, which is why the service reaches for getattr
    and hasattr rather than attributes — see `_unit_column_label`.
    """
    defaults = dict(
        customer_name='Penske Truck Leasing',
        invoice_number='INV-1043',
        invoice_date=datetime.date(2026, 8, 24),
        payment_terms_display='Net 30',
        line_items=[_item('4471', 'Windshield Repair', 84.75)],
        total=84.75, total_discount=0, tax_amount=0, tax_rate=0,
        unit_column_label='Unit #', id=42, pk=42,
    )
    defaults.update(kwargs)
    return NS(**defaults)


def _service(tenant=None):
    """The service without its __init__ — no S3 client, no invoice service.

    Matches how the CODE-232 regression tests build it; `_build_html_email`
    needs only `self.tenant`.
    """
    svc = InvoiceEmailService.__new__(InvoiceEmailService)
    svc.tenant = tenant
    svc.invoice_service = MagicMock()
    svc.s3_client = None
    svc.s3_bucket = None
    return svc


class InvoiceEmailUsesTheChassisTests(TestCase):
    """It is the same email shell as everything else now."""

    def test_renders_through_base_html(self):
        html = _service()._build_html_email(_invoice_data())
        # The chassis's ground and its 600px card — base.html, not a
        # bespoke document.
        self.assertIn('#f7f8fa', html)
        self.assertIn('email-container', html)

    def test_the_old_hardcoded_palette_is_gone(self):
        """The f-string's colours were nobody's brand — not even ours."""
        html = _service()._build_html_email(_invoice_data())
        for dead in ('#1e40af', '#93c5fd', '#eff6ff', '#f3f4f6'):
            with self.subTest(colour=dead):
                self.assertNotIn(dead, html)

    def test_no_tracking_pixel(self):
        """Deliberate: scanners prefetch it and it is a spam signal."""
        html = _service()._build_html_email(_invoice_data())
        self.assertNotIn('width="1" height="1"', html)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InvoiceEmailWearsTheShopBrandTests(TestCase):
    """The whole reason this was worth doing."""

    def setUp(self):
        from apps.tenants.models import SubscriptionPlan
        from apps.tenants.services.signup_service import create_tenant_with_owner

        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0,
                      'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Glass Guy Auto Glass', email='owner@glassguy.example',
            password='testpass123!', first_name='Ray', last_name='Duncan',
        )
        self.tenant = result['tenant']
        # branding_enabled is a read-only property gated on the plan
        # (custom_branding, Pro and up) — the tier is what turns the colour
        # on, it is not a field you can set.
        self.tenant.plan = 'pro'
        self.tenant.brand_color = '#b91c1c'
        self.tenant.business_email = 'service@glassguy.example'
        self.tenant.business_phone = '501-555-0134'
        self.tenant.business_address = '18 Beech St\nLittle Rock, AR'
        self.tenant.save(update_fields=[
            'plan', 'brand_color', 'business_email', 'business_phone',
            'business_address',
        ])
        self.assertTrue(
            self.tenant.branding_enabled,
            'test needs a tenant whose plan applies its brand colour',
        )

    def test_the_shops_colour_reaches_the_button(self):
        html = _service(self.tenant)._build_html_email(
            _invoice_data(), payment_link='https://rssystems.io/pay/42/tok/',
        )
        self.assertIn('#b91c1c', html)

    def test_the_shop_is_the_sender_identity(self):
        html = _service(self.tenant)._build_html_email(_invoice_data())
        self.assertIn('Glass Guy Auto Glass', html)
        self.assertIn('501-555-0134', html)
        self.assertIn('service@glassguy.example', html)

    def test_a_shop_without_the_feature_gets_no_colour(self):
        """A brand colour on a plan that doesn't include branding is a leak."""
        self.tenant.plan = 'starter'
        self.tenant.save(update_fields=['plan'])
        html = _service(self.tenant)._build_html_email(_invoice_data())
        self.assertNotIn('#b91c1c', html)
        # The shop is still named — identity applies on every plan.
        self.assertIn('Glass Guy Auto Glass', html)

    def test_a_tenant_logo_does_not_raise(self):
        """`django.contrib.sites` is NOT in INSTALLED_APPS.

        `_absolute_media_url` imported it outside its own try, so it raised
        RuntimeError — not ImportError — and took the whole email down for
        any tenant with a logo. Production sets AWS_S3_CUSTOM_DOMAIN and
        returns before the import, which is why it only ever fired locally.
        """
        self.tenant.logo = 'tenant_logos/glassguy.png'
        self.tenant.save(update_fields=['logo'])
        html = _service(self.tenant)._build_html_email(_invoice_data())
        self.assertIn('Glass Guy Auto Glass', html)


class InvoiceLineItemsTests(TestCase):
    """A line item is a label/value row now, not a three-column table."""

    def test_fleet_line_carries_the_unit_noun(self):
        html = _service()._build_html_email(_invoice_data())
        self.assertIn('Unit 4471 · Windshield Repair', html)

    def test_an_individual_is_named_by_their_vehicle(self):
        """CLAUDE.md's rule: the LABEL changes with who the customer is.

        Ignoring it is what printed "Unit #Silver Camry" on invoices.
        """
        data = _invoice_data(
            unit_column_label='Vehicle',
            line_items=[_item('2019 Ford F-150', 'Windshield Replacement', 420.00)],
        )
        html = _service()._build_html_email(data)
        self.assertIn('2019 Ford F-150 · Windshield Replacement', html)
        self.assertNotIn('Unit 2019 Ford F-150', html)

    def test_a_job_with_no_vehicle_prints_only_the_service(self):
        data = _invoice_data(line_items=[_item('', 'Chip Repair', 40.00)])
        html = _service()._build_html_email(data)
        self.assertIn('Chip Repair', html)
        self.assertNotIn('·', html.split('Chip Repair')[0][-40:])

    def test_totals_appear(self):
        html = _service()._build_html_email(_invoice_data())
        self.assertIn('Total due', html)
        self.assertIn('$84.75', html)

    def test_tax_and_discount_rows_only_when_there_is_any(self):
        clean = _service()._build_html_email(_invoice_data())
        self.assertNotIn('Discount', clean)
        self.assertNotIn('Tax (', clean)

        data = _invoice_data(
            total_discount=10.00, tax_amount=6.19, tax_rate=8.5, total=80.94,
        )
        html = _service()._build_html_email(data)
        self.assertIn('Discount', html)
        self.assertIn('-$10.00', html)
        self.assertIn('Tax (8.5%)', html)
        self.assertIn('$6.19', html)

    def test_a_missing_invoice_date_does_not_raise(self):
        """The old builder called .strftime() on it unguarded."""
        html = _service()._build_html_email(_invoice_data(invoice_date=None))
        self.assertIn('INV-1043', html)


class InvoiceEmailActionsTests(TestCase):
    """One primary action; the other is a link."""

    def test_paying_is_the_button_when_the_shop_can_take_payment(self):
        html = _service()._build_html_email(
            _invoice_data(), payment_link='https://rssystems.io/pay/42/tok/',
        )
        self.assertIn('Pay invoice — $84.75', html)
        self.assertIn('View invoice online', html)

    def test_viewing_is_the_button_when_it_cannot(self):
        """A shop with no Stripe Connect must not get a dead-end button."""
        html = _service()._build_html_email(_invoice_data())
        self.assertNotIn('Pay invoice', html)
        self.assertIn('View invoice online', html)

    def test_the_pdf_note_says_what_is_attached(self):
        plain = _service()._build_html_email(_invoice_data())
        self.assertIn('A PDF copy of this invoice is attached', plain)

        with_photos = _service()._build_html_email(
            _invoice_data(), include_photos=True,
        )
        self.assertIn('repair photos are attached', with_photos)


class ShopCopyReachesTheHtmlHalfTests(TestCase):
    """CODE-119's template used to be written to nobody.

    `BillingConfig.invoice_email_template` fed the plain-text alternative
    only. A shop writing "we're closed the week of the 4th, call Dana" onto
    its invoices was writing it to the half almost no mail client shows.
    """

    def setUp(self):
        from apps.tenants.models import SubscriptionPlan
        from apps.tenants.services.signup_service import create_tenant_with_owner

        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0,
                      'trial_days': 30, 'is_active': True},
        )
        self.tenant = create_tenant_with_owner(
            business_name='Glass Guy Auto Glass', email='owner@glassguy.example',
            password='testpass123!', first_name='Ray', last_name='Duncan',
        )['tenant']

    def _set_template(self, template):
        from apps.billing.models import BillingConfig
        cfg = BillingConfig.get_for_tenant(self.tenant)
        cfg.invoice_email_template = template
        cfg.save(update_fields=['invoice_email_template'])

    def test_the_shops_own_copy_is_rendered(self):
        self._set_template(
            'Hi {customer_name},\n\n'
            'Invoice {invoice_number} for {total} is ready. We are closed '
            'the week of the 4th — call Dana if you need us.'
        )
        html = _service(self.tenant)._build_html_email(_invoice_data())
        self.assertIn('Penske Truck Leasing', html)
        self.assertIn('call Dana if you need us', html)

    def test_no_template_means_no_body_paragraphs(self):
        """Not a fallback to boilerplate — the rows already say it all."""
        html = _service(self.tenant)._build_html_email(_invoice_data())
        self.assertIn('Here', html)  # the headline still renders
        self.assertNotIn('call Dana', html)

    def test_an_unrenderable_template_is_skipped_not_printed(self):
        """A legacy template with an unknown placeholder must not leak raw."""
        self._set_template('Hi {customer_name}, ref {nonexistent_key}.')
        html = _service(self.tenant)._build_html_email(_invoice_data())
        self.assertNotIn('nonexistent_key', html)
        self.assertIn('$84.75', html)


class InvoiceEmailEscapingTests(TestCase):
    """Django's autoescape replaced the hand-rolled html.escape() calls.

    Same boundary, same result — CODE-232 stays closed. This asserts the
    other half: that nothing is escaped twice, which is what happens when
    a value is escaped in Python and then rendered through a template.
    """

    def test_a_hostile_customer_name_is_escaped_once(self):
        data = _invoice_data(customer_name='<script>alert(1)</script>')
        html = _service()._build_html_email(data)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('&amp;lt;', html)

    def test_an_ampersand_survives_as_one_entity(self):
        data = _invoice_data(customer_name='Smith & Sons')
        html = _service()._build_html_email(data)
        self.assertIn('Smith &amp; Sons', html)
        self.assertNotIn('Smith &amp;amp; Sons', html)
