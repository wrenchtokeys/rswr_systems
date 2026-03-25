"""
CODE-180: reward_fulfillment_detail() used the wrong email field to look up
          the Customer, making customer_repairs always empty when the user's
          login email differs from the company billing email.

Root cause:
    The view looked up the customer by matching Customer.email against
    CustomerUser.user.email:

        customer_email = redemption.reward.customer_user.user.email
        customer = customer_qs.get(email=customer_email)

    These are DIFFERENT things:
    - Customer.email      = company billing email (e.g. ap@eostrucking.com)
    - CustomerUser.user.email = individual contact's login email (e.g. john@eostrucking.com)

    When these differ (the common case for fleet accounts), the .get() raises
    Customer.DoesNotExist, which the except block silently swallows, leaving
    customer_repairs = [] — technicians can't see any repairs on the fulfillment
    page even when active repairs exist.

Fix (CODE-180):
    Resolve the customer through the ORM relationship directly:
        customer = redemption.reward.customer_user.customer
    CustomerUser already has a direct FK to Customer — one fewer DB query
    and always correct regardless of what emails contain.

Tests:
    1. Normal case — user email matches customer billing email → works
    2. BUG case — user email differs from customer billing email → repairs now visible
    3. Cross-tenant guard — redemption from wrong tenant → 404
    4. Broken chain — no customer_user → graceful empty result, no crash
    5. Source-code check — ensures the old email lookup is gone from the view
"""

import inspect

from django.test import TestCase, RequestFactory
from django.http import Http404
from django.contrib.auth.models import User
from django.template.response import TemplateResponse

from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.rewards_referrals.models import (
    LoyaltyConfig, Reward, RewardOption, RewardRedemption, RewardType,
)
import apps.technician_portal.views.rewards as rewards_module
from apps.technician_portal.views.rewards import reward_fulfillment_detail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_counter = [0]

def _uid():
    _counter[0] += 1
    return _counter[0]


def _make_tenant(name):
    uid = _uid()
    owner = User.objects.create_user(username=f'towner_{uid}', password='x')
    return Tenant.objects.create(
        name=f'{name}_{uid}', slug=f'{name.lower().replace(" ", "-")}-{uid}', owner=owner
    )


def _make_user(username_prefix, email=None, tenant=None):
    uid = _uid()
    un = f'{username_prefix}_{uid}'
    email = email or f'{un}@test.com'
    u = User.objects.create_user(username=un, password='x', email=email)
    if tenant:
        TenantMembership.objects.create(user=u, tenant=tenant, role='owner', is_active=True)
    return u


def _make_technician(user, tenant, is_manager=True):
    return Technician.objects.create(user=user, tenant=tenant, is_manager=is_manager)


def _make_customer(name, tenant, email=''):
    uid = _uid()
    # Use unique email suffix to avoid unique_customer_email_per_tenant violation
    final_email = email or f'billing-{uid}@fleet.com'
    return Customer.objects.create(name=f'{name}_{uid}', tenant=tenant, email=final_email)


def _make_customer_user(user, customer):
    return CustomerUser.objects.create(user=user, customer=customer)


def _make_reward_option(tenant):
    uid = _uid()
    rt, _ = RewardType.objects.get_or_create(
        name=f'Discount-{uid}',
        defaults={'category': 'REPAIR_DISCOUNT', 'discount_type': 'percentage', 'discount_value': 10},
    )
    return RewardOption.objects.create(
        tenant=tenant, name=f'10% Off {uid}', points_required=100, reward_type=rt,
    )


def _make_redemption(customer_user, reward_option):
    reward, _ = Reward.objects.get_or_create(
        customer_user=customer_user,
        defaults={'tenant': customer_user.customer.tenant, 'points': 500},
    )
    return RewardRedemption.objects.create(
        reward=reward, reward_option=reward_option, status='PENDING',
    )


def _make_repair(customer, tenant, technician, queue_status='IN_PROGRESS'):
    uid = _uid()
    return Repair.objects.create(
        customer=customer, tenant=tenant, technician=technician,
        queue_status=queue_status, damage_type='Chip',
        unit_number=f'UNIT-{uid}', service_date='2026-01-15',
    )


def _build_request(factory, user, tenant):
    req = factory.get('/fake/')
    req.user = user
    req.tenant = tenant
    return req


def _get_customer_repairs_from_response(response):
    """Extract customer_repairs list from a TemplateResponse or plain HttpResponse."""
    if isinstance(response, TemplateResponse):
        response.render()
        return list(response.context_data.get('customer_repairs', []))
    # Fall back: try .context (from test client) or return [] if not available
    ctx = getattr(response, 'context', None)
    if ctx:
        return list(ctx.get('customer_repairs', []))
    return []


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestCode180RewardFulfillmentCustomerLookup(TestCase):
    """reward_fulfillment_detail() must use CustomerUser.customer FK, not email."""

    def setUp(self):
        self.factory = RequestFactory()
        self.tenant = _make_tenant('FixFleet')
        LoyaltyConfig.objects.get_or_create(tenant=self.tenant)
        self.reward_option = _make_reward_option(self.tenant)

        # Admin manager technician who will open the fulfillment page
        self.admin_user = _make_user('admin_180', tenant=self.tenant)
        self.admin_tech = _make_technician(self.admin_user, self.tenant, is_manager=True)

    # ------------------------------------------------------------------
    # Test 1: Normal — user email matches customer billing email
    # ------------------------------------------------------------------

    def test_normal_case_matching_emails(self):
        """When user.email == customer.email, the view renders and shows repairs."""
        uid = _uid()
        customer = _make_customer('Fleet Alpha', self.tenant, email=f'alpha-{uid}@fleet.com')
        cust_user = _make_user('alpha_contact', email=f'alpha-{uid}@fleet.com', tenant=self.tenant)
        customer_user = _make_customer_user(cust_user, customer)
        repair = _make_repair(customer, self.tenant, self.admin_tech)

        redemption = _make_redemption(customer_user, self.reward_option)
        req = _build_request(self.factory, self.admin_user, self.tenant)
        response = reward_fulfillment_detail(req, redemption.id)

        self.assertEqual(response.status_code, 200)

    # ------------------------------------------------------------------
    # Test 2: BUG CASE — user email differs from customer billing email
    # ------------------------------------------------------------------

    def test_user_email_differs_from_customer_email_shows_repairs(self):
        """
        Fleet accounts: customer.email = ap@fleet.com, user.email = john@fleet.com

        OLD CODE (buggy):
            customer_qs.get(email='john@fleet.com')  → DoesNotExist → repairs = []
            customer_repairs is empty, the select dropdown doesn't include the repair.

        NEW CODE (fix):
            customer = redemption.reward.customer_user.customer  → correct, repairs visible
            The repair unit number DOES appear in the select dropdown.
        """
        uid = _uid()
        # Company billing email (Customer.email)
        customer = _make_customer('EOS Trucking', self.tenant, email=f'ap-{uid}@eos.com')
        # Individual contact's login email (different from billing email)
        cust_user = _make_user('eos_john', email=f'john-{uid}@eos.com', tenant=self.tenant)
        customer_user = _make_customer_user(cust_user, customer)
        # Active repair for this customer — store the unit_number for HTML assertion
        repair = _make_repair(customer, self.tenant, self.admin_tech, queue_status='APPROVED')

        redemption = _make_redemption(customer_user, self.reward_option)
        # Assign redemption to admin_tech so the "fulfill" form section shows
        # (template: {% elif can_fulfill %} requires assigned_technician to be set
        # OR is_admin=True. Since the template first shows Claim card when status=PENDING
        # and no assigned technician, we assign it to show the fulfillment form.)
        redemption.assigned_technician = self.admin_tech
        redemption.save()

        req = _build_request(self.factory, self.admin_user, self.tenant)
        response = reward_fulfillment_detail(req, redemption.id)

        self.assertEqual(response.status_code, 200)

        # Check the rendered HTML contains the repair's unit number.
        # With the fix, the customer is resolved via CustomerUser.customer FK,
        # so the repair IS included and its unit_number appears in the select.
        # With the old code, customer lookup fails (email mismatch → DoesNotExist),
        # customer_repairs = [] and the unit_number would NOT appear.
        content = response.content.decode()
        self.assertIn(
            repair.unit_number,
            content,
            f"Repair unit '{repair.unit_number}' must appear in the page even when "
            f"user email ({cust_user.email!r}) != customer billing email ({customer.email!r}). "
            "Old code returned empty customer_repairs due to Customer.DoesNotExist on email mismatch."
        )

    # ------------------------------------------------------------------
    # Test 3: Cross-tenant guard → 404
    # ------------------------------------------------------------------

    def test_cross_tenant_redemption_returns_404(self):
        """Redemption from another tenant → 404 under the current tenant."""
        other_tenant = _make_tenant('OtherCo')
        LoyaltyConfig.objects.get_or_create(tenant=other_tenant)
        uid = _uid()
        other_customer = _make_customer('Other Fleet', other_tenant, email=f'fleet-{uid}@other.com')
        other_user = _make_user('other_fleet', email=f'fleet-{uid}@other.com', tenant=other_tenant)
        other_cu = _make_customer_user(other_user, other_customer)
        other_opt = _make_reward_option(other_tenant)
        redemption = _make_redemption(other_cu, other_opt)

        req = _build_request(self.factory, self.admin_user, self.tenant)
        with self.assertRaises(Http404):
            reward_fulfillment_detail(req, redemption.id)

    # ------------------------------------------------------------------
    # Test 4: Broken chain → graceful empty result
    # ------------------------------------------------------------------

    def test_broken_customer_chain_handled_gracefully(self):
        """
        If reward.customer_user is None (broken data), customer_repairs
        defaults to [] without raising an exception.
        """
        uid = _uid()
        customer = _make_customer('Ghost Fleet', self.tenant, email=f'ghost-{uid}@fleet.com')
        cust_user = _make_user('ghost_fleet', email=f'ghost-{uid}@fleet.com', tenant=self.tenant)
        customer_user = _make_customer_user(cust_user, customer)
        redemption = _make_redemption(customer_user, self.reward_option)

        # Simulate broken chain in memory (not saved to DB)
        redemption.reward.customer_user = None

        req = _build_request(self.factory, self.admin_user, self.tenant)
        try:
            response = reward_fulfillment_detail(req, redemption.id)
            self.assertEqual(response.status_code, 200)
            repairs_in_ctx = _get_customer_repairs_from_response(response)
            self.assertEqual(repairs_in_ctx, [])
        except Exception as e:
            self.fail(f"View crashed with broken customer chain: {e}")

    # ------------------------------------------------------------------
    # Test 5: Source-code regression — old email lookup must be gone
    # ------------------------------------------------------------------

    def test_view_source_does_not_use_email_lookup(self):
        """
        Regression guard: ensure the old email-based Customer lookup is gone.
        The old code looked up the customer by email:
            customer_email = redemption.reward.customer_user.user.email
            customer = customer_qs.get(email=customer_email)
        After the fix, the customer is resolved via ORM FK.
        """
        source = inspect.getsource(reward_fulfillment_detail)
        # The old lookup constructed a 'customer_email' variable from user.email
        # and used it to query Customer.email.  After the fix, neither the
        # variable assignment nor the email-scoped query should exist.
        self.assertNotIn(
            'customer_email =',
            source,
            "The old 'customer_email = ...' assignment must be removed. "
            "Customer should be resolved via redemption.reward.customer_user.customer"
        )
        self.assertIn(
            'customer_user.customer',
            source,
            "The fix must resolve the customer via redemption.reward.customer_user.customer"
        )
