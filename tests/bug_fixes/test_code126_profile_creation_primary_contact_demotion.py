"""
Regression tests for CODE-126:
profile_creation() joining existing company with is_primary_contact=True
failed to demote the existing primary before creating the new CustomerUser.

Without the fix both CustomerUsers hold is_primary_contact=True simultaneously,
causing non-deterministic notification routing in repairs.py.

Mirrors the pattern fixed in account_settings() by CODE-116.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.urls import reverse

from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Customer, Technician
from apps.tenants.models import Tenant, TenantMembership


_owner_counter = 0


def _make_tenant(slug="test-shop-126"):
    global _owner_counter
    _owner_counter += 1
    owner = User.objects.create_user(
        username=f"owner_126_{_owner_counter}",
        password="pass",
        email=f"owner126_{_owner_counter}@test.com",
    )
    return Tenant.objects.create(
        name="Test Shop 126",
        slug=slug,
        owner=owner,
        is_active=True,
    )


def _make_customer(tenant, name="Fleet Co"):
    return Customer.objects.create(
        name=name,
        tenant=tenant,
    )


def _make_user(username, email=None):
    return User.objects.create_user(
        username=username,
        email=email or f"{username}@example.com",
        password="testpass123",
    )


class ProfileCreationPrimaryDemotionTest(TestCase):
    """Test that profile_creation() demotes existing primary when joining existing company."""

    def setUp(self):
        self.tenant = _make_tenant()
        self.customer = _make_customer(self.tenant)

        # Existing primary contact for the company
        self.existing_user = _make_user("existing_primary")
        self.existing_cu = CustomerUser.objects.create(
            user=self.existing_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.existing_user,
            role="viewer",
            is_active=True,
        )

        # New user joining the same company
        self.new_user = _make_user("new_joiner")
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.new_user,
            role="viewer",
            is_active=True,
        )

    def _post_profile(self, is_primary):
        """POST to profile_creation as new_user, joining existing company."""
        self.client.force_login(self.new_user)
        # Simulate the middleware setting request.tenant via session
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        return self.client.post(
            reverse('profile_creation'),
            {
                'is_new_company': 'no',
                'customer': str(self.customer.id),
                'is_primary_contact': 'True' if is_primary else '',
            },
        )

    def test_existing_primary_demoted_when_new_user_becomes_primary(self):
        """When new user joins as primary, old primary should be demoted."""
        self._post_profile(is_primary=True)

        # New user should now be primary
        new_cu = CustomerUser.objects.get(user=self.new_user, customer=self.customer)
        self.assertTrue(new_cu.is_primary_contact)

        # Existing primary should have been demoted
        self.existing_cu.refresh_from_db()
        self.assertFalse(
            self.existing_cu.is_primary_contact,
            "Existing primary contact was NOT demoted — CODE-126 bug is present"
        )

    def test_at_most_one_primary_contact_per_company(self):
        """After fix, company must have exactly one primary contact."""
        self._post_profile(is_primary=True)

        primary_count = CustomerUser.objects.filter(
            customer=self.customer,
            is_primary_contact=True,
        ).count()
        self.assertEqual(
            primary_count, 1,
            f"Expected 1 primary contact, got {primary_count} — multiple primaries exist"
        )

    def test_joining_as_non_primary_does_not_affect_existing_primary(self):
        """When new user joins without claiming primary, existing primary is unchanged."""
        self._post_profile(is_primary=False)

        # Existing primary should still be primary
        self.existing_cu.refresh_from_db()
        self.assertTrue(
            self.existing_cu.is_primary_contact,
            "Existing primary contact was incorrectly demoted when new user is NOT primary"
        )

        # New user should not be primary
        new_cu = CustomerUser.objects.get(user=self.new_user, customer=self.customer)
        self.assertFalse(new_cu.is_primary_contact)

    def test_joining_new_company_as_primary_does_not_crash(self):
        """
        When creating a brand-new company and claiming primary, no demotion query
        is needed (no existing CustomerUsers) and the save should succeed.
        """
        self.client.force_login(self.new_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        response = self.client.post(
            reverse('profile_creation'),
            {
                'is_new_company': 'yes',
                'company_name': 'Brand New Co',
                'company_email': 'new@brandnew.com',
                'company_phone': '',
                'company_address': '',
                'is_primary_contact': 'True',
            },
        )

        new_customers = Customer.objects.filter(name='Brand New Co', tenant=self.tenant)
        self.assertTrue(new_customers.exists(), "New company was not created")
        new_cu = CustomerUser.objects.filter(
            user=self.new_user, customer=new_customers.first()
        ).first()
        self.assertIsNotNone(new_cu, "CustomerUser not created for new company")
        self.assertTrue(new_cu.is_primary_contact)

    def test_multiple_sequential_joins_only_one_primary(self):
        """
        If 3 users join the same company claiming primary, only the last one should
        end up as primary.  All previously-created CUs should be demoted.
        """
        user2 = _make_user("joiner2")
        user3 = _make_user("joiner3")
        TenantMembership.objects.create(tenant=self.tenant, user=user2, role="viewer", is_active=True)
        TenantMembership.objects.create(tenant=self.tenant, user=user3, role="viewer", is_active=True)

        for user in (user2, user3):
            self.client.force_login(user)
            session = self.client.session
            session['tenant_id'] = self.tenant.id
            session.save()
            self.client.post(
                reverse('profile_creation'),
                {
                    'is_new_company': 'no',
                    'customer': str(self.customer.id),
                    'is_primary_contact': 'True',
                },
            )

        primary_count = CustomerUser.objects.filter(
            customer=self.customer,
            is_primary_contact=True,
        ).count()
        self.assertEqual(
            primary_count, 1,
            f"Expected exactly 1 primary after 3 sequential joins, got {primary_count}"
        )

    def test_customeruser_created_regardless_of_primary_flag(self):
        """A CustomerUser record is always created, even when not claiming primary."""
        self._post_profile(is_primary=False)
        self.assertTrue(
            CustomerUser.objects.filter(user=self.new_user, customer=self.customer).exists()
        )
