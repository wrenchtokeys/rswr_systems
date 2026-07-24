"""
A refused action should not cost the technician their place.

Permission failures in the technician portal used to end in
`redirect('technician_dashboard')` regardless of where the user came from. For
a tech working a job on a phone that means: tap an action, read a one-line
error, and land on a dashboard with no way back to the job except navigating
the whole hierarchy again. In several cases the message even named the fix
("use the reassign feature") while navigating away from the page that offers
it.

apps/technician_portal/views/repairs.py now routes these through `deny()`,
which returns the user to the repair whenever `can_view_repair()` says they
may still see it, and only falls back to the dashboard when they genuinely
cannot.
"""

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from apps.customer_portal.models import CustomerInvitation
from apps.technician_portal.models import Repair, Technician
from apps.technician_portal.views.repairs import can_view_repair
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class DenyRedirectTargetTests(TestCase):
    """update_queue_status / reassign refusals keep the user on the repair."""

    def setUp(self):
        self.owner_user = User.objects.create_user('owner_deny', password='pw', email='owner@deny.test')
        self.shop = Tenant.objects.create(
            name='Deny Shop', slug='deny-shop', plan='trial',
            is_active=True, owner=self.owner_user,
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')

        # A lead tech: is_manager on the Technician record, but NOT a tenant
        # admin. is_tenant_admin() counts role='manager' as admin, which would
        # bypass every gate under test here.
        self.mgr_user = User.objects.create_user('mgr_deny', password='pw', email='mgr@deny.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.mgr_user, role='technician')
        self.mgr_tech = Technician.objects.create(
            tenant=self.shop, user=self.mgr_user,
            is_active=True, is_manager=True, can_repair=True, can_assign_work=True,
        )

        self.tech_user = User.objects.create_user('tech_deny', password='pw', email='tech@deny.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.tech_user, role='technician')
        self.tech = Technician.objects.create(
            tenant=self.shop, user=self.tech_user,
            is_active=True, is_manager=False, can_repair=True,
        )

        # A second plain tech, not managed by anyone, to exercise the
        # genuinely-cannot-view path.
        self.other_user = User.objects.create_user('other_deny', password='pw', email='other@deny.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.other_user, role='technician')
        self.other_tech = Technician.objects.create(
            tenant=self.shop, user=self.other_user,
            is_active=True, is_manager=False, can_repair=True,
        )

        self.customer = Customer.objects.create(tenant=self.shop, name='Deny Fleet')
        self.client = Client()

    def _login(self, user):
        self.client.logout()
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def _repair(self, **kwargs):
        defaults = dict(
            tenant=self.shop, customer=self.customer, technician=self.tech,
            queue_status='APPROVED', unit_number='T-1', cost=50,
        )
        defaults.update(kwargs)
        status = defaults.pop('queue_status')
        repair = Repair.objects.create(queue_status=status, **defaults)
        # resolve_initial_shop_status() auto-approves shop-created work on
        # save(), so PENDING has to be written past the model hook.
        if repair.queue_status != status:
            Repair.objects.filter(pk=repair.pk).update(queue_status=status)
            repair.refresh_from_db()
        return repair

    def test_pending_repair_refusal_returns_to_the_repair(self):
        """A tech's own PENDING repair can be viewed, so don't eject them."""
        repair = self._repair(queue_status='PENDING')
        self._login(self.tech_user)

        response = self.client.post(
            reverse('update_queue_status', kwargs={'repair_id': repair.id}),
            {'status': 'IN_PROGRESS'},
        )

        self.assertRedirects(
            response,
            reverse('repair_detail', kwargs={'repair_id': repair.id}),
            msg_prefix="A tech refused on their own pending repair should land "
                       "back on that repair, not the dashboard",
        )

    def test_refusal_falls_back_to_dashboard_when_repair_not_viewable(self):
        """Someone who can't see the repair has nowhere to go back to."""
        repair = self._repair(technician=self.tech)
        self._login(self.other_user)

        response = self.client.post(
            reverse('update_queue_status', kwargs={'repair_id': repair.id}),
            {'status': 'COMPLETED'},
        )

        self.assertRedirects(
            response,
            reverse('technician_dashboard'),
            msg_prefix="Redirecting to a repair the user cannot view would "
                       "bounce them twice and stack two error messages",
        )

    def test_reassign_refusal_returns_to_the_repair(self):
        """A lead tech refused on reassign can still see the job."""
        repair = self._repair(technician=self.mgr_tech)
        self._login(self.mgr_user)

        response = self.client.get(
            reverse('reassign_to_self', kwargs={'repair_id': repair.id})
        )

        self.assertRedirects(
            response,
            reverse('repair_detail', kwargs={'repair_id': repair.id}),
        )

    def test_other_techs_job_points_at_the_reassign_action(self):
        """The headline case: the message names "Reassign to me", so land on
        the page that actually offers it."""
        self.mgr_tech.managed_technicians.add(self.tech)
        repair = self._repair(technician=self.tech)
        self._login(self.mgr_user)

        response = self.client.post(
            reverse('update_queue_status', kwargs={'repair_id': repair.id}),
            {'status': 'IN_PROGRESS'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain[-1][0],
            reverse('repair_detail', kwargs={'repair_id': repair.id}),
        )
        # can_reassign_to_self drives the "Reassign to me" link in the template.
        self.assertTrue(
            response.context.get('can_reassign_to_self'),
            "The page we redirect to must actually offer the action the error "
            "message told the user to use",
        )


class CanViewRepairHelperTests(TestCase):
    """can_view_repair() is the gate deny() consults; keep it honest."""

    def setUp(self):
        self.owner_user = User.objects.create_user('owner_cv', password='pw', email='owner@cv.test')
        self.shop = Tenant.objects.create(
            name='CV Shop', slug='cv-shop', plan='trial',
            is_active=True, owner=self.owner_user,
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')

        self.mgr_user = User.objects.create_user('mgr_cv', password='pw', email='mgr@cv.test')
        self.mgr = Technician.objects.create(
            tenant=self.shop, user=self.mgr_user,
            is_active=True, is_manager=True, can_repair=True,
        )
        self.tech_user = User.objects.create_user('tech_cv', password='pw', email='tech@cv.test')
        self.tech = Technician.objects.create(
            tenant=self.shop, user=self.tech_user,
            is_active=True, is_manager=False, can_repair=True,
        )
        self.mgr.managed_technicians.add(self.tech)
        self.customer = Customer.objects.create(tenant=self.shop, name='CV Fleet')

    def _repair(self, **kwargs):
        defaults = dict(
            tenant=self.shop, customer=self.customer, technician=self.tech,
            queue_status='APPROVED', unit_number='U-1', cost=50,
        )
        defaults.update(kwargs)
        status = defaults.pop('queue_status')
        repair = Repair.objects.create(queue_status=status, **defaults)
        # See DenyRedirectTargetTests._repair — the model hook auto-approves.
        if repair.queue_status != status:
            Repair.objects.filter(pk=repair.pk).update(queue_status=status)
            repair.refresh_from_db()
        return repair

    def test_admin_always_sees(self):
        self.assertTrue(can_view_repair(self._repair(), None, user_is_admin=True))

    def test_no_technician_profile_sees_nothing(self):
        self.assertFalse(can_view_repair(self._repair(), None))

    def test_assignee_sees_own_repair(self):
        self.assertTrue(can_view_repair(self._repair(), self.tech))

    def test_requested_is_manager_only(self):
        repair = self._repair(queue_status='REQUESTED')
        self.assertFalse(can_view_repair(repair, self.tech))
        self.assertTrue(can_view_repair(repair, self.mgr))

    def test_pending_visible_to_assignee_and_managers(self):
        repair = self._repair(queue_status='PENDING')
        self.assertTrue(can_view_repair(repair, self.tech))
        self.assertTrue(can_view_repair(repair, self.mgr))


class InvitationRefusalTests(TestCase):
    """Invitation refusals return to the customer, where success already lands."""

    def setUp(self):
        self.owner_user = User.objects.create_user('owner_inv', password='pw', email='owner@inv.test')
        self.shop = Tenant.objects.create(
            name='Inv Shop', slug='inv-shop', plan='trial',
            is_active=True, owner=self.owner_user,
        )
        TenantMembership.objects.create(tenant=self.shop, user=self.owner_user, role='owner')

        self.tech_user = User.objects.create_user('tech_inv', password='pw', email='tech@inv.test')
        TenantMembership.objects.create(tenant=self.shop, user=self.tech_user, role='technician')
        Technician.objects.create(
            tenant=self.shop, user=self.tech_user,
            is_active=True, is_manager=False, can_repair=True,
        )

        self.customer = Customer.objects.create(tenant=self.shop, name='Inv Fleet')
        self.invitation = CustomerInvitation.objects.create(
            customer=self.customer, email='contact@inv.test',
        )
        self.client = Client()
        self.client.force_login(self.tech_user)
        session = self.client.session
        session['tenant_id'] = self.shop.id
        session.save()

    def test_non_manager_resend_refusal_returns_to_customer(self):
        response = self.client.post(
            reverse('resend_customer_invitation', kwargs={'invitation_id': self.invitation.id})
        )
        self.assertRedirects(
            response,
            reverse('customer_detail', kwargs={'customer_id': self.customer.id}),
        )

    def test_non_manager_cancel_refusal_returns_to_customer(self):
        response = self.client.post(
            reverse('cancel_customer_invitation', kwargs={'invitation_id': self.invitation.id})
        )
        self.assertRedirects(
            response,
            reverse('customer_detail', kwargs={'customer_id': self.customer.id}),
        )
