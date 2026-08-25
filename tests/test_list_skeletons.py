"""Skeletons and optimistic status changes (UI_MAGIC_SESSIONS S11).

Three contracts, all of which fail silently in the browser if broken.

1. `data-skeleton-list` is the ONLY thing static/js/list-loading.js looks for.
   A list that loses the attribute keeps working perfectly and simply stops
   saying anything during the second it spends waiting on the server.
2. `data-optimistic-row` / `-badge` / `-due` / `-actions` are the handles the
   optimistic flip and its rollback reach for. A renamed wrapper does not throw
   — `querySelector` returns null, the row silently never flips, and the
   feature quietly degrades to what it replaced.
3. `owner_invoice_bulk_action` must name the invoices it actually paid. Without
   `paid_ids` the page can only flip every selected row and hope; a partial
   success then leaves invoices looking paid that are not, until the next load.
"""

import json
import re
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.billing.models import Invoice, InvoiceLineItem
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer
from core.templatetags.ui import status_badge


def _make_shop():
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name='Skeleton Shop', email='sk@test.com', password='testpass123!',
        first_name='Test', last_name='Owner',
    )


class _ShopCase(TestCase):
    def setUp(self):
        result = _make_shop()
        self.tenant = result['tenant']
        self.user = result['user']
        self.technician = Technician.objects.filter(tenant=self.tenant).first()
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Ridgeline Fleet Services',
            email='fleet@ridgeline.test', phone='5015550100',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.technician,
            unit_number='U101', damage_type='CHIP', queue_status='PENDING',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _invoice(self, number, status='SENT', total='150.00', paid='0.00'):
        invoice = Invoice.objects.create(
            customer=self.customer, invoice_number=number, status=status,
            subtotal=Decimal(total), total=Decimal(total), amount_paid=Decimal(paid),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Windshield repair', quantity=1,
            unit_price=Decimal(total), amount=Decimal(total),
        )
        return invoice


class SkeletonMarkupTests(_ShopCase):
    """Both breakpoint twins of both lists opt in."""

    def test_jobs_list_marks_both_row_containers(self):
        html = self.client.get('/tech/jobs/').content.decode()
        # One for the mobile card stack, one for the desktop <tbody>. Only the
        # painted one ever traces, but the page cannot know which that is.
        self.assertEqual(html.count('data-skeleton-list'), 2)

    def test_invoice_list_marks_both_row_containers(self):
        self._invoice('INV-1001')
        html = self.client.get('/owner/invoices/').content.decode()
        self.assertEqual(html.count('data-skeleton-list'), 2)

    def test_both_shells_load_the_scripts(self):
        html = self.client.get('/tech/jobs/').content.decode()
        self.assertIn('js/list-loading.js', html)
        self.assertIn('js/optimistic.js', html)

    def test_create_invoice_modal_waits_with_a_skeleton_not_a_spinner(self):
        self._invoice('INV-1001')
        html = self.client.get('/owner/invoices/').content.decode()
        loading = re.search(
            r'<div id="modal-loading".*?</div>\s*</div>\s*</div>', html, re.S)
        self.assertIsNotNone(loading, 'the modal loading state is gone')
        block = loading.group(0)
        self.assertNotIn('fa-spinner', block)
        self.assertIn('sk-bar', block)


class OptimisticMarkupTests(_ShopCase):
    """The handles the optimistic flip reaches for."""

    def test_invoice_rows_carry_every_handle(self):
        invoice = self._invoice('INV-1001')
        html = self.client.get('/owner/invoices/').content.decode()
        # Mobile card + desktop row.
        self.assertEqual(
            html.count('data-optimistic-row="invoice-%d"' % invoice.id), 2)
        for handle in ('data-optimistic-badge', 'data-optimistic-due',
                       'data-optimistic-actions'):
            self.assertIn(handle, html, '%s is not rendered' % handle)

    def test_job_rows_are_keyed_by_service_type_not_bare_id(self):
        """A repair and a replacement can share an integer id."""
        html = self.client.get('/tech/jobs/').content.decode()
        self.assertIn('data-optimistic-row="repair-%d"' % self.repair.id, html)
        self.assertNotIn('data-optimistic-row="%d"' % self.repair.id, html)

    def test_status_badge_hooks_are_opt_in(self):
        plain = status_badge('SENT', kind='invoice')
        self.assertFalse(plain['optimistic'])
        opted = status_badge('SENT', kind='invoice', optimistic=True)
        self.assertTrue(opted['optimistic'])
        # The classes the JS rewrites to must stay the tag's own.
        self.assertEqual(
            status_badge('PAID', kind='invoice')['classes'], 'bg-green-100 text-green-800')


class BulkMarkPaidReconciliationTests(_ShopCase):
    """The server has to name what it paid, not just count it."""

    def _mark_paid(self, ids):
        response = self.client.post(
            reverse('owner_invoice_bulk_action'),
            data=json.dumps({'action': 'mark_paid', 'invoice_ids': ids,
                             'payment_method': 'CASH'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_names_the_invoices_it_paid(self):
        one = self._invoice('INV-1001')
        two = self._invoice('INV-1002', total='240.00')
        data = self._mark_paid([one.id, two.id])
        self.assertTrue(data['success'])
        self.assertCountEqual(data['paid_ids'], [one.id, two.id])
        self.assertEqual(data['skipped_ids'], [])

    def test_names_the_invoices_it_skipped(self):
        """The row the page must roll back, and the reason it exists."""
        payable = self._invoice('INV-1001')
        already = self._invoice('INV-1002', status='PAID', total='240.00', paid='240.00')
        data = self._mark_paid([payable.id, already.id])
        self.assertEqual(data['paid_ids'], [payable.id])
        self.assertEqual(data['skipped_ids'], [already.id])
        # And the count in the message agrees with the ids beside it.
        self.assertIn('1 invoice(s)', data['message'])

    def test_a_cancelled_invoice_is_skipped_not_paid(self):
        voided = self._invoice('INV-1001', status='CANCELLED')
        data = self._mark_paid([voided.id])
        self.assertEqual(data['paid_ids'], [])
        self.assertEqual(data['skipped_ids'], [voided.id])
