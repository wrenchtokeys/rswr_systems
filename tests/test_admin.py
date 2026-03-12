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


# =============================================================================
# Phase 5: Tenant-Aware Filtering Tests
# =============================================================================

class TenantFilterMixinTests(TestCase):
    """Tests for TenantFilterMixin — superuser vs. non-superuser queryset filtering."""

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
        from apps.technician_portal.models import Repair
        from decimal import Decimal

        # Two tenants
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial-test', defaults={
                'name': 'Trial Test', 'monthly_price': Decimal('0'), 'trial_days': 14
            }
        )

        # Superuser can see everything
        cls.superuser = User.objects.create_superuser(
            username='super_filter', email='super@filter.com', password='Test1234!'
        )
        # Staff user belonging only to tenant A
        cls.staff_a = User.objects.create_user(
            username='staff_a_filter', email='staffa@filter.com',
            password='Test1234!', is_staff=True, is_superuser=False
        )
        owner_b = User.objects.create_user(username='owner_b_filter', password='Test1234!')

        # Grant view/change permissions for Repair and Customer
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        from apps.technician_portal.models import Repair as RepairModel
        from core.models import Customer as CustomerModel
        for model_cls in [RepairModel, CustomerModel]:
            ct = ContentType.objects.get_for_model(model_cls)
            for codename in [f'view_{ct.model}', f'change_{ct.model}']:
                perm = Permission.objects.filter(content_type=ct, codename=codename).first()
                if perm:
                    cls.staff_a.user_permissions.add(perm)

        cls.tenant_a = Tenant.objects.create(name='Tenant A', slug='tenant-a-filter', owner=cls.staff_a)
        cls.tenant_b = Tenant.objects.create(name='Tenant B', slug='tenant-b-filter', owner=owner_b)
        TenantMembership.objects.create(
            tenant=cls.tenant_a, user=cls.staff_a, role='manager', is_active=True
        )

        # A customer per tenant
        from core.models import Customer
        cls.cust_a = Customer.objects.create(name='Customer A', tenant=cls.tenant_a)
        cls.cust_b = Customer.objects.create(name='Customer B', tenant=cls.tenant_b)

        # A technician per tenant
        from apps.technician_portal.models import Technician
        cls.tech_a = Technician.objects.create(user=cls.staff_a, tenant=cls.tenant_a, expertise='General')
        cls.tech_b = Technician.objects.create(user=owner_b, tenant=cls.tenant_b, expertise='General')

        # A repair per tenant
        cls.repair_a = Repair.objects.create(
            customer=cls.cust_a, tenant=cls.tenant_a, technician=cls.tech_a,
            unit_number='UNIT-A', cost=Decimal('50'), queue_status='COMPLETED'
        )
        cls.repair_b = Repair.objects.create(
            customer=cls.cust_b, tenant=cls.tenant_b, technician=cls.tech_b,
            unit_number='UNIT-B', cost=Decimal('75'), queue_status='COMPLETED'
        )

    def setUp(self):
        self.client = Client()

    def _get_changelist_ids(self, url, user):
        self.client.force_login(user)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        return set(obj.pk for obj in resp.context['cl'].queryset)

    def test_superuser_sees_all_repairs(self):
        ids = self._get_changelist_ids(
            reverse('admin:technician_portal_repair_changelist'), self.superuser
        )
        self.assertIn(self.repair_a.pk, ids)
        self.assertIn(self.repair_b.pk, ids)

    def test_non_superuser_sees_only_own_tenant_repairs(self):
        ids = self._get_changelist_ids(
            reverse('admin:technician_portal_repair_changelist'), self.staff_a
        )
        self.assertIn(self.repair_a.pk, ids)
        self.assertNotIn(self.repair_b.pk, ids)

    def test_superuser_sees_all_customers(self):
        ids = self._get_changelist_ids(
            reverse('admin:core_customer_changelist'), self.superuser
        )
        self.assertIn(self.cust_a.pk, ids)
        self.assertIn(self.cust_b.pk, ids)

    def test_non_superuser_sees_only_own_tenant_customers(self):
        ids = self._get_changelist_ids(
            reverse('admin:core_customer_changelist'), self.staff_a
        )
        self.assertIn(self.cust_a.pk, ids)
        self.assertNotIn(self.cust_b.pk, ids)


# =============================================================================
# Phase 6a: Bulk Invoice Generation Tests
# =============================================================================

class BulkInvoiceGenerationTests(TestCase):
    """Tests for the 'Generate draft invoices' admin action on CustomerAdmin."""

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant, SubscriptionPlan
        from apps.technician_portal.models import Repair
        from decimal import Decimal

        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial-inv-test', defaults={
                'name': 'Trial Inv Test', 'monthly_price': Decimal('0'), 'trial_days': 14
            }
        )
        cls.admin_user = User.objects.create_superuser(
            username='admin_inv', email='admin_inv@test.com', password='Test1234!'
        )
        cls.tenant = Tenant.objects.create(name='Invoice Tenant', slug='invoice-tenant', owner=cls.admin_user)

        from core.models import Customer
        from apps.technician_portal.models import Technician
        cls.customer = Customer.objects.create(name='Inv Customer', tenant=cls.tenant)
        cls.tech = Technician.objects.create(user=cls.admin_user, tenant=cls.tenant, expertise='General')

        # Two completed repairs, no invoices
        cls.repair1 = Repair.objects.create(
            customer=cls.customer, tenant=cls.tenant, technician=cls.tech,
            unit_number='T001', cost=Decimal('100'), queue_status='COMPLETED'
        )
        cls.repair2 = Repair.objects.create(
            customer=cls.customer, tenant=cls.tenant, technician=cls.tech,
            unit_number='T002', cost=Decimal('150'), queue_status='COMPLETED'
        )
        # One pending repair (should NOT be billed)
        cls.repair_pending = Repair.objects.create(
            customer=cls.customer, tenant=cls.tenant, technician=cls.tech,
            unit_number='T003', cost=Decimal('50'), queue_status='PENDING'
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_generate_invoices_creates_draft(self):
        from apps.billing.models import Invoice, InvoiceLineItem
        url = reverse('admin:core_customer_changelist')
        data = {
            'action': 'generate_invoices',
            '_selected_action': [self.customer.pk],
        }
        resp = self.client.post(url, data, follow=True)
        self.assertEqual(resp.status_code, 200)

        invoice = Invoice.objects.filter(customer=self.customer, status='DRAFT').first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.line_items.count(), 2)

        line_repairs = set(invoice.line_items.values_list('repair_id', flat=True))
        self.assertIn(self.repair1.pk, line_repairs)
        self.assertIn(self.repair2.pk, line_repairs)
        self.assertNotIn(self.repair_pending.pk, line_repairs)

    def test_generate_invoices_skips_already_billed(self):
        """Running the action twice should not create duplicate line items."""
        from apps.billing.models import Invoice, InvoiceLineItem
        url = reverse('admin:core_customer_changelist')
        data = {
            'action': 'generate_invoices',
            '_selected_action': [self.customer.pk],
        }
        self.client.post(url, data, follow=True)
        self.client.post(url, data, follow=True)

        # Should still be just one invoice (second run: no unbilled repairs left)
        self.assertEqual(
            Invoice.objects.filter(customer=self.customer, status='DRAFT').count(), 1
        )


# =============================================================================
# Phase 6b: Audit Log Admin Tests
# =============================================================================

class AuditLogAdminTests(TestCase):
    """Tests that the Django LogEntry admin view loads correctly."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='admin_audit', email='admin_audit@test.com', password='Test1234!'
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_audit_log_changelist_loads(self):
        url = reverse('admin:admin_logentry_changelist')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_audit_log_no_add_permission(self):
        url = reverse('admin:admin_logentry_add')
        resp = self.client.get(url)
        # Should redirect or 403 (Django returns 403 for no add permission)
        self.assertIn(resp.status_code, [302, 403])


# =============================================================================
# Phase 6c: Global Search Tests
# =============================================================================

class GlobalSearchTests(TestCase):
    """Tests for the custom global admin search view."""

    @classmethod
    def setUpTestData(cls):
        from apps.tenants.models import Tenant
        from decimal import Decimal

        cls.admin_user = User.objects.create_superuser(
            username='admin_search', email='admin_search@test.com', password='Test1234!'
        )
        cls.tenant = Tenant.objects.create(name='Search Tenant', slug='search-tenant', owner=cls.admin_user)

        from core.models import Customer
        cls.customer = Customer.objects.create(
            name='Searchable Corp', email='search@corp.com', tenant=cls.tenant
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)

    def test_search_page_loads(self):
        url = reverse('admin:global_search')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_search_returns_customer_results(self):
        url = reverse('admin:global_search')
        resp = self.client.get(url, {'q': 'Searchable'})
        self.assertEqual(resp.status_code, 200)
        customers = resp.context['results']['customers']
        self.assertTrue(any(c.pk == self.customer.pk for c in customers))

    def test_search_empty_query_no_results(self):
        url = reverse('admin:global_search')
        resp = self.client.get(url, {'q': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context.get('results', {}), {})

    def test_search_no_match_returns_empty(self):
        url = reverse('admin:global_search')
        resp = self.client.get(url, {'q': 'xyzzy_no_match_12345'})
        self.assertEqual(resp.status_code, 200)
        results = resp.context['results']
        self.assertFalse(
            any(list(v) for v in results.values()),
            "Expected no results for a non-matching query"
        )
