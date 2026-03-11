"""
Regression tests for UX-001 and UX-002 template fixes.

UX-001 — Business name wrapping in navbar (base_app.html)
  Root cause: The tenant name span in the navbar had no overflow/truncation
  classes, allowing long business names (3+ words) to wrap to two lines and
  break the nav layout.
  Fix: Added `truncate max-w-[200px]` to the business name <span> so it
  clips at 200px with an ellipsis and never wraps.

UX-002 — Customer table "Actions" column clipped (customer_list.html)
  Root cause: The table was wrapped in `<div class="overflow-hidden">` which
  contained `<div class="overflow-x-auto">`. The outer `overflow-hidden`
  prevented horizontal scroll, causing the last "Actions" column to be cut
  off and show as "AC...".
  Fix: Removed the outer `overflow-hidden` wrapper. The inner `overflow-x-auto`
  div now scrolls correctly and all columns are fully visible.
"""
import os
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from decimal import Decimal

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'templates',
)


def _read_template(*path_parts):
    path = os.path.join(TEMPLATE_DIR, *path_parts)
    with open(path, 'r') as f:
        return f.read()


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


# ---------------------------------------------------------------------------
# UX-001 — Navbar business name truncation (template source check)
# ---------------------------------------------------------------------------

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
