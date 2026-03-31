"""
CODE-236: TaxRateAdmin missing tenant in fieldsets

Regression test: TaxRateAdmin had 'tenant' in list_display and list_filter
but NOT in fieldsets. A superuser creating a new tax rate via the admin
would save it with tenant=NULL because the form never showed the tenant
dropdown. This makes the rate invisible to non-superuser staff (TenantFilterMixin
scopes by tenant) and unused for invoice tax calculations (which filter by tenant).

Fix: Add 'tenant' to the first fieldset group in TaxRateAdmin.

Also tests DeliveryLogAdmin list_select_related (CODE-236b): ensures the
tenant FK is eagerly loaded to avoid N+1 queries in the changelist.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.billing.admin import TaxRateAdmin
from apps.billing.models import TaxRate
from core.admin import DeliveryLogAdmin
from core.models import NotificationDeliveryLog


class TaxRateAdminFieldsetsTest(TestCase):
    """Ensure TaxRateAdmin includes tenant in fieldsets."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = TaxRateAdmin(TaxRate, self.site)

    def test_tenant_in_fieldsets(self):
        """tenant must appear in at least one fieldset so the add/change form renders it."""
        all_fields = []
        for _name, opts in self.admin.fieldsets:
            for field in opts.get('fields', []):
                if isinstance(field, (list, tuple)):
                    all_fields.extend(field)
                else:
                    all_fields.append(field)
        self.assertIn('tenant', all_fields,
                       "TaxRateAdmin fieldsets must include 'tenant' "
                       "so new records are not created with tenant=NULL")

    def test_tenant_in_first_fieldset(self):
        """tenant should appear in the first fieldset for visibility."""
        first_fieldset_name, first_opts = self.admin.fieldsets[0]
        first_fields = []
        for field in first_opts.get('fields', []):
            if isinstance(field, (list, tuple)):
                first_fields.extend(field)
            else:
                first_fields.append(field)
        self.assertIn('tenant', first_fields,
                       "tenant should be in the first fieldset for prominence")

    def test_form_has_tenant_field(self):
        """The admin add form must include a tenant field."""
        factory = RequestFactory()
        request = factory.get('/admin/')
        request.user = User(is_superuser=True, is_staff=True, pk=1)
        FormClass = self.admin.get_form(request, obj=None)
        self.assertIn('tenant', FormClass.base_fields,
                       "Add form must have a 'tenant' field")


class DeliveryLogAdminSelectRelatedTest(TestCase):
    """Ensure DeliveryLogAdmin has list_select_related to avoid N+1."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = DeliveryLogAdmin(NotificationDeliveryLog, self.site)

    def test_list_select_related_includes_tenant(self):
        """list_select_related must include 'tenant' to avoid N+1 queries."""
        sr = self.admin.list_select_related
        self.assertIsNotNone(sr, "list_select_related should not be None")
        self.assertIn('tenant', sr,
                       "DeliveryLogAdmin.list_select_related must include 'tenant' "
                       "since 'tenant' is in list_display")
