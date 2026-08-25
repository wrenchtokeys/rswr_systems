"""Render every customer-facing email to local HTML files. No sending.

Born from the invoice-email redesign: until this existed, the only way to
see what a customer actually received was to deploy to production and send
a real email to a real person. Every template change was reviewed as diff
text and shipped blind, which is how six months of emails went out ugly.

    python manage.py preview_emails
    python manage.py preview_emails --out /tmp/previews --tenant glass-guy

Open the printed index.html in a browser. Narrow the window under 620px to
check the phone layout — the chassis's media query runs in a browser the
same as in a mail client.

What renders:
  - The invoice email through the real `InvoiceEmailService._build_html_email`
    (a long fleet invoice, an individual's single-line invoice, and a shop
    with no online payments), with duck-typed invoice data — nothing is
    written to the database.
  - Every `NotificationTemplate` row that has an email body, through the
    same `render()` the notification service calls, against one rich sample
    context. Templates with no email body are listed, not rendered — a
    seeded template is not a deliverable one (see CLAUDE.md).

`--tenant <slug>` previews with that tenant's branding (colour, name,
logo); the default is the platform's. Sample data is hardcoded here on
purpose — previews must not depend on what happens to be in the dev
database.
"""
import datetime
import os
from types import SimpleNamespace as NS

from django.core.management.base import BaseCommand, CommandError


def _item(unit, damage, cost):
    return NS(unit_number=unit, damage_type=damage, final_cost=cost,
              description='', repair_obj=None, replacement_obj=None)


def _invoice_data(**kwargs):
    defaults = dict(
        customer_name='Penske Truck Leasing',
        invoice_number='INV-1042',
        invoice_date=datetime.date(2026, 8, 25),
        payment_terms_display='Net 30',
        line_items=[_item('4471', 'Windshield Repair', 84.75)],
        total=84.75, total_discount=0, tax_amount=0, tax_rate=0,
        unit_column_label='Unit #', id=42, pk=42,
    )
    defaults.update(kwargs)
    return NS(**defaults)


class Command(BaseCommand):
    help = (
        "Render the customer-facing emails to local HTML files for visual "
        "review — no deploy, no sending, no database writes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--out', default='email_previews',
            help='Directory to write the HTML files into (default: ./email_previews/)',
        )
        parser.add_argument(
            '--tenant', default=None, metavar='SLUG',
            help="Preview with this tenant's branding instead of the platform's",
        )

    def handle(self, *args, **options):
        tenant = None
        if options['tenant']:
            from apps.tenants.models import Tenant
            tenant = Tenant.objects.filter(slug=options['tenant']).first()
            if tenant is None:
                raise CommandError(f"No tenant with slug '{options['tenant']}'")

        out_dir = os.path.abspath(options['out'])
        os.makedirs(out_dir, exist_ok=True)

        pages = []
        pages += self._invoice_previews(out_dir, tenant)
        pages += self._direct_template_previews(out_dir, tenant)
        pages += self._branded_previews(out_dir, tenant)
        pages += self._notification_previews(out_dir, tenant)
        index = self._write_index(out_dir, pages)

        rendered = sum(1 for p in pages if p['file'])
        skipped = sum(1 for p in pages if not p['file'])
        self.stdout.write(self.style.SUCCESS(
            f"Rendered {rendered} emails ({skipped} templates have no email body)."
        ))
        self.stdout.write(f"open {index}")

    # ------------------------------------------------------------------
    def _write(self, out_dir, name, html):
        path = os.path.join(out_dir, name)
        with open(path, 'w') as f:
            f.write(html)
        return name

    def _invoice_previews(self, out_dir, tenant):
        from apps.billing.services.invoice_email_service import InvoiceEmailService

        service = InvoiceEmailService(tenant=tenant)
        long_fleet = _invoice_data(
            line_items=[
                _item('4521', 'Windshield Repair', 50.00),
                _item('4521', 'Windshield Repair', 40.00),
                _item('4522', 'Windshield Repair', 50.00),
                _item('4523', 'Windshield Replacement', 425.00),
                _item('4523', 'Mobile service fee', 35.00),
                _item('4527', 'Windshield Repair', 50.00),
                _item('4527', 'Windshield Repair', 40.00),
                _item('4527', 'Windshield Repair', 35.00),
                _item('4530', 'Rock chip repair - crack near driver side pillar', 65.00),
                _item('4531', 'Windshield Repair', 50.00),
                _item('4540', 'Windshield Replacement', 395.00),
            ],
            total=1337.62, total_discount=64.25, tax_amount=116.87, tax_rate=9.5,
        )
        individual = _invoice_data(
            customer_name='Sarah Mitchell', invoice_number='INV-1051',
            unit_column_label='Vehicle',
            line_items=[_item('2022 Toyota Camry', 'Windshield Repair', 50.00)],
            total=54.75, tax_amount=4.75, tax_rate=9.5,
        )
        fixtures = [
            ('invoice — long fleet invoice', 'invoice_long_fleet.html',
             long_fleet, 'https://example.invalid/pay/'),
            ('invoice — individual, one line', 'invoice_individual.html',
             individual, 'https://example.invalid/pay/'),
            ('invoice — shop without online payments', 'invoice_no_payment.html',
             individual, None),
        ]
        pages = []
        for title, name, data, pay_link in fixtures:
            html = service._build_html_email(
                data, payment_link=pay_link,
                view_link='https://example.invalid/invoice/',
            )
            pages.append({'title': title, 'file': self._write(out_dir, name, html)})
        return pages

    def _direct_template_previews(self, out_dir, tenant):
        """Emails rendered straight from a template file, not a DB row."""
        import decimal

        from django.template.loader import render_to_string

        from core.models.email_branding import EmailBrandingConfig

        branding = EmailBrandingConfig.get_tenant_context(tenant)
        paid_invoice = {
            'invoice_number': 'INV-1042', 'total': decimal.Decimal('1337.62'),
            'amount_due': decimal.Decimal('0.00'),
        }
        partial_invoice = dict(paid_invoice, amount_due=decimal.Decimal('637.62'))
        payment = {
            'amount': decimal.Decimal('700.00'),
            'get_payment_method_display': 'Card',
            'payment_date': datetime.date(2026, 8, 25),
            'reference_number': 'PMT-2201',
        }
        fixtures = [
            ('payment receipt — paid in full', 'payment_received_paid.html',
             'emails/notifications/payment_received.html',
             {'branding': branding, 'invoice': paid_invoice,
              'payment': dict(payment, amount=decimal.Decimal('1337.62')),
              'pay_url': '', 'receipt_pdf_url': 'https://example.invalid/receipt.pdf'}),
            ('payment receipt — partial payment', 'payment_received_partial.html',
             'emails/notifications/payment_received.html',
             {'branding': branding, 'invoice': partial_invoice, 'payment': payment,
              'pay_url': 'https://example.invalid/pay/',
              'receipt_pdf_url': 'https://example.invalid/receipt.pdf'}),
            ('customer portal invitation', 'customer_invitation.html',
             'emails/customer_invitation.html',
             {'branding': branding, 'recipient_name': 'Dana',
              'inviter_name': 'Ray Duncan', 'customer_name': 'Penske Truck Leasing',
              'shop_name': branding.get('company_name', 'RS Systems'),
              'invite_url': 'https://rssystems.io/app/invite/3f9c2a71b64d/'}),
        ]
        pages = []
        for title, name, template, context in fixtures:
            html = render_to_string(template, context)
            pages.append({'title': title, 'file': self._write(out_dir, name, html)})
        return pages

    def _branded_previews(self, out_dir, tenant):
        """send_branded_email() callers, through the real rendering half.

        The kwargs are representative samples of what the call sites pass —
        the context assembly itself is render_branded_email, so the shell,
        identity rules and row normalization cannot drift from a real send.
        """
        from core.email_utils import render_branded_email

        fixtures = [
            ('owner — payment received', 'branded_owner_payment.html', dict(
                subject='Payment: $84.75 from Penske Truck Leasing (paid in full)',
                headline='Penske Truck Leasing just paid $84.75.',
                lede='Applied to invoice INV-1042.',
                body_paragraphs=[],
                detail_rows=[
                    ('Customer', 'Penske Truck Leasing'),
                    ('Invoice', 'INV-1042'),
                    ('Amount paid', '$84.75', 'strong money'),
                    ('Method', 'Card'),
                    ('Date', 'August 25, 2026'),
                    ('Invoice total', '$84.75'),
                    ('Total paid', '$84.75'),
                    ('Balance', '$0.00', 'strong money'),
                ],
                tenant=tenant,
            )),
            ('customer — combined fleet receipt', 'branded_combined_receipt.html', dict(
                subject='Your receipt from The Shop — $1,337.62 across 3 invoices',
                headline='Payment received — thank you.',
                lede='Your payment of $1,337.62 was applied across 3 invoices as shown below.',
                body_paragraphs=[],
                detail_rows=[
                    ('Amount received', '$1,337.62', 'strong money'),
                    ('Method', 'Check'),
                    ('Date', 'August 25, 2026'),
                    ('Invoice INV-1039', '$425.00 — paid in full'),
                    ('Invoice INV-1040', '$512.62 — paid in full'),
                    ('Invoice INV-1042', '$400.00 — $84.75 remaining'),
                ],
                tenant=tenant,
            )),
            ('customer — review request', 'branded_review_request.html', dict(
                subject='How was your experience?',
                headline='How was your experience with us?',
                body_paragraphs=[
                    'Thanks for trusting us with your windshield. If we did a '
                    'good job, a quick Google review helps other drivers find us.',
                ],
                button_text='Leave a Google Review',
                button_url='https://example.invalid/review/',
                secondary_button_text='Unsubscribe from review requests',
                secondary_button_url='https://example.invalid/opt-out/',
                tenant=tenant,
            )),
            ('platform — trial ending alert', 'branded_trial_alert.html', dict(
                subject='Your trial ends in 3 days',
                headline='Your trial ends in 3 days.',
                body_paragraphs=[
                    'Pick a plan before Thursday to keep your shop running '
                    'without interruption. Your data stays put either way.',
                ],
                button_text='Choose a plan',
                button_url='https://rssystems.io/owner/billing/',
                tenant=tenant,
                platform=True,
            )),
        ]
        pages = []
        for title, name, kwargs in fixtures:
            html, _text = render_branded_email(**kwargs)
            pages.append({'title': title, 'file': self._write(out_dir, name, html)})
        return pages

    def _notification_previews(self, out_dir, tenant):
        from core.models.notification_template import NotificationTemplate

        context = self._sample_context(tenant)
        pages = []
        for template in NotificationTemplate.objects.order_by('name'):
            if not template.email_html_template:
                pages.append({'title': template.name, 'file': None,
                              'note': 'no email body — in-app/SMS only'})
                continue
            try:
                html = template.render(dict(context))['email_html']
            except Exception as exc:  # a broken template is a finding, not a crash
                pages.append({'title': template.name, 'file': None,
                              'note': f'render failed: {exc}'})
                continue
            name = f"notification_{template.name}.html"
            pages.append({'title': template.name,
                          'file': self._write(out_dir, name, html)})
        if not pages:
            self.stdout.write(self.style.WARNING(
                'No NotificationTemplate rows — run setup_notification_templates '
                'to preview the lifecycle emails.'
            ))
        return pages

    @staticmethod
    def _sample_context(tenant):
        """One context generous enough for every lifecycle template.

        Keys a given template doesn't use are ignored; a key missing from
        here renders as an empty string, which the bodies already guard
        with {% if %}. Flat display strings, matching what
        NotificationService really passes (the job object never reaches
        the template — its context is persisted as JSON).
        """
        from core.models.email_branding import EmailBrandingConfig

        return {
            'branding': EmailBrandingConfig.get_tenant_context(tenant),
            'customer_name': 'Penske Truck Leasing',
            'technician_name': 'Ray Duncan',
            'new_technician_name': 'Cass Elliott',
            'vehicle_label': 'Unit #',
            'vehicle_identifier': '4471',
            'unit_number': '4471',
            'repair_id': 1042,
            'replacement_id': 88,
            'damage_type': 'Star Break',
            'damage_description': 'Star break, lower passenger corner',
            'description': 'Windshield replacement',
            'glass_position': 'Windshield',
            'glass_type': 'OEM',
            'nags_number': 'FW02555',
            'needs_adas': True,
            'service_location': 'Mobile — 412 Main St, Benton',
            'scheduled_when': 'Tomorrow, 9:00 AM',
            'preferred_time': 'Mornings',
            'first_time': 'Thu Aug 27, 9:00 AM',
            'second_time': 'Fri Aug 28, 1:00 PM',
            'day': 'Tuesday',
            'completed_on': 'August 25, 2026',
            'warranty_display': 'Lifetime warranty',
            'job_cost_display': '$84.75',
            'labor_cost_display': '$120.00',
            'parts_cost_display': '$305.00',
            'job_count': 3,
            'repair_count': 3,
            'job_summary': 'Unit 4471 — Windshield Repair · Unit 4522 — Windshield Repair',
            'job_type': 'repair',
            'denial_reason': 'Damage exceeds repairable size.',
            'customer_notes': 'Gate code 4417.',
            'status': 'COMPLETED',
            'paid': True,
            'total': '$84.75',
            'pricing_note': 'Priced per your fleet agreement.',
            'invoice': {'invoice_number': 'INV-1042', 'amount_due': '$84.75'},
            'payment': {
                'get_payment_method_display': 'Card',
                'payment_date': datetime.date(2026, 8, 25),
                'reference_number': 'PMT-2201',
            },
            'receipt_pdf_url': 'https://example.invalid/receipt.pdf',
            'repair': {'break_description': 'Star break, lower passenger corner'},
        }

    def _write_index(self, out_dir, pages):
        rows = []
        for page in pages:
            if page['file']:
                rows.append(
                    f'<li><a href="{page["file"]}">{page["title"]}</a></li>'
                )
            else:
                rows.append(
                    f'<li><span style="color:#9ca3af">{page["title"]}'
                    f' — {page.get("note", "")}</span></li>'
                )
        html = (
            '<!doctype html><meta charset="utf-8">'
            '<title>Email previews</title>'
            '<body style="font-family:-apple-system,sans-serif; max-width:640px;'
            ' margin:40px auto; line-height:1.9;">'
            '<h1 style="font-size:20px;">Email previews</h1>'
            '<p style="color:#6b7280;">Rendered by <code>manage.py '
            'preview_emails</code>. Narrow the window under 620px to check '
            'the phone layout.</p>'
            f'<ul>{"".join(rows)}</ul></body>'
        )
        path = os.path.join(out_dir, 'index.html')
        with open(path, 'w') as f:
            f.write(html)
        return path
