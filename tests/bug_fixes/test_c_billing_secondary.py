"""
Regression tests for Workstream C (Remediation Plan 2026-07-09):
secondary billing-correctness fixes.

C1 — malformed custom reminder template sent a BLANK dunning email (the
     default body was overwritten with _render_template's '' sentinel).
C2 — Stripe payment dedup was check-then-create; DB partial unique index
     on Payment.stripe_payment_id now closes the double-credit race.
C3 — overdue reminders: exact-day match meant duplicates on double runs
     and silently skipped tiers on missed cron days. Tier tracking via
     Invoice.last_reminder_days_overdue makes it idempotent + catch-up.
C4 — tax rate lookup ignored customer location; now city+state, then
     state, then tenant default.
C5 — UnitRepairCount increment is now an atomic locked read-modify-write.
C6 — auto-invoice emailed the customer even when the Invoice record
     failed to create (double-billing on the next batch run).
C7 — invoice/payment dates now use timezone.localdate() (UTC-date drift
     gave evening-shift invoices tomorrow's date).
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem, Payment, TaxRate
from apps.billing.services.reminder_service import ReminderService
from apps.billing.services.tax_service import TaxService
from apps.billing.tasks import process_overdue_invoices
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


class BillingSecondaryTestBase(TestCase):
    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='C Test Shop',
            email='owner_c@test.com',
            password='testpass123!',
            first_name='COwner',
            last_name='Owner',
        )
        self.tenant = result['tenant']
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='C Fleet', customer_type='FLEET',
            email='ap@cfleet.test', city='Little Rock', state='AR',
        )

    def _make_invoice(self, number='INV-C-001', status='OVERDUE', days_overdue=10):
        invoice = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number=number,
            status=status,
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            invoice_date=timezone.localdate() - timedelta(days=days_overdue + 30),
            due_date=timezone.localdate() - timedelta(days=days_overdue),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, description='Chip repair', quantity=1,
            unit_price=Decimal('100.00'), amount=Decimal('100.00'),
        )
        return invoice


class C1MalformedTemplateTests(BillingSecondaryTestBase):
    def test_malformed_template_falls_back_to_default_body(self):
        config = BillingConfig.get_for_tenant(self.tenant)
        config.reminder_email_template = 'Hi {custome'  # stray brace
        config.save(update_fields=['reminder_email_template'])

        invoice = self._make_invoice()
        result = ReminderService(tenant=self.tenant).send_reminder(invoice, 'overdue_7d')
        self.assertTrue(result['success'])

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertTrue(body.strip(), "reminder body must never be empty")
        self.assertIn(
            invoice.invoice_number, body,
            "fallback default body must reference the invoice",
        )


class C2StripePaymentDedupTests(BillingSecondaryTestBase):
    def test_db_constraint_blocks_duplicate_stripe_payment(self):
        invoice = self._make_invoice(status='SENT')
        Payment.objects.create(
            invoice=invoice, amount=Decimal('50.00'),
            payment_method='STRIPE', stripe_payment_id='pi_dup_test',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payment.objects.create(
                    invoice=invoice, amount=Decimal('50.00'),
                    payment_method='STRIPE', stripe_payment_id='pi_dup_test',
                )

    def test_blank_stripe_ids_are_exempt(self):
        invoice = self._make_invoice(number='INV-C-002', status='SENT')
        Payment.objects.create(
            invoice=invoice, amount=Decimal('10.00'), payment_method='CASH',
        )
        # A second manual payment (blank stripe id) must be fine
        Payment.objects.create(
            invoice=invoice, amount=Decimal('20.00'), payment_method='CHECK',
        )
        self.assertEqual(invoice.payments.count(), 2)

    def test_record_stripe_payment_returns_duplicate_on_race(self):
        from apps.billing.services.stripe_service import StripeService
        invoice = self._make_invoice(number='INV-C-003', status='SENT')
        svc = StripeService()

        first = svc._record_stripe_payment(invoice.id, Decimal('100.00'), 'pi_race_test')
        self.assertTrue(first['success'])
        self.assertNotIn('duplicate', first)

        second = svc._record_stripe_payment(invoice.id, Decimal('100.00'), 'pi_race_test')
        self.assertTrue(second['success'])
        self.assertTrue(second.get('duplicate'), "second delivery must be flagged duplicate")
        self.assertEqual(
            invoice.payments.filter(stripe_payment_id='pi_race_test').count(), 1,
        )


class C3ReminderIdempotencyTests(BillingSecondaryTestBase):
    def setUp(self):
        super().setUp()
        config = BillingConfig.get_for_tenant(self.tenant)
        config.overdue_reminder_enabled = True
        config.overdue_reminder_days = '7,14,30'
        config.save(update_fields=['overdue_reminder_enabled', 'overdue_reminder_days'])

    def test_double_run_sends_once(self):
        self._make_invoice(days_overdue=8)
        process_overdue_invoices()
        process_overdue_invoices()  # same day, again (manual + cron)
        self.assertEqual(
            len(mail.outbox), 1,
            "running the command twice in one day must not double-email",
        )

    def test_missed_tier_is_caught_up(self):
        # Invoice is 16 days overdue and NO reminder was ever sent (cron was
        # down on days 7 and 14). Old exact-match logic would never send
        # either tier; new logic sends the highest crossed tier (14).
        invoice = self._make_invoice(days_overdue=16)
        process_overdue_invoices()
        self.assertEqual(len(mail.outbox), 1, "a missed tier must still send")
        invoice.refresh_from_db()
        self.assertEqual(invoice.last_reminder_days_overdue, 14)

        # Next tier still fires when crossed
        invoice.due_date = timezone.localdate() - timedelta(days=31)
        invoice.save(update_fields=['due_date'])
        process_overdue_invoices()
        self.assertEqual(len(mail.outbox), 2)
        invoice.refresh_from_db()
        self.assertEqual(invoice.last_reminder_days_overdue, 30)


class C4TaxLocationLookupTests(BillingSecondaryTestBase):
    def test_city_state_match_wins_over_newest(self):
        TaxRate.objects.create(
            tenant=self.tenant, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )
        # Newer rate for a DIFFERENT city — old logic returned this for everyone
        TaxRate.objects.create(
            tenant=self.tenant, city='North Little Rock', state='AR',
            state_rate=Decimal('6.500'), city_rate=Decimal('0.500'),
            is_active=True,
        )

        result = TaxService(tenant=self.tenant).calculate_tax(
            subtotal=Decimal('100.00'), customer=self.customer,
        )
        self.assertEqual(
            result['rate'], Decimal('6.500'),
            "Little Rock customer must get the Little Rock rate, not the "
            "most recently added city's rate",
        )

    def test_falls_back_to_tenant_default_when_no_location_match(self):
        TaxRate.objects.create(
            tenant=self.tenant, city='North Little Rock', state='AR',
            state_rate=Decimal('6.500'), city_rate=Decimal('0.500'),
            is_active=True,
        )
        stranger = Customer.objects.create(
            tenant=self.tenant, name='C Stranger', customer_type='FLEET',
            city='Memphis', state='TN',
        )
        result = TaxService(tenant=self.tenant).calculate_tax(
            subtotal=Decimal('100.00'), customer=stranger,
        )
        self.assertEqual(result['rate'], Decimal('7.000'), "tenant default still applies")

    def test_no_rates_still_means_zero_tax(self):
        result = TaxService(tenant=self.tenant).calculate_tax(
            subtotal=Decimal('100.00'), customer=self.customer,
        )
        self.assertEqual(result['rate'], Decimal('0.000'))
        self.assertEqual(result['amount'], Decimal('0.00'))


class C6AutoInvoiceNoRecordNoEmailTests(BillingSecondaryTestBase):
    def test_email_suppressed_when_invoice_record_fails(self):
        from apps.billing.services.auto_invoice_service import AutoInvoiceService
        from apps.customer_portal.models import CustomerRepairPreference
        from apps.technician_portal.models import Repair, Technician

        CustomerRepairPreference.objects.create(
            customer=self.customer,
            invoice_preference='per_ticket',
            auto_email_invoices=True,
        )
        technician = Technician.objects.filter(tenant=self.tenant).first()
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=technician,
            unit_number='C6-UNIT', queue_status='COMPLETED',
        )

        svc = AutoInvoiceService()
        with patch.object(
            AutoInvoiceService, '_save_to_s3',
            return_value=f'invoices/{self.customer.id}/2026/fake.pdf',
        ), patch(
            'apps.billing.services.invoice_tracking_service.InvoiceTrackingService.create_invoice_from_services',
            side_effect=RuntimeError('db hiccup'),
        ):
            result = svc.generate_and_save(repair)

        self.assertFalse(
            result.get('emailed'),
            "no Invoice record -> no email; otherwise the repair is billed "
            "again on the next batch run after the customer already paid",
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('db hiccup', str(result.get('error', '')))


class C7LocaldateTests(BillingSecondaryTestBase):
    def test_invoice_date_default_is_localdate(self):
        field = Invoice._meta.get_field('invoice_date')
        self.assertIs(field.default, timezone.localdate)

    def test_payment_date_default_is_localdate(self):
        field = Payment._meta.get_field('payment_date')
        self.assertIs(field.default, timezone.localdate)
