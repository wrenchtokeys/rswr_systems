"""
CODE-266: Email uniqueness checks use exact-match (filter(email=...)) instead of
          iexact, so legacy users stored with mixed-case emails can register
          duplicate accounts.

Affected paths:
  1. apps/saas/views.py – invite_team_member: User.objects.filter(email=email).first()
  2. apps/saas/views.py – shop_join POST: User.objects.filter(email=email).exists()
  3. apps/tenants/services/signup_service.py: User.objects.filter(email=email).exists()
  4. apps/tenants/views.py – saas_signup POST: User.objects.filter(email=email).exists()

Fix: change all four to email__iexact.  Even though incoming email is .lower()'d
before the lookup, legacy rows in the DB may still store mixed-case values.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from unittest.mock import patch


class EmailIexactInviteTeamMemberTests(TestCase):
    """invite_team_member: finds existing user regardless of stored case."""

    def setUp(self):
        # Simulate a legacy user whose email was stored with mixed case
        self.legacy_user = User.objects.create_user(
            username='legacyuser',
            email='Legacy.User@Example.com',
            password='pass1234'
        )

    def test_invite_finds_mixed_case_email(self):
        """filter(email__iexact=) finds user even if DB has mixed case."""
        # The invite view lower-cases the POST email then does iexact lookup.
        lowercased = 'legacy.user@example.com'
        found = User.objects.filter(email__iexact=lowercased).first()
        self.assertIsNotNone(found)
        self.assertEqual(found.id, self.legacy_user.id)

    def test_invite_exact_match_would_miss_mixed_case(self):
        """Sanity: exact-match misses mixed-case legacy email (shows why iexact matters)."""
        lowercased = 'legacy.user@example.com'
        exact_found = User.objects.filter(email=lowercased).first()
        self.assertIsNone(exact_found)


class EmailIexactSignupServiceTests(TestCase):
    """signup_service.create_tenant_with_owner: rejects duplicate mixed-case emails."""

    def setUp(self):
        self.legacy_user = User.objects.create_user(
            username='legacyowner',
            email='OWNER@SHOP.COM',
            password='pass1234'
        )

    def test_signup_service_rejects_mixed_case_duplicate(self):
        """create_tenant_with_owner raises SignupError for mixed-case duplicate."""
        from apps.tenants.services.signup_service import create_tenant_with_owner, SignupError
        with self.assertRaises(SignupError) as ctx:
            create_tenant_with_owner(
                first_name='New',
                last_name='Owner',
                email='owner@shop.com',  # same email, different case
                password='StrongPass1!',
                business_name='New Shop',
            )
        self.assertIn('already exists', str(ctx.exception))

    def test_signup_service_accepts_genuinely_new_email(self):
        """create_tenant_with_owner succeeds for a truly new email."""
        from apps.tenants.services.signup_service import create_tenant_with_owner
        result = create_tenant_with_owner(
            first_name='Brand',
            last_name='New',
            email='brand.new@shop.com',
            password='StrongPass1!',
            business_name='Brand New Shop',
        )
        self.assertIsNotNone(result)


class EmailIexactSaasSignupViewTests(TestCase):
    """apps/tenants/views.py saas_signup POST: rejects duplicate mixed-case email."""

    def setUp(self):
        self.client_obj = None
        self.legacy_user = User.objects.create_user(
            username='dupuser',
            email='Dup.User@Company.com',
            password='pass1234'
        )

    def test_saas_signup_rejects_mixed_case_duplicate(self):
        """saas_signup POST returns error for mixed-case duplicate."""
        from django.test import Client
        client = Client()
        resp = client.post('/signup/', {
            'first_name': 'New',
            'last_name': 'User',
            'email': 'dup.user@company.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
            'business_name': 'Dup Shop',
        })
        # Should not create a new user (unique email guard)
        new_user_count = User.objects.filter(email__iexact='dup.user@company.com').count()
        self.assertEqual(new_user_count, 1)  # only the legacy user, no duplicate created

    def test_iexact_lookup_directly(self):
        """Direct ORM test confirms iexact finds mixed-case stored email."""
        found = User.objects.filter(email__iexact='dup.user@company.com').exists()
        self.assertTrue(found)

    def test_exact_lookup_misses(self):
        """Exact lookup misses mixed-case stored email (regression prevention)."""
        found = User.objects.filter(email='dup.user@company.com').exists()
        self.assertFalse(found)


class ShopJoinEmailIexactTests(TestCase):
    """apps/saas/views.py shop_join: rejects duplicate mixed-case email."""

    def setUp(self):
        self.legacy_user = User.objects.create_user(
            username='fleetuser',
            email='Fleet.Manager@Fleet.Com',
            password='pass1234'
        )
        # Need a tenant/slug for the join view.
        # Tenant requires an owner (not-null), so create an owner user first.
        self.owner_user = User.objects.create_user(
            username='shopowner',
            email='shop.owner@fleet.com',
            password='pass1234'
        )
        from apps.tenants.models import Tenant
        self.tenant = Tenant.objects.create(
            name='Test Fleet Shop',
            slug='test-fleet-shop',
            is_active=True,
            owner=self.owner_user,
        )

    def test_shop_join_rejects_mixed_case_duplicate(self):
        """shop_join POST with mixed-case duplicate email shows error, no new user."""
        from django.test import Client
        client = Client()
        resp = client.post(f'/join/{self.tenant.slug}/', {
            'first_name': 'Fleet',
            'last_name': 'Mgr',
            'email': 'fleet.manager@fleet.com',
            'password': 'StrongPass1!',
            'confirm_password': 'StrongPass1!',
        })
        # No duplicate user should be created
        count = User.objects.filter(email__iexact='fleet.manager@fleet.com').count()
        self.assertEqual(count, 1)
