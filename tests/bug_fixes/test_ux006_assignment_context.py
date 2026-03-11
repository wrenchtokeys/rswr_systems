"""
Regression tests for UX-006: Repair Assignment "Primary Tech First" default
is misleading for new accounts.

Root cause: The default assignment strategy is `primary_first`, but new accounts
have no primary techs set per customer. Repairs silently fall to the manual queue
with no explanation shown in the Settings UI.

Fix:
  - `owner_settings` view now includes `any_customer_has_primary_tech` in context.
  - Template shows a yellow warning banner when `primary_first` is selected but no
    customers have a primary tech assigned.
  - Template shows a grey italic hint when a non-primary_first strategy is selected
    (to explain what the option requires).
"""
import os
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def _make_tenant_with_owner(name, username, plan_slug='trial'):
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
        username, f'{username}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name, slug=username, subdomain=username, owner=user,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


# ---------------------------------------------------------------------------
# Context variable tests
# ---------------------------------------------------------------------------

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
