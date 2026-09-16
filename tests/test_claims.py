"""
Insurance claim tracking, Tier 1 (IMPROVEMENT_SESSIONS B5): a job flagged
"Insurance claim" makes its invoice a claim to track → the owner records what
the insurer actually sent → the claim reads short / paid / closed and the
"Owed to you" card counts short-paid claims separately from unpaid invoices.

Guard module: the acceptance criteria in the session doc, one test each, plus
the money-derivation and tenant-isolation invariants.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.billing.claim_models import InsuranceClaim
from apps.billing.models import Invoice, InvoiceLineItem, Payment
from apps.billing.services import claim_service
from apps.billing.services.claim_service import ClaimError
from apps.billing.services.invoice_sync import recalculate_invoice_totals
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.security.audit import log_event
from apps.security.models import SecurityAuditLog
from apps.technician_portal.models import Repair, Technician
from apps.tenants.models import TenantMembership
from core.models import Customer
from tests.test_e2e_today import make_tenant

TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'BASE_URL': 'https://rssystems.io',
}

D = Decimal


def shop_client(user, tenant):
    client = Client()
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()
    return client


@override_settings(**TEST_SETTINGS)
class ClaimTestCase(TestCase):
    def setUp(self):
        self.owner, self.tenant = make_tenant('Claim Shop', 'claim_owner')
        self.tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True, is_manager=True,
            can_repair=True, can_replace=True,
        )
        self.customer = Customer.objects.create(
            name='Pat Person', tenant=self.tenant, customer_type='RETAIL', email='pat@example.com',
        )
        self.client = shop_client(self.owner, self.tenant)

    def make_job(self, insurance=True, price='380.00', **kwargs):
        fields = dict(
            insurance_claim=insurance,
            insurance_company='State Farm' if insurance else '',
            claim_number='SF-123' if insurance else '',
            authorization_number='AUTH-9' if insurance else '',
            deductible=D('100.00') if insurance else None,
        )
        fields.update(kwargs)
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            damage_type='Crack', queue_status='COMPLETED', cost_override=D(price),
            unit_number='', vehicle_year=2020, vehicle_make='Toyota', vehicle_model='Camry',
            **fields,
        )

    def make_invoice(self, job=None, **job_kwargs):
        job = job or self.make_job(**job_kwargs)
        return InvoiceTrackingService(tenant=self.tenant).create_invoice_from_services(
            self.customer, [job],
        )

    def pay(self, invoice, amount, from_insurer=True, **kwargs):
        claim = InsuranceClaim.objects.get(invoice=invoice) if from_insurer else None
        return Payment.objects.create(
            invoice=invoice, amount=D(amount), payment_method='CHECK', claim=claim,
            recorded_by=self.owner, **kwargs,
        )

    def claim_of(self, invoice):
        return InsuranceClaim.objects.select_related('invoice').get(invoice=invoice)


class ClaimMoneyTests(ClaimTestCase):
    """The claim's numbers are derived from the job, the invoice and the payments."""

    def test_invoice_from_flagged_job_tracks_a_claim(self):
        invoice = self.make_invoice()
        self.assertEqual(invoice.total, D('380.00'))
        claim = self.claim_of(invoice)
        self.assertEqual(claim.tenant, self.tenant)
        self.assertEqual(claim.insurer, 'State Farm')
        self.assertEqual(claim.claim_number, 'SF-123')
        self.assertEqual(claim.authorization_number, 'AUTH-9')
        self.assertEqual(claim.deductible, D('100.00'))
        self.assertEqual(claim.status, 'SUBMITTED')
        self.assertEqual(claim.submitted_on, invoice.invoice_date)
        # Expected = invoice total minus the customer's deductible.
        self.assertEqual(claim.expected_amount, D('280.00'))
        self.assertEqual(claim.received_amount, D('0.00'))
        self.assertEqual(claim.short_amount, D('280.00'))
        # Audited, with the tenant on the row.
        row = SecurityAuditLog.objects.get(event_type='claim_created')
        self.assertEqual(row.metadata['tenant_id'], self.tenant.id)
        self.assertEqual(row.metadata['claim_id'], claim.id)
        self.assertEqual(row.metadata['source'], 'auto')

    def test_unflagged_job_makes_no_claim(self):
        invoice = self.make_invoice(insurance=False)
        self.assertFalse(InsuranceClaim.objects.filter(invoice=invoice).exists())
        self.assertFalse(SecurityAuditLog.objects.filter(event_type='claim_created').exists())

    def test_one_claim_per_invoice(self):
        invoice = self.make_invoice()
        with self.assertRaises(ClaimError):
            claim_service.create_claim(invoice, insurer='Again')
        self.assertEqual(InsuranceClaim.objects.filter(invoice=invoice).count(), 1)
        # ensure_ is idempotent, not a second row
        self.assertEqual(claim_service.ensure_claim_for_invoice(invoice).id, self.claim_of(invoice).id)

    def test_expected_follows_invoice_then_pin_then_authorized(self):
        invoice = self.make_invoice()
        claim = self.claim_of(invoice)
        self.assertEqual(claim.expected_amount, D('280.00'))
        claim_service.update_claim(claim, billed_amount=D('300.00'))
        self.assertEqual(claim.expected_amount, D('300.00'))
        self.assertEqual(claim.status, 'SUBMITTED')
        claim_service.update_claim(claim, authorized_amount=D('250.00'))
        self.assertEqual(claim.expected_amount, D('250.00'))
        self.assertEqual(claim.authorized_short_of_billed, D('50.00'))
        self.assertEqual(claim.status, 'AUTHORIZED')
        # Pin cleared: back to following the invoice; authorized still wins.
        claim_service.update_claim(claim, billed_amount=None)
        self.assertEqual(claim.effective_billed_amount, D('280.00'))
        self.assertEqual(claim.expected_amount, D('250.00'))
        self.assertTrue(SecurityAuditLog.objects.filter(event_type='claim_updated').exists())

    def test_insurer_payment_reconciles_short_then_paid(self):
        invoice = self.make_invoice()
        self.pay(invoice, '212.00')
        claim = self.claim_of(invoice)
        self.assertEqual(claim.received_amount, D('212.00'))
        self.assertEqual(claim.short_amount, D('68.00'))
        self.assertEqual(claim.status, 'SHORT')
        self.pay(invoice, '68.00')
        claim = self.claim_of(invoice)
        self.assertEqual(claim.status, 'PAID')
        self.assertEqual(claim.short_amount, D('0.00'))
        # The invoice knows about the same money.
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, D('280.00'))
        self.assertEqual(invoice.status, 'PARTIAL')  # the deductible is still owed

    def test_customer_deductible_does_not_count_as_insurer_money(self):
        invoice = self.make_invoice()
        self.pay(invoice, '100.00', from_insurer=False)
        claim = self.claim_of(invoice)
        self.assertEqual(claim.received_amount, D('0.00'))
        self.assertEqual(claim.status, 'SUBMITTED')
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, D('100.00'))

    def test_deleting_an_insurer_payment_reverts_the_claim(self):
        invoice = self.make_invoice()
        p = self.pay(invoice, '280.00')
        self.assertEqual(self.claim_of(invoice).status, 'PAID')
        p.delete()
        claim = self.claim_of(invoice)
        self.assertEqual(claim.received_amount, D('0.00'))
        self.assertEqual(claim.status, 'SUBMITTED')

    def test_line_edit_reprices_an_unpinned_claim(self):
        invoice = self.make_invoice()
        self.pay(invoice, '280.00')
        self.assertEqual(self.claim_of(invoice).status, 'PAID')
        line = invoice.line_items.get()
        line.unit_price = D('430.00')
        line.amount = D('430.00')
        line.save()
        recalculate_invoice_totals(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, D('430.00'))
        claim = self.claim_of(invoice)
        self.assertEqual(claim.expected_amount, D('330.00'))
        self.assertEqual(claim.status, 'SHORT')
        self.assertEqual(claim.short_amount, D('50.00'))

    def test_close_writes_off_the_short_and_reopen_derives_again(self):
        invoice = self.make_invoice()
        self.pay(invoice, '212.00')
        claim = self.claim_of(invoice)
        claim_service.close_claim(claim, user=self.owner, reason='Not worth the call')
        self.assertEqual(claim.status, 'CLOSED')
        self.assertEqual(claim.written_off_amount, D('68.00'))
        self.assertEqual(claim.short_amount, D('68.00'))
        self.assertEqual(claim.outstanding_amount, D('0.00'))
        self.assertEqual(claim.closed_by, self.owner)
        self.assertEqual(claim.close_reason, 'Not worth the call')
        with self.assertRaises(ClaimError):
            claim_service.update_claim(claim, insurer='X')
        with self.assertRaises(ClaimError):
            claim_service.close_claim(claim)
        # A closed claim ignores money-derived status until reopened.
        self.pay(invoice, '68.00')
        self.assertEqual(self.claim_of(invoice).status, 'CLOSED')
        claim_service.reopen_claim(self.claim_of(invoice))
        claim = self.claim_of(invoice)
        self.assertEqual(claim.status, 'PAID')
        self.assertEqual(claim.written_off_amount, D('0.00'))
        self.assertIsNone(claim.closed_at)
        events = set(SecurityAuditLog.objects.values_list('event_type', flat=True))
        self.assertTrue({'claim_created', 'claim_closed', 'claim_reopened'} <= events)

    def test_cancelled_invoice_refuses_a_claim(self):
        invoice = self.make_invoice(insurance=False)
        invoice.cancel()
        with self.assertRaises(ClaimError):
            claim_service.create_claim(invoice, insurer='Any')

    def test_rollup_splits_short_from_waiting_and_skips_customer_covered(self):
        short = self.make_invoice()
        self.pay(short, '212.00')                       # short $68, owed $68
        waiting = self.make_invoice()                   # nothing in, owed $280
        covered = self.make_invoice()
        self.pay(covered, '212.00')                     # insurer short $68 ...
        self.pay(covered, '168.00', from_insurer=False)  # ... customer paid the rest
        covered.refresh_from_db()
        self.assertEqual(covered.status, 'PAID')
        self.assertEqual(self.claim_of(covered).status, 'SHORT')
        self.assertEqual(self.claim_of(covered).outstanding_amount, D('0.00'))
        rollup = claim_service.rollup(self.tenant)
        self.assertEqual(rollup['short'], {'count': 1, 'total': D('68.00')})
        self.assertEqual(rollup['waiting'], {'count': 1, 'total': D('280.00')})


class ClaimViewTests(ClaimTestCase):
    """Owner surfaces: list, detail, the invoice page, the aging card."""

    def test_claim_list_renders_and_filters(self):
        short = self.make_invoice()
        self.pay(short, '212.00')
        waiting = self.make_invoice()
        r = self.client.get(reverse('claim_list'))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('State Farm', body)
        self.assertIn('$68.00', body)
        self.assertIn('$280.00', body)
        r = self.client.get(reverse('claim_list') + '?status=short')
        self.assertEqual(len(r.context['claims']), 1)
        self.assertEqual(r.context['claims'][0].invoice_id, short.id)
        r = self.client.get(reverse('claim_list') + '?status=waiting')
        self.assertEqual([c.invoice_id for c in r.context['claims']], [waiting.id])
        r = self.client.get(reverse('claim_list') + '?status=paid')
        self.assertEqual(len(r.context['claims']), 0)

    def test_claim_detail_is_tenant_scoped(self):
        invoice = self.make_invoice()
        claim = self.claim_of(invoice)
        r = self.client.get(reverse('claim_detail', args=[claim.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Insurer still owes')
        other_owner, other_tenant = make_tenant('Other Shop', 'other_claim_owner')
        other = shop_client(other_owner, other_tenant)
        self.assertEqual(other.get(reverse('claim_detail', args=[claim.id])).status_code, 404)
        self.assertEqual(other.post(reverse('claim_close', args=[claim.id])).status_code, 404)
        self.assertNotContains(other.get(reverse('claim_list')), 'State Farm')

    def test_technician_cannot_open_claims(self):
        tech_user = User.objects.create_user('claim_tech', 'tech@example.com', 'pw')
        Technician.objects.create(user=tech_user, tenant=self.tenant, is_active=True, can_repair=True)
        TenantMembership.objects.create(tenant=self.tenant, user=tech_user, role='technician')
        tech = shop_client(tech_user, self.tenant)
        r = tech.get(reverse('claim_list'))
        self.assertNotEqual(r.status_code, 200)

    def test_record_insurer_payment_through_the_invoice_endpoint(self):
        invoice = self.make_invoice()
        claim = self.claim_of(invoice)
        mail.outbox = []
        r = self.client.post(reverse('owner_record_payment', args=[invoice.id]), {
            'amount': '312.00', 'payment_method': 'CHECK', 'reference_number': 'CHK 4471',
            'from_insurer': '1', 'next': reverse('claim_detail', args=[claim.id]),
        })
        self.assertRedirects(r, reverse('claim_detail', args=[claim.id]))
        payment = Payment.objects.get(invoice=invoice)
        self.assertEqual(payment.claim_id, claim.id)
        self.assertEqual(payment.reference_number, 'CHK 4471')
        claim.refresh_from_db()
        self.assertEqual(claim.received_amount, D('312.00'))
        # 312 of 280 expected: paid in full; the invoice still has the deductible open.
        self.assertEqual(claim.status, 'PAID')
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_due, D('68.00'))
        # An insurer's check emails nobody.
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(SecurityAuditLog.objects.filter(event_type='claim_payment').exists())
        r = self.client.get(reverse('claim_detail', args=[claim.id]))
        self.assertContains(r, 'CHK 4471')
        self.assertContains(r, 'Paid in full')

    def test_short_message_names_the_short_amount(self):
        invoice = self.make_invoice()
        r = self.client.post(reverse('owner_record_payment', args=[invoice.id]), {
            'amount': '212.00', 'payment_method': 'ACH', 'from_insurer': '1',
        }, follow=True)
        self.assertContains(r, 'short $68.00')
        # The invoice page's claim panel shows the same number.
        self.assertContains(r, 'Short-paid')
        self.assertContains(r, '$68.00')

    def test_from_insurer_without_a_claim_is_refused(self):
        invoice = self.make_invoice(insurance=False)
        r = self.client.post(reverse('owner_record_payment', args=[invoice.id]), {
            'amount': '50.00', 'payment_method': 'CASH', 'from_insurer': '1',
        }, follow=True)
        self.assertContains(r, 'no insurance claim')
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())

    def test_invoice_page_offers_tracking_and_one_tap_creates_it(self):
        invoice = self.make_invoice(insurance=False)
        r = self.client.get(reverse('owner_invoice_detail', args=[invoice.id]))
        self.assertContains(r, 'Track insurance claim')
        self.assertContains(r, 'Billing an insurer')
        r = self.client.post(reverse('claim_create', args=[invoice.id]), {
            'insurer': 'Progressive', 'claim_number': 'PG-77', 'deductible': '250',
        })
        claim = self.claim_of(invoice)
        self.assertRedirects(r, reverse('claim_detail', args=[claim.id]))
        self.assertEqual(claim.insurer, 'Progressive')
        self.assertEqual(claim.deductible, D('250.00'))
        self.assertEqual(claim.expected_amount, D('130.00'))
        self.assertEqual(SecurityAuditLog.objects.get(event_type='claim_created').metadata['source'], 'owner')
        r = self.client.get(reverse('owner_invoice_detail', args=[invoice.id]))
        self.assertContains(r, 'Open claim')
        self.assertContains(r, 'This payment is from the insurer')
        self.assertNotContains(r, 'Track insurance claim')
        # Second tap is refused, not duplicated.
        r = self.client.post(reverse('claim_create', args=[invoice.id]), {}, follow=True)
        self.assertContains(r, 'already has an insurance claim')
        self.assertEqual(InsuranceClaim.objects.filter(invoice=invoice).count(), 1)

    def test_invoice_page_prefills_from_the_flagged_job(self):
        job = self.make_job()
        invoice = self.make_invoice(job)
        InsuranceClaim.objects.filter(invoice=invoice).delete()  # pretend it was never tracked
        r = self.client.get(reverse('owner_invoice_detail', args=[invoice.id]))
        self.assertContains(r, 'marked as an insurance claim with State Farm')
        self.assertContains(r, 'value="SF-123"')

    def test_edit_close_and_reopen_views(self):
        invoice = self.make_invoice()
        claim = self.claim_of(invoice)
        r = self.client.post(reverse('claim_edit', args=[claim.id]), {
            'insurer': 'State Farm', 'claim_number': 'SF-123', 'authorization_number': 'AUTH-9',
            'deductible': '100', 'billed_amount': '', 'authorized_amount': '250.00',
            'submitted_on': '2026-09-01', 'notes': 'Spoke to Dana',
        })
        self.assertRedirects(r, reverse('claim_detail', args=[claim.id]))
        claim.refresh_from_db()
        self.assertEqual(claim.status, 'AUTHORIZED')
        self.assertEqual(claim.authorized_amount, D('250.00'))
        self.assertEqual(str(claim.submitted_on), '2026-09-01')
        self.assertEqual(claim.notes, 'Spoke to Dana')
        r = self.client.post(reverse('claim_edit', args=[claim.id]), {'authorized_amount': 'lots'}, follow=True)
        self.assertContains(r, 'must be a dollar amount')
        r = self.client.post(reverse('claim_close', args=[claim.id]), {'reason': 'Customer paid'}, follow=True)
        self.assertContains(r, '$250.00 written off')
        claim.refresh_from_db()
        self.assertEqual(claim.status, 'CLOSED')
        r = self.client.post(reverse('claim_reopen', args=[claim.id]), follow=True)
        self.assertContains(r, 'Claim reopened')
        claim.refresh_from_db()
        self.assertEqual(claim.status, 'AUTHORIZED')

    def test_owed_to_you_card_counts_claims_separately(self):
        short = self.make_invoice()
        self.pay(short, '212.00')
        self.make_invoice()  # waiting
        r = self.client.get(reverse('owner_invoice_list'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['claims_short'], {'count': 1, 'total': D('68.00')})
        self.assertEqual(r.context['claims_waiting'], {'count': 1, 'total': D('280.00')})
        self.assertContains(r, 'Short-paid by insurers')
        self.assertContains(r, 'Waiting on insurers')
        self.assertContains(r, 'Insurer short $68.00')
        # The insurance pill lists only invoices carrying a claim.
        plain = self.make_invoice(insurance=False)
        r = self.client.get(reverse('owner_invoice_list') + '?status=insurance')
        ids = {inv.id for inv in r.context['invoices']}
        self.assertIn(short.id, ids)
        self.assertNotIn(plain.id, ids)

    def test_owed_to_you_card_is_quiet_without_claims(self):
        self.make_invoice(insurance=False)
        r = self.client.get(reverse('owner_invoice_list'))
        self.assertNotContains(r, 'data-claims-summary')


class AuditHelperTests(TestCase):
    def test_unknown_event_type_is_a_bug(self):
        with self.assertRaises(ValueError):
            log_event(None, 'claim_exploded', 'nope')

    def test_service_call_without_request_records_unspecified_ip(self):
        row = log_event(None, 'claim_created', 'auto')
        self.assertEqual(row.ip_address, '0.0.0.0')
        self.assertIsNone(row.user)
