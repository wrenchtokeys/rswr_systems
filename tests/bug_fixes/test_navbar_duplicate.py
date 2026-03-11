"""
Regression tests for BUG-003 — Duplicate/overlapping sticky navbar on scroll.

Root cause:
  Two inner-page elements used `sticky top-0 z-10`, which conflicts with the
  main nav's `sticky top-0 z-50`. When scrolling, both tried to stick at
  top:0, making the inner bar slide behind/over the main nav — visually
  appearing as a "second navbar".

  Affected elements:
  - repair_detail.html: "Quick Actions Bar"
  - owner_invoices.html: batch action bar (#batch-bar)

Fix:
  Changed `top-0` → `top-16` (64px = h-16, the main nav's height) on both
  inner sticky bars. They now dock below the nav instead of overlapping it.

After this fix:
  - The Quick Actions Bar in repair_detail.html sticks at top-16
  - The batch bar in owner_invoices.html sticks at top-16
  - The main nav remains the only element sticking at top-0
"""
import os
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from decimal import Decimal

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'templates',
)


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
