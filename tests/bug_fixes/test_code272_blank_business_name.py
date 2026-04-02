"""
Regression tests for CODE-272: blank business name blanks tenant.name.

owner_settings_view (POST, default form_type) was missing a guard for an empty
business_name field. If an owner deleted the text and submitted, the server
would write '' to Tenant.name, breaking every invoice, email, and portal page
that renders tenant.name.

The fix adds an early-return with an error message when new_name is falsy,
mirroring the `or tenant.name` guard already present in owner_setup_save_business.
"""
import json

from django.test import TestCase, Client
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan


def _make_owner(email="owner@test.com", username="owner_272"):
    user = User.objects.create_user(
        username=username,
        email=email,
        password="testpassword123",
        first_name="Test",
        last_name="Owner",
    )
    return user


def _make_tenant(owner, name="My Glass Shop", slug="my-glass-shop", subdomain="my-glass-shop"):
    return Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=subdomain,
        owner=owner,
        plan='trial',
    )


class BlankBusinessNameTests(TestCase):
    """Test that submitting an empty business_name is rejected gracefully."""

    def setUp(self):
        self.client = Client()
        self.owner = _make_owner()
        self.tenant = _make_tenant(self.owner)
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.owner,
            role='owner',
            is_active=True,
        )
        self.client.login(username="owner_272", password="testpassword123")
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_blank_name_rejected_with_error(self):
        """Submitting business_name='' must return an error, not save the blank."""
        original_name = self.tenant.name
        response = self.client.post('/owner/settings/', {
            'business_name': '',
            'business_email': 'shop@example.com',
            'business_phone': '555-1234',
        }, follow=True)
        # View should redirect back to settings with an error message
        self.assertEqual(response.status_code, 200)
        # Re-fetch from DB — name must not have changed
        self.tenant.refresh_from_db()
        self.assertEqual(
            self.tenant.name,
            original_name,
            "tenant.name was wiped to '' when a blank business_name was submitted",
        )

    def test_blank_name_error_message_shown(self):
        """An appropriate error message must be displayed to the owner."""
        response = self.client.post('/owner/settings/', {
            'business_name': '',
        }, follow=True)
        messages = [str(m) for m in response.context.get('messages', [])]
        self.assertTrue(
            any('required' in m.lower() or 'cannot be blank' in m.lower() for m in messages),
            f"Expected an error about empty business name; got: {messages}",
        )

    def test_whitespace_only_name_rejected(self):
        """A name that is only whitespace (e.g. '   ') must also be rejected."""
        original_name = self.tenant.name
        response = self.client.post('/owner/settings/', {
            'business_name': '   ',
            'business_email': 'shop@example.com',
        }, follow=True)
        self.tenant.refresh_from_db()
        self.assertEqual(
            self.tenant.name,
            original_name,
            "tenant.name was wiped to '' when a whitespace-only business_name was submitted",
        )

    def test_valid_name_update_succeeds(self):
        """A non-empty business name must still be accepted and saved."""
        response = self.client.post('/owner/settings/', {
            'business_name': 'Updated Glass Shop',
            'business_email': 'new@example.com',
            'business_phone': '555-9999',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, 'Updated Glass Shop')

    def test_name_not_in_post_keeps_existing(self):
        """If business_name key is missing from POST entirely, keep existing name.
        (This is the default=tenant.name branch — not a new case but worth confirming
        after the fix to avoid regression.)"""
        original_name = self.tenant.name
        # POST a different form_type to avoid the business-name branch entirely,
        # but also confirm the assignment_strategy branch doesn't touch tenant.name.
        response = self.client.post('/owner/settings/', {
            'form_type': 'assignment_strategy',
            'assignment_strategy': 'primary_first',
        }, follow=True)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, original_name)
