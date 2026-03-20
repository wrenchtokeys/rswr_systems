"""
Regression tests for CODE-078:
    edit_company() lowercased the customer name with `.lower()`, silently
    corrupting "EOS Trucking" → "eos trucking" on every save.

Covers:
    - POST preserves mixed-case name
    - POST rejects empty name
    - POST strips leading/trailing whitespace but keeps internal case
    - POST all-caps name preserved as-is
    - GET renders the form
    - Non-customer user is redirected by @customer_required
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_tenant(name="EC Test Shop"):
    owner = User.objects.create_user(
        username=f"_owner_ec_{name.lower().replace(' ', '_')}",
        email=f"owner_ec_{name.lower().replace(' ', '_')}@example.com",
        password="pw",
    )
    return Tenant.objects.create(
        name=name,
        slug=f"ec-{name.lower().replace(' ', '-')}",
        subdomain=f"ec-{name.lower().replace(' ', '-')}",
        owner=owner,
        is_active=True,
    )


class EditCompanyNameTestCase(TestCase):
    """Tests for edit_company() view — case preservation fix (CODE-078)."""

    def setUp(self):
        self.client = Client()
        self.tenant = _make_tenant("EC Test Shop")

        self.customer = Customer.objects.create(
            name="EOS Trucking",
            tenant=self.tenant,
            email="eos@example.com",
        )

        self.user = User.objects.create_user(
            username="eos_user_ec",
            email="eos_user_ec@example.com",
            password="testpass123",
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.user,
            role="viewer",
            is_active=True,
        )
        self.cu = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer,
            is_primary_contact=True,
        )
        self.url = "/app/company/edit/"

    def _login(self):
        session = self.client.session
        session["tenant_slug"] = self.tenant.slug
        session.save()
        self.client.force_login(self.user)

    def _post(self, name, **kwargs):
        data = {
            "name": name,
            "email": kwargs.get("email", ""),
            "phone": kwargs.get("phone", ""),
            "address": kwargs.get("address", ""),
            "city": kwargs.get("city", ""),
            "state": kwargs.get("state", ""),
            "zip_code": kwargs.get("zip_code", ""),
        }
        return self.client.post(self.url, data)

    # ------------------------------------------------------------------
    # Happy path — name should be stored exactly as entered
    # ------------------------------------------------------------------

    def test_post_preserves_mixed_case_name(self):
        """Customer name must NOT be lowercased on save (CODE-078)."""
        self._login()
        self._post("EOS Trucking")
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.name, "EOS Trucking",
            "Customer name must preserve original case.",
        )

    def test_post_preserves_all_caps_name(self):
        """All-caps company name must be stored as-is."""
        self._login()
        self._post("ACME CORP")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "ACME CORP")

    def test_post_preserves_title_case(self):
        """Title case names must be stored as-is."""
        self._login()
        self._post("West Tree Service")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "West Tree Service")

    def test_post_strips_whitespace_but_preserves_internal_case(self):
        """Leading/trailing whitespace stripped but internal case preserved."""
        self._login()
        self._post("  Penske Truck Leasing  ")
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, "Penske Truck Leasing")

    def test_post_redirects_on_success(self):
        """Successful POST should redirect (to customer dashboard)."""
        self._login()
        response = self._post("EOS Trucking")
        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # Validation — empty name should be rejected
    # ------------------------------------------------------------------

    def test_post_rejects_empty_name(self):
        """Empty company name must return 200 with error, not save."""
        self._login()
        original_name = self.customer.name
        response = self._post("")
        self.assertNotEqual(response.status_code, 302, "Should not redirect on empty name.")
        self.customer.refresh_from_db()
        self.assertEqual(
            self.customer.name, original_name,
            "Customer name must not be cleared on empty POST.",
        )

    def test_post_rejects_whitespace_only_name(self):
        """Whitespace-only company name must also be rejected."""
        self._login()
        original_name = self.customer.name
        response = self._post("   ")
        self.assertNotEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.name, original_name)

    # ------------------------------------------------------------------
    # GET renders form
    # ------------------------------------------------------------------

    def test_get_renders_form(self):
        """GET request should return 200 with the edit form."""
        self._login()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EOS Trucking")

    # ------------------------------------------------------------------
    # Non-customer user is redirected (@customer_required)
    # ------------------------------------------------------------------

    def test_non_customer_user_redirected(self):
        """User without CustomerUser record should be redirected."""
        other_user = User.objects.create_user(
            username="other_user_ec2",
            email="other_ec2@example.com",
            password="testpass123",
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=other_user,
            role="viewer",
            is_active=True,
        )
        session = self.client.session
        session["tenant_slug"] = self.tenant.slug
        session.save()
        self.client.force_login(other_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
