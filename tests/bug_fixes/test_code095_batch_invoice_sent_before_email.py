"""
Regression tests for CODE-095:
  _create_batch_invoice() was stamping status='SENT' and sent_at BEFORE attempting
  email delivery. If the email failed, the invoice was permanently 'SENT' even
  though the customer never received it.

  Fix:
    1. Invoice is always created as DRAFT.
    2. Email is attempted via _send_batch_invoice_email() which now returns bool.
    3. Only if email succeeds → status='SENT' + sent_at stamped.
    4. If email fails → stays DRAFT, a WARNING is logged (owner can retry manually).
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from apps.tenants.models import Tenant
from core.models import Customer
from apps.technician_portal.models import Repair, Technician
from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.customer_portal.models import CustomerRepairPreference


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant(name='Auto Batch Shop'):
    owner = User.objects.create_user(
        username=f'owner_{User.objects.count()}',
        email=f'owner{User.objects.count()}@example.com',
        password='pass',
    )
    return Tenant.objects.create(
        name=name,
        slug=f'{name.lower().replace(" ", "-")}-{Tenant.objects.count()}',
        plan='trial',
        owner=owner,
    )


def _make_customer(tenant, name='Fleet Co', email='fleet@example.com'):
    return Customer.objects.create(tenant=tenant, name=name, email=email)


def _make_technician(tenant):
    user = User.objects.create_user(
        username=f'tech_{User.objects.count()}',
        email=f'tech{User.objects.count()}@example.com',
        password='pass',
    )
    return Technician.objects.create(tenant=tenant, user=user, is_active=True)


def _make_repair(tenant, customer, technician, cost=Decimal('50.00'), status='COMPLETED'):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='T-001',
        damage_type='Chip',
        queue_status=status,
        cost=cost,
        service_date=timezone.now().date(),
    )


def _make_config(tenant, auto_send=True):
    config, _ = BillingConfig.objects.get_or_create(tenant=tenant)
    config.company_name = tenant.name
    config.company_phone = '555-0000'
    config.company_email = 'shop@example.com'
    config.default_payment_terms = 'NET30'
    config.default_due_days = 30
    config.invoice_number_prefix = 'BATCH'
    config.batch_invoice_auto_send = auto_send
    config.batch_invoice_frequency = 'weekly'
    config.batch_invoice_day = 0  # Monday
    config.tax_enabled = False
    config.save()
    return config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class BatchInvoiceSentBeforeEmailTests(TestCase):
    """CODE-095: batch invoice SENT status only set after email confirmed."""

    def setUp(self):
        self.tenant = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.config = _make_config(self.tenant, auto_send=True)
        self.technician = _make_technician(self.tenant)
        self.repair = _make_repair(self.tenant, self.customer, self.technician)

    # ------------------------------------------------------------------
    # 1. auto_send=False: invoice created as DRAFT, no email, status=DRAFT
    # ------------------------------------------------------------------

    def test_auto_send_false_creates_draft(self):
        """When auto_send=False the invoice should always be DRAFT."""
        from apps.billing.tasks import _create_batch_invoice
        self.config.batch_invoice_auto_send = False
        self.config.save()

        with patch('apps.billing.tasks._send_batch_invoice_email') as mock_send:
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        self.assertIsNotNone(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'DRAFT')
        mock_send.assert_not_called()
        self.assertIsNone(invoice.sent_at)

    # ------------------------------------------------------------------
    # 2. auto_send=True, email succeeds: invoice promoted to SENT
    # ------------------------------------------------------------------

    def test_auto_send_email_success_marks_sent(self):
        """Successful email delivery → invoice.status='SENT' + sent_at set."""
        from apps.billing.tasks import _create_batch_invoice

        with patch('apps.billing.tasks._send_batch_invoice_email', return_value=True):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        self.assertIsNotNone(invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')
        self.assertIsNotNone(invoice.sent_at)

    # ------------------------------------------------------------------
    # 3. auto_send=True, email FAILS: invoice stays DRAFT (not SENT)
    # ------------------------------------------------------------------

    def test_auto_send_email_failure_stays_draft(self):
        """Email delivery failure → invoice stays DRAFT (not permanently SENT)."""
        from apps.billing.tasks import _create_batch_invoice

        with patch('apps.billing.tasks._send_batch_invoice_email', return_value=False):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        self.assertIsNotNone(invoice)
        invoice.refresh_from_db()
        # Must remain DRAFT — customer never received anything
        self.assertEqual(invoice.status, 'DRAFT')
        self.assertIsNone(invoice.sent_at)

    # ------------------------------------------------------------------
    # 4. _send_batch_invoice_email returns False for missing email
    # ------------------------------------------------------------------

    def test_send_batch_email_returns_false_when_no_email(self):
        """Customer with no email → _send_batch_invoice_email returns False."""
        from apps.billing.tasks import _send_batch_invoice_email

        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='TEST-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            payment_terms='NET30',
            status='DRAFT',
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
            discount=0,
            tax_rate=0,
            tax_amount=0,
            amount_paid=0,
        )

        no_email_customer = Customer.objects.create(
            tenant=self.tenant,
            name='No Email Co',
            email='',  # no email
        )
        invoice.customer = no_email_customer

        result = _send_batch_invoice_email(invoice, self.config)
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # 5. _send_batch_invoice_email returns True on successful send
    # ------------------------------------------------------------------

    def test_send_batch_email_returns_true_on_success(self):
        """Successful send_mail call → _send_batch_invoice_email returns True."""
        from apps.billing.tasks import _send_batch_invoice_email

        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='TEST-002',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            payment_terms='NET30',
            status='DRAFT',
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
            discount=0,
            tax_rate=0,
            tax_amount=0,
            amount_paid=0,
        )

        with patch('apps.billing.tasks.send_mail', return_value=1) as mock_mail:
            result = _send_batch_invoice_email(invoice, self.config)

        self.assertTrue(result)
        mock_mail.assert_called_once()
        # Verify fail_silently=False (so exceptions propagate and we can catch them)
        _, kwargs = mock_mail.call_args
        self.assertFalse(kwargs.get('fail_silently', True))

    # ------------------------------------------------------------------
    # 6. _send_batch_invoice_email returns False on send_mail exception
    # ------------------------------------------------------------------

    def test_send_batch_email_returns_false_on_exception(self):
        """send_mail raising an exception → returns False (doesn't re-raise)."""
        from apps.billing.tasks import _send_batch_invoice_email

        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='TEST-003',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            payment_terms='NET30',
            status='DRAFT',
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
            discount=0,
            tax_rate=0,
            tax_amount=0,
            amount_paid=0,
        )

        with patch('apps.billing.tasks.send_mail', side_effect=Exception('SMTP error')):
            result = _send_batch_invoice_email(invoice, self.config)

        self.assertFalse(result)

    # ------------------------------------------------------------------
    # 7. Invoice is always created as DRAFT inside the atomic block
    #    (even when auto_send=True — status is patched after the atomic commits)
    # ------------------------------------------------------------------

    def test_invoice_initially_created_as_draft_even_when_auto_send_true(self):
        """Inside the atomic block, invoice is always DRAFT until email confirmed."""
        from apps.billing.tasks import _create_batch_invoice

        captured_statuses = []

        original_send = __import__('apps.billing.tasks', fromlist=['_send_batch_invoice_email'])

        def mock_send(invoice, config):
            # At this point (just before email), invoice should already be saved.
            # We check what the DB has — it must still be DRAFT.
            inv_from_db = Invoice.objects.get(pk=invoice.pk)
            captured_statuses.append(inv_from_db.status)
            return True  # simulate success

        with patch('apps.billing.tasks._send_batch_invoice_email', side_effect=mock_send):
            invoice = _create_batch_invoice(self.tenant, self.customer, self.config)

        # Status when email was called: should be DRAFT
        self.assertEqual(captured_statuses, ['DRAFT'],
                         "Invoice must be DRAFT when _send_batch_invoice_email is called")
        # Final status after success: SENT
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'SENT')

    # ------------------------------------------------------------------
    # 8. No repairs → _create_batch_invoice returns None (no crash)
    # ------------------------------------------------------------------

    def test_no_repairs_returns_none(self):
        """No uninvoiced repairs → returns None, no invoice created."""
        from apps.billing.tasks import _create_batch_invoice

        # Mark the repair as already invoiced
        existing_invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='PREV-001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date(),
            payment_terms='NET30',
            status='SENT',
            subtotal=Decimal('50.00'),
            total=Decimal('50.00'),
            discount=0,
            tax_rate=0,
            tax_amount=0,
            amount_paid=0,
        )
        InvoiceLineItem.objects.create(
            invoice=existing_invoice,
            repair=self.repair,
            description='Repair',
            quantity=1,
            unit_price=Decimal('50.00'),
            amount=Decimal('50.00'),
            repair_date=self.repair.service_date,
            unit_number='T-001',
        )

        result = _create_batch_invoice(self.tenant, self.customer, self.config)
        self.assertIsNone(result)
