"""
Individual / general-public work: on-the-fly customer creation, the Fleet vs
Individual jobs filter, and the fleet-linked flat account discount.

Covers:
- QuickJobForm inline "add an individual" path (RETAIL/WALK_IN, limits, dup names)
- job_list ?customer_type=fleet|individual filtering
- Customer.get_effective_discount_percentage resolution (own > parent > 0)
- Discount applied to repairs AND replacements (price-book, parts+labor, override)
- Tax computed on the discounted cost
"""

from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.billing.models import TaxRate
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.tenants.services.usage_service import UsageService
from apps.technician_portal.models import Technician, Repair, Replacement
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_shop(business_name, email, services='both'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial', 'monthly_price': Decimal('0.00'),
            'trial_days': 30, 'display_order': 0, 'is_active': True,
        },
    )
    result = create_tenant_with_owner(
        business_name=business_name, email=email, password='testpass123!',
        first_name='Test', last_name='Owner', services_offered=services,
    )
    return result['user'], result['tenant']


def login(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


@override_settings(**TEST_SETTINGS)
class InlineIndividualCreateTests(TestCase):
    """Add an individual customer straight from the quick job form."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Dad Glass', 'dad@test.com', 'replacement')
        login(self.client, self.user, self.tenant)

    def _post(self, **overrides):
        data = {
            'service_type': 'replacement',
            'new_customer_name': 'Jane Doe',
            'new_customer_phone': '555-123-4567',
            'unit_number': '2022 Honda Civic',
            'work_done': 'Windshield replacement',
            'price': '300.00',
            'already_completed': 'on',
        }
        data.update(overrides)
        return self.client.post(reverse('job_create'), data)

    def test_new_individual_creates_retail_customer_and_job(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(tenant=self.tenant, name='Jane Doe')
        self.assertEqual(customer.customer_type, 'RETAIL')
        self.assertEqual(customer.phone, '555-123-4567')  # stored as entered
        repl = Replacement.objects.get(tenant=self.tenant)
        self.assertEqual(repl.customer, customer)
        self.assertEqual(repl.cost, Decimal('300.00'))

    def test_walkin_flag_sets_walk_in_type(self):
        resp = self._post(new_customer_is_walkin='on')
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(tenant=self.tenant, name='Jane Doe')
        self.assertEqual(customer.customer_type, 'WALK_IN')

    def test_neither_customer_nor_name_is_rejected(self):
        resp = self._post(new_customer_name='')
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertEqual(Replacement.objects.filter(tenant=self.tenant).count(), 0)

    def test_duplicate_name_shows_friendly_error(self):
        Customer.objects.create(tenant=self.tenant, name='Jane Doe', customer_type='RETAIL')
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')
        # Only the pre-existing customer remains; no job created.
        self.assertEqual(Customer.objects.filter(tenant=self.tenant, name='Jane Doe').count(), 1)
        self.assertEqual(Replacement.objects.filter(tenant=self.tenant).count(), 0)

    def test_over_limit_blocks_inline_create(self):
        # Cap the plan at the current customer count so the next add is blocked.
        svc = UsageService(self.tenant)
        plan = svc.plan
        plan.max_customers = svc.count_customers()
        plan.save()
        resp = self._post()
        self.assertEqual(resp.status_code, 302)  # redirected to job_list with a warning
        self.assertFalse(Customer.objects.filter(tenant=self.tenant, name='Jane Doe').exists())
        self.assertEqual(Replacement.objects.filter(tenant=self.tenant).count(), 0)


@override_settings(**TEST_SETTINGS)
class AccountDiscountTests(TestCase):
    """Fleet-linked flat discount, inherited by linked individuals."""

    def setUp(self):
        self.user, self.tenant = make_shop('Dad Glass', 'dad@test.com', 'both')
        self.tech = Technician.objects.filter(tenant=self.tenant).first()
        TaxRate.objects.create(
            tenant=self.tenant, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), is_active=True,
        )
        self.acme = Customer.objects.create(
            tenant=self.tenant, name='Acme Trucking', customer_type='FLEET',
            account_discount_percentage=Decimal('20.00'),
        )
        self.maria = Customer.objects.create(
            tenant=self.tenant, name='Maria Lopez', customer_type='RETAIL',
            parent_account=self.acme,
        )

    def test_effective_discount_resolution(self):
        # Individual inherits the fleet parent's discount.
        self.assertEqual(self.maria.get_effective_discount_percentage(), Decimal('20.00'))
        # Fleet account uses its own.
        self.assertEqual(self.acme.get_effective_discount_percentage(), Decimal('20.00'))
        # Own discount overrides the parent's.
        self.maria.account_discount_percentage = Decimal('10.00')
        self.assertEqual(self.maria.get_effective_discount_percentage(), Decimal('10.00'))
        # Standalone individual with no discount and no parent → 0.
        solo = Customer.objects.create(
            tenant=self.tenant, name='Solo Sam', customer_type='RETAIL')
        self.assertEqual(solo.get_effective_discount_percentage(), Decimal('0'))

    def test_repair_price_book_discounted(self):
        # Retail first-repair price is the tenant default $50 → 20% off = $40.
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.maria, technician=self.tech,
            unit_number='CIV-1',
        )
        self.assertEqual(repair.cost, Decimal('40.00'))

    def test_repair_cost_override_discounted(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.maria, technician=self.tech,
            unit_number='CIV-1', cost_override=Decimal('100.00'),
        )
        self.assertEqual(repair.cost, Decimal('80.00'))

    def test_replacement_parts_labor_discounted(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.maria, technician=self.tech,
            parts_cost=Decimal('200.00'), labor_cost=Decimal('100.00'),
        )
        self.assertEqual(repl.cost, Decimal('240.00'))  # 300 * 0.8

    def test_replacement_cost_override_discounted(self):
        repl = Replacement.objects.create(
            tenant=self.tenant, customer=self.maria, technician=self.tech,
            cost_override=Decimal('300.00'),
        )
        self.assertEqual(repl.cost, Decimal('240.00'))

    def test_tax_computed_on_discounted_cost(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.maria, technician=self.tech,
            unit_number='CIV-1',
        )
        # Tax is on the discounted $40, not the $50 list: 40 * 6.5% = 2.60.
        self.assertEqual(repair.cost, Decimal('40.00'))
        self.assertEqual(repair.tax_amount, Decimal('2.60'))

    def test_no_discount_is_noop(self):
        solo = Customer.objects.create(
            tenant=self.tenant, name='Solo Sam', customer_type='RETAIL')
        repair = Repair.objects.create(
            tenant=self.tenant, customer=solo, technician=self.tech, unit_number='X',
        )
        self.assertEqual(repair.cost, Decimal('50.00'))


@override_settings(**TEST_SETTINGS)
class JobsListCustomerTypeFilterTests(TestCase):
    """Fleet vs Individual toggle on the unified jobs list."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Dad Glass', 'dad@test.com', 'both')
        self.tech = Technician.objects.filter(tenant=self.tenant).first()
        self.fleet = Customer.objects.create(
            tenant=self.tenant, name='Acme Trucking', customer_type='FLEET')
        self.individual = Customer.objects.create(
            tenant=self.tenant, name='Maria Lopez', customer_type='RETAIL')
        Repair.objects.create(
            tenant=self.tenant, customer=self.fleet, technician=self.tech, unit_number='F1')
        Repair.objects.create(
            tenant=self.tenant, customer=self.individual, technician=self.tech, unit_number='I1')
        login(self.client, self.user, self.tenant)

    def _names(self, resp):
        return {j.customer.name for j in resp.context['jobs']}

    def test_fleet_filter(self):
        resp = self.client.get(reverse('job_list'), {'customer_type': 'fleet'})
        self.assertEqual(self._names(resp), {'Acme Trucking'})

    def test_individual_filter(self):
        resp = self.client.get(reverse('job_list'), {'customer_type': 'individual'})
        self.assertEqual(self._names(resp), {'Maria Lopez'})

    def test_all_shows_both(self):
        resp = self.client.get(reverse('job_list'))
        self.assertEqual(self._names(resp), {'Acme Trucking', 'Maria Lopez'})
