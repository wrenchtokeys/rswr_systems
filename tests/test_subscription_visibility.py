"""Who is allowed to see that a shop's subscription exists.

The subscription is a contract between RS Systems and the shop:

  owner/manager – everything: plan, countdown, reason, upgrade link.
  technician    – told only that the shop is locked, and who unlocks it.
  the shop's
  customers     – told nothing about it, ever, and never hard-blocked.

Before this, a fleet contact tapping Approve during a shop's grace period was
told "Your subscription has expired… Upgrade to continue making changes", and
past that grace period got dropped onto /subscription-blocked/ rendered in the
internal app shell — RS Systems' mark, a "Search jobs, customers and invoices"
box and a link to the technician profile page.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.customer_portal.models import CustomerRepairPreference, CustomerUser
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.tenants.services.usage_service import limit_message_for
from apps.tenants.subscription_middleware import (
    audience_for_role, shop_unavailable_message, subscription_audience,
)
from apps.technician_portal.models import Technician
from core.models import Customer

TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}

# Words that must never reach a portal customer. Anything here tells the
# shop's customer something about the shop's bill.
# NB: assertions against rendered HTML look for "taking online requests right
# now" rather than the full sentence — Django autoescapes the apostrophe in
# "isn't" to &#x27;.
BILLING_WORDS = (
    'subscription', 'Subscription', 'past due', 'Past Due', 'past_due',
    'read-only', 'Read-only', 'Upgrade', 'upgrade', 'payment method',
    'Free Trial', 'free trial', 'plan', 'Plan',
)


def _make_shop(name='Glass Co', trial_days_ago=0, plan='trial', **tenant_kwargs):
    plan_obj, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': Decimal('0.00'),
                  'trial_days': 30, 'display_order': 0},
    )
    slug = name.replace(' ', '-').lower()
    owner = User.objects.create_user(f'owner-{slug}', f'owner-{slug}@test.com',
                                     'pass', first_name='Shop')
    tenant = Tenant.objects.create(
        name=name, slug=slug, subdomain=slug, owner=owner,
        subscription_plan=plan_obj, plan=plan,
        business_phone='(501) 555-0123',
        trial_started_at=timezone.now() - timezone.timedelta(days=trial_days_ago),
        **tenant_kwargs,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner')
    return tenant, owner


def _make_customer_user(tenant, username='fleet-contact'):
    customer = Customer.objects.create(
        tenant=tenant, name='Acme Fleet', email='acme@example.com',
        customer_type='FLEET',
    )
    user = User.objects.create_user(username, 'acme@example.com', 'pass')
    CustomerUser.objects.create(user=user, customer=customer,
                                is_primary_contact=True)
    return user, customer


def _make_tech(tenant, username='wrench'):
    user = User.objects.create_user(username, f'{username}@test.com', 'pass')
    TenantMembership.objects.create(tenant=tenant, user=user, role='technician')
    Technician.objects.create(user=user, tenant=tenant, is_active=True)
    return user


def _sign_in(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.pk
    session.save()


@override_settings(**TEST_OVERRIDES)
class AudienceTests(TestCase):
    """The role → audience mapping everything else keys off."""

    def setUp(self):
        self.tenant, self.owner = _make_shop()

    def test_owner_and_manager_are_the_billing_audience(self):
        self.assertEqual(subscription_audience(self.owner, self.tenant), 'owner')
        self.assertEqual(audience_for_role('manager'), 'owner')
        self.assertEqual(audience_for_role('superuser'), 'owner')

    def test_technician_is_staff(self):
        tech = _make_tech(self.tenant)
        self.assertEqual(subscription_audience(tech, self.tenant), 'staff')

    def test_portal_user_is_a_customer(self):
        user, _ = _make_customer_user(self.tenant)
        self.assertEqual(subscription_audience(user, self.tenant), 'customer')

    def test_viewer_membership_is_a_customer(self):
        """'viewer' is a portal-only membership — an external customer."""
        self.assertEqual(audience_for_role('viewer'), 'customer')

    def test_unknown_role_is_treated_as_a_customer(self):
        """Say the least to whoever we can't place."""
        self.assertEqual(audience_for_role(None), 'customer')

    def test_owner_of_another_shop_is_not_this_shop_s_owner(self):
        other_tenant, other_owner = _make_shop(name='Rival Glass')
        self.assertEqual(
            subscription_audience(other_owner, self.tenant), 'customer')


@override_settings(**TEST_OVERRIDES)
class CustomerNeverLearnsAboutBillingTests(TestCase):
    """The shop's customers are not a party to the shop's subscription."""

    def setUp(self):
        self.client = Client()
        # Trial ran out 35 days ago: expired, still inside the 14-day grace.
        self.tenant, self.owner = _make_shop(trial_days_ago=35)
        self.user, self.customer = _make_customer_user(self.tenant)
        _sign_in(self.client, self.user, self.tenant)

    def assertNoBillingWords(self, text, where):
        for word in BILLING_WORDS:
            self.assertNotIn(word, text, f"{where} leaked {word!r}")

    def test_grace_period_banner_says_nothing_about_billing(self):
        response = self.client.get('/app/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("taking online requests right now", body)
        self.assertIn('(501) 555-0123', body)

    def test_blocked_write_message_says_nothing_about_billing(self):
        response = self.client.post(
            '/app/repairs/request/', {}, follow=True, HTTP_REFERER='/app/')
        body = response.content.decode()
        self.assertIn("taking online requests right now", body)
        self.assertNotIn('Upgrade to continue making changes', body)
        self.assertNotIn('could not collect payment', body)

    def test_past_due_write_message_says_nothing_about_billing(self):
        self.tenant.plan = 'pro'
        self.tenant.subscription_status = 'past_due'
        self.tenant.past_due_since = timezone.now() - timezone.timedelta(days=30)
        self.tenant.save()
        response = self.client.post(
            '/app/repairs/request/', {}, follow=True, HTTP_REFERER='/app/')
        body = response.content.decode()
        self.assertNotIn('could not collect payment', body)
        self.assertIn("taking online requests right now", body)

    def test_warn_only_past_due_never_reaches_the_customer(self):
        """Day 3 of a failed card: nothing is broken, so nobody is told."""
        self.tenant.plan = 'pro'
        self.tenant.subscription_status = 'past_due'
        self.tenant.trial_started_at = timezone.now()
        self.tenant.past_due_since = timezone.now() - timezone.timedelta(days=3)
        self.tenant.save()
        body = self.client.get('/app/').content.decode()
        self.assertNotIn('past due', body)
        self.assertNotIn('Payment failed', body)

    def test_customer_is_never_hard_blocked(self):
        """Grace over. The shop is walled off; its customers are not."""
        self.tenant.trial_started_at = timezone.now() - timezone.timedelta(days=200)
        self.tenant.save()
        response = self.client.get('/app/')
        self.assertEqual(response.status_code, 200,
                         "customer was redirected off their own portal")
        self.assertNotIn('subscription-blocked', response.request['PATH_INFO'])

    def test_customer_can_still_reach_invoices_after_the_shop_lapses(self):
        self.tenant.trial_started_at = timezone.now() - timezone.timedelta(days=200)
        self.tenant.save()
        self.assertEqual(self.client.get('/app/invoices/').status_code, 200)

    def test_account_settings_writes_are_not_exempt(self):
        """/app/account/ looks personal but saves shop workflow config.

        Its POST handler also saves a RepairPreferenceForm, which writes
        field_repair_approval_mode (whether the shop's jobs auto-approve or
        land as PENDING) plus invoice_preference / auto_email_invoices /
        billing_email. Letting that through while the shop is frozen would
        reconfigure the shop's workflow for the moment it came back.
        """
        from apps.tenants.subscription_middleware import (
            CUSTOMER_ALLOWED_WRITE_PREFIXES,
        )
        self.assertFalse(
            '/app/account/settings/'.startswith(CUSTOMER_ALLOWED_WRITE_PREFIXES))

        prefs = CustomerRepairPreference.objects.create(
            customer=self.customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
            units_per_visit_threshold=5,
        )
        response = self.client.post(
            '/app/account/settings/',
            {'field_repair_approval_mode': 'AUTO_APPROVE',
             'units_per_visit_threshold': 5},
            follow=True, HTTP_REFERER='/app/',
        )
        prefs.refresh_from_db()
        self.assertEqual(prefs.field_repair_approval_mode, 'REQUIRE_APPROVAL',
                         "a frozen shop's approval mode was rewritten")
        self.assertIn("taking online requests right now",
                      response.content.decode())

    def test_paying_an_invoice_survives_the_write_block(self):
        """Money moving TO the shop is the last thing to switch off."""
        from apps.tenants.subscription_middleware import (
            CUSTOMER_ALLOWED_WRITE_PREFIXES,
        )
        self.assertTrue('/app/invoices/1/pay/'.startswith(
            CUSTOMER_ALLOWED_WRITE_PREFIXES))
        # Not a redirect back to /app/ with an error: the view itself answers.
        response = self.client.post('/app/invoices/999999/pay/', {},
                                    HTTP_REFERER='/app/')
        self.assertNotEqual(response.get('Location', ''), '/app/')

    def test_blocked_page_uses_the_portal_shell_if_they_reach_it(self):
        response = self.client.get('/subscription-blocked/')
        body = response.content.decode()
        self.assertNotIn('Search jobs, customers and invoices', body)
        self.assertNotIn('Subscription Expired | RS Systems', body)
        self.assertIn('Glass Co', body)
        self.assertIn('(501) 555-0123', body)

    def test_the_two_customer_messages_are_the_same_sentence(self):
        """Banner copy and refusal copy come from one function."""
        sentence = shop_unavailable_message(self.tenant)
        self.assertIn('Glass Co', sentence)
        self.assertIn('(501) 555-0123', sentence)
        self.assertNoBillingWords(sentence, 'shop_unavailable_message')

    def test_message_without_a_phone_number_still_makes_sense(self):
        self.tenant.business_phone = ''
        sentence = shop_unavailable_message(self.tenant)
        self.assertIn('contact the shop directly', sentence)
        self.assertNoBillingWords(sentence, 'shop_unavailable_message')


@override_settings(**TEST_OVERRIDES)
class UnplaceableUserIsStillBlockedTests(TestCase):
    """Telling someone the least must not also grant them more.

    audience_for_role() sends an unrecognised role to 'customer' so that a
    user we can't identify hears the least about the shop's billing. The
    block decision deliberately does NOT reuse that answer: only an
    affirmatively identified portal customer (CustomerUser, or a 'viewer'
    membership) skips the wall. Sharing one default would have made "we
    can't place you" quietly permissive about access.

    Reachability, since it is narrower than it first looks: a user with no
    membership at all never gets here, because every branch of
    TenantMiddleware that sets request.tenant checks TenantMembership first
    (or is_superuser, who skips this middleware entirely) — they are turned
    away one step earlier with "no tenant". What IS reachable is a
    membership whose role we don't recognise, e.g. a role added to the model
    later and not taught to common.auth. That resolves a tenant, produces an
    unplaceable role, and would have skipped the wall.
    """

    def setUp(self):
        self.client = Client()
        # Trial ran out long ago: expired, grace over, hard block.
        self.tenant, self.owner = _make_shop(trial_days_ago=200)

    def test_an_unrecognised_membership_role_hits_the_wall(self):
        stranger = User.objects.create_user('stranger', 's@example.com', 'pass')
        TenantMembership.objects.create(
            tenant=self.tenant, user=stranger, role='auditor', is_active=True,
        )
        _sign_in(self.client, stranger, self.tenant)
        response = self.client.get('/app/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/subscription-blocked/', response['Location'])

    def test_no_membership_never_reaches_the_decision_at_all(self):
        """Turned away for having no tenant, one step before this logic."""
        stranger = User.objects.create_user('nobody', 'n@example.com', 'pass')
        _sign_in(self.client, stranger, self.tenant)
        response = self.client.get('/app/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_but_a_real_portal_customer_does_not(self):
        user, _ = _make_customer_user(self.tenant)
        _sign_in(self.client, user, self.tenant)
        self.assertEqual(self.client.get('/app/').status_code, 200)

    def test_the_write_exemption_is_identity_not_disclosure(self):
        """The same split, one level down, in _handle_grace_period.

        During grace / paused / past-due-read-only every audience passes
        through _handle_grace_period, so gating its write allowlist on the
        disclosure answer would hand an unrecognised role the portal
        customer's POST exemption — letting it write paths a technician on
        the same shop is refused.
        """
        tenant, _ = _make_shop(name='Grace Co', trial_days_ago=35)  # in grace

        stranger = User.objects.create_user('oddrole', 'o@example.com', 'pass')
        TenantMembership.objects.create(
            tenant=tenant, user=stranger, role='auditor', is_active=True,
        )
        client = Client()
        _sign_in(client, stranger, tenant)
        # Not followed: an 'auditor' has a tenant but no CustomerUser, so
        # /app/ bounces it onward into a portal redirect loop that has
        # nothing to do with this assertion. The refusal is the 302 itself.
        response = client.post('/app/notifications/mark-all-read/', {},
                               HTTP_REFERER='/app/')
        self.assertEqual(response.status_code, 302, "write was not refused")
        self.assertEqual(response['Location'], '/app/')

        # The real portal customer keeps the exemption.
        customer_user, _ = _make_customer_user(tenant, username='real-contact')
        client2 = Client()
        _sign_in(client2, customer_user, tenant)
        response2 = client2.post('/app/notifications/mark-all-read/', {},
                                 HTTP_REFERER='/app/')
        self.assertNotEqual(response2.get('Location', ''), '/app/',
                            "the customer's own write was wrongly refused")

    def test_the_two_defaults_are_deliberately_different(self):
        from apps.tenants.subscription_middleware import PORTAL_CUSTOMER_ROLES
        # Told the least...
        self.assertEqual(audience_for_role(None), 'customer')
        # ...but not exempt from the block.
        self.assertNotIn(None, PORTAL_CUSTOMER_ROLES)
        self.assertEqual(PORTAL_CUSTOMER_ROLES, {'customer', 'viewer'})


@override_settings(**TEST_OVERRIDES)
class TechnicianSeesOnlyWhatBlocksThemTests(TestCase):
    """A technician can't pay the bill; don't make them carry it."""

    def setUp(self):
        self.client = Client()

    def test_healthy_trial_shows_no_countdown(self):
        tenant, _ = _make_shop(trial_days_ago=1)
        tech = _make_tech(tenant)
        _sign_in(self.client, tech, tenant)
        body = self.client.get('/tech/').content.decode()
        self.assertNotIn('free trial', body)
        self.assertNotIn('Free Trial', body)
        self.assertNotIn('days remaining', body)

    def test_trial_ending_soon_shows_no_countdown(self):
        tenant, _ = _make_shop(trial_days_ago=27)
        tech = _make_tech(tenant)
        _sign_in(self.client, tech, tenant)
        body = self.client.get('/tech/').content.decode()
        self.assertNotIn('free trial', body)
        self.assertNotIn('expires in', body)

    def test_warn_only_past_due_is_not_the_technician_s_problem(self):
        tenant, _ = _make_shop(trial_days_ago=1, plan='pro',
                               subscription_status='past_due')
        tenant.past_due_since = timezone.now() - timezone.timedelta(days=3)
        tenant.save()
        tech = _make_tech(tenant)
        _sign_in(self.client, tech, tenant)
        body = self.client.get('/tech/').content.decode()
        self.assertNotIn('Payment failed', body)
        self.assertNotIn('past due', body)

    def test_read_only_says_so_without_naming_a_reason(self):
        tenant, _ = _make_shop(trial_days_ago=35)
        tech = _make_tech(tenant)
        _sign_in(self.client, tech, tenant)
        body = self.client.get('/tech/').content.decode()
        self.assertIn('Read-only mode', body)
        self.assertIn('shop owner', body)
        self.assertNotIn('Upgrade Now', body)
        self.assertNotIn('free trial', body)

    def test_write_refusal_names_no_amount_or_plan(self):
        tenant, _ = _make_shop(trial_days_ago=35)
        tech = _make_tech(tenant)
        _sign_in(self.client, tech, tenant)
        response = self.client.post('/tech/repairs/create/', {}, follow=True,
                                    HTTP_REFERER='/tech/')
        body = response.content.decode()
        self.assertIn('Contact your shop owner', body)
        self.assertNotIn('days of read-only access remaining', body)

    def test_no_plan_badge_in_the_account_menu(self):
        tenant, _ = _make_shop(trial_days_ago=1)
        tech = _make_tech(tenant)
        _sign_in(self.client, tech, tenant)
        body = self.client.get('/tech/').content.decode()
        self.assertIn('Glass Co', body)          # the shop's name is fine
        self.assertNotIn('Free Trial', body)     # its plan is not

    def test_plan_limit_copy_is_rewritten_for_staff(self):
        tenant, owner = _make_shop()
        tech = _make_tech(tenant)
        owner_msg = ("Your Starter plan allows 200 jobs/month and you've "
                     "used them all. Upgrade to Pro for unlimited jobs.")
        self.assertEqual(limit_message_for(owner, tenant, owner_msg), owner_msg)
        staff_msg = limit_message_for(tech, tenant, owner_msg)
        self.assertNotIn('Starter', staff_msg)
        self.assertNotIn('Pro', staff_msg)
        self.assertIn('shop owner', staff_msg)


@override_settings(**TEST_OVERRIDES)
class OwnerStillSeesEverythingTests(TestCase):
    """None of the above may quietly disarm the owner's own warnings."""

    def setUp(self):
        self.client = Client()

    def test_owner_gets_the_countdown_and_the_button(self):
        tenant, owner = _make_shop(trial_days_ago=27)
        _sign_in(self.client, owner, tenant)
        body = self.client.get('/owner/').content.decode()
        self.assertIn('free trial expires in', body)
        self.assertIn('Upgrade Now', body)

    def test_owner_in_grace_gets_the_reason_and_the_countdown(self):
        tenant, owner = _make_shop(trial_days_ago=35)
        _sign_in(self.client, owner, tenant)
        body = self.client.get('/owner/').content.decode()
        self.assertIn('Read-only mode', body)
        self.assertIn('read-only access remaining', body)
        self.assertIn('Upgrade Now', body)

    def test_owner_write_refusal_keeps_the_upgrade_path(self):
        tenant, owner = _make_shop(trial_days_ago=35)
        _sign_in(self.client, owner, tenant)
        response = self.client.post('/tech/repairs/create/', {}, follow=True,
                                    HTTP_REFERER='/owner/')
        self.assertIn('Upgrade to continue making changes',
                      response.content.decode())

    def test_plan_badge_is_still_in_the_owner_s_account_menu(self):
        tenant, owner = _make_shop(trial_days_ago=1)
        _sign_in(self.client, owner, tenant)
        body = self.client.get('/owner/').content.decode()
        self.assertIn('Free Trial', body)


@override_settings(**TEST_OVERRIDES)
class PausedSubscriptionTests(TestCase):
    """'paused' used to be unmapped, so pausing changed nothing at all."""

    def setUp(self):
        self.client = Client()

    def test_paused_is_a_stored_status(self):
        from apps.tenants.services.subscription_reconcile import STATUS_MAP
        self.assertEqual(STATUS_MAP['paused'], 'paused')
        self.assertIn(
            'paused',
            dict(Tenant._meta.get_field('subscription_status').choices),
        )

    def test_paused_shop_is_read_only_not_wide_open(self):
        tenant, owner = _make_shop(trial_days_ago=1, plan='pro',
                                   subscription_status='paused')
        _sign_in(self.client, owner, tenant)
        self.assertEqual(self.client.get('/owner/').status_code, 200)
        response = self.client.post('/tech/repairs/create/', {}, follow=True,
                                    HTTP_REFERER='/owner/')
        self.assertIn('paused', response.content.decode())

    def test_paused_shop_tells_its_customers_nothing(self):
        tenant, _ = _make_shop(trial_days_ago=1, plan='pro',
                               subscription_status='paused')
        user, _ = _make_customer_user(tenant)
        _sign_in(self.client, user, tenant)
        body = self.client.get('/app/').content.decode()
        self.assertIn("taking online requests right now", body)
        self.assertNotIn('paused', body)

    def test_an_unmapped_status_is_shouted_about(self):
        from apps.tenants.services import subscription_reconcile
        tenant, _ = _make_shop(subscription_status='active')
        with self.assertLogs(subscription_reconcile.__name__, level='WARNING') as logs:
            subscription_reconcile.apply_subscription_state(
                tenant, {'id': 'sub_x', 'status': 'some_new_stripe_status'},
            )
        self.assertTrue(any('Unmapped Stripe subscription status' in line
                            for line in logs.output))
