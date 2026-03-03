"""
Billing Models Tests — Invoice, Payment, TaxRate, BillingConfig

Tests model behavior, validation, auto-calculations, and constraints.

Author: Amelia (Clawdbot AI)
"""

from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem, Payment, TaxRate
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


@override_settings(**TEST_OVERRIDES)
class BillingConfigTests(TestCase):
    """BillingConfig singleton behavior and computed properties."""

    def test_get_instance_creates_default(self):
        self.assertEqual(BillingConfig.objects.count(), 0)
        config = BillingConfig.get_instance()
        self.assertEqual(BillingConfig.objects.count(), 1)
        self.assertEqual(config.company_name, 'Rockstar Windshield Repair')

    def test_singleton_enforcement(self):
        BillingConfig.get_instance()
        with self.assertRaises(ValidationError):
            BillingConfig(singleton_id=True).save()

    def test_cannot_delete(self):
        config = BillingConfig.get_instance()
        with self.assertRaises(ValidationError):
            config.delete()

    def test_full_address(self):
        config = BillingConfig.get_instance()
        config.company_address = '123 Main St'
        config.company_city = 'Little Rock'
        config.company_state = 'AR'
        config.company_zip = '72201'
        config.save()
        self.assertIn('123 Main St', config.full_address)
        self.assertIn('Little Rock, AR 72201', config.full_address)

    def test_full_address_partial(self):
        config = BillingConfig.get_instance()
        config.company_city = 'Fayetteville'
        config.company_state = 'AR'
        config.save()
        self.assertEqual(config.full_address, 'Fayetteville, AR')

    def test_due_days_for_terms(self):
        config = BillingConfig.get_instance()
        config.default_payment_terms = 'NET30'
        self.assertEqual(config.due_days_for_terms, 30)

        config.default_payment_terms = 'COD'
        self.assertEqual(config.due_days_for_terms, 0)

        config.default_payment_terms = 'NET60'
        self.assertEqual(config.due_days_for_terms, 60)

    def test_tax_defaults(self):
        config = BillingConfig.get_instance()
        self.assertFalse(config.tax_enabled)
        self.assertEqual(config.state_tax_rate, Decimal('6.500'))


@override_settings(**TEST_OVERRIDES)
class InvoiceModelTests(TestCase):
    """Invoice model behavior: status transitions, amounts, constraints."""

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('owner1', 'o@test.com', 'pass')
        self.tenant = Tenant.objects.create(
            name='Test Shop', slug='test-shop', subdomain='test-shop',
            owner=self.user, subscription_plan=self.plan,
        )
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, role='owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', email='fleet@test.com',
        )

    def _make_invoice(self, **kwargs):
        defaults = {
            'tenant': self.tenant,
            'customer': self.customer,
            'invoice_number': 'INV-001',
            'subtotal': Decimal('100.00'),
            'total': Decimal('100.00'),
        }
        defaults.update(kwargs)
        return Invoice.objects.create(**defaults)

    def test_create_invoice(self):
        inv = self._make_invoice()
        self.assertEqual(inv.status, 'DRAFT')
        self.assertEqual(inv.amount_due, Decimal('100.00'))

    def test_amount_due(self):
        inv = self._make_invoice(amount_paid=Decimal('40.00'))
        self.assertEqual(inv.amount_due, Decimal('60.00'))

    def test_is_overdue_false_when_paid(self):
        inv = self._make_invoice(status='PAID', due_date=date.today() - timedelta(days=5))
        self.assertFalse(inv.is_overdue)

    def test_is_overdue_true(self):
        inv = self._make_invoice(status='SENT', due_date=date.today() - timedelta(days=1))
        self.assertTrue(inv.is_overdue)

    def test_is_overdue_false_future(self):
        inv = self._make_invoice(status='SENT', due_date=date.today() + timedelta(days=5))
        self.assertFalse(inv.is_overdue)

    def test_update_status_paid(self):
        inv = self._make_invoice(amount_paid=Decimal('100.00'))
        inv.update_status()
        self.assertEqual(inv.status, 'PAID')
        self.assertIsNotNone(inv.paid_at)

    def test_update_status_partial(self):
        inv = self._make_invoice(amount_paid=Decimal('50.00'))
        inv.update_status()
        self.assertEqual(inv.status, 'PARTIAL')

    def test_update_status_cancelled_unchanged(self):
        inv = self._make_invoice(status='CANCELLED', amount_paid=Decimal('100.00'))
        inv.update_status()
        self.assertEqual(inv.status, 'CANCELLED')

    def test_mark_sent(self):
        inv = self._make_invoice()
        inv.mark_sent()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'SENT')
        self.assertIsNotNone(inv.sent_at)

    def test_mark_sent_only_from_draft(self):
        inv = self._make_invoice(status='PAID')
        inv.mark_sent()
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'PAID')  # unchanged

    def test_cancel(self):
        inv = self._make_invoice()
        inv.cancel(reason='Customer requested')
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'CANCELLED')
        self.assertIn('Customer requested', inv.internal_notes)

    def test_unique_invoice_number_per_tenant(self):
        self._make_invoice(invoice_number='INV-DUP')
        with self.assertRaises(Exception):  # IntegrityError
            self._make_invoice(invoice_number='INV-DUP')

    def test_different_tenants_same_invoice_number(self):
        user2 = User.objects.create_user('owner2', 'o2@test.com', 'pass')
        tenant2 = Tenant.objects.create(
            name='Shop 2', slug='shop-2', subdomain='shop-2',
            owner=user2, subscription_plan=self.plan,
        )
        cust2 = Customer.objects.create(tenant=tenant2, name='Other Co')
        self._make_invoice(invoice_number='INV-SAME')
        # Should not raise
        Invoice.objects.create(
            tenant=tenant2, customer=cust2, invoice_number='INV-SAME',
            subtotal=Decimal('50.00'), total=Decimal('50.00'),
        )

    def test_str(self):
        inv = self._make_invoice()
        self.assertIn('INV-001', str(inv))
        self.assertIn('Fleet Co', str(inv))


@override_settings(**TEST_OVERRIDES)
class InvoiceLineItemTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('owner', 'o@test.com', 'pass')
        self.tenant = Tenant.objects.create(
            name='Shop', slug='shop', subdomain='shop',
            owner=self.user, subscription_plan=self.plan,
        )
        self.customer = Customer.objects.create(tenant=self.tenant, name='Cust')
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-LI', subtotal=Decimal('50.00'), total=Decimal('50.00'),
        )

    def test_auto_calculate_amount(self):
        li = InvoiceLineItem(
            invoice=self.invoice, description='Repair', quantity=2,
            unit_price=Decimal('25.00'), amount=Decimal('0'),
        )
        # amount=0 won't trigger auto-calc (falsy), so set to None-ish
        li.amount = None
        li.save()
        # Should be 2 * 25 - 0 = 50
        self.assertEqual(li.amount, Decimal('50.00'))

    def test_amount_with_discount(self):
        li = InvoiceLineItem(
            invoice=self.invoice, description='Repair',
            quantity=1, unit_price=Decimal('50.00'),
            discount=Decimal('10.00'), amount=None,
        )
        li.save()
        self.assertEqual(li.amount, Decimal('40.00'))


@override_settings(**TEST_OVERRIDES)
class PaymentModelTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('owner', 'o@test.com', 'pass')
        self.tenant = Tenant.objects.create(
            name='Shop', slug='shop', subdomain='shop',
            owner=self.user, subscription_plan=self.plan,
        )
        self.customer = Customer.objects.create(tenant=self.tenant, name='Cust')
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-PAY', subtotal=Decimal('100.00'),
            total=Decimal('100.00'), status='SENT',
        )

    def test_payment_updates_invoice(self):
        Payment.objects.create(
            invoice=self.invoice, amount=Decimal('60.00'),
            payment_method='CASH',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('60.00'))
        self.assertEqual(self.invoice.status, 'PARTIAL')

    def test_full_payment_marks_paid(self):
        Payment.objects.create(
            invoice=self.invoice, amount=Decimal('100.00'),
            payment_method='CHECK',
        )
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertIsNotNone(self.invoice.paid_at)

    def test_multiple_payments(self):
        Payment.objects.create(invoice=self.invoice, amount=Decimal('30.00'), payment_method='CASH')
        Payment.objects.create(invoice=self.invoice, amount=Decimal('70.00'), payment_method='CASH')
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('100.00'))
        self.assertEqual(self.invoice.status, 'PAID')


@override_settings(**TEST_OVERRIDES)
class TaxRateModelTests(TestCase):

    def setUp(self):
        self.plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                      'trial_days': 30, 'display_order': 0},
        )
        self.user = User.objects.create_user('owner', 'o@test.com', 'pass')
        self.tenant = Tenant.objects.create(
            name='Shop', slug='shop', subdomain='shop',
            owner=self.user, subscription_plan=self.plan,
        )

    def test_auto_calculate_total(self):
        tr = TaxRate.objects.create(
            tenant=self.tenant, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), county_rate=Decimal('1.000'),
            city_rate=Decimal('2.000'), special_rate=Decimal('0.500'),
        )
        self.assertEqual(tr.total_rate, Decimal('10.000'))

    def test_normalize_city_and_state(self):
        tr = TaxRate.objects.create(
            tenant=self.tenant, city='  fayetteville  ', state='ar',
        )
        self.assertEqual(tr.city, 'fayetteville')
        self.assertEqual(tr.state, 'AR')

    def test_str(self):
        tr = TaxRate.objects.create(
            tenant=self.tenant, city='Conway', state='AR',
            state_rate=Decimal('6.500'),
        )
        self.assertIn('Conway', str(tr))
        self.assertIn('AR', str(tr))
