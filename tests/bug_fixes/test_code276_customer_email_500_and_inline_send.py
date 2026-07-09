"""
Regression tests for CODE-276 / CODE-277:

CODE-276 — Editing a customer to add an email 500'd in production.
  Two root causes, both from the conditional unique constraint
  unique_customer_email_per_tenant (condition: email IS NOT NULL):

    1. Forms saved "no email" as '' (empty string), not NULL. The constraint
       only ignores NULL, so the SECOND no-email customer in a tenant raised
       IntegrityError on save.
    2. Django's ModelForm validation skips UniqueConstraints that have a
       condition, so giving a customer an email already used by another
       customer in the tenant went straight to the DB → IntegrityError → 500.

  Fix: Customer.save() normalizes '' → None, customer forms clean blank
  email to None and validate duplicates with a friendly error, and
  edit_customer() catches IntegrityError as a safety net.
  Migration core.0021 nulls out existing '' emails.

CODE-277 — The Send Invoice modal dead-ended when the customer had no email
  ("add an email in the customer's settings first" with no link). The modal
  now shows an inline email field; owner_send_invoice() validates it, saves
  it to the customer, and proceeds with the send in one step.
"""

from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.billing.models import Invoice


def _make_tenant(name='Email Fix Shop'):
    owner = User.objects.create_user(
        username=f'owner_ef_{User.objects.count()}',
        email=f'owner_ef_{User.objects.count()}@example.com',
        password='testpass123',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=f'email-fix-{Tenant.objects.count()}',
        plan='trial',
        owner=owner,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_draft_invoice(tenant, customer):
    return Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-TEST-{Invoice.objects.count():04d}',
        invoice_date=timezone.now().date(),
        subtotal=Decimal('50.00'),
        tax_amount=Decimal('4.88'),
        total=Decimal('54.88'),
        amount_paid=Decimal('0.00'),
        status='DRAFT',
    )


class CustomerEmailNormalizationTests(TestCase):
    """CODE-276: '' emails must be stored as NULL."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant()

    def test_model_save_normalizes_empty_string_to_null(self):
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='')
        c.refresh_from_db()
        self.assertIsNone(c.email)

    def test_model_save_strips_whitespace(self):
        c = Customer.objects.create(tenant=self.tenant, name='acme', email='  ap@acme.com  ')
        c.refresh_from_db()
        self.assertEqual(c.email, 'ap@acme.com')

    def test_two_customers_without_email_in_same_tenant(self):
        """The original production crash: second no-email customer raised
        IntegrityError because both rows stored email=''."""
        Customer.objects.create(tenant=self.tenant, name='first co', email='')
        second = Customer.objects.create(tenant=self.tenant, name='second co', email='')
        self.assertIsNone(second.email)
        self.assertEqual(Customer.objects.filter(tenant=self.tenant).count(), 2)


class EditCustomerEmail500Tests(TestCase):
    """CODE-276: edit_customer must never 500 on email conflicts."""

    def setUp(self):
        from apps.technician_portal.models import Technician
        self.tenant, self.owner = _make_tenant()
        Technician.objects.create(tenant=self.tenant, user=self.owner, is_active=True, is_manager=True)
        self.client = Client()
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_edit(self, customer, email, name=None):
        return self.client.post(reverse('edit_customer', args=[customer.id]), {
            'name': name or customer.name, 'customer_type': 'FLEET', 'email': email,
            'phone': '', 'address': '', 'city': '', 'state': '', 'zip_code': '',
            'primary_technician': '', 'tax_exempt_certificate': '',
        })

    def test_add_email_to_customer_without_email(self):
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='')
        resp = self._post_edit(c, 'ap@eostrucking.com')
        self.assertEqual(resp.status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.email, 'ap@eostrucking.com')

    def test_duplicate_email_shows_form_error_not_500(self):
        Customer.objects.create(tenant=self.tenant, name='other co', email='shared@example.com')
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='')
        resp = self._post_edit(c, 'shared@example.com')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already uses this email')
        c.refresh_from_db()
        self.assertIsNone(c.email)

    def test_duplicate_email_case_insensitive(self):
        Customer.objects.create(tenant=self.tenant, name='other co', email='shared@example.com')
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='')
        resp = self._post_edit(c, 'SHARED@EXAMPLE.COM')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already uses this email')

    def test_same_email_in_other_tenant_is_allowed(self):
        other_tenant, _ = _make_tenant('Other Shop')
        Customer.objects.create(tenant=other_tenant, name='their co', email='shared@example.com')
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='')
        resp = self._post_edit(c, 'shared@example.com')
        self.assertEqual(resp.status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.email, 'shared@example.com')

    def test_clearing_email_saves_null(self):
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='old@example.com')
        resp = self._post_edit(c, '')
        self.assertEqual(resp.status_code, 302)
        c.refresh_from_db()
        self.assertIsNone(c.email)

    def test_keeping_own_email_is_allowed(self):
        c = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='ap@eostrucking.com')
        resp = self._post_edit(c, 'ap@eostrucking.com')
        self.assertEqual(resp.status_code, 302)


class SendInvoiceInlineEmailTests(TestCase):
    """CODE-277: owner_send_invoice accepts an inline email for no-email customers."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant()
        self.customer = Customer.objects.create(tenant=self.tenant, name='eos trucking', email='')
        self.invoice = _make_draft_invoice(self.tenant, self.customer)
        self.client = Client()
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_send(self, email=None, follow=True):
        data = {}
        if email is not None:
            data['email'] = email
        return self.client.post(
            reverse('owner_send_invoice', kwargs={'invoice_id': self.invoice.id}),
            data, follow=follow,
        )

    def test_inline_email_saved_and_invoice_sent(self):
        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
            return_value=(True, 'Sent OK'),
        ) as mock_send:
            self._post_send('ap@eostrucking.com')

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'ap@eostrucking.com')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'SENT')
        self.assertEqual(mock_send.call_args.kwargs['recipient_email'], 'ap@eostrucking.com')

    def test_invalid_inline_email_rejected(self):
        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        ) as mock_send:
            resp = self._post_send('not-an-email')

        mock_send.assert_not_called()
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.email)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'DRAFT')
        messages = [m.message for m in resp.context['messages']]
        self.assertTrue(any('not a valid email' in m for m in messages), messages)

    def test_inline_email_duplicate_of_other_customer_rejected(self):
        Customer.objects.create(tenant=self.tenant, name='other co', email='shared@example.com')
        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        ) as mock_send:
            resp = self._post_send('shared@example.com')

        mock_send.assert_not_called()
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.email)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'DRAFT')
        messages = [m.message for m in resp.context['messages']]
        self.assertTrue(any('already uses that email' in m for m in messages), messages)

    def test_no_email_still_blocks_send(self):
        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
        ) as mock_send:
            resp = self._post_send()

        mock_send.assert_not_called()
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'DRAFT')
        messages = [m.message for m in resp.context['messages']]
        self.assertTrue(any('no email address on file' in m for m in messages), messages)

    def test_inline_email_ignored_when_customer_already_has_email(self):
        self.customer.email = 'existing@eostrucking.com'
        self.customer.save()
        with patch(
            'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email',
            return_value=(True, 'Sent OK'),
        ) as mock_send:
            self._post_send('other@example.com')

        # Existing email on file wins — the inline field only fills a gap.
        self.assertEqual(mock_send.call_args.kwargs['recipient_email'], 'existing@eostrucking.com')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'existing@eostrucking.com')
