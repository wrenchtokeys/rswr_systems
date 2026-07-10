"""
Regression tests for B2, B3, B4, B5 (Remediation Plan 2026-07-09).

B2 — /test-notification/ was @login_required only: any authenticated user
     (including a customer-portal user) could read an arbitrary — almost
     certainly cross-tenant — repair's data, trigger on-demand emails, and
     receive stack traces in the JSON response. Now staff-gated,
     tenant-scoped, traceback logged server-side only, and both diagnostic
     endpoints are mounted only when settings.DEBUG.

B3 — technician_batch_start_work executed APPROVED -> IN_PROGRESS
     transitions on GET (no method guard), bypassing CSRF protection.
     Now requires POST, matching its sibling batch_complete_all.

B4 — The referred-side "welcome bonus" could be collected repeatedly by
     redeeming different coworkers' codes. Now granted at most once per
     customer_user; referrer-side bonus unchanged (earns per referral).

B5 — NOT-REPRODUCED: the audit claimed fields='__all__' on
     CustomerRepairPreference's admin form exposed an editable tenant FK,
     but the model has NO tenant field (it is tenant-scoped through its
     customer OneToOne). No change made.
"""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch

from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import PointTransaction, ReferralCode
from apps.rewards_referrals.services import ReferralService
from apps.tenants.models import SubscriptionPlan, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Technician
from core.models import Customer

User = get_user_model()


class SecurityFixesTestBase(TestCase):
    def setUp(self):
        self.client = Client()
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='B Sec Shop',
            email='owner_bsec@test.com',
            password='testpass123!',
            first_name='BsecOwner',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(user=self.user, tenant=self.tenant)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='B Sec Fleet', customer_type='FLEET',
        )

    def _login(self, user=None):
        user = user or self.user
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()


class B2DiagnosticEndpointTests(SecurityFixesTestBase):
    def test_non_staff_user_cannot_use_test_notification(self):
        """Non-staff users are bounced to the admin login, not served JSON."""
        try:
            url = reverse('test_notification')
        except NoReverseMatch:
            # Route not mounted (DEBUG=False environments) — even better.
            return
        self._login()
        self.assertFalse(self.user.is_staff)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.get('Content-Type'), 'application/json')

    def test_staff_response_never_contains_traceback(self):
        try:
            url = reverse('test_notification')
        except NoReverseMatch:
            return
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self._login()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'Traceback', response.content)
        self.assertNotIn(b'traceback', response.content)


class B3BatchStartWorkMethodGuardTests(SecurityFixesTestBase):
    def _make_batch(self):
        batch_id = uuid.uuid4()
        repairs = []
        for i in (1, 2):
            repairs.append(Repair.objects.create(
                tenant=self.tenant,
                customer=self.customer,
                technician=self.technician,
                unit_number='B3-UNIT',
                queue_status='APPROVED',
                repair_batch_id=batch_id,
                break_number=i,
                total_breaks_in_batch=2,
            ))
        return batch_id, repairs

    def test_get_does_not_start_work(self):
        batch_id, repairs = self._make_batch()
        self._login()
        response = self.client.get(
            reverse('technician_batch_start_work', args=[batch_id])
        )
        self.assertEqual(response.status_code, 302, "GET must redirect, not act")
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(
                r.queue_status, 'APPROVED',
                "A GET request must not transition batch repairs (CSRF bypass)",
            )

    def test_post_starts_work(self):
        batch_id, repairs = self._make_batch()
        self._login()
        response = self.client.post(
            reverse('technician_batch_start_work', args=[batch_id])
        )
        self.assertEqual(response.status_code, 302)
        for r in repairs:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'IN_PROGRESS')


class B4ReferralBonusFarmingTests(SecurityFixesTestBase):
    def _make_customer_user(self, name):
        user = User.objects.create_user(
            username=f'b4_{name}', email=f'b4_{name}@test.com', password='pass123!',
        )
        cu = CustomerUser.objects.create(user=user, customer=self.customer)
        TenantMembership.objects.create(
            tenant=self.tenant, user=user, role='viewer', is_active=True,
        )
        return cu

    def test_welcome_bonus_granted_at_most_once(self):
        newbie = self._make_customer_user('newbie')
        referrers = [self._make_customer_user(f'ref{i}') for i in range(3)]
        codes = [
            ReferralCode.objects.create(customer_user=r, code=f'B4CODE{i}')
            for i, r in enumerate(referrers)
        ]

        for code in codes:
            result = ReferralService.process_referral(code, newbie)
            self.assertTrue(result, "each distinct-code referral is recorded")

        received = PointTransaction.objects.filter(
            customer_user=newbie, transaction_type='referral_received',
        ).count()
        self.assertEqual(
            received, 1,
            "The one-time welcome bonus must not be farmable via multiple coworkers' codes",
        )

        made = PointTransaction.objects.filter(
            transaction_type='referral_made',
            customer_user__in=referrers,
        ).count()
        self.assertEqual(made, 3, "each referrer still earns their per-referral bonus")
