"""
Regression tests for UX-003: Customer Portal link has no "what customers see" context.

Root cause: The Customer Portal section in Owner Settings only showed a shareable
link with a small gray helper text. Owners had no way to preview what customers
actually see when they visit the signup page.

Fix:
  - Added a "Preview" button (opens shop_join_url in a new tab) alongside Copy Link.
  - Expanded helper text to mention the Preview button's purpose.
  - `shop_join_url` is already in context — no view changes needed.
"""
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_tenant_with_owner(name, slug, plan_slug='trial'):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=plan_slug,
        defaults={
            'name': plan_slug.title(),
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        slug, f'{slug}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=user,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_OVERRIDES)
class PortalPreviewContextTest(TestCase):
    """Verify that owner_settings view includes shop_join_url in context."""

    def setUp(self):
        self.user, self.tenant = _make_tenant_with_owner('Preview Co', 'previewco')
        self.client = Client()
        self.client.force_login(self.user)

    def test_shop_join_url_in_context(self):
        """shop_join_url must be present in owner settings context."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('shop_join_url', resp.context)

    def test_shop_join_url_contains_tenant_slug(self):
        """shop_join_url should contain the tenant slug."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        shop_join_url = resp.context['shop_join_url']
        self.assertIn('previewco', shop_join_url)

    def test_shop_join_url_contains_join_path(self):
        """shop_join_url should reference the /join/ route."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        shop_join_url = resp.context['shop_join_url']
        self.assertIn('/join/', shop_join_url)


@override_settings(**TEST_OVERRIDES)
class PortalPreviewTemplateTest(TestCase):
    """Verify that the Customer Portal section renders the Preview button."""

    def setUp(self):
        self.user, self.tenant = _make_tenant_with_owner('Preview Test Shop', 'previewshop')
        self.client = Client()
        self.client.force_login(self.user)

    def test_preview_button_renders(self):
        """The 'Preview' button (with id=previewBtn) must appear in the settings page."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'previewBtn')

    def test_preview_button_links_to_join_url(self):
        """Preview button href must reference the shop's join URL."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        # The rendered page should contain a link to /join/<slug>/
        self.assertContains(resp, '/join/previewshop/')

    def test_preview_button_opens_new_tab(self):
        """Preview button should have target="_blank" to open in a new tab."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('target="_blank"', content)

    def test_copy_link_button_still_renders(self):
        """Copy Link button must still exist after adding the Preview button."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'copyBtn')
        self.assertContains(resp, 'Copy Link')

    def test_preview_helper_text_updated(self):
        """Helper text should mention 'Preview' to guide owners."""
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Preview')
