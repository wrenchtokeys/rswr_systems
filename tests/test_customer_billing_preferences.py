"""
Tests for Customer Billing Preferences UX (CODE-209).

Verifies the inline billing preferences on the customer creation form:
- No billing prefs → no CustomerRepairPreference created
- Billing prefs provided → correct record created
- Invalid values rejected
- Shop default shown correctly in form context
- Tenant isolation on created records
"""

from decimal import Decimal

from django.test import TestCase, override_settings

from apps.billing.models import BillingConfig
from apps.customer_portal.models import CustomerRepairPreference
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class CustomerBillingPreferencesTests(TestCase):
    """Tests for inline billing preferences on customer creation."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Test Shop',
            email='owner@test.com',
            password='testpass123!',
            first_name='Test',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _post_create(self, extra=None):
        """POST to create_customer with base fields + optional extras."""
        data = {'name': 'Acme Trucking'}
        if extra:
            data.update(extra)
        return self.client.post('/tech/customers/create/', data)

    # ── No billing prefs → no record ────────────────────────────

    def test_no_billing_prefs_creates_no_preference_record(self):
        resp = self._post_create()
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        self.assertFalse(
            CustomerRepairPreference.objects.filter(customer=customer).exists()
        )

    def test_empty_billing_fields_creates_no_preference_record(self):
        """Even if details section was opened but nothing filled in."""
        resp = self._post_create({
            'invoice_preference': '',
            'payment_terms': '',
            'billing_email': '',
            'batch_invoice_day': '',
        })
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        self.assertFalse(
            CustomerRepairPreference.objects.filter(customer=customer).exists()
        )

    # ── Billing prefs provided → record created ─────────────────

    def test_invoice_preference_only_creates_record(self):
        resp = self._post_create({'invoice_preference': 'batch'})
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        pref = CustomerRepairPreference.objects.get(customer=customer)
        self.assertEqual(pref.invoice_preference, 'batch')
        # Other fields should be defaults
        self.assertEqual(pref.payment_terms, '')
        self.assertIsNone(pref.billing_email)
        self.assertIsNone(pref.batch_invoice_day)

    def test_all_billing_fields_creates_record(self):
        resp = self._post_create({
            'invoice_preference': 'per_ticket',
            'payment_terms': 'NET30',
            'billing_email': 'ap@acme.com',
            'batch_invoice_day': '15',
        })
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        pref = CustomerRepairPreference.objects.get(customer=customer)
        self.assertEqual(pref.invoice_preference, 'per_ticket')
        self.assertEqual(pref.payment_terms, 'NET30')
        self.assertEqual(pref.billing_email, 'ap@acme.com')
        self.assertEqual(pref.batch_invoice_day, 15)

    def test_payment_terms_only_creates_record(self):
        resp = self._post_create({'payment_terms': 'NET45'})
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        pref = CustomerRepairPreference.objects.get(customer=customer)
        self.assertEqual(pref.payment_terms, 'NET45')

    def test_billing_email_only_creates_record(self):
        resp = self._post_create({'billing_email': 'billing@acme.com'})
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        pref = CustomerRepairPreference.objects.get(customer=customer)
        self.assertEqual(pref.billing_email, 'billing@acme.com')

    def test_batch_invoice_day_only_creates_record(self):
        resp = self._post_create({'batch_invoice_day': '1'})
        self.assertEqual(resp.status_code, 302)
        customer = Customer.objects.get(name='Acme Trucking')
        pref = CustomerRepairPreference.objects.get(customer=customer)
        self.assertEqual(pref.batch_invoice_day, 1)

    # ── Validation ───────────────────────────────────────────────

    def test_invalid_invoice_preference_rejected(self):
        resp = self._post_create({'invoice_preference': 'invalid_value'})
        # Form should re-render with errors (200), not redirect (302)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Customer.objects.filter(name='Acme Trucking').exists())

    def test_invalid_payment_terms_rejected(self):
        resp = self._post_create({'payment_terms': 'NET999'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Customer.objects.filter(name='Acme Trucking').exists())

    def test_batch_invoice_day_too_high_rejected(self):
        resp = self._post_create({'batch_invoice_day': '29'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Customer.objects.filter(name='Acme Trucking').exists())

    def test_batch_invoice_day_too_low_rejected(self):
        resp = self._post_create({'batch_invoice_day': '0'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Customer.objects.filter(name='Acme Trucking').exists())

    def test_invalid_billing_email_rejected(self):
        resp = self._post_create({'billing_email': 'not-an-email'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Customer.objects.filter(name='Acme Trucking').exists())

    # ── Shop default shown in form context ───────────────────────

    def test_form_shows_shop_default_payment_terms(self):
        """GET form should show the shop's default payment terms."""
        # Set shop default to NET30
        config = BillingConfig.get_for_tenant(self.tenant)
        config.default_payment_terms = 'NET30'
        config.save(update_fields=['default_payment_terms'])

        resp = self.client.get('/tech/customers/create/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Net 30', content)
        self.assertIn('shop default', content)

    def test_form_shows_cod_default_when_no_config(self):
        """Default BillingConfig has COD — verify it shows."""
        resp = self.client.get('/tech/customers/create/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # COD is the default payment terms
        self.assertIn('shop default', content)

    # ── Tenant isolation ─────────────────────────────────────────

    def test_billing_pref_tenant_isolation(self):
        """Preferences created for one tenant's customer are not visible to another."""
        # Create customer with billing prefs for tenant 1
        self._post_create({
            'invoice_preference': 'batch',
            'payment_terms': 'NET60',
        })
        customer1 = Customer.objects.get(name='Acme Trucking', tenant=self.tenant)
        pref1 = CustomerRepairPreference.objects.get(customer=customer1)
        self.assertEqual(pref1.payment_terms, 'NET60')

        # Create second tenant
        result2 = create_tenant_with_owner(
            business_name='Other Shop',
            email='owner2@test.com',
            password='testpass123!',
            first_name='Other',
            last_name='Owner',
        )
        tenant2 = result2['tenant']
        user2 = result2['user']

        # Verify customer1's pref is scoped to tenant1's customer
        self.assertEqual(pref1.customer.tenant, self.tenant)
        self.assertNotEqual(pref1.customer.tenant, tenant2)

        # Create a customer under tenant2 with different prefs
        self.client.force_login(user2)
        session = self.client.session
        session['tenant_id'] = tenant2.id
        session.save()
        self.client.post('/tech/customers/create/', {
            'name': 'Acme Trucking',
            'invoice_preference': 'per_ticket',
            'payment_terms': 'NET15',
        })
        customer2 = Customer.objects.get(name='Acme Trucking', tenant=tenant2)
        pref2 = CustomerRepairPreference.objects.get(customer=customer2)
        self.assertEqual(pref2.payment_terms, 'NET15')

        # Confirm they are different records
        self.assertNotEqual(pref1.pk, pref2.pk)

    # ── Template rendering ───────────────────────────────────────

    def test_form_contains_billing_section(self):
        resp = self.client.get('/tech/customers/create/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Billing & Preferences', content)
        self.assertIn('billing-preferences-section', content)
        self.assertIn('invoice_preference', content)
        self.assertIn('payment_terms', content)
        self.assertIn('billing_email', content)
        self.assertIn('batch_invoice_day', content)
        self.assertIn('Most fleet customers prefer batch billing', content)
