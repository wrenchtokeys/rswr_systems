"""
CODE-204: referral_leaderboard view raises TemplateDoesNotExist.

The `referral_leaderboard` view at /referrals/referral-leaderboard/ renders
`customer_portal/referrals/leaderboard.html`, but that template did not exist.
Any authenticated customer visiting the leaderboard page received a 500 error.

Fix: created the missing template.

This test verifies:
1. GET /referrals/referral-leaderboard/ returns HTTP 200 for an authenticated customer.
2. The empty-state renders correctly when there are no top referrers.
3. The ranked list renders correctly when top_referrers are present.
4. The view is login-protected (anonymous → redirect to login).
5. The leaderboard is tenant-scoped (cross-tenant referrers do not appear).
"""

import os
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import ReferralCode, Referral
from decimal import Decimal


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

_tenant_counter = 0


def _make_tenant(name):
    """Create a minimal active tenant."""
    global _tenant_counter
    _tenant_counter += 1
    slug = f'ldr-tenant-{_tenant_counter}'
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    owner = User.objects.create_user(
        username=f'ldr_owner_{_tenant_counter}',
        email=f'ldr_owner_{_tenant_counter}@example.com',
        password='testpass',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(
        tenant=tenant,
        user=owner,
        role='owner',
        is_active=True,
    )
    return tenant, owner


def _make_customer_user(tenant, username, email):
    """Create a CustomerUser scoped to a tenant."""
    user = User.objects.create_user(
        username=username,
        email=email,
        password='testpass',
    )
    customer = Customer.objects.create(
        name=f'{username} Company',
        email=email,
        tenant=tenant,
    )
    TenantMembership.objects.create(
        tenant=tenant,
        user=user,
        role='customer',
        is_active=True,
    )
    cu = CustomerUser.objects.create(
        user=user,
        customer=customer,
    )
    return user, cu


@override_settings(**TEST_OVERRIDES)
class LeaderboardTemplateExistsTest(TestCase):
    """Verify the leaderboard page loads without a TemplateDoesNotExist error."""

    def setUp(self):
        self.tenant, _ = _make_tenant('Leaderboard Test Shop')
        self.user, self.cu = _make_customer_user(
            self.tenant, 'ldr_main_user', 'ldr_main@example.com'
        )
        self.client = Client(HTTP_HOST='testserver')
        self.client.force_login(self.user)

    def _get(self):
        """GET the leaderboard URL with tenant context injected via session."""
        session = self.client.session
        session['tenant_id'] = self.tenant.pk
        session.save()
        return self.client.get(reverse('referral_leaderboard'))

    def test_leaderboard_returns_200_empty(self):
        """No referrals yet — empty state renders without 500."""
        response = self._get()
        self.assertEqual(
            response.status_code,
            200,
            f"Expected 200 but got {response.status_code}.",
        )

    def test_leaderboard_uses_correct_template(self):
        """The response uses leaderboard.html, not a fallback."""
        response = self._get()
        self.assertEqual(response.status_code, 200)
        template_names = [t.name for t in response.templates]
        self.assertIn(
            'customer_portal/referrals/leaderboard.html',
            template_names,
            f"Expected leaderboard.html in templates; found: {template_names}",
        )

    def test_leaderboard_redirects_anonymous_user(self):
        """Anonymous users must be redirected to login, not shown a 500."""
        anon_client = Client(HTTP_HOST='testserver')
        response = anon_client.get(reverse('referral_leaderboard'))
        # Should redirect (302) to login, not 500.
        self.assertIn(
            response.status_code,
            [301, 302],
            f"Expected redirect for anonymous user but got {response.status_code}",
        )

    def test_leaderboard_empty_state_content(self):
        """Empty state shows the 'no referrals yet' message."""
        response = self._get()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('No referrals yet', content)

    def test_leaderboard_context_top_referrers_empty(self):
        """Context variable top_referrers is an empty list when no one has referred."""
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertIn('top_referrers', response.context)
        self.assertEqual(len(response.context['top_referrers']), 0)

    def test_leaderboard_with_referrers_renders_correctly(self):
        """When referrers exist, the ranked list renders without errors."""
        _, referrer_cu = _make_customer_user(self.tenant, 'ldr_ref1', 'ref1_ldr@example.com')
        _, referred_cu = _make_customer_user(self.tenant, 'ldr_ref2', 'ref2_ldr@example.com')

        code = ReferralCode.objects.create(code='LDRTST1', customer_user=referrer_cu)
        Referral.objects.create(referral_code=code, customer_user=referred_cu)

        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertIn('top_referrers', response.context)
        top = response.context['top_referrers']
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]['count'], 1)
        # Page should NOT show the empty state.
        content = response.content.decode()
        self.assertNotIn('No referrals yet', content)

    def test_leaderboard_tenant_scoped(self):
        """Referrers from a different tenant must not appear in this tenant's leaderboard."""
        # Tenant A (self.tenant): referrer with 1 referral
        _, referrer_a = _make_customer_user(self.tenant, 'ldr_a1', 'a1_ldr@example.com')
        _, referred_a = _make_customer_user(self.tenant, 'ldr_a2', 'a2_ldr@example.com')
        code_a = ReferralCode.objects.create(code='LDRA001', customer_user=referrer_a)
        Referral.objects.create(referral_code=code_a, customer_user=referred_a)

        # Tenant B: referrer with 5 referrals — should NOT appear in Tenant A's board
        tenant_b, _ = _make_tenant('Leaderboard Test Shop B')
        _, referrer_b = _make_customer_user(tenant_b, 'ldr_b1', 'b1_ldr@example.com')
        code_b = ReferralCode.objects.create(code='LDRB001', customer_user=referrer_b)
        for i in range(5):
            _, referred_b_cu = _make_customer_user(
                tenant_b, f'ldr_b_ref_{i}', f'b_ref_{i}_ldr@example.com'
            )
            Referral.objects.create(referral_code=code_b, customer_user=referred_b_cu)

        response = self._get()
        self.assertEqual(response.status_code, 200)
        top = response.context['top_referrers']
        # Only Tenant A's referrer should appear.
        self.assertEqual(len(top), 1)
        emails = [e['user'].user.email for e in top]
        self.assertIn('a1_ldr@example.com', emails)
        self.assertNotIn('b1_ldr@example.com', emails)


@override_settings(**TEST_OVERRIDES)
class LeaderboardTemplateStructureTest(TestCase):
    """Validate the template file exists and has correct structure."""

    TEMPLATE_DIR = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'templates',
    )

    def _read_template(self, *path_parts):
        path = os.path.join(self.TEMPLATE_DIR, *path_parts)
        with open(path, 'r') as f:
            return f.read()

    def test_leaderboard_template_file_exists(self):
        """The template file must exist on disk."""
        path = os.path.join(
            self.TEMPLATE_DIR,
            'customer_portal', 'referrals', 'leaderboard.html',
        )
        self.assertTrue(
            os.path.exists(path),
            f"leaderboard.html template missing at {path}",
        )

    def test_leaderboard_template_extends_customer_base(self):
        """leaderboard.html must extend customer_portal/base_customer.html."""
        content = self._read_template('customer_portal', 'referrals', 'leaderboard.html')
        self.assertIn(
            "extends 'customer_portal/base_customer.html'",
            content,
        )

    def test_leaderboard_template_has_back_link(self):
        """leaderboard.html must contain a back link to the rewards page."""
        content = self._read_template('customer_portal', 'referrals', 'leaderboard.html')
        self.assertIn('customer_rewards', content)
