"""
The "Not sent" invoice filter and flag (Oct 2026).

An owner who writes tickets all day and invoices at the end needs one place
that answers "which of these did I never actually send?". That is:

- a DRAFT nobody emailed or texted (an email send promotes DRAFT -> SENT, so
  a draft with no text on record is one that never went out), and
- an email that bounced / was rejected / was marked spam on an invoice that
  is still owed.

Covered here:
- Invoice.needs_sending_q() and Invoice.needs_sending agree, case by case
- /owner/invoices/?status=unsent lists exactly those invoices
- the pill carries a count, the "Owed to you" card carries a line, and the
  row carries a "Not sent" flag plus a Send button
"""

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from core.models import Customer
from tests.helpers import make_tenant

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}

LIST_URL = '/owner/invoices/'


def make_invoice(customer, tenant, total='50.00', status='DRAFT', **fields):
    n = Invoice.objects.count() + 1
    inv = Invoice.objects.create(
        customer=customer,
        tenant=tenant,
        invoice_number=f'INV-NS-{n:04d}',
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=status,
        subtotal=Decimal(total),
        total=Decimal(total),
        **fields,
    )
    InvoiceLineItem.objects.create(
        invoice=inv, description=f'Job {n}', quantity=1,
        unit_price=Decimal(total), amount=Decimal(total),
    )
    return inv


@override_settings(**TEST_OVERRIDES)
class NeedsSendingTests(TestCase):
    """The Q and the property are two spellings of one rule."""

    def setUp(self):
        self.user, self.tenant = make_tenant('NeedsSendShop', 'needsendowner')
        self.customer = Customer.objects.create(
            name='Unsent Co', tenant=self.tenant, email='ap@unsent.test',
        )

    def _cases(self):
        now = timezone.now()
        return {
            'draft_never_sent': (make_invoice(self.customer, self.tenant), True),
            'draft_texted': (
                make_invoice(self.customer, self.tenant, last_sms_at=now, last_sms_to='+15015550100'),
                False,
            ),
            'sent_pending_delivery': (
                make_invoice(self.customer, self.tenant, status='SENT', sent_at=now,
                             email_delivery_status='sent'),
                False,
            ),
            'sent_delivered': (
                make_invoice(self.customer, self.tenant, status='SENT', sent_at=now,
                             email_delivery_status='delivered'),
                False,
            ),
            'sent_delayed': (
                make_invoice(self.customer, self.tenant, status='SENT', sent_at=now,
                             email_delivery_status='delayed'),
                False,
            ),
            'sent_bounced': (
                make_invoice(self.customer, self.tenant, status='SENT', sent_at=now,
                             email_delivery_status='bounced'),
                True,
            ),
            'overdue_rejected': (
                make_invoice(self.customer, self.tenant, status='OVERDUE', sent_at=now,
                             email_delivery_status='rejected'),
                True,
            ),
            'partial_complained': (
                make_invoice(self.customer, self.tenant, status='PARTIAL', sent_at=now,
                             email_delivery_status='complained', amount_paid=Decimal('10.00')),
                True,
            ),
            'paid_bounced': (
                make_invoice(self.customer, self.tenant, status='PAID', sent_at=now,
                             email_delivery_status='bounced', amount_paid=Decimal('50.00')),
                False,
            ),
            'cancelled_bounced': (
                make_invoice(self.customer, self.tenant, status='CANCELLED', sent_at=now,
                             email_delivery_status='bounced'),
                False,
            ),
            'paid': (
                make_invoice(self.customer, self.tenant, status='PAID', amount_paid=Decimal('50.00')),
                False,
            ),
        }

    def test_property_and_q_agree(self):
        cases = self._cases()
        matched = set(
            Invoice.objects.filter(Invoice.needs_sending_q()).values_list('pk', flat=True)
        )
        for name, (inv, expected) in cases.items():
            with self.subTest(case=name):
                self.assertEqual(inv.needs_sending, expected, f'property: {name}')
                self.assertEqual(inv.pk in matched, expected, f'Q: {name}')


@override_settings(**TEST_OVERRIDES)
class UnsentFilterPageTests(TestCase):

    def setUp(self):
        self.user, self.tenant = make_tenant('UnsentShop', 'unsentowner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='End Of Day Fleet', tenant=self.tenant, email='ap@eod.test',
        )

    def test_unsent_filter_lists_drafts_and_bounces_only(self):
        draft = make_invoice(self.customer, self.tenant)
        bounced = make_invoice(
            self.customer, self.tenant, status='SENT', sent_at=timezone.now(),
            email_delivery_status='bounced',
        )
        sent = make_invoice(
            self.customer, self.tenant, status='SENT', sent_at=timezone.now(),
            email_delivery_status='delivered',
        )
        paid = make_invoice(self.customer, self.tenant, status='PAID', amount_paid=Decimal('50.00'))

        resp = self.client.get(LIST_URL + '?status=unsent')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['status_filter'], 'unsent')
        self.assertContains(resp, draft.invoice_number)
        self.assertContains(resp, bounced.invoice_number)
        self.assertNotContains(resp, sent.invoice_number)
        self.assertNotContains(resp, paid.invoice_number)

    def test_unsent_filter_scoped_to_tenant(self):
        other_user, other_tenant = make_tenant('OtherUnsent', 'otherunsent')
        other_customer = Customer.objects.create(name='Other', tenant=other_tenant)
        theirs = make_invoice(other_customer, other_tenant)
        mine = make_invoice(self.customer, self.tenant)

        resp = self.client.get(LIST_URL + '?status=unsent')
        self.assertContains(resp, mine.invoice_number)
        self.assertNotContains(resp, theirs.invoice_number)
        self.assertEqual(resp.context['unsent_count'], 1)

    def test_pill_and_card_carry_count_and_amount(self):
        make_invoice(self.customer, self.tenant, total='40.00')
        make_invoice(self.customer, self.tenant, total='60.00')
        make_invoice(self.customer, self.tenant, status='SENT', sent_at=timezone.now())

        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['unsent_count'], 2)
        self.assertEqual(resp.context['unsent_amount'], Decimal('100.00'))
        self.assertIn(('unsent', 'Not sent'), resp.context['status_pills'])
        html = resp.content.decode()
        self.assertIn('data-unsent-summary', html)
        self.assertIn('Not sent yet · 2 invoices', html)
        self.assertIn('$100.00', html)
        # The pill's count bubble
        self.assertRegex(html, r'bg-amber-100 text-amber-700">2</span>')

    def test_card_line_absent_when_everything_went_out(self):
        make_invoice(self.customer, self.tenant, status='SENT', sent_at=timezone.now())
        resp = self.client.get(LIST_URL)
        self.assertEqual(resp.context['unsent_count'], 0)
        self.assertNotIn('data-unsent-summary', resp.content.decode())

    def test_row_flags_draft_and_offers_send(self):
        draft = make_invoice(self.customer, self.tenant)
        sent = make_invoice(self.customer, self.tenant, status='SENT', sent_at=timezone.now())

        resp = self.client.get(LIST_URL)
        html = resp.content.decode()
        # Both breakpoint twins render the flag and the button.
        self.assertEqual(html.count('>Not sent</div>'), 2)
        self.assertEqual(
            html.count(f"openSendEmailModal({draft.id}, "), 2,
            'the draft row needs a one-tap Send on both the card and the table row',
        )
        self.assertNotIn(f"openSendEmailModal({sent.id}, ", html)
        # Line count feeds the modal's "Items" row (escapejs encodes the
        # hyphens in the invoice number, so match from the count on).
        self.assertRegex(html, rf"openSendEmailModal\({draft.id}, [^)]*, 1, '{draft.total}'\)")

    def test_texted_draft_is_not_flagged(self):
        texted = make_invoice(
            self.customer, self.tenant, last_sms_at=timezone.now(), last_sms_to='+15015550100',
        )
        resp = self.client.get(LIST_URL + '?status=unsent')
        self.assertNotContains(resp, texted.invoice_number)
        self.assertNotIn('>Not sent</div>', resp.content.decode())

    def test_empty_unsent_filter_says_so_plainly(self):
        make_invoice(self.customer, self.tenant, status='SENT', sent_at=timezone.now())
        resp = self.client.get(LIST_URL + '?status=unsent')
        self.assertContains(resp, 'Nothing waiting to be sent')
        self.assertContains(resp, 'Every invoice has gone out')

    def test_send_modal_subject_matches_what_is_sent(self):
        make_invoice(self.customer, self.tenant)
        resp = self.client.get(LIST_URL)
        html = resp.content.decode()
        self.assertIn("const SHOP_NAME = 'UnsentShop';", html)
        self.assertIn('Invoice ${invoiceNumber} from ${SHOP_NAME}', html)
        self.assertNotIn('[RS Systems] Invoice', html)
