"""
Regression tests for UX-007: Customer detail page missing phone number field.

UX-007 — Customer detail page missing phone number field
  Where: /tech/customers/<id>/
  What: Only email is shown in the contact info card. No phone number displayed
        even though phone is collected during customer creation.
  Root cause: The template conditionally rendered phone only when populated, but
              gave no indication or CTA to add it when missing. Admins/managers
              viewing a customer with no phone saw nothing — making it look like
              the field didn't exist at all.
  Fix: When `can_edit_customer` is True and phone (or email) is absent, render
       a faded "Add phone number" / "Add email address" link pointing to the
       customer edit page. When the contact info section is fully empty and the
       user CANNOT edit, show the "No contact information on file." fallback.
"""

import os
from decimal import Decimal
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

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
# Template source checks (fast, no DB required)
# ---------------------------------------------------------------------------

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
