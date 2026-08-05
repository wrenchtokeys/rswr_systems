"""
Referral signup flow (customer-anchored loyalty).

Referral codes are entered (or prefilled via ?ref=) on the public
/join/<slug>/ page. A valid code records a PENDING Referral — NO points
move at signup. Bonuses pay out via referral_payout_hook when the referred
customer's first job completes: the referrer's COMPANY earns the referrer
bonus, the referred company earns a one-time welcome bonus. The shop owner
gets an email + in-app notification for every portal self-signup.
"""

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, TechnicianNotification, Repair
from apps.tenants.models import Tenant, TenantMembership
from apps.rewards_referrals.models import LoyaltyConfig, Referral, ReferralCode
from apps.rewards_referrals.services import LoyaltyService, ReferralService


def _make_tenant(name, slug):
    owner = User.objects.create_user(f"owner_{slug}", f"owner_{slug}@test.com", "Pass123!")
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner,
        plan="trial", trial_started_at=timezone.now(),
    )
    TenantMembership.objects.create(user=owner, tenant=tenant, role="owner", is_active=True)
    return owner, tenant


def _make_referrer(tenant, slug_suffix="ref"):
    """An existing portal customer with a referral code."""
    customer = Customer.objects.create(tenant=tenant, name=f"Referrer Co {slug_suffix}")
    user = User.objects.create_user(f"referrer_{slug_suffix}", f"referrer_{slug_suffix}@test.com", "Pass123!")
    cu = CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=True)
    code = ReferralCode.objects.create(code=f"REF{slug_suffix.upper()}1", customer_user=cu)
    return customer, cu, code


SIGNUP_FORM = {
    'first_name': 'New',
    'last_name': 'Fleet',
    'email': 'newfleet@test.com',
    'phone': '',
    'company_name': 'New Fleet Trucking',
    'password': 'Str0ng!Passw0rd77',
    'confirm_password': 'Str0ng!Passw0rd77',
}


# The /join/ endpoint is IP rate-limited; in full-suite runs earlier tests
# exhaust the shared-cache counter for 127.0.0.1, so disable limiting here
# (test_code237 covers the rate limit itself).
@override_settings(RATELIMIT_ENABLE=False)
class JoinPageReferralTest(TestCase):
    def setUp(self):
        self.owner, self.tenant = _make_tenant("Join Shop", "joinshop")
        self.referrer_customer, self.referrer_cu, self.code = _make_referrer(self.tenant)

    def test_ref_param_prefills_code(self):
        response = self.client.get(f"/join/{self.tenant.slug}/?ref={self.code.code}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.code.code)

    def test_signup_with_valid_code_records_pending_referral_no_points(self):
        form = dict(SIGNUP_FORM, referral_code=self.code.code)
        response = self.client.post(f"/join/{self.tenant.slug}/", form)
        self.assertEqual(response.status_code, 302)

        referral = Referral.objects.get()
        self.assertEqual(referral.status, 'PENDING')
        self.assertIsNone(referral.awarded_at)
        self.assertEqual(referral.referral_code, self.code)

        # Zero points moved at signup — for anyone.
        self.assertEqual(LoyaltyService.get_balance(self.referrer_customer), 0)
        new_customer = Customer.objects.get(name='New Fleet Trucking')
        self.assertEqual(new_customer.customer_type, 'FLEET')
        self.assertEqual(LoyaltyService.get_balance(new_customer), 0)

    def test_signup_with_invalid_code_still_succeeds_without_referral(self):
        form = dict(SIGNUP_FORM, referral_code='BOGUS99')
        response = self.client.post(f"/join/{self.tenant.slug}/", form)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(name='New Fleet Trucking').exists())
        self.assertEqual(Referral.objects.count(), 0)

    def test_signup_with_cross_tenant_code_records_no_referral(self):
        _, other_tenant = _make_tenant("Other Shop", "othershop")
        _, _, other_code = _make_referrer(other_tenant, "other")
        form = dict(SIGNUP_FORM, referral_code=other_code.code)
        response = self.client.post(f"/join/{self.tenant.slug}/", form)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Customer.objects.filter(name='New Fleet Trucking').exists())
        self.assertEqual(Referral.objects.count(), 0)

    def test_owner_notified_on_signup(self):
        manager_user = User.objects.create_user("joinmgr", "joinmgr@test.com", "Pass123!")
        manager_tech = Technician.objects.create(
            user=manager_user, tenant=self.tenant, is_active=True, is_manager=True,
        )
        mail.outbox = []
        form = dict(SIGNUP_FORM, referral_code=self.code.code)
        self.client.post(f"/join/{self.tenant.slug}/", form)

        note = TechnicianNotification.objects.get(technician=manager_tech)
        self.assertIn('New Fleet Trucking', note.message)
        self.assertIn('fleet account', note.message)

        signup_emails = [m for m in mail.outbox if 'New customer signup' in m.subject]
        self.assertEqual(len(signup_emails), 1)
        self.assertIn(self.owner.email, signup_emails[0].to)


class SameCompanyReferralTest(TestCase):
    def test_two_users_of_same_company_cannot_refer_each_other(self):
        _, tenant = _make_tenant("Same Shop", "sameshop")
        customer, cu1, code = _make_referrer(tenant)
        colleague = User.objects.create_user("colleague", "colleague@test.com", "Pass123!")
        cu2 = CustomerUser.objects.create(user=colleague, customer=customer)
        self.assertFalse(ReferralService.record_referral(code, cu2))
        self.assertEqual(Referral.objects.count(), 0)


class ReferralPayoutOnFirstJobTest(TestCase):
    def setUp(self):
        _, self.tenant = _make_tenant("Payout Shop", "payoutshop")
        self.config = LoyaltyConfig.get_for_tenant(self.tenant)
        self.referrer_customer, self.referrer_cu, self.code = _make_referrer(self.tenant)

        # Referred company signed up with the code (PENDING referral, no points)
        self.referred_customer = Customer.objects.create(tenant=self.tenant, name="Referred Co")
        referred_user = User.objects.create_user("referred", "referred@test.com", "Pass123!")
        self.referred_cu = CustomerUser.objects.create(
            user=referred_user, customer=self.referred_customer, is_primary_contact=True,
        )
        self.assertTrue(ReferralService.record_referral(self.code, self.referred_cu))

        tech_user = User.objects.create_user("payouttech", "pt@test.com", "Pass123!")
        self.tech = Technician.objects.create(user=tech_user, tenant=self.tenant, is_active=True)

    def _complete_repair(self, unit):
        repair = Repair.objects.create(
            tenant=self.tenant, technician=self.tech, customer=self.referred_customer,
            unit_number=unit, damage_type="Chip", queue_status="APPROVED",
        )
        repair.queue_status = "COMPLETED"
        repair.save()
        return repair

    def test_first_completed_job_pays_both_companies(self):
        self._complete_repair("U-1")

        referral = Referral.objects.get()
        self.assertEqual(referral.status, 'AWARDED')
        self.assertIsNotNone(referral.awarded_at)

        # Referrer's company earns the referrer bonus.
        self.assertEqual(
            LoyaltyService.get_balance(self.referrer_customer),
            self.config.referral_bonus_referrer,
        )
        # Referred company: completion points + one-time welcome bonus.
        self.assertEqual(
            LoyaltyService.get_balance(self.referred_customer),
            self.config.points_per_repair + self.config.referral_bonus_referred,
        )

    def test_second_job_does_not_double_pay(self):
        self._complete_repair("U-1")
        self._complete_repair("U-2")

        self.assertEqual(
            LoyaltyService.get_balance(self.referrer_customer),
            self.config.referral_bonus_referrer,
        )
        self.assertEqual(
            LoyaltyService.get_balance(self.referred_customer),
            2 * self.config.points_per_repair + self.config.referral_bonus_referred,
        )
