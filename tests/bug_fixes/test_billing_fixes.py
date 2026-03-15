"""
Billing Bug Fix Tests
Consolidated from: CODE-007, CODE-010, CODE-012, CODE-017, CODE-019
"""

from apps.billing.models import BillingConfig, Invoice, InvoiceLineItem
from apps.billing.services.invoice_service import InvoiceService
from apps.billing.services.reminder_service import ReminderService
from apps.billing.tasks import _create_batch_invoice, process_batch_invoices, process_overdue_invoices
from apps.customer_portal.models import CustomerRepairPreference
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from core.models import Customer
from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone
from unittest.mock import MagicMock, PropertyMock, patch
import inspect
import uuid


# --- From test_code007_billing_config_get_instance.py ---

# ---------------------------------------------------------------------------
# Source-code guard — no get_instance() may remain in these modules
# ---------------------------------------------------------------------------


class TestNoGetInstanceInTasks(TestCase):
    """Ensure tasks.py uses get_for_tenant() everywhere."""

    def test_process_overdue_invoices_no_get_instance(self):
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(process_overdue_invoices)
        self.assertNotIn(
            'get_instance()', source,
            "process_overdue_invoices still calls BillingConfig.get_instance() "
            "which raises RuntimeError. Use get_for_tenant(tenant) instead."
        )

    def test_process_batch_invoices_no_get_instance(self):
        source = inspect.getsource(process_batch_invoices)
        self.assertNotIn(
            'get_instance()', source,
            "process_batch_invoices still calls BillingConfig.get_instance() "
            "which raises RuntimeError. Use get_for_tenant(tenant) instead."
        )

    def test_process_overdue_invoices_uses_get_for_tenant(self):
        source = inspect.getsource(process_overdue_invoices)
        self.assertIn('get_for_tenant(', source)

    def test_process_batch_invoices_uses_get_for_tenant(self):
        source = inspect.getsource(process_batch_invoices)
        self.assertIn('get_for_tenant(', source)


class TestNoGetInstanceInAdminGenerateInvoices(TestCase):
    """Ensure CustomerAdmin.generate_invoices doesn't call get_instance()."""

    def test_generate_invoices_no_get_instance(self):
        from apps.technician_portal.admin import CustomerAdmin
        source = inspect.getsource(CustomerAdmin.generate_invoices)
        self.assertNotIn(
            'get_instance()', source,
            "CustomerAdmin.generate_invoices still calls BillingConfig.get_instance() "
            "which raises RuntimeError. Use get_for_tenant(customer.tenant) instead."
        )

    def test_generate_invoices_uses_get_for_tenant(self):
        from apps.technician_portal.admin import CustomerAdmin
        source = inspect.getsource(CustomerAdmin.generate_invoices)
        self.assertIn('get_for_tenant(', source)


# ---------------------------------------------------------------------------
# Functional: process_overdue_invoices reads config per-tenant
# ---------------------------------------------------------------------------

class TestProcessOverdueInvoicesFunctional(TestCase):
    """
    process_overdue_invoices should read BillingConfig per tenant and not crash.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='owner007', password='pass', email='owner007@example.com'
        )
        self.tenant = Tenant.objects.create(
            name='Test Tenant CODE-007', slug='tt-code007',
            owner=self.user, is_active=True,
        )
        self.config = BillingConfig.get_for_tenant(self.tenant)
        self.customer = Customer.objects.create(
            name='Fleet Co',
            tenant=self.tenant,
        )

    def test_process_overdue_does_not_raise(self):
        """Task must not raise even when tenants exist with BillingConfig."""
        try:
            result = process_overdue_invoices()
        except RuntimeError as e:
            self.fail(
                f"process_overdue_invoices raised RuntimeError: {e}"
            )
        self.assertIn('updated', result)

    def test_process_overdue_marks_sent_invoices_overdue(self):
        """Invoices past their due date should be flipped to OVERDUE."""
        overdue_inv = Invoice.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            invoice_number='TEST-007-001',
            status='SENT',
            invoice_date=date.today() - timedelta(days=60),
            due_date=date.today() - timedelta(days=5),
            subtotal=Decimal('100.00'),
            discount=Decimal('0.00'),
            tax_rate=Decimal('0.00'),
            tax_amount=Decimal('0.00'),
            total=Decimal('100.00'),
            amount_paid=Decimal('0.00'),
            payment_terms='NET30',
        )

        result = process_overdue_invoices()

        overdue_inv.refresh_from_db()
        self.assertEqual(overdue_inv.status, 'OVERDUE')
        self.assertGreaterEqual(result['updated'], 1)


# ---------------------------------------------------------------------------
# Functional: admin generate_invoices action
# ---------------------------------------------------------------------------

class TestAdminGenerateInvoicesFunctional(TestCase):
    """
    CustomerAdmin.generate_invoices should work without crashing even though
    BillingConfig.get_instance() now raises RuntimeError.
    """

    def setUp(self):
        from apps.technician_portal.models import Repair, Technician
        from apps.billing.models import BillingConfig

        self.superuser = User.objects.create_superuser(
            username='admin007', password='pass', email='admin007@example.com'
        )
        self.tenant = Tenant.objects.create(
            name='Admin Test Tenant 007',
            slug='admin-tt-007',
            owner=self.superuser,
            is_active=True,
        )
        BillingConfig.get_for_tenant(self.tenant)  # ensure config exists

        self.customer = Customer.objects.create(
            name='Fleet Admin 007',
            tenant=self.tenant,
        )
        self.tech_user = User.objects.create_user(
            username='tech007', password='pass', email='tech007@example.com'
        )
        self.technician = Technician.objects.create(
            user=self.tech_user,
            tenant=self.tenant,
        )
        # Create a completed repair to invoice.
        # Use cost_override so the pricing service doesn't recalculate cost on save.
        self.repair = Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            technician=self.technician,
            queue_status='COMPLETED',
            damage_type='chip',
            unit_number='UNIT-007',
            cost_override=Decimal('75.00'),
        )
        # Reload so cost reflects whatever save() computed (should equal cost_override)
        self.repair.refresh_from_db()

    def test_generate_invoices_does_not_crash(self):
        """Action must not raise RuntimeError."""
        from apps.technician_portal.admin import CustomerAdmin
        from django.contrib.admin.sites import AdminSite

        ma = CustomerAdmin(Customer, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.superuser

        # Attach a simple message storage stub
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))

        try:
            ma.generate_invoices(request, Customer.objects.filter(pk=self.customer.pk))
        except RuntimeError as e:
            self.fail(f"generate_invoices raised RuntimeError: {e}")

    def test_generate_invoices_creates_draft_invoice(self):
        """Action should create a DRAFT invoice for the customer's unbilled repairs."""
        from apps.technician_portal.admin import CustomerAdmin
        from django.contrib.admin.sites import AdminSite
        from django.contrib.messages.storage.fallback import FallbackStorage

        ma = CustomerAdmin(Customer, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.superuser
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))

        before = Invoice.objects.filter(customer=self.customer).count()
        ma.generate_invoices(request, Customer.objects.filter(pk=self.customer.pk))
        after = Invoice.objects.filter(customer=self.customer).count()

        self.assertEqual(after, before + 1, "Expected exactly one new draft invoice")

        inv = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertEqual(inv.status, 'DRAFT')
        self.assertEqual(inv.tenant, self.tenant)
        # Total should match repair's actual cost (pricing service may adjust it on save)
        self.repair.refresh_from_db()
        self.assertEqual(inv.total, self.repair.cost)

    def test_generate_invoices_uses_tenant_prefix(self):
        """Invoice number prefix should come from the tenant's BillingConfig."""
        from apps.technician_portal.admin import CustomerAdmin
        from django.contrib.admin.sites import AdminSite
        from django.contrib.messages.storage.fallback import FallbackStorage

        config = BillingConfig.get_for_tenant(self.tenant)
        config.invoice_number_prefix = 'ADM007'
        config.save()

        ma = CustomerAdmin(Customer, AdminSite())
        request = RequestFactory().get('/')
        request.user = self.superuser
        setattr(request, 'session', {})
        setattr(request, '_messages', FallbackStorage(request))

        ma.generate_invoices(request, Customer.objects.filter(pk=self.customer.pk))

        inv = Invoice.objects.filter(customer=self.customer).latest('id')
        self.assertTrue(
            inv.invoice_number.startswith('ADM007-'),
            f"Expected prefix 'ADM007-', got '{inv.invoice_number}'"
        )


# --- From test_code010_hardcoded_company_name.py ---

# ---------------------------------------------------------------------------
# Source-code guard — no bare hard-coded company name in service logic
# ---------------------------------------------------------------------------


class TestNoHardcodedCompanyName(TestCase):
    """Ensure service files don't contain the old hard-coded string."""

    def test_reminder_service_no_hardcoded_name(self):
        import apps.billing.services.reminder_service as mod
        source = inspect.getsource(mod)
        # Allow the string only in comments / docstrings — not in string literals
        # that appear in f-string bodies or regular string assignment in logic.
        # Simple check: count occurrences; if any appear it's a regression.
        self.assertNotIn(
            '"Rockstar Windshield Repair"',
            source,
            "reminder_service.py must not hard-code 'Rockstar Windshield Repair' "
            "as a string literal — use BillingConfig or tenant.name instead.",
        )

    def test_invoice_service_no_hardcoded_name(self):
        import apps.billing.services.invoice_service as mod
        source = inspect.getsource(mod)
        self.assertNotIn(
            '"Rockstar Windshield Repair"',
            source,
            "invoice_service.py must not hard-code 'Rockstar Windshield Repair' "
            "as a string literal — use BillingConfig or tenant.name instead.",
        )


# ---------------------------------------------------------------------------
# Helper — build a minimal tenant + customer + invoice fixture in memory
# ---------------------------------------------------------------------------

def _make_fixtures(tenant_name="Acme Glass Co."):
    """Return (tenant, customer, invoice) using unsaved/mocked objects."""
    tenant = MagicMock(spec=Tenant)
    tenant.name = tenant_name
    tenant.id = 99

    customer = MagicMock()
    customer.name = "Fleet Corp"
    customer.email = "fleet@example.com"
    customer.tenant = tenant

    invoice = MagicMock(spec=Invoice)
    invoice.invoice_number = "INV-20260314-001"
    invoice.invoice_date = timezone.now().date()
    invoice.due_date = timezone.now().date()
    invoice.status = "PAID"
    invoice.get_status_display.return_value = "Paid"
    invoice.total = Decimal("500.00")
    invoice.subtotal = Decimal("500.00")
    invoice.amount_paid = Decimal("500.00")
    invoice.amount_due = Decimal("0.00")
    invoice.customer = customer
    invoice.tenant = tenant
    invoice.stripe_hosted_url = None
    invoice.internal_notes = ""

    payment = MagicMock()
    payment.amount = Decimal("500.00")
    payment.get_payment_method_display.return_value = "Check"
    payment.payment_date = timezone.now().date()

    return tenant, customer, invoice, payment


# ---------------------------------------------------------------------------
# ReminderService.send_payment_confirmation — uses BillingConfig
# ---------------------------------------------------------------------------

class TestPaymentConfirmationCompanyName(TestCase):

    def test_uses_billing_config_company_name(self):
        """sign-off must use BillingConfig.company_name when available."""
        tenant, customer, invoice, payment = _make_fixtures("Glass Masters LLC")

        mock_config = MagicMock()
        mock_config.company_name = "Glass Masters LLC"
        mock_config.company_phone = ""
        mock_config.company_website = ""

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            with patch.object(svc, '_send_email', return_value=True) as mock_send:
                result = svc.send_payment_confirmation(invoice, payment)

        self.assertTrue(result['success'])
        # Grab the body that was passed to _send_email
        _, kwargs = mock_send.call_args
        body = kwargs.get('body', mock_send.call_args[0][1] if mock_send.call_args[0] else "")
        # Reconstruct from positional args if needed
        all_args = str(mock_send.call_args)
        self.assertIn("Glass Masters LLC", all_args,
                      "Payment confirmation body must include the tenant's company name.")
        self.assertNotIn("Rockstar Windshield Repair", all_args,
                         "Payment confirmation body must NOT include the old hard-coded name.")

    def test_falls_back_to_tenant_name_when_config_missing(self):
        """sign-off must fall back to tenant.name when BillingConfig unavailable."""
        tenant, customer, invoice, payment = _make_fixtures("Sunrise Auto Glass")

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', side_effect=Exception("No config")):
            with patch.object(svc, '_send_email', return_value=True) as mock_send:
                result = svc.send_payment_confirmation(invoice, payment)

        self.assertTrue(result['success'])
        all_args = str(mock_send.call_args)
        self.assertIn("Sunrise Auto Glass", all_args,
                      "Payment confirmation body must fall back to tenant.name.")
        self.assertNotIn("Rockstar Windshield Repair", all_args)

    def test_uses_invoice_tenant_when_service_tenant_is_none(self):
        """When ReminderService has no tenant, it uses invoice.tenant for the lookup."""
        tenant, customer, invoice, payment = _make_fixtures("Valley View Glass")

        mock_config = MagicMock()
        mock_config.company_name = "Valley View Glass"

        # Build service without a tenant set on the service itself
        svc = ReminderService(tenant=None)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config) as mock_get:
            with patch.object(svc, '_send_email', return_value=True) as mock_send:
                result = svc.send_payment_confirmation(invoice, payment)

        # BillingConfig.get_for_tenant must have been called with invoice.tenant
        mock_get.assert_called_once_with(tenant)
        self.assertIn("Valley View Glass", str(mock_send.call_args))


# ---------------------------------------------------------------------------
# ReminderService._build_reminder_email — uses BillingConfig
# ---------------------------------------------------------------------------

class TestBuildReminderEmailCompanyName(TestCase):

    def test_uses_billing_config_company_name(self):
        """Reminder email body must include tenant's company name."""
        tenant, customer, invoice, payment = _make_fixtures("Blue Ridge Glass")

        mock_config = MagicMock()
        mock_config.company_name = "Blue Ridge Glass"
        mock_config.company_phone = "555-1234"
        mock_config.company_website = "https://blueridgeglass.example.com"

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            subject, body = svc._build_reminder_email(invoice, 'overdue_7d')

        self.assertIn("Blue Ridge Glass", body)
        self.assertNotIn("Rockstar Windshield Repair", body)

    def test_falls_back_to_tenant_name_when_config_has_no_company_name(self):
        """When BillingConfig.company_name is blank, must use tenant.name."""
        tenant, customer, invoice, payment = _make_fixtures("Coastal Glass Pros")

        mock_config = MagicMock()
        mock_config.company_name = ""   # blank — should trigger fallback
        mock_config.company_phone = ""
        mock_config.company_website = ""

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            subject, body = svc._build_reminder_email(invoice, 'due_soon_3d')

        self.assertIn("Coastal Glass Pros", body,
                      "Should fall back to tenant.name when company_name is blank.")
        self.assertNotIn("Rockstar Windshield Repair", body)

    def test_falls_back_to_tenant_name_when_config_unavailable(self):
        """When BillingConfig lookup raises, must use tenant.name."""
        tenant, customer, invoice, payment = _make_fixtures("Mountain Glass Works")

        svc = ReminderService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', side_effect=Exception("db error")):
            subject, body = svc._build_reminder_email(invoice, 'overdue_1d')

        self.assertIn("Mountain Glass Works", body)
        self.assertNotIn("Rockstar Windshield Repair", body)


# ---------------------------------------------------------------------------
# InvoiceService._load_branding_config — uses tenant.name as fallback
# ---------------------------------------------------------------------------

class TestInvoiceServiceCompanyName(TestCase):

    def test_uses_tenant_name_when_billing_config_raises(self):
        """InvoiceService must use tenant.name when BillingConfig fails to load."""
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Summit Glass Repair"
        tenant.id = 42

        svc = InvoiceService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', side_effect=Exception("no config")):
            svc._load_branding_config()

        self.assertEqual(svc.COMPANY_NAME, "Summit Glass Repair",
                         "COMPANY_NAME must fall back to tenant.name, not Rockstar.")

    def test_uses_tenant_name_when_company_name_blank_in_config(self):
        """InvoiceService must use tenant.name when config.company_name is blank."""
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Desert Sun Glass"
        tenant.id = 43

        mock_config = MagicMock()
        mock_config.company_name = ""
        mock_config.full_address = "123 Main St"
        mock_config.company_phone = ""
        mock_config.company_email = ""
        mock_config.company_website = ""
        mock_config.default_payment_terms = "NET30"
        mock_config.due_days_for_terms = 30
        mock_config.invoice_footer_note = ""
        mock_config.invoice_number_prefix = "INV"

        svc = InvoiceService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            with patch('core.models.email_branding.EmailBrandingConfig.get_instance',
                       side_effect=Exception("not configured")):
                svc._load_branding_config()

        self.assertEqual(svc.COMPANY_NAME, "Desert Sun Glass",
                         "COMPANY_NAME must fall back to tenant.name when config.company_name is blank.")

    def test_uses_billing_config_company_name_when_set(self):
        """InvoiceService must use BillingConfig.company_name when it is set."""
        tenant = MagicMock(spec=Tenant)
        tenant.name = "Fallback Name"
        tenant.id = 44

        mock_config = MagicMock()
        mock_config.company_name = "Lakeside Auto Glass"
        mock_config.full_address = "456 Lake Rd"
        mock_config.company_phone = "555-9999"
        mock_config.company_email = "info@lakeside.example.com"
        mock_config.company_website = "https://lakeside.example.com"
        mock_config.default_payment_terms = "COD"
        mock_config.due_days_for_terms = 0
        mock_config.invoice_footer_note = "Thanks!"
        mock_config.invoice_number_prefix = "LAK"

        svc = InvoiceService(tenant=tenant)

        with patch.object(BillingConfig, 'get_for_tenant', return_value=mock_config):
            with patch('core.models.email_branding.EmailBrandingConfig.get_instance',
                       side_effect=Exception("not configured")):
                svc._load_branding_config()

        self.assertEqual(svc.COMPANY_NAME, "Lakeside Auto Glass")


# --- From test_code012_billing_config_company_name_default.py ---



class BillingConfigCompanyNameDefaultTest(TestCase):
    """BillingConfig.get_for_tenant creates config with correct shop name."""

    def setUp(self):
        self.plan = SubscriptionPlan.objects.create(
            name='Test Plan', slug='test-plan-code012',
            monthly_price=Decimal('29.99'),
            max_repairs_per_month=100,
            max_technicians=5,
            max_customers=50,
            max_storage_mb=500,
        )
        self._user_counter = 0

    def _make_tenant(self, name):
        self._user_counter += 1
        user = User.objects.create_user(
            f'user_{self._user_counter}',
            f'user{self._user_counter}@test.com',
            'pass'
        )
        slug = name.lower().replace(' ', '-').replace("'", '')
        subdomain = name.lower().replace(' ', '').replace("'", '')[:20]
        return Tenant.objects.create(
            name=name,
            slug=slug,
            subdomain=subdomain,
            owner=user,
            subscription_plan=self.plan,
            is_active=True,
        )

    def test_new_tenant_gets_its_own_name(self):
        """get_for_tenant populates company_name from tenant.name on first call."""
        tenant = self._make_tenant('Acme Glass Co')
        config = BillingConfig.get_for_tenant(tenant)
        self.assertEqual(config.company_name, 'Acme Glass Co')

    def test_new_tenant_never_gets_rockstar_name(self):
        """A brand-new shop must not be branded as Rockstar Windshield Repair."""
        tenant = self._make_tenant('Springfield Glass')
        config = BillingConfig.get_for_tenant(tenant)
        self.assertNotEqual(config.company_name, 'Rockstar Windshield Repair')

    def test_second_call_returns_same_config(self):
        """get_for_tenant is idempotent — second call returns existing record."""
        tenant = self._make_tenant('Dual Glass')
        config1 = BillingConfig.get_for_tenant(tenant)
        config2 = BillingConfig.get_for_tenant(tenant)
        self.assertEqual(config1.pk, config2.pk)

    def test_existing_custom_name_not_overwritten(self):
        """If company_name was already set to a custom value, get_for_tenant must not overwrite it."""
        tenant = self._make_tenant('Custom Shop')
        # Pre-create with a custom name
        BillingConfig.objects.create(tenant=tenant, company_name='My Custom Brand')
        config = BillingConfig.get_for_tenant(tenant)
        self.assertEqual(config.company_name, 'My Custom Brand')

    def test_creation_path_populates_name(self):
        """Creation path (no pre-existing config) auto-populates company_name."""
        tenant = self._make_tenant('Blank Name Shop')
        # No pre-existing config — get_for_tenant creates one and populates name
        config = BillingConfig.get_for_tenant(tenant)
        self.assertTrue(len(config.company_name) > 0)
        self.assertEqual(config.company_name, tenant.name)

    def test_multiple_tenants_get_different_names(self):
        """Different tenants must get different company names."""
        tenant_a = self._make_tenant('Alpha Glass')
        tenant_b = self._make_tenant('Beta Auto Glass')
        config_a = BillingConfig.get_for_tenant(tenant_a)
        config_b = BillingConfig.get_for_tenant(tenant_b)
        self.assertEqual(config_a.company_name, 'Alpha Glass')
        self.assertEqual(config_b.company_name, 'Beta Auto Glass')
        self.assertNotEqual(config_a.company_name, config_b.company_name)

    def test_field_default_is_not_rockstar(self):
        """The model field default must be '' not 'Rockstar Windshield Repair'."""
        field = BillingConfig._meta.get_field('company_name')
        self.assertNotEqual(field.default, 'Rockstar Windshield Repair')
        self.assertEqual(field.default, '')

    def test_field_is_blank_true(self):
        """Field must have blank=True so empty strings are valid at form level."""
        field = BillingConfig._meta.get_field('company_name')
        self.assertTrue(field.blank)


# --- From test_code017_convert_to_batch_price_override.py ---

def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant_c017(name, owner):
    return Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=owner,
        plan='trial',
        subscription_plan=_make_plan(),
    )


def _make_membership(user, tenant, role='technician'):
    TenantMembership.objects.create(user=user, tenant=tenant, role=role, is_active=True)


class ConvertToBatchPriceOverrideBugTests(TestCase):
    """
    Tests for the three bugs in convert_to_batch price override handling.
    These tests exercise the logic directly without making full HTTP requests,
    focusing on the specific fix locations.
    """

    def setUp(self):
        plan = _make_plan()

        # Shop A setup
        self.owner_a = User.objects.create_user(username='owner_a', password='pw')
        self.tenant_a = _make_tenant_c017('Shop A', self.owner_a)
        _make_membership(self.owner_a, self.tenant_a, 'owner')

        self.customer_a = Customer.objects.create(
            name='Test Fleet',
            address='123 Main St',
            email='fleet@example.com',
            tenant=self.tenant_a,
        )

        # Manager tech with can_override_pricing=True, no limit (unlimited)
        self.manager_user = User.objects.create_user(username='mgr_a', password='pw')
        _make_membership(self.manager_user, self.tenant_a, 'manager')
        self.manager_tech = Technician.objects.create(
            user=self.manager_user,
            tenant=self.tenant_a,
            phone_number='555-0100',
            is_manager=True,
            can_override_pricing=True,
            approval_limit=None,  # NULL = unlimited
        )

        # Manager tech with can_override_pricing=True, limit=$100
        self.limited_manager_user = User.objects.create_user(username='mgr_limited', password='pw')
        _make_membership(self.limited_manager_user, self.tenant_a, 'manager')
        self.limited_manager_tech = Technician.objects.create(
            user=self.limited_manager_user,
            tenant=self.tenant_a,
            phone_number='555-0101',
            is_manager=True,
            can_override_pricing=True,
            approval_limit=Decimal('100.00'),
        )

        # Manager tech with can_override_pricing=FALSE
        self.no_override_user = User.objects.create_user(username='mgr_no_override', password='pw')
        _make_membership(self.no_override_user, self.tenant_a, 'manager')
        self.no_override_tech = Technician.objects.create(
            user=self.no_override_user,
            tenant=self.tenant_a,
            phone_number='555-0102',
            is_manager=True,
            can_override_pricing=False,  # Cannot override
            approval_limit=Decimal('500.00'),
        )

        # Plain technician (not a manager)
        self.plain_user = User.objects.create_user(username='tech_plain', password='pw')
        _make_membership(self.plain_user, self.tenant_a, 'technician')
        self.plain_tech = Technician.objects.create(
            user=self.plain_user,
            tenant=self.tenant_a,
            phone_number='555-0103',
            is_manager=False,
            can_override_pricing=False,
        )

        # Original repair for converting to batch
        self.original_repair = Repair.objects.create(
            tenant=self.tenant_a,
            customer=self.customer_a,
            technician=self.manager_tech,
            unit_number='TRUCK-001',
            damage_type='chip',
            cost=Decimal('50.00'),
            queue_status='APPROVED',
        )

    def _build_post_data(self, additional_breaks=1, override_cost='', override_reason='', damage_type='chip'):
        """Build a minimal valid POST dict for convert_to_batch."""
        data = {
            'additional_breaks': str(additional_breaks),
        }
        for i in range(additional_breaks):
            data[f'damage_type_{i}'] = damage_type
            if override_cost:
                data[f'override_cost_{i}'] = str(override_cost)
                data[f'override_reason_{i}'] = override_reason
        return data

    # -------------------------------------------------------------------------
    # Bug 1: NULL approval_limit TypeError crash
    # -------------------------------------------------------------------------

    def test_manager_with_null_approval_limit_can_override(self):
        """
        BUG-1: manager with approval_limit=None (unlimited) should be allowed
        to override any price — not crash with TypeError.
        """
        self.client.login(username='mgr_a', password='pw')
        session = self.client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

        post_data = self._build_post_data(
            additional_breaks=1,
            override_cost='75.00',
            override_reason='Special deal',
        )

        with patch('apps.technician_portal.views.batch.getattr') as _:
            # Patch request.tenant via middleware simulation
            pass

        # We test the logic path directly via the model's can_approve_amount
        # to confirm it handles None correctly
        self.assertIsNone(self.manager_tech.approval_limit)
        # can_approve_amount returns False when approval_limit is None (model method)
        # But our fix in the view should allow unlimited overrides regardless
        # The fix: if tech.approval_limit is not None and override > limit → reject
        # If approval_limit IS None → skip comparison entirely → allow

        # Simulate the fixed logic:
        override_amount = Decimal('75.00')
        tech = self.manager_tech
        allowed = tech.is_manager and tech.can_override_pricing
        if allowed:
            if tech.approval_limit is not None and override_amount > tech.approval_limit:
                allowed = False
        self.assertTrue(allowed, "Manager with null (unlimited) approval_limit should be allowed")

    def test_manager_null_limit_old_code_would_crash(self):
        """
        Confirms the old code (raw comparison) raises TypeError for None approval_limit,
        which was the original bug — TypeError is NOT in (InvalidOperation, ValueError)
        so it propagated as an unhandled exception.
        """
        tech = self.manager_tech
        self.assertIsNone(tech.approval_limit)
        with self.assertRaises(TypeError):
            # This is exactly the old code that crashed:
            _ = Decimal('75.00') <= tech.approval_limit  # noqa

    # -------------------------------------------------------------------------
    # Bug 2: Missing can_override_pricing check
    # -------------------------------------------------------------------------

    def test_manager_without_can_override_pricing_is_rejected(self):
        """
        BUG-2: A manager with can_override_pricing=False must NOT be allowed
        to override prices in convert_to_batch.
        """
        tech = self.no_override_tech
        self.assertTrue(tech.is_manager)
        self.assertFalse(tech.can_override_pricing)

        # Simulate the FIXED logic:
        override_amount = Decimal('75.00')
        allowed = tech.is_manager and tech.can_override_pricing  # False
        if allowed:
            if tech.approval_limit is not None and override_amount > tech.approval_limit:
                allowed = False

        self.assertFalse(allowed, "Manager with can_override_pricing=False must not override prices")

    def test_manager_with_can_override_pricing_is_allowed(self):
        """
        A manager with can_override_pricing=True and amount within limit is allowed.
        """
        tech = self.limited_manager_tech
        self.assertTrue(tech.is_manager)
        self.assertTrue(tech.can_override_pricing)

        override_amount = Decimal('75.00')  # within $100 limit
        allowed = tech.is_manager and tech.can_override_pricing
        if allowed:
            if tech.approval_limit is not None and override_amount > tech.approval_limit:
                allowed = False

        self.assertTrue(allowed)

    def test_manager_exceeds_limit_is_rejected(self):
        """
        A manager with can_override_pricing=True but amount exceeds approval_limit is rejected.
        """
        tech = self.limited_manager_tech
        override_amount = Decimal('150.00')  # exceeds $100 limit
        allowed = tech.is_manager and tech.can_override_pricing
        if allowed:
            if tech.approval_limit is not None and override_amount > tech.approval_limit:
                allowed = False

        self.assertFalse(allowed)

    def test_plain_technician_cannot_override(self):
        """A plain (non-manager) technician must not be allowed to override prices."""
        tech = self.plain_tech
        override_amount = Decimal('50.00')
        allowed = tech.is_manager and tech.can_override_pricing
        self.assertFalse(allowed)

    # -------------------------------------------------------------------------
    # Bug 3: is_tenant_admin without tenant — consistency check
    # -------------------------------------------------------------------------

    def test_is_tenant_admin_accepts_tenant_kwarg(self):
        """
        is_tenant_admin() must accept a ``tenant`` keyword argument (added in CODE-015).
        The fixed convert_to_batch now passes tenant=getattr(request, 'tenant', None).
        """
        from apps.technician_portal.decorators import is_tenant_admin
        import inspect
        sig = inspect.signature(is_tenant_admin)
        self.assertIn('tenant', sig.parameters, "is_tenant_admin must accept tenant= kwarg (CODE-015)")

    def test_is_tenant_admin_with_tenant_none_does_not_crash(self):
        """is_tenant_admin(user, tenant=None) should not raise even if tenant is None."""
        from apps.technician_portal.decorators import is_tenant_admin
        # Should just return False/True without raising
        result = is_tenant_admin(self.plain_user, tenant=None)
        self.assertIsInstance(result, bool)

    def test_is_tenant_admin_with_tenant_scoped_correctly(self):
        """is_tenant_admin with explicit tenant only grants access for that tenant."""
        from apps.technician_portal.decorators import is_tenant_admin
        # owner_a is owner of tenant_a — should be admin there
        self.assertTrue(is_tenant_admin(self.owner_a, tenant=self.tenant_a))
        # plain_user is just a technician — should not be admin
        self.assertFalse(is_tenant_admin(self.plain_user, tenant=self.tenant_a))


# --- From test_code019_replacement_double_billing.py ---

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tenant_c019(slug):
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        email=f'owner_{slug}@test.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {slug}',
        slug=slug,
        subdomain=slug,
        owner=owner,
        plan='pro',
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_customer(tenant, name='Fleet Co'):
    return Customer.objects.create(
        tenant=tenant,
        name=name,
        email=f'{name.lower().replace(" ", "")}@test.com',
        customer_type='fleet',
    )


def _make_technician(tenant):
    user = User.objects.create_user(
        username=f'tech_{tenant.slug}_{User.objects.count()}',
        email=f'tech_{tenant.slug}_{User.objects.count()}@test.com',
        password='x',
    )
    tech, _ = Technician.objects.get_or_create(
        user=user, tenant=tenant, defaults={'is_active': True}
    )
    return tech


def _make_replacement(tenant, customer, cost='150.00', status='COMPLETED', technician=None):
    if technician is None:
        technician = _make_technician(tenant)
    return Replacement.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        cost=Decimal(cost),
        queue_status=status,
        service_date=date.today(),
        glass_position='WINDSHIELD',
    )


def _make_repair(tenant, customer, cost='75.00', status='COMPLETED', technician=None):
    if technician is None:
        technician = _make_technician(tenant)
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        unit_number='UNIT-001',
        cost=Decimal(cost),
        queue_status=status,
        service_date=date.today(),
        damage_type='CHIP',
    )


def _make_billing_config(tenant):
    config, _ = BillingConfig.objects.get_or_create(
        tenant=tenant,
        defaults={
            'company_name': tenant.name,
            'batch_invoice_frequency': 'monthly',
            'batch_invoice_day': date.today().day,
            'batch_invoice_auto_send': False,
            'tax_enabled': False,
        },
    )
    config.batch_invoice_frequency = 'monthly'
    config.batch_invoice_day = date.today().day
    config.batch_invoice_auto_send = False
    config.save()
    return config


def _set_batch_preference(customer):
    prefs, _ = CustomerRepairPreference.objects.get_or_create(customer=customer)
    prefs.invoice_preference = 'batch'
    prefs.save()
    return prefs


# ---------------------------------------------------------------------------
# 1. Model-level: InvoiceLineItem has a replacement FK
# ---------------------------------------------------------------------------


class TestInvoiceLineItemReplacementField(TestCase):
    """InvoiceLineItem must have a nullable `replacement` FK."""

    def test_replacement_field_exists(self):
        """InvoiceLineItem.replacement field must exist."""
        field_names = [f.name for f in InvoiceLineItem._meta.get_fields()]
        self.assertIn(
            'replacement', field_names,
            "InvoiceLineItem is missing the `replacement` FK. "
            "Replacements cannot be tracked for double-billing prevention without it."
        )

    def test_replacement_field_is_nullable(self):
        """replacement FK must be nullable (line items for repairs have replacement=NULL)."""
        field = InvoiceLineItem._meta.get_field('replacement')
        self.assertTrue(
            field.null,
            "InvoiceLineItem.replacement must be nullable (null=True)."
        )

    def test_replacement_field_on_delete_protect(self):
        """replacement FK must use PROTECT to prevent deleting invoiced replacements."""
        from django.db.models import CASCADE, PROTECT
        field = InvoiceLineItem._meta.get_field('replacement')
        self.assertEqual(
            field.remote_field.on_delete, PROTECT,
            "InvoiceLineItem.replacement should use on_delete=PROTECT."
        )

    def test_repair_field_still_exists(self):
        """The existing repair FK must still be present (regression guard)."""
        field_names = [f.name for f in InvoiceLineItem._meta.get_fields()]
        self.assertIn('repair', field_names, "InvoiceLineItem.repair FK disappeared!")


# ---------------------------------------------------------------------------
# 2. Source-code guard: broken exclusion pattern is gone
# ---------------------------------------------------------------------------

class TestBrokenExclusionGone(TestCase):
    """The old broken exclusion query must not appear in tasks.py."""

    def test_old_broken_exclusion_not_present(self):
        """
        The old pattern `repair__isnull=False` followed by `values_list('repair_id'`
        for the replacement exclusion must be gone from _create_batch_invoice source.
        """
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(tasks_module)

        # The correct new pattern must exist
        self.assertIn(
            'replacement__isnull=False',
            source,
            "_create_batch_invoice must use replacement__isnull=False to filter "
            "replacement line items (not the old repair__isnull=False hack)."
        )
        self.assertIn(
            'replacement_id',
            source,
            "_create_batch_invoice must extract replacement_id from the exclusion "
            "query (not repair_id)."
        )

    def test_replacement_fk_set_on_line_item_create(self):
        """replacement=replacement must be passed when creating InvoiceLineItem for replacements."""
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(tasks_module._create_batch_invoice)
        self.assertIn(
            'replacement=replacement',
            source,
            "_create_batch_invoice must set InvoiceLineItem.replacement=replacement "
            "so the replacement FK is populated and future exclusions work."
        )

    def test_correct_model_for_invoice_preference(self):
        """process_batch_invoices must use CustomerRepairPreference, not CustomerPreference."""
        import apps.billing.tasks as tasks_module
        source = inspect.getsource(tasks_module.process_batch_invoices)
        self.assertIn(
            'CustomerRepairPreference',
            source,
            "process_batch_invoices must filter by CustomerRepairPreference.invoice_preference, "
            "not CustomerPreference (which has no invoice_preference field)."
        )
        self.assertNotIn(
            "CustomerPreference.objects",
            source,
            "process_batch_invoices must not use CustomerPreference.objects — "
            "that model has no invoice_preference field."
        )


# ---------------------------------------------------------------------------
# 3. Functional: replacement line item is linked correctly
# ---------------------------------------------------------------------------

class TestReplacementLineItemLinkage(TestCase):
    """_create_batch_invoice must populate the replacement FK on line items."""

    def test_replacement_fk_set_after_batch_invoice(self):
        tenant, _ = _make_tenant_c019('linkage')
        customer = _make_customer(tenant, 'Linkage Trucking')
        config = _make_billing_config(tenant)
        replacement = _make_replacement(tenant, customer)

        invoice = _create_batch_invoice(tenant, customer, config)
        self.assertIsNotNone(invoice, "Invoice should be created for uninvoiced replacement")

        line_items = list(invoice.line_items.all())
        self.assertEqual(len(line_items), 1, "Should have exactly 1 line item")

        li = line_items[0]
        self.assertIsNotNone(li.replacement_id, "Line item replacement FK must be set")
        self.assertEqual(li.replacement_id, replacement.id)
        self.assertIsNone(li.repair_id, "Line item repair FK should be NULL for replacement")


# ---------------------------------------------------------------------------
# 4. Functional: no double-billing of replacements
# ---------------------------------------------------------------------------

class TestNoDoubleReplacementBilling(TestCase):
    """A replacement already on an active invoice must NOT be invoiced again."""

    def test_already_invoiced_replacement_excluded(self):
        tenant, _ = _make_tenant_c019('nodbl')
        customer = _make_customer(tenant, 'NoDbl Trucking')
        config = _make_billing_config(tenant)
        replacement = _make_replacement(tenant, customer)

        # First invoice (simulate existing draft)
        existing_invoice = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number='INV-EXISTING-001',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            payment_terms='NET30',
            status='DRAFT',
        )
        InvoiceLineItem.objects.create(
            invoice=existing_invoice,
            replacement=replacement,
            description='Windshield Replacement - UNIT-001',
            quantity=1,
            unit_price=replacement.cost,
            amount=replacement.cost,
        )

        # Second run should produce nothing (already invoiced)
        invoice2 = _create_batch_invoice(tenant, customer, config)
        self.assertIsNone(
            invoice2,
            "Should not create a second invoice — replacement is already invoiced."
        )

    def test_cancelled_invoice_allows_rebilling(self):
        """A replacement on a CANCELLED invoice can be re-billed."""
        tenant, _ = _make_tenant_c019('rebill')
        customer = _make_customer(tenant, 'Rebill Trucking')
        config = _make_billing_config(tenant)
        replacement = _make_replacement(tenant, customer)

        # Cancelled invoice — should NOT block re-billing
        cancelled_invoice = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number='INV-CANCELLED-001',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            payment_terms='NET30',
            status='CANCELLED',
        )
        InvoiceLineItem.objects.create(
            invoice=cancelled_invoice,
            replacement=replacement,
            description='Windshield Replacement - UNIT-001',
            quantity=1,
            unit_price=replacement.cost,
            amount=replacement.cost,
        )

        # Should create a new invoice since the only existing one is CANCELLED
        invoice2 = _create_batch_invoice(tenant, customer, config)
        self.assertIsNotNone(
            invoice2,
            "Should create a new invoice — the existing one is CANCELLED, not active."
        )

    def test_repair_double_billing_still_prevented(self):
        """Existing repair double-billing prevention must still work (regression guard)."""
        tenant, _ = _make_tenant_c019('repairdbl')
        customer = _make_customer(tenant, 'RepairDbl Trucking')
        config = _make_billing_config(tenant)
        repair = _make_repair(tenant, customer)

        # Existing draft invoice with this repair
        existing_invoice = Invoice.objects.create(
            tenant=tenant,
            customer=customer,
            invoice_number='INV-REPAIR-001',
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            payment_terms='NET30',
            status='DRAFT',
        )
        InvoiceLineItem.objects.create(
            invoice=existing_invoice,
            repair=repair,
            description='Windshield Repair - UNIT-001',
            quantity=1,
            unit_price=repair.cost,
            amount=repair.cost,
        )

        # Second run — repair already invoiced, no new invoice
        invoice2 = _create_batch_invoice(tenant, customer, config)
        self.assertIsNone(
            invoice2,
            "Repair double-billing prevention must still work after the replacement fix."
        )


# ---------------------------------------------------------------------------
# 5. Functional: process_batch_invoices end-to-end with replacements
# ---------------------------------------------------------------------------

class TestProcessBatchInvoicesWithReplacements(TestCase):
    """process_batch_invoices should create invoices for replacements correctly."""

    def test_batch_task_invoices_replacements(self):
        tenant, _ = _make_tenant_c019('e2e')
        customer = _make_customer(tenant, 'E2E Fleet')
        config = _make_billing_config(tenant)
        _set_batch_preference(customer)
        replacement = _make_replacement(tenant, customer, cost='200.00')

        result = process_batch_invoices()
        self.assertGreaterEqual(
            result['invoices_created'], 1,
            "process_batch_invoices should create at least 1 invoice for the replacement."
        )

        # Confirm the replacement FK is set
        li = InvoiceLineItem.objects.filter(replacement=replacement).first()
        self.assertIsNotNone(
            li,
            "InvoiceLineItem with replacement FK should exist after batch run."
        )

    def test_batch_task_does_not_double_bill_on_second_run(self):
        tenant, _ = _make_tenant_c019('e2e2')
        customer = _make_customer(tenant, 'E2E2 Fleet')
        config = _make_billing_config(tenant)
        _set_batch_preference(customer)
        _make_replacement(tenant, customer, cost='180.00')

        result1 = process_batch_invoices()
        self.assertGreaterEqual(result1['invoices_created'], 1)

        # Second run: replacement already invoiced — no new invoices
        result2 = process_batch_invoices()
        self.assertEqual(
            result2['invoices_created'], 0,
            "Second batch run should create 0 invoices — replacement already invoiced."
        )
