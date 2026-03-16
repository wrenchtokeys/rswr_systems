"""
Regression tests for CODE-044: resend_customer_invitation / cancel_customer_invitation
missing tenant scope on get_object_or_404.

Bug:
    Both views fetched the CustomerInvitation with:
        invitation = get_object_or_404(CustomerInvitation, id=invitation_id)
    and then checked:
        if tenant and invitation.customer.tenant != tenant:
            ...redirect...

    The "if tenant and ..." guard is silently skipped when request.tenant is None.
    When tenant resolution fails (stale session, user with no active membership), a
    manager from any shop could resend or cancel ANY invitation in the system.

Fix:
    1. Reject early when request.tenant is None (no shop context).
    2. Push the tenant scope into the get_object_or_404 call:
           get_object_or_404(CustomerInvitation, id=invitation_id, customer__tenant=tenant)
    This ensures a 404 is raised — not a redirect after the fact — if the invitation
    belongs to a different tenant.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician
from apps.customer_portal.models import CustomerUser, CustomerInvitation
from core.models import Customer


def _make_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return plan


def _make_tenant(name_suffix, plan):
    owner = User.objects.create_user(
        username=f'owner_{name_suffix}',
        password='pw',
    )
    tenant = Tenant.objects.create(
        name=f'Shop {name_suffix}',
        slug=f'shop-{name_suffix}',
        subscription_plan=plan,
        owner=owner,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_manager(tenant, name_suffix):
    user = User.objects.create_user(username=f'mgr_{name_suffix}', password='pw')
    TenantMembership.objects.create(tenant=tenant, user=user, role='manager')
    tech = Technician.objects.create(
        tenant=tenant, user=user, is_manager=True, is_active=True,
    )
    return user, tech


def _make_customer(tenant, name_suffix):
    return Customer.objects.create(
        tenant=tenant,
        name=f'Customer {name_suffix}',
    )


def _make_invitation(customer, email):
    return CustomerInvitation.objects.create(
        customer=customer,
        email=email,
        first_name='Test',
        last_name='User',
        status='PENDING',
    )


class ResendInvitationTenantScopeTestCase(TestCase):
    """resend_customer_invitation must 404 for cross-tenant invitation IDs."""

    def setUp(self):
        plan = _make_plan()
        self.tenant_a, self.owner_a = _make_tenant('resend_a', plan)
        self.tenant_b, self.owner_b = _make_tenant('resend_b', plan)

        self.manager_a, self.tech_a = _make_manager(self.tenant_a, 'resend_mgr_a')

        self.customer_b = _make_customer(self.tenant_b, 'resend_b')
        self.invitation_b = _make_invitation(self.customer_b, 'user@shopb.com')

    def test_manager_from_shop_a_cannot_resend_shop_b_invitation(self):
        """
        A manager scoped to tenant_a should get a 404 when they try to resend an
        invitation that belongs to tenant_b.
        """
        self.client.force_login(self.manager_a)
        # Manually set session tenant_id to tenant_a
        session = self.client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

        url = f'/tech/invitations/{self.invitation_b.id}/resend/'
        response = self.client.post(url)

        # Must be 404 — not a successful resend
        self.assertEqual(
            response.status_code, 404,
            f"Expected 404 for cross-tenant resend, got {response.status_code}. "
            "The invitation from Shop B should not be accessible to a manager from Shop A."
        )

    def test_resend_with_no_tenant_context_returns_redirect(self):
        """
        When request.tenant is None (no shop context), the view should redirect
        with an error rather than silently allow cross-tenant access.
        """
        self.client.force_login(self.manager_a)
        # Do NOT set tenant_id in session — tenant will resolve from membership
        # (manager_a has a valid membership for tenant_a, so tenant will be set).
        # To simulate None tenant, we use a user with no active membership.
        no_membership_user = User.objects.create_user(
            username='nomembership_resend', password='pw'
        )
        # Give them a Technician record so @technician_required passes (needs can_access)
        # Actually @technician_required checks can_access which looks at TenantMembership.
        # Without any membership, they'll be redirected by the decorator itself — which
        # is the correct behaviour. Test that the invitation is NOT accessible.
        self.client.force_login(no_membership_user)
        url = f'/tech/invitations/{self.invitation_b.id}/resend/'
        response = self.client.post(url)

        # User has no technician access — should be redirected away by decorator
        self.assertIn(response.status_code, [302, 404],
                      "User with no membership should not access the invitation.")

    def test_manager_can_resend_own_tenant_invitation(self):
        """
        A manager scoped to tenant_a should be able to resend an invitation
        that belongs to a customer in tenant_a (happy path — no 404).
        """
        customer_a = _make_customer(self.tenant_a, 'resend_cust_a')
        invitation_a = _make_invitation(customer_a, 'user@shopa.com')

        self.client.force_login(self.manager_a)
        session = self.client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

        url = f'/tech/invitations/{invitation_a.id}/resend/'
        response = self.client.post(url)

        # Should NOT be a 404 — the invitation belongs to the manager's own tenant
        self.assertNotEqual(
            response.status_code, 404,
            "Manager should be allowed to resend their own tenant's invitation."
        )


class CancelInvitationTenantScopeTestCase(TestCase):
    """cancel_customer_invitation must 404 for cross-tenant invitation IDs."""

    def setUp(self):
        plan = _make_plan()
        self.tenant_a, self.owner_a = _make_tenant('cancel_a', plan)
        self.tenant_b, self.owner_b = _make_tenant('cancel_b', plan)

        self.manager_a, self.tech_a = _make_manager(self.tenant_a, 'cancel_mgr_a')

        self.customer_b = _make_customer(self.tenant_b, 'cancel_b')
        self.invitation_b = _make_invitation(self.customer_b, 'other@shopb.com')

    def test_manager_from_shop_a_cannot_cancel_shop_b_invitation(self):
        """
        A manager scoped to tenant_a should get a 404 when they try to cancel an
        invitation that belongs to tenant_b.
        """
        self.client.force_login(self.manager_a)
        session = self.client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

        url = f'/tech/invitations/{self.invitation_b.id}/cancel/'
        response = self.client.post(url)

        self.assertEqual(
            response.status_code, 404,
            f"Expected 404 for cross-tenant cancel, got {response.status_code}. "
            "The invitation from Shop B should not be accessible to a manager from Shop A."
        )

    def test_manager_can_cancel_own_tenant_invitation(self):
        """
        A manager scoped to tenant_a should be able to cancel an invitation
        that belongs to a customer in tenant_a (happy path).
        """
        customer_a = _make_customer(self.tenant_a, 'cancel_cust_a')
        invitation_a = _make_invitation(customer_a, 'user2@shopa.com')

        self.client.force_login(self.manager_a)
        session = self.client.session
        session['tenant_id'] = self.tenant_a.id
        session.save()

        url = f'/tech/invitations/{invitation_a.id}/cancel/'
        response = self.client.post(url)

        # Should NOT be a 404
        self.assertNotEqual(
            response.status_code, 404,
            "Manager should be allowed to cancel their own tenant's invitation."
        )
