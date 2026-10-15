"""
"Not invoiced" on the Jobs list (Oct 2026).

An owner who writes several tickets a day and invoices at the end could not
tell, on the Jobs page, which finished jobs already had an invoice. The
Invoices page only offered one invoice per customer; some customers want a
ticket per job. Covered here:

- live_invoices_by_job() / needs_invoice(): one definition of "on a live
  invoice" (voided and trashed invoices release their jobs)
- /tech/jobs/?invoiced=no lists finished, un-ticketed jobs only; =yes the
  reverse; the pill carries a count
- each row says "No invoice" or names its invoice; owners get a one-tap
  Create invoice that posts back to the list via ``next``
- a plain technician sees neither the pill nor the button
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceLineItem
from apps.billing.services.job_invoice_lookup import live_invoices_by_job, needs_invoice
from apps.technician_portal.models import Technician, Repair, Replacement
from apps.tenants.models import TenantMembership
from core.models import Customer
from django.contrib.auth import get_user_model
from tests.test_fieldops_s2 import make_shop, login, TEST_SETTINGS

JOBS_URL = '/tech/jobs/'


def make_invoice_for(job, tenant, status='SENT', deleted=False):
    n = Invoice.all_objects.count() + 1  # default manager hides trashed rows
    inv = Invoice.objects.create(
        customer=job.customer, tenant=tenant,
        invoice_number=f'INV-NI-{n:04d}', invoice_date=date.today(),
        status=status, subtotal=Decimal('50.00'), total=Decimal('50.00'),
        deleted_at=timezone.now() if deleted else None,
    )
    kwargs = {'repair': job} if isinstance(job, Repair) else {'replacement': job}
    InvoiceLineItem.objects.create(
        invoice=inv, description='Job', quantity=1,
        unit_price=Decimal('50.00'), amount=Decimal('50.00'), **kwargs,
    )
    return inv


@override_settings(**TEST_SETTINGS)
class JobsNotInvoicedBase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Ticket Per Job Shop', 'tpj@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            name='Penske Fleet', tenant=self.tenant, email='ap@penske.test',
        )
        login(self.client, self.user, self.tenant)

    def repair(self, status='COMPLETED', unit='T-1', **kw):
        return Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=unit, queue_status=status, damage_type='CHIP', **kw,
        )

    def replacement(self, status='COMPLETED', unit='R-1', **kw):
        return Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number=unit, queue_status=status, **kw,
        )


class LookupTests(JobsNotInvoicedBase):

    def test_live_invoice_maps_and_needs_invoice(self):
        bare = self.repair(unit='bare')
        sent = self.repair(unit='sent')
        inv = make_invoice_for(sent, self.tenant)
        voided = self.repair(unit='voided')
        make_invoice_for(voided, self.tenant, status='CANCELLED')
        trashed = self.repair(unit='trashed')
        make_invoice_for(trashed, self.tenant, deleted=True)
        skipped = self.repair(unit='skipped', skip_invoicing=True)
        open_job = self.repair(unit='open', status='IN_PROGRESS')
        repl = self.replacement()
        repl_inv = make_invoice_for(repl, self.tenant, status='DRAFT')

        by_repair, by_replacement = live_invoices_by_job(self.tenant)
        self.assertEqual(by_repair, {sent.id: {'id': inv.id, 'number': inv.invoice_number}})
        self.assertEqual(by_replacement, {repl.id: {'id': repl_inv.id, 'number': repl_inv.invoice_number}})

        self.assertTrue(needs_invoice(bare, None))
        self.assertTrue(needs_invoice(voided, None))
        self.assertTrue(needs_invoice(trashed, None))
        self.assertFalse(needs_invoice(sent, by_repair[sent.id]))
        self.assertFalse(needs_invoice(skipped, None))
        self.assertFalse(needs_invoice(open_job, None))

    def test_lookup_is_tenant_scoped(self):
        other_user, other_tenant = make_shop('Other Shop', 'other-tpj@test.com')
        other_tech = Technician.objects.get(user=other_user, tenant=other_tenant)
        other_customer = Customer.objects.create(name='Theirs', tenant=other_tenant)
        theirs = Repair.objects.create(
            tenant=other_tenant, customer=other_customer, technician=other_tech,
            unit_number='X', queue_status='COMPLETED', damage_type='CHIP',
        )
        make_invoice_for(theirs, other_tenant)
        by_repair, _ = live_invoices_by_job(self.tenant)
        self.assertEqual(by_repair, {})


class JobsListFilterTests(JobsNotInvoicedBase):

    def test_not_invoiced_filter_lists_finished_unticketed_jobs_only(self):
        bare = self.repair(unit='BARE-1')
        bare_repl = self.replacement(unit='BARE-R')
        invoiced = self.repair(unit='INVD-1')
        make_invoice_for(invoiced, self.tenant)
        skipped = self.repair(unit='SKIP-1', skip_invoicing=True)
        in_progress = self.repair(unit='PROG-1', status='IN_PROGRESS')

        resp = self.client.get(JOBS_URL + '?invoiced=no')
        self.assertEqual(resp.status_code, 200)
        ids = {(j.service_type, j.id) for j in resp.context['jobs']}
        self.assertEqual(ids, {('repair', bare.id), ('replacement', bare_repl.id)})
        self.assertEqual(resp.context['invoiced_filter'], 'no')
        self.assertEqual(resp.context['uninvoiced_count'], 2)

    def test_invoiced_filter_lists_ticketed_jobs_only(self):
        bare = self.repair(unit='BARE-1')
        invoiced = self.repair(unit='INVD-1')
        make_invoice_for(invoiced, self.tenant)
        resp = self.client.get(JOBS_URL + '?invoiced=yes')
        ids = {j.id for j in resp.context['jobs']}
        self.assertEqual(ids, {invoiced.id})

    def test_count_ignores_other_filters(self):
        self.repair(unit='A')
        self.repair(unit='B')
        resp = self.client.get(JOBS_URL + '?status=IN_PROGRESS')
        self.assertEqual(len(resp.context['jobs']), 0)
        self.assertEqual(resp.context['uninvoiced_count'], 2)

    def test_pill_shows_count_and_toggles(self):
        self.repair(unit='A')
        resp = self.client.get(JOBS_URL)
        html = resp.content.decode()
        self.assertIn('data-not-invoiced-pill', html)
        self.assertRegex(html, r'bg-amber-100 text-amber-700">1</span>')
        self.assertIn('?invoiced=no', html)

        resp = self.client.get(JOBS_URL + '?invoiced=no')
        self.assertContains(resp, 'bg-amber-50 border-amber-300 text-amber-800')

    def test_empty_filter_says_so(self):
        invoiced = self.repair(unit='INVD-1')
        make_invoice_for(invoiced, self.tenant)
        resp = self.client.get(JOBS_URL + '?invoiced=no')
        self.assertContains(resp, 'Every finished job has an invoice')

    def test_bad_value_falls_back_to_all(self):
        self.repair(unit='A')
        resp = self.client.get(JOBS_URL + '?invoiced=maybe')
        self.assertEqual(resp.context['invoiced_filter'], 'all')
        self.assertEqual(len(resp.context['jobs']), 1)


class JobsListRowTests(JobsNotInvoicedBase):

    def test_row_flags_and_create_invoice_button(self):
        bare = self.repair(unit='BARE-1')
        invoiced = self.repair(unit='INVD-1')
        inv = make_invoice_for(invoiced, self.tenant)

        resp = self.client.get(JOBS_URL)
        html = resp.content.decode()
        self.assertTrue(resp.context['user_can_invoices'])
        # Both breakpoint twins flag the bare job and carry the form.
        self.assertIn('>No invoice</div>', html)
        self.assertIn('No invoice yet', html)
        self.assertEqual(
            html.count(f'/owner/invoices/generate-from-repair/{bare.id}/'), 2,
            'Create invoice must be on the card and the table row',
        )
        self.assertNotIn(f'/owner/invoices/generate-from-repair/{invoiced.id}/', html)
        # The invoiced row names its invoice and links to it.
        self.assertIn(inv.invoice_number, html)
        self.assertIn(f'/owner/invoices/{inv.id}/', html)
        # The form carries the list URL back so the owner stays put.
        self.assertIn('name="next" value="/tech/jobs/"', html)

    def test_replacement_row_posts_to_replacement_generator(self):
        repl = self.replacement()
        resp = self.client.get(JOBS_URL)
        self.assertContains(resp, f'/owner/invoices/generate-from-replacement/{repl.id}/')

    def test_create_invoice_returns_to_list_and_row_is_ticketed(self):
        bare = self.repair(unit='BARE-1')
        resp = self.client.post(
            f'/owner/invoices/generate-from-repair/{bare.id}/',
            {'next': '/tech/jobs/?invoiced=no'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/tech/jobs/?invoiced=no')
        inv = Invoice.objects.get(line_items__repair=bare)
        self.assertEqual(inv.status, 'DRAFT')

        resp = self.client.get('/tech/jobs/?invoiced=no', follow=True)
        self.assertEqual(len(resp.context['jobs']), 0)
        self.assertContains(resp, f'Invoice {inv.invoice_number} created for Penske Fleet')
        self.assertContains(resp, 'Not sent')

        resp = self.client.get(JOBS_URL)
        self.assertContains(resp, inv.invoice_number)
        self.assertNotContains(resp, 'No invoice yet')

    def test_replacement_generator_honours_next(self):
        repl = self.replacement()
        resp = self.client.post(
            f'/owner/invoices/generate-from-replacement/{repl.id}/',
            {'next': '/tech/jobs/'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/tech/jobs/')
        self.assertTrue(Invoice.objects.filter(line_items__replacement=repl).exists())

    def test_offsite_next_is_ignored(self):
        bare = self.repair(unit='BARE-1')
        resp = self.client.post(
            f'/owner/invoices/generate-from-repair/{bare.id}/',
            {'next': 'https://evil.example/'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/owner/invoices/'))
        resp = self.client.post(
            f'/owner/invoices/generate-from-repair/{self.repair(unit="B").id}/',
            {'next': '//evil.example/'},
        )
        self.assertTrue(resp.url.startswith('/owner/invoices/'))


class PlainTechnicianTests(JobsNotInvoicedBase):

    def test_technician_sees_no_pill_and_no_button(self):
        User = get_user_model()
        tech_user = User.objects.create_user('planetech', 'planetech@test.com', 'pass')
        TenantMembership.objects.create(
            user=tech_user, tenant=self.tenant, role='technician', is_active=True,
        )
        tech = Technician.objects.create(user=tech_user, tenant=self.tenant, is_active=True)
        job = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=tech,
            unit_number='T-9', queue_status='COMPLETED', damage_type='CHIP',
        )
        client = Client()
        login(client, tech_user, self.tenant)
        resp = client.get(JOBS_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['user_can_invoices'])
        html = resp.content.decode()
        self.assertNotIn('data-not-invoiced-pill', html)
        self.assertNotIn(f'/owner/invoices/generate-from-repair/{job.id}/', html)
