"""
Admin Console Tests — Phase 1 & 2 Verification

Tests:
- Admin pages load (200) for superuser
- Custom dashboard renders
- CSV export actions (Repair, Invoice, Customer)
- Subscription management actions (extend trial, activate, deactivate)

Run with:
    python manage.py test tests.test_admin --settings=rs_systems.settings.development
"""

import csv
import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone


class AdminPageLoadTests(TestCase):
    """Verify all key admin changelist pages return 200 for superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='test_admin',
            email='admin@test.com',
            password='Test1234!'
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def _assert_page_ok(self, url_name, *args):
        url = reverse(url_name, args=args) if args else reverse(url_name)
        response = self.client.get(url)
        self.assertEqual(
            response.status_code, 200,
            f"Expected 200 for {url_name}, got {response.status_code}"
        )
        return response

    def test_admin_index_loads(self):
        """Admin dashboard (index) should return 200."""
        self._assert_page_ok('admin:index')

    def test_tenant_changelist(self):
        self._assert_page_ok('admin:tenants_tenant_changelist')

    def test_tenant_add(self):
        self._assert_page_ok('admin:tenants_tenant_add')

    def test_subscription_plan_changelist(self):
        self._assert_page_ok('admin:tenants_subscriptionplan_changelist')

    def test_tenant_membership_changelist(self):
        self._assert_page_ok('admin:tenants_tenantmembership_changelist')

    def test_invoice_changelist(self):
        self._assert_page_ok('admin:billing_invoice_changelist')

    def test_payment_changelist(self):
        self._assert_page_ok('admin:billing_payment_changelist')

    def test_taxrate_changelist(self):
        self._assert_page_ok('admin:billing_taxrate_changelist')

    def test_repair_changelist(self):
        self._assert_page_ok('admin:technician_portal_repair_changelist')

    def test_customer_changelist(self):
        self._assert_page_ok('admin:core_customer_changelist')

    def test_technician_changelist(self):
        self._assert_page_ok('admin:technician_portal_technician_changelist')

    def test_customeruser_changelist(self):
        self._assert_page_ok('admin:customer_portal_customeruser_changelist')

    def test_customer_invitation_changelist(self):
        self._assert_page_ok('admin:customer_portal_customerinvitation_changelist')

    def test_user_changelist(self):
        self._assert_page_ok('admin:auth_user_changelist')

    def test_notification_changelist(self):
        self._assert_page_ok('admin:core_notification_changelist')


class AdminDashboardTests(TestCase):
    """Custom dashboard metrics render correctly."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='dash_admin',
            email='dash@test.com',
            password='Test1234!'
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_dashboard_loads(self):
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        # Dashboard template should mention subscription-related content
        content = response.content.decode()
        self.assertIn('Subscription Overview', content)
        self.assertIn('This Month', content)
        self.assertIn('Recent Activity', content)
        self.assertIn('Quick Links', content)

    def test_dashboard_context_has_metrics(self):
        response = self.client.get(reverse('admin:index'))
        # Flatten the context (may be a ContextList with multiple levels)
        if hasattr(response.context, 'flatten'):
            ctx_flat = response.context.flatten()
        else:
            ctx_flat = {}
            for c in response.context:
                if hasattr(c, 'flatten'):
                    ctx_flat.update(c.flatten())
        # All metric keys should be present
        metric_keys = [
            'tenant_active_count', 'tenant_trial_count', 'tenant_grace_count',
            'tenant_expired_count', 'tenant_total',
            'repairs_this_month', 'invoices_this_month',
            'revenue_this_month', 'outstanding_balance',
        ]
        for key in metric_keys:
            self.assertIn(key, ctx_flat, f"Missing dashboard context key: {key}")

    def test_dashboard_handles_empty_db(self):
        """Dashboard should render cleanly with no data."""
        response = self.client.get(reverse('admin:index'))
        self.assertEqual(response.status_code, 200)
        # Access keys via ContextList's string key lookup
        self.assertEqual(response.context['tenant_total'], 0)
        self.assertEqual(response.context['repairs_this_month'], 0)


class RepairCSVExportTests(TestCase):
    """Test CSV export action on RepairAdmin."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='repair_admin',
            email='repair@test.com',
            password='Test1234!'
        )
        # Create minimal data
        from apps.tenants.models import Tenant
        cls.tenant = Tenant.objects.create(
            name='Export Test Shop',
            slug='export-test-shop',
            subdomain='export-test',
            owner=cls.admin_user,
        )
        from core.models import Customer
        cls.customer = Customer.objects.create(
            name='Export Customer',
            tenant=cls.tenant,
        )
        tech_user = User.objects.create_user(username='repair_tech', password='pass')
        from apps.technician_portal.models import Technician, Repair
        cls.technician = Technician.objects.create(user=tech_user)
        cls.repair = Repair.objects.create(
            tenant=cls.tenant,
            customer=cls.customer,
            technician=cls.technician,
            unit_number='UNIT-001',
            queue_status='COMPLETED',
            cost=Decimal('50.00'),
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_export_csv_returns_csv(self):
        url = reverse('admin:technician_portal_repair_changelist')
        data = {
            'action': 'export_csv',
            '_selected_action': [self.__class__.repair.pk],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('repairs.csv', response['Content-Disposition'])

    def test_export_csv_content(self):
        url = reverse('admin:technician_portal_repair_changelist')
        data = {
            'action': 'export_csv',
            '_selected_action': [self.__class__.repair.pk],
        }
        response = self.client.post(url, data)
        content = response.content.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        self.assertEqual(rows[0][0], 'ID')
        self.assertEqual(rows[0][2], 'Customer')
        self.assertEqual(rows[1][2], 'Export Customer')
        self.assertEqual(rows[1][3], 'UNIT-001')


class InvoiceCSVExportTests(TestCase):
    """Test CSV export action on InvoiceAdmin."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='invoice_admin',
            email='invoice@test.com',
            password='Test1234!'
        )
        from apps.tenants.models import Tenant
        cls.tenant = Tenant.objects.create(
            name='Invoice Test Shop',
            slug='invoice-test-shop',
            subdomain='invoice-test',
            owner=cls.admin_user,
        )
        from core.models import Customer
        cls.customer = Customer.objects.create(
            name='Invoice Customer',
            tenant=cls.tenant,
        )
        from apps.billing.models import Invoice
        cls.invoice = Invoice.objects.create(
            customer=cls.customer,
            invoice_number='INV-0001',
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=30),
            subtotal=Decimal('100.00'),
            total=Decimal('100.00'),
            status='SENT',
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_export_csv_returns_csv(self):
        url = reverse('admin:billing_invoice_changelist')
        data = {
            'action': 'export_csv',
            '_selected_action': [self.invoice.pk],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('invoices.csv', response['Content-Disposition'])

    def test_export_csv_content(self):
        url = reverse('admin:billing_invoice_changelist')
        data = {
            'action': 'export_csv',
            '_selected_action': [self.invoice.pk],
        }
        response = self.client.post(url, data)
        content = response.content.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        self.assertEqual(rows[0][0], 'Invoice #')
        self.assertEqual(rows[1][0], 'INV-0001')
        self.assertEqual(rows[1][1], 'Invoice Customer')


class CustomerCSVExportTests(TestCase):
    """Test CSV export action on CustomerAdmin."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='customer_admin',
            email='cust_admin@test.com',
            password='Test1234!'
        )
        from apps.tenants.models import Tenant
        cls.tenant = Tenant.objects.create(
            name='Customer Export Shop',
            slug='customer-export-shop',
            subdomain='customer-export',
            owner=cls.admin_user,
        )
        from core.models import Customer
        cls.customer = Customer.objects.create(
            name='Exported Co',
            tenant=cls.tenant,
            email='exported@test.com',
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_export_csv_returns_csv(self):
        url = reverse('admin:core_customer_changelist')
        data = {
            'action': 'export_csv',
            '_selected_action': [self.customer.pk],
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('customers.csv', response['Content-Disposition'])

    def test_export_csv_content(self):
        url = reverse('admin:core_customer_changelist')
        data = {
            'action': 'export_csv',
            '_selected_action': [self.customer.pk],
        }
        response = self.client.post(url, data)
        content = response.content.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        self.assertEqual(rows[0][0], 'ID')
        self.assertEqual(rows[1][1], 'Exported Co')


class SubscriptionActionTests(TestCase):
    """Test subscription management admin actions on TenantAdmin."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='sub_admin',
            email='sub@test.com',
            password='Test1234!'
        )
        from apps.tenants.models import Tenant
        cls.tenant = Tenant.objects.create(
            name='Action Test Shop',
            slug='action-test-shop',
            subdomain='action-test',
            owner=cls.admin_user,
            plan='trial',
            subscription_status='trialing',
            trial_started_at=timezone.now(),
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)
        # Refresh from DB each test
        self.tenant = type(self).tenant.__class__.objects.get(pk=type(self).tenant.pk)

    def _post_action(self, action):
        url = reverse('admin:tenants_tenant_changelist')
        return self.client.post(url, {
            'action': action,
            '_selected_action': [self.tenant.pk],
        })

    def test_activate_subscription(self):
        response = self._post_action('activate_subscription')
        self.assertIn(response.status_code, [200, 302])
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertTrue(self.tenant.is_active)

    def test_deactivate_subscription(self):
        self._post_action('deactivate_subscription')
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'expired')
        self.assertIsNotNone(self.tenant.grace_period_end)
        self.assertGreater(self.tenant.grace_period_end, timezone.now())

    def test_extend_trial_7_days(self):
        original_start = self.tenant.trial_started_at
        self._post_action('extend_trial_7_days')
        self.tenant.refresh_from_db()
        expected = original_start + timedelta(days=7)
        # Allow 1 second tolerance
        diff = abs((self.tenant.trial_started_at - expected).total_seconds())
        self.assertLess(diff, 2)

    def test_extend_trial_30_days(self):
        original_start = self.tenant.trial_started_at
        self._post_action('extend_trial_30_days')
        self.tenant.refresh_from_db()
        expected = original_start + timedelta(days=30)
        diff = abs((self.tenant.trial_started_at - expected).total_seconds())
        self.assertLess(diff, 2)

    def test_deactivate_sets_grace_period(self):
        self._post_action('deactivate_subscription')
        self.tenant.refresh_from_db()
        # Grace period should be ~30 days from now
        days_remaining = (self.tenant.grace_period_end - timezone.now()).days
        self.assertGreaterEqual(days_remaining, 29)
        self.assertTrue(self.tenant.is_in_grace_period)
