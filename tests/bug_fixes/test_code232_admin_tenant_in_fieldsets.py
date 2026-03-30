"""
CODE-232b: Admin fieldsets missing tenant field

Regression tests for ViscosityRecommendationAdmin and RewardOptionAdmin
which had 'tenant' in list_display/list_filter but NOT in fieldsets.
This meant superusers creating new records via admin would save them
with tenant=NULL, making them invisible to non-superuser staff and
logically orphaned from any shop.

Fix: Add 'tenant' to fieldsets so the form renders the tenant dropdown.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory

from apps.technician_portal.admin import ViscosityRecommendationAdmin
from apps.technician_portal.models import ViscosityRecommendation
from apps.rewards_referrals.admin import RewardOptionAdmin
from apps.rewards_referrals.models import RewardOption


class ViscosityRecommendationAdminFieldsetsTest(TestCase):
    """Ensure ViscosityRecommendationAdmin includes tenant in fieldsets."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = ViscosityRecommendationAdmin(ViscosityRecommendation, self.site)

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
                       "ViscosityRecommendationAdmin fieldsets must include 'tenant' "
                       "so new records are not created with tenant=NULL")

    def test_form_has_tenant_field(self):
        """The admin add form must include a tenant field."""
        factory = RequestFactory()
        request = factory.get('/admin/')
        request.user = User(is_superuser=True, is_staff=True, pk=1)
        # get_form returns the form class
        FormClass = self.admin.get_form(request, obj=None)
        self.assertIn('tenant', FormClass.base_fields,
                       "Add form must have a 'tenant' field")


class RewardOptionAdminFieldsetsTest(TestCase):
    """Ensure RewardOptionAdmin includes tenant in fieldsets."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = RewardOptionAdmin(RewardOption, self.site)

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
                       "RewardOptionAdmin fieldsets must include 'tenant' "
                       "so new records are not created with tenant=NULL")

    def test_form_has_tenant_field(self):
        """The admin add form must include a tenant field."""
        factory = RequestFactory()
        request = factory.get('/admin/')
        request.user = User(is_superuser=True, is_staff=True, pk=1)
        FormClass = self.admin.get_form(request, obj=None)
        self.assertIn('tenant', FormClass.base_fields,
                       "Add form must have a 'tenant' field")
