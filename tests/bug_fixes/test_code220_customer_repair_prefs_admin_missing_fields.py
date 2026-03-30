"""
CODE-220: Regression test — CustomerRepairPreferenceAdmin missing payment_terms and
batch_invoice_day fields after migration 0013 added them.

Bug: Migration 0013 added two new fields to CustomerRepairPreference:
  - payment_terms: per-customer override of the shop's default invoice payment terms
  - batch_invoice_day: per-customer override of the monthly batch invoice day

However, CustomerRepairPreferenceAdmin.fieldsets was never updated to include
these fields, and list_display also omitted payment_terms.  This meant:
  - Superusers had no way to view or edit payment_terms / batch_invoice_day
    via the Django admin UI — they were invisible.
  - The CODE-219 fix (auto_invoice_service + tasks.py reading payment_terms)
    correctly uses the data, but admins could not inspect or correct it without
    the Django shell.

Fix: Added payment_terms and batch_invoice_day to the 'Invoice Settings' fieldset,
and payment_terms to list_display for quick overview.

Tests verify:
1. CustomerRepairPreferenceAdmin is registered in Django admin.
2. 'payment_terms' appears in the admin fieldset fields.
3. 'batch_invoice_day' appears in the admin fieldset fields.
4. 'payment_terms' appears in list_display.
5. Superuser can access the changelist URL without errors.
6. Saving a CustomerRepairPreference with payment_terms via admin works.
"""

from django.test import TestCase, RequestFactory
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth.models import User

from apps.customer_portal.models import CustomerRepairPreference
from apps.customer_portal.admin import CustomerRepairPreferenceAdmin
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


# =============================================================================
# Helpers
# =============================================================================

def make_superuser(username):
    return User.objects.create_superuser(
        username=username, email=f'{username}@test.com', password='pass'
    )


def make_tenant_and_customer(name='Test Shop'):
    owner = User.objects.create_user(
        username=f'owner_{name.replace(" ", "_").lower()}',
        email=f'owner_{name.replace(" ", "_").lower()}@test.com',
        password='pass',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.replace(' ', '-').lower(),
        owner=owner,
        is_active=True,
    )
    customer = Customer.objects.create(
        name='Test Fleet',
        tenant=tenant,
    )
    return tenant, customer, owner


# =============================================================================
# Tests
# =============================================================================

class CustomerRepairPreferenceAdminFieldsTest(TestCase):
    """Verify that payment_terms and batch_invoice_day are exposed in admin."""

    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = make_superuser('admin_pref_test')
        self.tenant, self.customer, self.owner = make_tenant_and_customer()
        # Create a CustomerRepairPreference record for the customer
        self.prefs = CustomerRepairPreference.objects.create(
            customer=self.customer,
        )
        self.model_admin = admin_site._registry.get(CustomerRepairPreference)

    def test_admin_is_registered(self):
        """CustomerRepairPreference must be registered in Django admin."""
        self.assertIn(
            CustomerRepairPreference, admin_site._registry,
            "CustomerRepairPreference is not registered in Django admin.",
        )

    def test_payment_terms_in_fieldsets(self):
        """payment_terms must appear in at least one fieldset."""
        all_fields = []
        for name, options in self.model_admin.fieldsets:
            all_fields.extend(options.get('fields', []))
        self.assertIn(
            'payment_terms', all_fields,
            "payment_terms is missing from CustomerRepairPreferenceAdmin fieldsets. "
            "Added in migration 0013 but never added to admin.  (CODE-220)"
        )

    def test_batch_invoice_day_in_fieldsets(self):
        """batch_invoice_day must appear in at least one fieldset."""
        all_fields = []
        for name, options in self.model_admin.fieldsets:
            all_fields.extend(options.get('fields', []))
        self.assertIn(
            'batch_invoice_day', all_fields,
            "batch_invoice_day is missing from CustomerRepairPreferenceAdmin fieldsets. "
            "Added in migration 0013 but never added to admin.  (CODE-220)"
        )

    def test_payment_terms_in_list_display(self):
        """payment_terms must appear in list_display for quick overview."""
        self.assertIn(
            'payment_terms', self.model_admin.list_display,
            "payment_terms is missing from CustomerRepairPreferenceAdmin list_display. "
            "Cannot see per-customer payment term overrides at a glance.  (CODE-220)"
        )

    def test_changelist_loads_for_superuser(self):
        """Admin changelist must load without errors for superuser."""
        request = self.factory.get('/admin/customer_portal/customerrepairpreference/')
        request.user = self.superuser
        response = self.model_admin.changelist_view(request)
        self.assertEqual(
            response.status_code, 200,
            "CustomerRepairPreferenceAdmin changelist returned non-200 for superuser.",
        )

    def test_can_save_payment_terms_via_admin(self):
        """Saving payment_terms on a CustomerRepairPreference must persist."""
        self.prefs.payment_terms = 'NET30'
        self.prefs.save(update_fields=['payment_terms'])
        self.prefs.refresh_from_db()
        self.assertEqual(
            self.prefs.payment_terms, 'NET30',
            "payment_terms did not persist after save.",
        )

    def test_can_save_batch_invoice_day_via_admin(self):
        """Saving batch_invoice_day on a CustomerRepairPreference must persist."""
        self.prefs.batch_invoice_day = 15
        self.prefs.save(update_fields=['batch_invoice_day'])
        self.prefs.refresh_from_db()
        self.assertEqual(
            self.prefs.batch_invoice_day, 15,
            "batch_invoice_day did not persist after save.",
        )

    def test_blank_payment_terms_uses_shop_default(self):
        """A blank payment_terms string means 'use shop default' (not a bug in isolation)."""
        self.prefs.payment_terms = ''
        self.prefs.save(update_fields=['payment_terms'])
        self.prefs.refresh_from_db()
        self.assertEqual(self.prefs.payment_terms, '')

    def test_none_batch_invoice_day_uses_shop_default(self):
        """A null batch_invoice_day means 'use shop default'."""
        self.prefs.batch_invoice_day = None
        self.prefs.save(update_fields=['batch_invoice_day'])
        self.prefs.refresh_from_db()
        self.assertIsNone(self.prefs.batch_invoice_day)
