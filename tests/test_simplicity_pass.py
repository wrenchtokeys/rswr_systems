"""
Tests for the simplicity pass:

1. Flat repair price editable when progressive pricing is off, and a partial
   pricing POST no longer resets untouched tiers to factory defaults.
2. Multi-break batch pricing respects the progressive-pricing toggle
   (tenant-level and customer-level) instead of always walking tiers.
3. Owner settings context: batch next-run preview, "no batch customers"
   warning, and the reminders-on-but-no-days misconfiguration flag.
4. Price override authorization unified on is_manager (the old
   can_override_pricing flag was never set by any signup/team path), and
   RepairForm removes — not hides — the override fields for non-managers so
   an edit-save can't silently wipe an existing custom price.
5. Invoice line-item edits write back to the linked repair so the job's
   price in RS Systems matches the invoice.
"""

import json
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.dummy.EmailBackend',
}


def make_owner_tenant(business_name, email):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name='Test', last_name='Owner',
    )


class OwnerClientMixin:
    def login_owner(self, result):
        self.user = result['user']
        self.tenant = result['tenant']
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()


@override_settings(**TEST_OVERRIDES)
class FlatPricingSettingsTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Flat Shop', 'flat@test.com'))

    def test_partial_post_preserves_other_tiers(self):
        """Posting only repair_price_1 must not reset tiers 2-5 to defaults."""
        self.tenant.repair_price_2 = Decimal('42.00')
        self.tenant.repair_price_5_plus = Decimal('21.00')
        self.tenant.save(update_fields=['repair_price_2', 'repair_price_5_plus'])

        resp = self.client.post('/owner/settings/', {
            'form_type': 'update_pricing_tiers',
            'repair_price_1': '60.00',
        })
        self.assertEqual(resp.status_code, 302)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.repair_price_1, Decimal('60.00'))
        self.assertEqual(self.tenant.repair_price_2, Decimal('42.00'))
        self.assertEqual(self.tenant.repair_price_5_plus, Decimal('21.00'))

    def test_flat_mode_page_has_editable_price(self):
        """With progressive off, the settings page must render a price input."""
        self.tenant.use_progressive_pricing = False
        self.tenant.save(update_fields=['use_progressive_pricing'])
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="repair_price_1"', html)
        self.assertIn('Price per repair', html)


@override_settings(**TEST_OVERRIDES)
class BatchPricingToggleTests(TestCase):

    def setUp(self):
        result = make_owner_tenant('Batch Shop', 'batch@test.com')
        self.tenant = result['tenant']
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', customer_type='FLEET',
        )

    def _prices(self, breaks=3):
        from apps.technician_portal.services.batch_pricing_service import calculate_batch_pricing
        return [b['price'] for b in calculate_batch_pricing(self.customer, 'U-1', breaks)]

    def test_progressive_on_walks_tiers(self):
        self.assertEqual(self._prices(), [Decimal('50.00'), Decimal('40.00'), Decimal('35.00')])

    def test_tenant_toggle_off_prices_flat(self):
        self.tenant.use_progressive_pricing = False
        self.tenant.repair_price_1 = Decimal('60.00')
        self.tenant.save(update_fields=['use_progressive_pricing', 'repair_price_1'])
        self.customer.refresh_from_db()
        self.assertEqual(self._prices(), [Decimal('60.00')] * 3)

    def test_customer_toggle_off_prices_flat(self):
        self.customer.use_progressive_pricing = False
        self.customer.save(update_fields=['use_progressive_pricing'])
        self.assertEqual(self._prices(), [Decimal('50.00')] * 3)

    def test_flat_respects_customer_custom_tier1(self):
        from apps.customer_portal.pricing_models import CustomerPricing
        self.tenant.use_progressive_pricing = False
        self.tenant.save(update_fields=['use_progressive_pricing'])
        self.customer.refresh_from_db()
        CustomerPricing.objects.create(
            customer=self.customer, use_custom_pricing=True,
            repair_1_price=Decimal('99.00'),
        )
        self.assertEqual(self._prices(), [Decimal('99.00')] * 3)

    def test_retail_customer_prices_flat(self):
        retail = Customer.objects.create(
            tenant=self.tenant, name='Walk In', customer_type='RETAIL',
        )
        from apps.technician_portal.services.batch_pricing_service import calculate_batch_pricing
        prices = [b['price'] for b in calculate_batch_pricing(retail, 'U-2', 3)]
        self.assertEqual(prices, [Decimal('50.00')] * 3)


@override_settings(**TEST_OVERRIDES)
class SettingsExplainerContextTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Explain Shop', 'explain@test.com'))
        from apps.billing.models import BillingConfig
        self.config = BillingConfig.get_for_tenant(self.tenant)

    def test_batch_next_run_matches_task_logic(self):
        from apps.billing.tasks import _should_run_batch_today
        self.config.batch_invoice_frequency = 'weekly'
        self.config.batch_invoice_day = 0  # Monday
        self.config.save()
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertEqual(resp.status_code, 200)
        next_run = resp.context['batch_next_run']
        self.assertIsNotNone(next_run)
        self.assertTrue(_should_run_batch_today(self.config, next_run))
        self.assertGreaterEqual(next_run, timezone.now().date())

    def test_warning_when_no_batch_customers(self):
        self.config.batch_invoice_frequency = 'weekly'
        self.config.batch_invoice_day = 0
        self.config.save()
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertFalse(resp.context['has_batch_customers'])
        self.assertIn('none of your customers are set to Batch', resp.content.decode())

    def test_no_warning_with_batch_customer(self):
        from apps.customer_portal.models import CustomerRepairPreference
        self.config.batch_invoice_frequency = 'weekly'
        self.config.batch_invoice_day = 0
        self.config.save()
        customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', customer_type='FLEET',
        )
        CustomerRepairPreference.objects.get_or_create(customer=customer)
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertTrue(resp.context['has_batch_customers'])
        self.assertNotIn('none of your customers are set to Batch', resp.content.decode())

    def test_reminders_misconfigured_flag(self):
        self.config.overdue_reminder_enabled = True
        self.config.overdue_reminder_days = ''
        self.config.save()
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertTrue(resp.context['reminders_misconfigured'])
        self.assertIn('no days are selected', resp.content.decode())

    def test_reminders_configured_no_flag(self):
        self.config.overdue_reminder_enabled = True
        self.config.overdue_reminder_days = '7,14,30'
        self.config.save()
        resp = self.client.get('/owner/settings/?tab=billing')
        self.assertFalse(resp.context['reminders_misconfigured'])


@override_settings(**TEST_OVERRIDES)
class PriceOverrideAccessTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Override Shop', 'override@test.com'))

    def test_multi_break_form_shows_price_field_to_owner(self):
        """A plain owner (can_override_pricing never set) sees the price field."""
        from apps.technician_portal.models import Technician
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.assertFalse(tech.can_override_pricing)  # the dead flag
        resp = self.client.get('/tech/repairs/create-multi-break/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('modal_cost_override', html)
        self.assertIn('Custom Price', html)

    def test_repair_form_keeps_override_fields_for_manager(self):
        from apps.technician_portal.forms import RepairForm
        form = RepairForm(user=self.user, tenant=self.tenant)
        self.assertIn('cost_override', form.fields)
        self.assertIn('override_reason', form.fields)

    def test_repair_form_removes_override_fields_for_plain_tech(self):
        """Fields must be REMOVED (not hidden) so an absent POST value can't
        clean to None and wipe an existing override on save."""
        from django.contrib.auth.models import User
        from apps.technician_portal.models import Technician
        from apps.technician_portal.forms import RepairForm
        plain_user = User.objects.create_user('plaintech', 'plain@test.com', 'pass')
        Technician.objects.create(
            tenant=self.tenant, user=plain_user,
            is_manager=False, is_active=True, can_repair=True,
        )
        form = RepairForm(user=plain_user, tenant=self.tenant)
        self.assertNotIn('cost_override', form.fields)
        self.assertNotIn('override_reason', form.fields)

    def test_repair_edit_page_renders_price_input(self):
        from apps.technician_portal.models import Repair, Technician
        tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', customer_type='FLEET',
        )
        repair = Repair.objects.create(
            tenant=self.tenant, customer=customer, technician=tech,
            unit_number='U-9', queue_status='APPROVED',
            service_date=timezone.now(),
        )
        resp = self.client.get(f'/tech/repairs/{repair.id}/update/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="cost_override"', html)


@override_settings(**TEST_OVERRIDES)
class LineItemRepairSyncTests(OwnerClientMixin, TestCase):

    def setUp(self):
        self.login_owner(make_owner_tenant('Sync Shop', 'sync@test.com'))
        from apps.technician_portal.models import Repair, Technician
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Penske', customer_type='FLEET',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='U-77', queue_status='COMPLETED',
            service_date=timezone.now(),
        )

    def _make_invoice_line(self, unit_price, discount, amount, tax_rate=Decimal('0.000')):
        from datetime import date, timedelta
        from apps.billing.models import Invoice, InvoiceLineItem
        inv = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            invoice_number='INV-SYNC-1', invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status='SENT', subtotal=unit_price,
            discount=discount, total=amount, tax_rate=tax_rate,
        )
        li = InvoiceLineItem.objects.create(
            invoice=inv, repair=self.repair, description='Windshield repair',
            quantity=1, unit_price=unit_price, discount=discount, amount=amount,
        )
        return inv, li

    def test_price_edit_syncs_back_to_repair(self):
        """Typing $60 charges exactly $60 and the repair record matches."""
        inv, li = self._make_invoice_line(
            unit_price=Decimal('65.00'), discount=Decimal('15.00'),
            amount=Decimal('50.00'),
        )
        resp = self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/',
            data=json.dumps({'unit_price': 60.00, 'discount': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['line_item']['amount'], 60.0)

        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))
        self.assertEqual(self.repair.cost_override, Decimal('60.00'))
        self.assertIn(inv.invoice_number, self.repair.override_reason)

    def test_repair_cost_survives_resave(self):
        """After the sync, a later Repair.save() keeps the invoiced price."""
        inv, li = self._make_invoice_line(
            unit_price=Decimal('50.00'), discount=Decimal('0.00'),
            amount=Decimal('50.00'),
        )
        self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/',
            data=json.dumps({'unit_price': 72.50, 'discount': 0}),
            content_type='application/json',
        )
        self.repair.refresh_from_db()
        self.repair.save()
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('72.50'))

    def test_price_edit_recomputes_repair_tax(self):
        """The write-back updates tax too — not just cost (repair 182 bug:
        a $50 repair edited to $1 on the invoice kept its $4.88 tax). The
        rate comes from the invoice itself."""
        from apps.billing.models import BillingConfig
        cfg = BillingConfig.get_for_tenant(self.tenant)
        cfg.tax_enabled = True
        cfg.default_tax_rate = Decimal('9.750')
        cfg.save()

        inv, li = self._make_invoice_line(
            unit_price=Decimal('50.00'), discount=Decimal('0.00'),
            amount=Decimal('50.00'), tax_rate=Decimal('9.750'),
        )
        self.repair.save()  # compute tax at the original $50 price
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.tax_amount, Decimal('4.88'))

        resp = self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/',
            data=json.dumps({'unit_price': 1.00, 'discount': 0}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('1.00'))
        self.assertEqual(self.repair.tax_rate, Decimal('9.750'))
        self.assertEqual(self.repair.tax_amount, Decimal('0.10'))

    def test_price_edit_on_untaxed_invoice_zeroes_stale_tax(self):
        """A job edited on a no-tax invoice ends up with zero tax, whatever
        the shop's current tax settings say — the invoice is the truth."""
        from apps.billing.models import BillingConfig
        cfg = BillingConfig.get_for_tenant(self.tenant)
        cfg.tax_enabled = True
        cfg.default_tax_rate = Decimal('9.750')
        cfg.save()

        inv, li = self._make_invoice_line(
            unit_price=Decimal('50.00'), discount=Decimal('0.00'),
            amount=Decimal('50.00'),  # invoice tax_rate stays 0
        )
        self.repair.save()  # tax computed from current config: $4.88
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.tax_amount, Decimal('4.88'))

        self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/',
            data=json.dumps({'unit_price': 60.00, 'discount': 0}),
            content_type='application/json',
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))
        self.assertEqual(self.repair.tax_amount, Decimal('0.00'))

    def test_price_edit_zeroes_tax_for_no_tax_job(self):
        """A no_tax job never picks up tax from the write-back, even on a
        taxed invoice."""
        from apps.technician_portal.models import Repair
        Repair.objects.filter(pk=self.repair.pk).update(no_tax=True)

        inv, li = self._make_invoice_line(
            unit_price=Decimal('50.00'), discount=Decimal('0.00'),
            amount=Decimal('50.00'), tax_rate=Decimal('9.750'),
        )
        self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/',
            data=json.dumps({'unit_price': 60.00, 'discount': 0}),
            content_type='application/json',
        )
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, Decimal('60.00'))
        self.assertEqual(self.repair.tax_amount, Decimal('0.00'))

    def test_description_only_edit_does_not_touch_repair(self):
        inv, li = self._make_invoice_line(
            unit_price=Decimal('50.00'), discount=Decimal('0.00'),
            amount=Decimal('50.00'),
        )
        original_cost = self.repair.cost
        resp = self.client.post(
            f'/api/billing/invoices/{inv.id}/line-items/{li.id}/update/',
            data=json.dumps({'description': 'Rock chip repair'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.cost, original_cost)
        self.assertIsNone(self.repair.cost_override)
