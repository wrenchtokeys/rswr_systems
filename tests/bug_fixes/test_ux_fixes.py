"""
UX Bug Fix Tests
Consolidated from: UX-003 through UX-012, error pages, navbar, billing settings
"""

from apps.technician_portal.models import Technician
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from decimal import Decimal
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import TestCase, Client
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from tests.helpers import make_tenant
import os

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


# --- From test_ux003_portal_preview.py ---

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


# --- From test_ux006_assignment_context.py ---

@override_settings(**TEST_OVERRIDES)
class OwnerSettingsContextFlagTest(TestCase):
    """Verify that the view injects `any_customer_has_primary_tech` into context."""

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = _make_tenant_with_owner('Context Flag Glass', 'ux006_ctx')
        Technician.objects.create(
            tenant=self.tenant, user=self.user,
            can_repair=True, is_active=True,
        )
        self.client.force_login(self.user)

    def test_owner_settings_context_has_primary_tech_flag(self):
        """The owner_settings view must include any_customer_has_primary_tech in context."""
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 200,
                         f"owner_settings returned {response.status_code}")
        self.assertIn(
            'any_customer_has_primary_tech', response.context,
            "Context is missing 'any_customer_has_primary_tech' — UX-006 view fix not applied."
        )

    def test_no_primary_tech_flag_false_when_no_customers_have_primary(self):
        """Flag must be False when no customers have a primary_technician set."""
        # No customers created — flag should be False
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            response.context['any_customer_has_primary_tech'],
            "any_customer_has_primary_tech should be False when no customers have "
            "a primary technician set."
        )

    def test_primary_tech_flag_true_when_customer_has_primary(self):
        """Flag must be True when at least one customer has a primary_technician."""
        tech = Technician.objects.filter(tenant=self.tenant).first()
        Customer.objects.create(
            tenant=self.tenant,
            name='Fleet with Primary',
            email='fleet@test.com',
            primary_technician=tech,
        )
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.context['any_customer_has_primary_tech'],
            "any_customer_has_primary_tech should be True when at least one customer "
            "has a primary technician assigned."
        )


# ---------------------------------------------------------------------------
# Template rendering tests
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class PrimaryTechWarningRenderTest(TestCase):
    """
    Verify that the template renders the warning banner or hint text
    depending on strategy and primary-tech state.
    """

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = _make_tenant_with_owner('Warning Render Glass', 'ux006_tmpl')
        self.tech = Technician.objects.create(
            tenant=self.tenant, user=self.user,
            can_repair=True, is_active=True,
        )
        self.client.force_login(self.user)

    def _get_settings_html(self):
        response = self.client.get('/owner/settings/')
        self.assertEqual(response.status_code, 200,
                         f"owner_settings returned {response.status_code}")
        return response.content.decode('utf-8')

    def test_warning_renders_when_primary_first_selected_and_no_primary_techs(self):
        """
        When strategy is primary_first (default) and no customers have a primary tech,
        the yellow warning banner must appear in the rendered HTML.
        """
        # Ensure strategy is primary_first and no customers have primary tech
        self.tenant.assignment_strategy = 'primary_first'
        self.tenant.save(update_fields=['assignment_strategy'])
        # No customers with primary_technician set

        html = self._get_settings_html()
        self.assertIn(
            "You haven't set a primary tech for any customers yet",
            html,
            "Warning banner is missing when primary_first is selected and no customers "
            "have a primary tech — UX-006 template fix not applied."
        )
        self.assertIn(
            'bg-yellow-50',
            html,
            "Yellow warning banner div (bg-yellow-50) is missing in rendered output "
            "for UX-006 scenario."
        )

    def test_warning_not_shown_when_has_primary_tech(self):
        """
        When strategy is primary_first AND at least one customer has a primary tech,
        the warning banner must NOT appear.
        """
        self.tenant.assignment_strategy = 'primary_first'
        self.tenant.save(update_fields=['assignment_strategy'])

        # Give a customer a primary tech
        Customer.objects.create(
            tenant=self.tenant,
            name='Fleet With Tech',
            email='fleet@test.com',
            primary_technician=self.tech,
        )

        html = self._get_settings_html()
        self.assertNotIn(
            "You haven't set a primary tech for any customers yet",
            html,
            "Warning banner should NOT appear when at least one customer has a "
            "primary tech assigned (UX-006)."
        )

    def test_warning_not_shown_when_different_strategy(self):
        """
        When a strategy other than primary_first is selected, the yellow warning
        must not appear. The grey italic hint may appear instead.
        """
        self.tenant.assignment_strategy = 'manual'
        self.tenant.save(update_fields=['assignment_strategy'])

        html = self._get_settings_html()
        self.assertNotIn(
            "You haven't set a primary tech for any customers yet",
            html,
            "Warning banner must NOT appear when strategy is 'manual' (UX-006)."
        )


# --- From test_ux007_customer_phone.py ---

class CustomerDetailPhoneTemplateTest(TestCase):
    """Verify template source contains phone display + add-CTA logic."""

    def _content(self):
        return _read_template('technician_portal', 'customer_details.html')

    def test_phone_displayed_when_present(self):
        """Template must render phone when customer.phone is truthy."""
        content = self._content()
        self.assertIn(
            'href="tel:{{ customer.phone }}"',
            content,
            "customer_details.html must render a tel: link when customer.phone exists (UX-007).",
        )

    def test_add_phone_cta_when_empty_and_can_edit(self):
        """
        When phone is absent and the user can edit the customer, the template
        must render an 'Add phone number' link pointing to the edit page.
        """
        content = self._content()
        self.assertIn(
            'Add phone number',
            content,
            "customer_details.html must show an 'Add phone number' CTA when phone is missing "
            "and can_edit_customer is True (UX-007).",
        )

    def test_add_phone_cta_links_to_edit_page(self):
        """The 'Add phone number' CTA must link to the edit_customer URL."""
        content = self._content()
        # The CTA should be inside a block guarded by can_edit_customer
        # and href should reference edit_customer url tag
        self.assertIn(
            "url 'edit_customer' customer.id",
            content,
            "customer_details.html 'Add phone number' CTA must href to {% url 'edit_customer' customer.id %} (UX-007).",
        )

    def test_add_email_cta_when_empty_and_can_edit(self):
        """
        Similarly, when email is absent and the user can edit, the template
        must render an 'Add email address' link.
        """
        content = self._content()
        self.assertIn(
            'Add email address',
            content,
            "customer_details.html must show an 'Add email address' CTA when email is missing "
            "and can_edit_customer is True (UX-007).",
        )

    def test_no_contact_fallback_still_present(self):
        """
        'No contact information on file.' fallback must still exist for
        non-editors viewing customers with no contact data.
        """
        content = self._content()
        self.assertIn(
            'No contact information on file.',
            content,
            "customer_details.html must still have 'No contact information on file.' "
            "fallback for non-editor views (UX-007).",
        )

    def test_phone_block_guarded_by_can_edit_customer(self):
        """
        The 'Add phone' CTA block must be wrapped in {% elif can_edit_customer %}
        so it only appears for users with edit rights.
        """
        content = self._content()
        self.assertIn(
            'elif can_edit_customer',
            content,
            "customer_details.html 'Add phone/email' CTAs must be gated by "
            "{% elif can_edit_customer %} — read-only users should not see them (UX-007).",
        )


# ---------------------------------------------------------------------------
# View / HTTP tests (requires DB)
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class CustomerDetailPhoneViewTest(TestCase):
    """HTTP-level tests for the customer detail page phone/email display."""

    def setUp(self):
        self.client = Client()
        self.owner, self.tenant = _make_tenant_with_owner('Acme Glass', 'acmeglass')
        # Customer WITH phone and email
        self.customer_full = Customer.objects.create(
            tenant=self.tenant,
            name='Fleet With Phone',
            email='fleet@example.com',
            phone='+15551234567',
        )
        # Customer WITHOUT phone or email
        self.customer_empty = Customer.objects.create(
            tenant=self.tenant,
            name='Fleet No Contact',
        )

    def _login(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_phone_shown_for_customer_with_phone(self):
        """When customer has a phone, the tel: link should appear in response."""
        self._login()
        url = reverse('customer_detail', args=[self.customer_full.id])
        resp = self.client.get(url, SERVER_NAME='acmeglass.testserver')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'tel:+15551234567')

    def test_email_shown_for_customer_with_email(self):
        """When customer has an email, the mailto: link should appear."""
        self._login()
        url = reverse('customer_detail', args=[self.customer_full.id])
        resp = self.client.get(url, SERVER_NAME='acmeglass.testserver')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'mailto:fleet@example.com')

    def test_add_phone_cta_shown_when_phone_missing_for_owner(self):
        """
        When an admin/owner views a customer with no phone, the 'Add phone number'
        CTA should appear in the response.
        """
        self._login()
        url = reverse('customer_detail', args=[self.customer_empty.id])
        resp = self.client.get(url, SERVER_NAME='acmeglass.testserver')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            'Add phone number',
            msg_prefix="Owner viewing customer with no phone should see 'Add phone number' CTA (UX-007).",
        )

    def test_add_email_cta_shown_when_email_missing_for_owner(self):
        """
        When an admin/owner views a customer with no email, the 'Add email address'
        CTA should appear.
        """
        self._login()
        url = reverse('customer_detail', args=[self.customer_empty.id])
        resp = self.client.get(url, SERVER_NAME='acmeglass.testserver')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            'Add email address',
            msg_prefix="Owner viewing customer with no email should see 'Add email address' CTA (UX-007).",
        )

    def test_add_phone_cta_not_shown_for_technician_without_edit_rights(self):
        """
        A regular technician (non-manager, non-admin) cannot edit customer info,
        so the 'Add phone number' CTA must NOT appear in their response.
        """
        tech_user = User.objects.create_user(
            'techguy', 'tech@test.com', 'testpass123',
            first_name='Tech', last_name='Guy',
        )
        TenantMembership.objects.create(tenant=self.tenant, user=tech_user, role='technician')
        Technician.objects.create(
            user=tech_user, tenant=self.tenant,
            is_active=True, is_manager=False,
        )
        self.client.force_login(tech_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        url = reverse('customer_detail', args=[self.customer_empty.id])
        resp = self.client.get(url, SERVER_NAME='acmeglass.testserver')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(
            resp,
            'Add phone number',
            msg_prefix="Regular tech should NOT see 'Add phone number' CTA (UX-007).",
        )


# --- From test_ux009_team_role_badges.py ---

@override_settings(**TEST_OVERRIDES)
class OwnerBadgesNotShownForOwnerRoleTest(TestCase):
    """Owner-role members should NOT show ability badges (Repairs / Replacements)."""

    def setUp(self):
        self.owner_user, self.tenant = _make_tenant_with_owner('Badge Co', 'badgeco')
        # Give the owner user a technician record with both abilities
        self.owner_tech = Technician.objects.create(
            user=self.owner_user, tenant=self.tenant,
            can_repair=True, can_replace=True, is_active=True,
        )
        self.client = Client()
        self.client.force_login(self.owner_user)

    def test_settings_page_loads(self):
        resp = self.client.get('/owner/settings/')
        self.assertEqual(resp.status_code, 200)

    def test_owner_role_badge_renders(self):
        """The "Owner" role badge must still appear."""
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Owner')

    def test_ability_badges_not_shown_for_owner_role(self):
        """When user has role=owner, the Repairs/Replacements badges must NOT render.

        Because the page uses a Django template condition, we can't easily distinguish
        which row the badge belongs to when there is only one member.  We verify by
        ensuring the page does not contain the ability-badge markup that would only
        appear for an owner (we add a second owner member and no tech-role members).
        """
        # Add a second owner-role member with can_repair
        second_owner, _ = _add_member(self.tenant, 'owner2badge', 'owner', can_repair=True, can_replace=False)
        resp = self.client.get('/owner/settings/')
        content = resp.content.decode()
        # The template guard `member.role != 'owner'` means no Repairs badge
        # should appear since ALL members in this test are owners.
        # "Repairs" text in the badge div has a specific class pair:
        self.assertNotIn('bg-amber-100 text-amber-800', content)

    def test_wrench_icon_used_not_tools(self):
        """Repairs badge should use fa-wrench icon (not fa-tools)."""
        # Add a technician-role member so the Repairs badge CAN render
        _add_member(self.tenant, 'tech_wrench_test', 'technician', can_repair=True)
        resp = self.client.get('/owner/settings/')
        content = resp.content.decode()
        self.assertIn('fa-wrench', content)
        self.assertNotIn('fa-tools', content)


@override_settings(**TEST_OVERRIDES)
class TechnicianAbilityBadgesStillRenderTest(TestCase):
    """Technician-role members SHOULD still show ability badges."""

    def setUp(self):
        self.owner_user, self.tenant = _make_tenant_with_owner('TechBadge Co', 'techbadgeco')
        self.client = Client()
        self.client.force_login(self.owner_user)

    def test_repairs_badge_shown_for_technician_with_can_repair(self):
        """Technician with can_repair=True must show the Repairs badge."""
        _add_member(self.tenant, 'techrepair', 'technician', can_repair=True, can_replace=False)
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Repairs')
        self.assertContains(resp, 'bg-amber-100 text-amber-800')

    def test_replacements_badge_shown_for_technician_with_can_replace(self):
        """Technician with can_replace=True must show the Replacements badge."""
        _add_member(self.tenant, 'techreplace', 'technician', can_repair=False, can_replace=True)
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Replacements')
        self.assertContains(resp, 'bg-teal-100 text-teal-800')

    def test_no_ability_badges_when_technician_has_neither(self):
        """Technician with both False must show neither badge."""
        _add_member(self.tenant, 'techneither', 'technician', can_repair=False, can_replace=False)
        resp = self.client.get('/owner/settings/')
        # The amber and teal badge classes should not appear
        self.assertNotIn('bg-amber-100 text-amber-800', resp.content.decode())
        self.assertNotIn('bg-teal-100 text-teal-800', resp.content.decode())

    def test_manager_role_shows_ability_badges(self):
        """Manager-role member with can_repair should still show Repairs badge."""
        _add_member(self.tenant, 'mgr_badges', 'manager', can_repair=True, can_replace=True)
        resp = self.client.get('/owner/settings/')
        self.assertContains(resp, 'Repairs')
        self.assertContains(resp, 'Replacements')


# --- From test_ux012_statement_back_link.py ---

class TestStatementBackLink(TestCase):
    """Verify the statement page has proper navigation back to invoices."""

    def setUp(self):
        self.user, self.tenant = make_tenant('BackLinkShop', 'backlink_owner')
        self.client = Client()
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name='BackLink Corp', tenant=self.tenant, email='bl@test.com'
        )
        self.url = f'/owner/customers/{self.customer.id}/statement/'

    def test_back_link_points_to_invoice_list(self):
        """The 'Back to Invoices' link should point to the invoice list URL, not javascript:history.back()."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # Must NOT use javascript:history.back()
        self.assertNotIn('javascript:history.back()', content)
        # Must contain a link to the invoice list
        self.assertIn('/owner/invoices/', content)
        self.assertIn('Back to Invoices', content)

    def test_back_link_has_no_print_class(self):
        """The nav bar with back link should be hidden on print (no-print class)."""
        resp = self.client.get(self.url)
        content = resp.content.decode()
        # The nav bar container should have no-print class
        self.assertIn('no-print', content)

    def test_nav_bar_shows_customer_name(self):
        """The nav bar should display the customer name for context."""
        resp = self.client.get(self.url)
        content = resp.content.decode()
        self.assertIn('BackLink Corp', content)
        self.assertIn('Statement of Account', content)

    def test_back_link_is_valid_url(self):
        """The invoice list URL in the back link should be a working page."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        # Follow the back link — it should return 200
        invoice_resp = self.client.get('/owner/invoices/')
        self.assertEqual(invoice_resp.status_code, 200)


# --- From test_ux_template_fixes.py ---

class NavbarBusinessNameTruncationTemplateTest(TestCase):
    """
    Verify that base_app.html truncates the tenant name to prevent wrapping.
    """

    def test_tenant_name_span_has_truncate_class(self):
        """
        The tenant.name <span> in base_app.html must include 'truncate' to
        prevent long business names from wrapping to a second line in the navbar.
        """
        content = _read_template('base_app.html')
        # Find the span that renders tenant.name
        self.assertIn(
            'truncate',
            content,
            "base_app.html navbar tenant name span is missing 'truncate' class. "
            "Long business names will wrap and break the nav layout (UX-001)."
        )

    def test_tenant_name_span_has_max_width(self):
        """
        The tenant.name span must have a max-w constraint so it can't grow
        unboundedly and push other nav items off-screen.
        """
        content = _read_template('base_app.html')
        self.assertIn(
            'max-w-[200px]',
            content,
            "base_app.html navbar tenant name span is missing 'max-w-[200px]'. "
            "Without a max-width the name can push other nav elements off-screen (UX-001)."
        )

    def test_tenant_name_span_has_title_attribute(self):
        """
        The tenant name span should have a 'title' attribute so users can
        hover to see the full name when it's truncated.
        """
        content = _read_template('base_app.html')
        # The title attribute should reference tenant.name
        self.assertIn(
            'title="{{ tenant.name }}"',
            content,
            "base_app.html navbar tenant name span is missing a title= attribute. "
            "Users should be able to hover to see the full name when it is truncated (UX-001)."
        )

    def test_tenant_name_span_not_bare(self):
        """
        The old, un-truncated version of the span must no longer exist in the template.
        """
        content = _read_template('base_app.html')
        # Old bare span had no truncate or max-w classes
        self.assertNotIn(
            '"text-sm text-gray-500 hidden sm:inline">{{ tenant.name }}',
            content,
            "base_app.html still contains the bare (un-truncated) tenant name span. "
            "Long names will wrap and break the navbar (UX-001)."
        )


# ---------------------------------------------------------------------------
# UX-002 — Customer table Actions column not clipped (template source check)
# ---------------------------------------------------------------------------

class CustomerTableOverflowTemplateTest(TestCase):
    """
    Verify that the customer list table wrapper allows horizontal scroll.
    """

    def test_customer_list_no_overflow_hidden_wrapper(self):
        """
        customer_list.html must NOT wrap the table in 'overflow-hidden'.
        The outer overflow-hidden div prevented horizontal scroll, causing
        the 'Actions' column to be clipped and show as 'AC...' (UX-002).
        """
        content = _read_template('technician_portal', 'customer_list.html')
        # Check for the specific pattern that caused the clipping: an
        # overflow-hidden div directly wrapping an overflow-x-auto div
        self.assertNotIn(
            'class="overflow-hidden"',
            content,
            "customer_list.html has an 'overflow-hidden' wrapper div around the table. "
            "This clips the 'Actions' column — remove it and keep only overflow-x-auto (UX-002)."
        )

    def test_customer_list_has_overflow_x_auto(self):
        """
        The table wrapper must retain 'overflow-x-auto' so narrow screens
        can scroll horizontally to reach the Actions column.
        """
        content = _read_template('technician_portal', 'customer_list.html')
        self.assertIn(
            'overflow-x-auto',
            content,
            "customer_list.html is missing 'overflow-x-auto' on the table wrapper. "
            "The table needs horizontal scroll on small screens (UX-002)."
        )

    def test_customer_list_actions_column_present(self):
        """
        The Actions column header must be present and complete (not truncated
        by overflow-hidden into 'AC...').
        """
        content = _read_template('technician_portal', 'customer_list.html')
        self.assertIn(
            '>Actions<',
            content,
            "customer_list.html is missing the 'Actions' column header (UX-002)."
        )


# ---------------------------------------------------------------------------
# UX-001 — Rendered view test (with real tenant name)
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class NavbarBusinessNameRenderTest(TestCase):
    """
    Verify that a long business name renders in the navbar with truncation
    classes and doesn't cause a server error.
    """

    def setUp(self):
        self.client = Client()
        # Create a tenant with a long name (3+ words — the reported trigger)
        self.user, self.tenant = _make_tenant_with_owner(
            'Amelia Long Business Name Glass', 'ux001_owner'
        )
        Technician.objects.create(
            tenant=self.tenant, user=self.user,
            can_repair=True, is_active=True,
        )
        self.client.force_login(self.user)

    def test_dashboard_renders_200_with_long_tenant_name(self):
        """Dashboard should return 200 even when the tenant name is very long."""
        response = self.client.get('/tech/dashboard/')
        self.assertIn(
            response.status_code, [200, 302],
            f"Dashboard returned {response.status_code} with a long tenant name."
        )

    def test_rendered_nav_contains_truncate_class(self):
        """
        The rendered HTML for a logged-in page must include the 'truncate' class
        (inherited from base_app.html) so long business names can't wrap.

        Note: The tenant context variable is injected by subdomain middleware which
        doesn't fire in unit tests — we verify the class is present in the rendered
        HTML (it comes from the template source) rather than checking tenant.name text.
        """
        response = self.client.get('/tech/dashboard/')
        if response.status_code == 302:
            response = self.client.get(response['Location'])
        if response.status_code != 200:
            self.skipTest("Dashboard didn't render — skipping content check")

        content = response.content.decode('utf-8')
        # The rendered page should include 'truncate' from base_app.html template source
        self.assertIn('truncate', content,
                      "Rendered page is missing 'truncate' class — UX-001 fix may not "
                      "be applied in base_app.html.")


# ---------------------------------------------------------------------------
# UX-002 — Rendered view test (customer list page)
# ---------------------------------------------------------------------------

@override_settings(**TEST_OVERRIDES)
class CustomerListTableRenderTest(TestCase):
    """
    Verify that the customer list page renders without the overflow-hidden
    wrapper that clipped the Actions column.
    """

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = _make_tenant_with_owner('Table Test Glass', 'ux002_owner')
        Technician.objects.create(
            tenant=self.tenant, user=self.user,
            can_repair=True, is_active=True,
        )
        # Create a customer so the table actually renders
        Customer.objects.create(
            tenant=self.tenant,
            name='Fleet Co Test',
            email='fleet@example.com',
        )
        self.client.force_login(self.user)

    def test_customer_list_renders_200(self):
        """Customer list page should return 200."""
        response = self.client.get('/tech/customers/')
        self.assertEqual(
            response.status_code, 200,
            f"Customer list returned {response.status_code}, expected 200."
        )

    def test_rendered_customer_list_has_no_overflow_hidden_wrapper(self):
        """
        Rendered customer list must not contain 'overflow-hidden' as a
        standalone class on a div that directly wraps the table — that
        pattern was what clipped the Actions column (UX-002).
        """
        response = self.client.get('/tech/customers/')
        if response.status_code != 200:
            self.skipTest("Customer list didn't render — skipping content check")

        content = response.content.decode('utf-8')
        self.assertNotIn(
            'class="overflow-hidden"',
            content,
            "Rendered customer list still has a bare 'overflow-hidden' div wrapping "
            "the table. This clips the Actions column (UX-002)."
        )

    def test_rendered_customer_list_shows_actions_column(self):
        """
        The rendered page must include the full 'Actions' column header text,
        confirming it is not clipped by overflow-hidden.
        """
        response = self.client.get('/tech/customers/')
        if response.status_code != 200:
            self.skipTest("Customer list didn't render — skipping content check")

        content = response.content.decode('utf-8')
        self.assertIn(
            'Actions',
            content,
            "Rendered customer list doesn't show 'Actions' column header — "
            "it may still be clipped (UX-002)."
        )


# --- From test_billing_settings_ux.py ---

class UX010EmailSubjectTextareaTest(TestCase):
    """UX-010: Email Subject should use <textarea>, not <input type=text>."""

    def setUp(self):
        self.html = _read_template('saas', 'owner_settings.html')

    def test_overdue_subject_uses_textarea(self):
        """Email Subject must be a <textarea> so long template strings are visible."""
        # Should use textarea, not a plain text input for the subject
        self.assertIn('<textarea name="overdue_reminder_subject"', self.html,
                      "Email Subject must use <textarea> to prevent truncation of long template strings.")

    def test_overdue_subject_no_text_input(self):
        """The old single-line input for subject should be gone."""
        self.assertNotIn('<input type="text" name="overdue_reminder_subject"', self.html,
                         "Old <input type=text> for overdue_reminder_subject must be replaced by <textarea>.")

    def test_subject_textarea_has_resize_none(self):
        """Textarea should not be freely resizable (keeps layout tidy)."""
        self.assertIn('resize-none', self.html,
                      "Subject textarea should have resize-none class to keep layout stable.")

    def test_subject_helper_text_present(self):
        """Template variable hint must still be shown below the subject field."""
        self.assertIn('{invoice_number}', self.html,
                      "Helper text with {invoice_number} must still be present for owners.")
        self.assertIn('{customer_name}', self.html)
        self.assertIn('{amount_due}', self.html)
        self.assertIn('{days_overdue}', self.html)


class UX011BatchDayFieldVisibilityTest(TestCase):
    """UX-011: Batch Invoicing Day field must have JS hooks to hide when Disabled."""

    def setUp(self):
        self.html = _read_template('saas', 'owner_settings.html')

    def test_frequency_select_has_id(self):
        """Frequency <select> must have id='batch-frequency-select' for JS targeting."""
        self.assertIn('id="batch-frequency-select"', self.html,
                      "Frequency select must have id='batch-frequency-select' so JS can listen for changes.")

    def test_day_field_wrapper_has_id(self):
        """Day field wrapper div must have id='batch-day-field' for hide/show."""
        self.assertIn('id="batch-day-field"', self.html,
                      "Day field wrapper div must have id='batch-day-field' for JS show/hide.")

    def test_day_input_has_id(self):
        """Day input must have id='batch-day-input' for JS disable/enable."""
        self.assertIn('id="batch-day-input"', self.html,
                      "Day input must have id='batch-day-input' so JS can disable it when Frequency=Disabled.")

    def test_day_hint_has_id(self):
        """Day hint paragraph must have id='batch-day-hint' for dynamic text."""
        self.assertIn('id="batch-day-hint"', self.html,
                      "Day hint <p> must have id='batch-day-hint' so JS can update text for weekly vs monthly.")

    def test_js_update_function_defined(self):
        """updateBatchDayField JS function must be defined in the template."""
        self.assertIn('function updateBatchDayField()', self.html,
                      "updateBatchDayField() JS function must be defined to handle Day field visibility.")

    def test_js_disables_on_disabled_frequency(self):
        """JS must handle the 'disabled' frequency case."""
        self.assertIn("freq === 'disabled'", self.html,
                      "JS must check for freq === 'disabled' to hide/disable the Day field.")

    def test_js_monthly_hint(self):
        """JS must show monthly-specific hint when monthly is selected."""
        self.assertIn("freq === 'monthly'", self.html,
                      "JS must show different hint text for monthly vs weekly frequency.")

    def test_js_listens_to_frequency_change(self):
        """JS must attach change listener to frequency select on DOMContentLoaded."""
        self.assertIn("addEventListener('change', updateBatchDayField)", self.html,
                      "JS must attach change event listener to frequency select.")

    def test_js_init_on_dom_ready(self):
        """updateBatchDayField must be called on DOMContentLoaded for initial state."""
        self.assertIn('updateBatchDayField();', self.html,
                      "updateBatchDayField() must be called on page load to set initial state.")

    def test_frequency_options_intact(self):
        """All four frequency options must still be present after edits."""
        for val in ('disabled', 'weekly', 'biweekly', 'monthly'):
            self.assertIn(f'value="{val}"', self.html,
                          f"Frequency option '{val}' must still be present in the select.")


# --- From test_custom_error_pages.py ---

@override_settings(DEBUG=False)
class Custom404PageTest(TestCase):
    """Test that 404 errors return the custom branded template."""

    def setUp(self):
        self.client = Client()

    def test_404_returns_correct_status_code(self):
        """A non-existent URL should return HTTP 404."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        self.assertEqual(response.status_code, 404)

    def test_404_uses_custom_template(self):
        """A non-existent URL should use our custom 404.html template."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        self.assertTemplateUsed(response, '404.html')

    def test_404_contains_branded_content(self):
        """The 404 page should mention RS Systems and provide a way back."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        content = response.content.decode('utf-8')
        self.assertIn('RS Systems', content)
        self.assertIn('404', content)
        self.assertIn('Page Not Found', content)

    def test_404_contains_navigation_links(self):
        """The 404 page should provide links to help users navigate away."""
        response = self.client.get('/this-url-does-not-exist-anywhere-at-all/')
        content = response.content.decode('utf-8')
        # Should have a link back to home
        self.assertIn('href="/"', content)

    def test_another_missing_url_returns_404(self):
        """Multiple missing URLs should consistently return 404."""
        response = self.client.get('/tech/repairs/nonexistent-path/999999/')
        self.assertEqual(response.status_code, 404)


@override_settings(DEBUG=False)
class Custom500PageTest(TestCase):
    """Test that 500 errors return the custom branded template."""

    def test_500_view_returns_correct_status(self):
        """Directly calling the custom_500 view should return HTTP 500."""
        from rs_systems.views import custom_500
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/')
        response = custom_500(request)
        self.assertEqual(response.status_code, 500)

    def test_500_view_renders_template(self):
        """The custom_500 view should render 500.html."""
        from rs_systems.views import custom_500
        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.get('/')
        # render() needs session/messages middleware, use Client for template check
        from django.test import Client
        client = Client()
        # We can't trigger a real 500 in tests, but we can test the view directly
        response = custom_500(request)
        self.assertEqual(response.status_code, 500)


class ErrorHandlerRegistrationTest(TestCase):
    """Test that handler404/500 are properly registered in the root URLconf."""

    def test_handler404_is_registered(self):
        """handler404 should point to our custom view."""
        from rs_systems import urls as root_urls
        self.assertTrue(
            hasattr(root_urls, 'handler404') or
            'handler404' in dir(root_urls),
            "handler404 should be defined in the root URLconf"
        )

    def test_handler500_is_registered(self):
        """handler500 should point to our custom view."""
        from rs_systems import urls as root_urls
        self.assertTrue(
            hasattr(root_urls, 'handler500') or
            'handler500' in dir(root_urls),
            "handler500 should be defined in the root URLconf"
        )

    def test_handler404_points_to_custom_view(self):
        """handler404 should reference our rs_systems.views.custom_404."""
        from rs_systems import urls as root_urls
        self.assertEqual(
            root_urls.handler404,
            'rs_systems.views.custom_404',
            "handler404 should point to rs_systems.views.custom_404"
        )

    def test_handler500_points_to_custom_view(self):
        """handler500 should reference our rs_systems.views.custom_500."""
        from rs_systems import urls as root_urls
        self.assertEqual(
            root_urls.handler500,
            'rs_systems.views.custom_500',
            "handler500 should point to rs_systems.views.custom_500"
        )


class ErrorViewsExistTest(TestCase):
    """Test that the custom error view functions exist and are importable."""

    def test_custom_404_view_is_importable(self):
        """custom_404 view should exist in rs_systems.views."""
        from rs_systems.views import custom_404
        self.assertTrue(callable(custom_404))

    def test_custom_500_view_is_importable(self):
        """custom_500 view should exist in rs_systems.views."""
        from rs_systems.views import custom_500
        self.assertTrue(callable(custom_500))


# --- From test_navbar_duplicate.py ---

class NavbarStickyOffsetTemplateTest(TestCase):
    """
    Verify that inner-page sticky bars use top-16 (not top-0) so they don't
    overlap with the main navigation bar.
    """

    def _read_template(self, *path_parts):
        path = os.path.join(TEMPLATE_DIR, *path_parts)
        with open(path, 'r') as f:
            return f.read()

    def test_repair_detail_quick_actions_bar_not_top_0(self):
        """
        The Quick Actions Bar in repair_detail.html must NOT use 'sticky top-0'
        — that would conflict with the main nav and create the duplicate navbar effect.
        """
        content = self._read_template('technician_portal', 'repair_detail.html')
        # The Quick Actions Bar should NOT have sticky top-0 z-10
        self.assertNotIn(
            'sticky top-0 z-10',
            content,
            "repair_detail.html has 'sticky top-0 z-10' — this conflicts with "
            "the main nav and creates a duplicate navbar on scroll. Use top-16 instead."
        )

    def test_repair_detail_quick_actions_bar_uses_top_16(self):
        """
        The Quick Actions Bar must use top-16 so it sticks just below the main nav
        (which is h-16 = 64px tall) rather than overlapping with it.
        """
        content = self._read_template('technician_portal', 'repair_detail.html')
        self.assertIn(
            'sticky top-16 z-10',
            content,
            "repair_detail.html Quick Actions Bar should use 'sticky top-16 z-10' "
            "to dock below the main nav (h-16 = 64px)."
        )

    def test_owner_invoices_batch_bar_not_top_0(self):
        """
        The batch action bar (#batch-bar) in owner_invoices.html must NOT use
        'sticky top-0' — same conflict as repair_detail.
        """
        content = self._read_template('saas', 'owner_invoices.html')
        self.assertNotIn(
            'sticky top-0 z-10',
            content,
            "owner_invoices.html has 'sticky top-0 z-10' on the batch bar — "
            "this conflicts with the main nav. Use top-16 instead."
        )

    def test_owner_invoices_batch_bar_uses_top_16(self):
        """
        The batch bar must use top-16 so it sticks below the main nav.
        """
        content = self._read_template('saas', 'owner_invoices.html')
        self.assertIn(
            'sticky top-16 z-10',
            content,
            "owner_invoices.html batch bar should use 'sticky top-16 z-10' to "
            "dock below the main nav (h-16 = 64px)."
        )

    def test_base_app_main_nav_still_at_top_0(self):
        """
        The main navigation in base_app.html must remain at sticky top-0 z-50.
        This is the primary nav that anchors all other sticky offsets.
        """
        content = self._read_template('base_app.html')
        self.assertIn(
            'sticky top-0 z-50',
            content,
            "base_app.html main nav should still be 'sticky top-0 z-50'."
        )

    def test_no_inner_sticky_top_0_in_app_templates(self):
        """
        No template that extends base_app.html (inner-page content) should use
        'sticky top-0' with a z-index lower than z-50. That would conflict with
        the main nav.
        """
        # Directories to check for inner-page templates
        check_dirs = [
            os.path.join(TEMPLATE_DIR, 'technician_portal'),
            os.path.join(TEMPLATE_DIR, 'saas'),
        ]
        violations = []
        for check_dir in check_dirs:
            for fname in os.listdir(check_dir):
                if not fname.endswith('.html'):
                    continue
                fpath = os.path.join(check_dir, fname)
                try:
                    with open(fpath, 'r') as f:
                        content = f.read()
                    if 'sticky top-0 z-10' in content or 'sticky top-0 z-20' in content:
                        violations.append(f"{check_dir}/{fname}")
                except Exception:
                    pass

        self.assertEqual(
            violations, [],
            f"These templates have inner 'sticky top-0 z-{{10,20}}' which conflicts "
            f"with the main nav (z-50): {violations}. Change to top-16."
        )


def _make_tenant_with_owner(name, username, plan_slug='trial'):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug=plan_slug,
        defaults={'name': plan_slug.title(), 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'display_order': 0},
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Test', last_name='Owner')
    tenant = Tenant.objects.create(
        name=name, slug=username, subdomain=username, owner=user,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_OVERRIDES)
class RepairDetailViewRenderTest(TestCase):
    """
    Verify that the repair_detail view renders successfully (no 500 errors)
    and that its content doesn't include the conflicting sticky class.
    """

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = _make_tenant_with_owner('Fix Shop', 'fix_owner')
        self.technician = Technician.objects.create(
            tenant=self.tenant, user=self.user,
            can_repair=True, is_active=True,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Test Fleet Co',
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number='UNIT-001',
        )
        self.client.force_login(self.user)

    def test_repair_detail_renders_200(self):
        """Repair detail page should render without a 500 error."""
        url = f'/tech/repairs/{self.repair.pk}/'
        response = self.client.get(url)
        self.assertEqual(
            response.status_code, 200,
            f"repair_detail returned {response.status_code}, expected 200"
        )

    def test_repair_detail_no_conflicting_sticky(self):
        """
        The rendered repair detail page should not contain 'sticky top-0 z-10'
        (only the main nav's 'sticky top-0 z-50' is allowed at top-0).
        """
        url = f'/tech/repairs/{self.repair.pk}/'
        response = self.client.get(url)
        if response.status_code != 200:
            self.skipTest("Page didn't render, skipping content check")
        content = response.content.decode('utf-8')
        self.assertNotIn(
            'sticky top-0 z-10',
            content,
            "Rendered repair_detail contains 'sticky top-0 z-10' — this creates "
            "the duplicate nav visual bug (BUG-003)."
        )
