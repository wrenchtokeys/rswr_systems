"""
Tests for Review Request System (Phase 1).

Covers:
- ReviewConfig (per-tenant, TenantConfig base)
- ReviewRequest model
- ReviewRequestService smart throttling logic
- review_request_hook integration
- send_review_requests management command
- Click tracking + opt-out endpoints
- Owner settings Reviews tab
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair, TechnicianNotification
from apps.technician_portal.review_models import ReviewConfig, ReviewRequest
from apps.technician_portal.review_service import (
    ReviewRequestService,
    _adjust_to_business_hours,
)
from core.models import Customer
from apps.customer_portal.models import CustomerUser


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name='Test Shop', owner_username='owner'):
    """Create a tenant with owner, technician, customer, and primary contact."""
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        owner_username, f'{owner_username}@test.com', 'testpass123!',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    tech = Technician.objects.create(
        user=user, tenant=tenant, is_manager=True, is_active=True,
    )
    customer = Customer.objects.create(
        tenant=tenant, name='Acme Fleet', customer_type='FLEET',
    )
    contact_user = User.objects.create_user(
        f'{owner_username}_contact', f'contact_{owner_username}@test.com', 'testpass123!',
        first_name='Contact', last_name='Person',
    )
    customer_user = CustomerUser.objects.create(
        user=contact_user, customer=customer, is_primary_contact=True,
    )
    return {
        'user': user,
        'tenant': tenant,
        'tech': tech,
        'customer': customer,
        'customer_user': customer_user,
        'contact_user': contact_user,
    }


def make_completed_repair(tenant, customer, tech, **kwargs):
    """Create a COMPLETED repair for testing."""
    defaults = {
        'tenant': tenant,
        'customer': customer,
        'technician': tech,
        'unit_number': 'TRUCK-001',
        'damage_type': 'Chip',
        'queue_status': 'COMPLETED',
        'cost': Decimal('50.00'),
    }
    defaults.update(kwargs)
    return Repair.objects.create(**defaults)


# =====================================================================
# Model Tests
# =====================================================================

class ReviewConfigModelTests(TestCase):
    """Test ReviewConfig inherits from TenantConfig correctly."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']

    def test_get_for_tenant_creates_default(self):
        config = ReviewConfig.get_for_tenant(self.tenant)
        self.assertIsNotNone(config.pk)
        self.assertFalse(config.is_enabled)
        self.assertEqual(config.retail_cooldown_days, 90)
        self.assertEqual(config.fleet_cooldown_days, 180)
        self.assertEqual(config.send_delay_hours, 2)
        self.assertEqual(config.business_hours_start, 9)
        self.assertEqual(config.business_hours_end, 19)

    def test_get_for_tenant_idempotent(self):
        c1 = ReviewConfig.get_for_tenant(self.tenant)
        c2 = ReviewConfig.get_for_tenant(self.tenant)
        self.assertEqual(c1.pk, c2.pk)

    def test_one_config_per_tenant(self):
        ReviewConfig.get_for_tenant(self.tenant)
        self.assertEqual(ReviewConfig.objects.filter(tenant=self.tenant).count(), 1)


class ReviewRequestModelTests(TestCase):
    """Test ReviewRequest model basics."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']
        self.customer_user = data['customer_user']
        self.tech = data['tech']

    def test_create_review_request(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequest.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_user=self.customer_user,
            repair=repair,
            status='pending',
            scheduled_at=timezone.now(),
        )
        self.assertIsNotNone(rr.token)
        self.assertEqual(rr.status, 'pending')

    def test_token_is_unique(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr1 = ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer, repair=repair,
            status='pending', scheduled_at=timezone.now(),
        )
        rr2 = ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer, repair=repair,
            status='skipped', skip_reason='test', scheduled_at=timezone.now(),
        )
        self.assertNotEqual(rr1.token, rr2.token)


# =====================================================================
# Service Tests — ReviewRequestService.schedule_review_request()
# =====================================================================

class ScheduleReviewRequestTests(TestCase):
    """Test smart throttling logic in schedule_review_request()."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']
        self.customer_user = data['customer_user']
        self.tech = data['tech']
        # Enable reviews (fixture customer is FLEET, so opt fleets in)
        self.config = ReviewConfig.get_for_tenant(self.tenant)
        self.config.is_enabled = True
        self.config.send_to_fleet = True
        self.config.google_review_url = 'https://g.page/test/review'
        self.config.save()

    def _make_repair(self, **kwargs):
        return make_completed_repair(self.tenant, self.customer, self.tech, **kwargs)

    def test_creates_pending_request(self):
        repair = self._make_repair()
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertIsNotNone(rr)
        self.assertEqual(rr.status, 'pending')
        self.assertEqual(rr.customer, self.customer)
        self.assertEqual(rr.customer_user, self.customer_user)

    def test_returns_none_when_disabled(self):
        self.config.is_enabled = False
        self.config.save()
        repair = self._make_repair()
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertIsNone(rr)

    def test_returns_none_when_no_google_url(self):
        self.config.google_review_url = ''
        self.config.save()
        repair = self._make_repair()
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertIsNone(rr)

    def test_returns_none_when_not_completed(self):
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='T-1', damage_type='Chip', queue_status='IN_PROGRESS',
            cost=Decimal('50.00'),
        )
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertIsNone(rr)

    def test_skips_goodwill_repair(self):
        repair = self._make_repair(is_goodwill_repair=True)
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'goodwill_repair')

    def test_returns_none_when_no_primary_contact(self):
        self.customer_user.is_primary_contact = False
        self.customer_user.save()
        repair = self._make_repair()
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertIsNone(rr)

    def test_skips_opted_out_customer(self):
        self.customer_user.review_opt_out = True
        self.customer_user.save()
        repair = self._make_repair()
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'customer_opted_out')

    def test_suppresses_negative_experience(self):
        repair = self._make_repair()
        TechnicianNotification.objects.create(
            technician=self.tech, repair=repair,
            message='Customer DENIED the repair.',
        )
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'suppressed')
        self.assertEqual(rr.skip_reason, 'negative_experience')

    def test_skips_already_reviewed(self):
        repair1 = self._make_repair()
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair1,
            status='reviewed', scheduled_at=timezone.now(),
        )
        repair2 = self._make_repair(unit_number='TRUCK-002')
        rr = ReviewRequestService.schedule_review_request(repair2)
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'already_reviewed')

    def test_fleet_cooldown(self):
        """Fleet customers respect fleet_cooldown_days."""
        repair1 = self._make_repair()
        # Simulate a sent request 30 days ago
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair1,
            status='sent', scheduled_at=timezone.now() - timedelta(days=30),
            sent_at=timezone.now() - timedelta(days=30),
        )
        repair2 = self._make_repair(unit_number='TRUCK-002')
        rr = ReviewRequestService.schedule_review_request(repair2)
        self.assertEqual(rr.status, 'skipped')
        self.assertIn('cooldown', rr.skip_reason)

    def test_cooldown_expired_allows_request(self):
        """After cooldown period, a new request is allowed."""
        self.config.fleet_cooldown_days = 30
        self.config.save()
        repair1 = self._make_repair()
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair1,
            status='sent', scheduled_at=timezone.now() - timedelta(days=31),
            sent_at=timezone.now() - timedelta(days=31),
        )
        repair2 = self._make_repair(unit_number='TRUCK-002')
        rr = ReviewRequestService.schedule_review_request(repair2)
        self.assertEqual(rr.status, 'pending')

    def test_retail_cooldown_shorter(self):
        """Retail customers use retail_cooldown_days."""
        self.customer.customer_type = 'RETAIL'
        self.customer.save()
        self.config.retail_cooldown_days = 90
        self.config.save()
        repair1 = self._make_repair()
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair1,
            status='sent', scheduled_at=timezone.now() - timedelta(days=60),
            sent_at=timezone.now() - timedelta(days=60),
        )
        repair2 = self._make_repair(unit_number='TRUCK-002')
        rr = ReviewRequestService.schedule_review_request(repair2)
        self.assertEqual(rr.status, 'skipped')
        self.assertIn('cooldown', rr.skip_reason)

    def test_no_duplicate_pending(self):
        """Don't create a second pending request for the same repair."""
        repair = self._make_repair()
        rr1 = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr1.status, 'pending')
        rr2 = ReviewRequestService.schedule_review_request(repair)
        self.assertIsNone(rr2)

    def test_tenant_isolation(self):
        """Review requests from tenant A don't affect tenant B."""
        data_b = make_tenant(name='Other Shop', owner_username='owner_b')
        tenant_b = data_b['tenant']
        customer_b = data_b['customer']
        config_b = ReviewConfig.get_for_tenant(tenant_b)
        config_b.is_enabled = True
        config_b.send_to_fleet = True
        config_b.google_review_url = 'https://g.page/other/review'
        config_b.save()

        # Tenant A has already_reviewed
        repair_a = self._make_repair()
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            status='reviewed', scheduled_at=timezone.now(),
        )

        # Tenant B should still be able to create a request
        repair_b = make_completed_repair(tenant_b, customer_b, data_b['tech'])
        rr = ReviewRequestService.schedule_review_request(repair_b)
        self.assertEqual(rr.status, 'pending')


# =====================================================================
# Business Hours Tests
# =====================================================================

class FleetGatingTests(TestCase):
    """Fleet accounts are excluded from review requests unless the shop opts in."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']          # FLEET (fixture default)
        self.customer_user = data['customer_user']
        self.tech = data['tech']
        self.config = ReviewConfig.get_for_tenant(self.tenant)
        self.config.is_enabled = True
        self.config.google_review_url = 'https://g.page/test/review'
        self.config.save()

    def _make_individual(self, customer_type='RETAIL'):
        customer = Customer.objects.create(
            tenant=self.tenant, name='Jane Driver', customer_type=customer_type,
        )
        contact = User.objects.create_user(
            f'contact_{customer_type.lower()}', f'{customer_type.lower()}@test.com',
            'testpass123!',
        )
        customer_user = CustomerUser.objects.create(
            user=contact, customer=customer, is_primary_contact=True,
        )
        return customer, customer_user

    def test_send_to_fleet_defaults_off(self):
        self.assertFalse(ReviewConfig.get_for_tenant(self.tenant).send_to_fleet)

    def test_fleet_skipped_by_default(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'fleet_disabled')

    def test_fleet_allowed_when_opted_in(self):
        self.config.send_to_fleet = True
        self.config.save()
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'pending')

    def test_retail_unaffected_by_fleet_gate(self):
        customer, _ = self._make_individual('RETAIL')
        repair = make_completed_repair(self.tenant, customer, self.tech)
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'pending')

    def test_walk_in_unaffected_by_fleet_gate(self):
        customer, _ = self._make_individual('WALK_IN')
        repair = make_completed_repair(self.tenant, customer, self.tech)
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'pending')

    def test_send_time_recheck_skips_fleet(self):
        # Scheduled while fleet was allowed, toggle switched off before cron ran
        self.config.send_to_fleet = True
        self.config.save()
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequestService.schedule_review_request(repair)
        self.assertEqual(rr.status, 'pending')
        self.config.send_to_fleet = False
        self.config.save()
        rr.scheduled_at = timezone.now() - timedelta(minutes=5)
        rr.save(update_fields=['scheduled_at'])
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'fleet_disabled')


class BusinessHoursTests(TestCase):
    """Test _adjust_to_business_hours helper.

    business_hours_start/end are a shop owner's wall-clock hours, so every
    assertion here is in LOCAL time. These tests used to build UTC hours with
    `timezone.now().replace(hour=...)` and assert on `result.hour`, which is
    the UTC hour -- they passed against a helper that compared UTC to a local
    window, and that is how review requests came to queue for ~4 AM local
    (FIELD_OPS N3).
    """

    @staticmethod
    def _local(hour, minute=0):
        now = timezone.localtime(timezone.now())
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def test_during_business_hours_unchanged(self):
        dt = self._local(14, 30)
        self.assertEqual(_adjust_to_business_hours(dt, 9, 19), dt)

    def test_after_hours_pushed_to_next_day(self):
        dt = self._local(20)
        result = timezone.localtime(_adjust_to_business_hours(dt, 9, 19))
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.date(), dt.date() + timedelta(days=1))

    def test_before_hours_pushed_to_start(self):
        dt = self._local(6)
        result = timezone.localtime(_adjust_to_business_hours(dt, 9, 19))
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 0)
        self.assertEqual(result.date(), dt.date())

    def test_exactly_at_end_pushed_to_next_day(self):
        dt = self._local(19)
        result = timezone.localtime(_adjust_to_business_hours(dt, 9, 19))
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.date(), dt.date() + timedelta(days=1))

    def test_the_result_is_a_local_morning_not_a_utc_one(self):
        """The regression itself: 09:00 UTC is 04:00 in America/Chicago."""
        dt = self._local(6)
        result = _adjust_to_business_hours(dt, 9, 19)
        self.assertEqual(timezone.localtime(result).hour, 9)
        self.assertNotEqual(timezone.localtime(result).hour, 4)


# =====================================================================
# send_pending_requests() Tests
# =====================================================================

@override_settings(**TEST_SETTINGS, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendPendingRequestsTests(TestCase):
    """Test ReviewRequestService.send_pending_requests()."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']
        self.customer_user = data['customer_user']
        self.tech = data['tech']
        self.config = ReviewConfig.get_for_tenant(self.tenant)
        self.config.is_enabled = True
        self.config.send_to_fleet = True
        self.config.google_review_url = 'https://g.page/test/review'
        self.config.save()

    def test_sends_due_requests(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='pending',
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 1)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'sent')
        self.assertIsNotNone(rr.sent_at)

    def test_skips_future_requests(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='pending',
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)

    def test_skips_if_config_deactivated(self):
        self.config.is_enabled = False
        self.config.save()
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='pending',
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'config_deactivated')

    def test_skips_if_opted_out_since_scheduling(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        rr = ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='pending',
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        # Opt out after scheduling
        self.customer_user.review_opt_out = True
        self.customer_user.save()
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')


# =====================================================================
# Hook Integration Tests
# =====================================================================

class ReviewRequestHookTests(TestCase):
    """Test that the review_request_hook correctly integrates with Repair completion."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']
        self.customer_user = data['customer_user']
        self.tech = data['tech']
        self.config = ReviewConfig.get_for_tenant(self.tenant)
        self.config.is_enabled = True
        self.config.send_to_fleet = True
        self.config.google_review_url = 'https://g.page/test/review'
        self.config.save()

    def test_hook_fires_on_status_transition(self):
        """Hook fires when repair transitions from non-COMPLETED to COMPLETED."""
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='TRANS-1', damage_type='Chip', queue_status='IN_PROGRESS',
            cost=Decimal('50.00'),
        )
        self.assertEqual(ReviewRequest.objects.filter(repair=repair).count(), 0)
        # Transition to COMPLETED
        repair.queue_status = 'COMPLETED'
        repair.save()
        self.assertEqual(
            ReviewRequest.objects.filter(repair=repair, status='pending').count(), 1,
        )

    def test_hook_idempotent_on_resave(self):
        """Re-saving a COMPLETED repair does not create a duplicate request."""
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='IDEM-1', damage_type='Chip', queue_status='IN_PROGRESS',
            cost=Decimal('50.00'),
        )
        repair.queue_status = 'COMPLETED'
        repair.save()
        self.assertEqual(ReviewRequest.objects.filter(repair=repair).count(), 1)
        # Re-save (already COMPLETED)
        repair.save()
        self.assertEqual(ReviewRequest.objects.filter(repair=repair).count(), 1)

    def test_hook_handles_exception_gracefully(self):
        """Hook should not raise even if service encounters an error."""
        from apps.technician_portal.hooks import review_request_hook
        # Create repair without triggering hook (IN_PROGRESS)
        repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='ERR-1', damage_type='Chip', queue_status='IN_PROGRESS',
            cost=Decimal('50.00'),
        )
        # Force an error by mangling tenant_id
        repair.tenant_id = 999999
        review_request_hook(repair)  # Should not raise


# =====================================================================
# Click Tracking + Opt-Out Endpoint Tests
# =====================================================================

@override_settings(**TEST_SETTINGS)
class ReviewEndpointTests(TestCase):
    """Test public click-tracking and opt-out endpoints."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']
        self.customer_user = data['customer_user']
        self.tech = data['tech']
        self.client = Client()
        config = ReviewConfig.get_for_tenant(self.tenant)
        config.is_enabled = True
        config.send_to_fleet = True
        config.google_review_url = 'https://g.page/test/review'
        config.save()

    def _make_sent_request(self):
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        return ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='sent', scheduled_at=timezone.now(),
            sent_at=timezone.now(),
        )

    def test_click_redirects_to_google(self):
        rr = self._make_sent_request()
        response = self.client.get(f'/reviews/click/{rr.token}/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://g.page/test/review')
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'clicked')
        self.assertIsNotNone(rr.clicked_at)

    def test_click_only_updates_sent_status(self):
        """Clicking a skipped/suppressed request doesn't change status."""
        rr = self._make_sent_request()
        rr.status = 'skipped'
        rr.save()
        self.client.get(f'/reviews/click/{rr.token}/')
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')  # unchanged

    def test_click_with_invalid_token_returns_404(self):
        import uuid
        response = self.client.get(f'/reviews/click/{uuid.uuid4()}/')
        self.assertEqual(response.status_code, 404)

    def test_opt_out_sets_flag(self):
        rr = self._make_sent_request()
        response = self.client.get(f'/reviews/opt-out/{rr.token}/')
        self.assertEqual(response.status_code, 200)
        self.customer_user.refresh_from_db()
        self.assertTrue(self.customer_user.review_opt_out)

    def test_opt_out_with_invalid_token_returns_404(self):
        import uuid
        response = self.client.get(f'/reviews/opt-out/{uuid.uuid4()}/')
        self.assertEqual(response.status_code, 404)


# =====================================================================
# Management Command Tests
# =====================================================================

@override_settings(**TEST_SETTINGS, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendReviewRequestsCommandTests(TestCase):
    """Test the send_review_requests management command."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.customer = data['customer']
        self.customer_user = data['customer_user']
        self.tech = data['tech']
        config = ReviewConfig.get_for_tenant(self.tenant)
        config.is_enabled = True
        config.send_to_fleet = True
        config.google_review_url = 'https://g.page/test/review'
        config.save()

    def test_command_sends_pending(self):
        from django.core.management import call_command
        from io import StringIO
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='pending',
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )
        out = StringIO()
        call_command('send_review_requests', stdout=out)
        self.assertIn('Sent 1', out.getvalue())

    def test_command_dry_run(self):
        from django.core.management import call_command
        from io import StringIO
        repair = make_completed_repair(self.tenant, self.customer, self.tech)
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=self.customer,
            customer_user=self.customer_user, repair=repair,
            status='pending',
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )
        out = StringIO()
        call_command('send_review_requests', dry_run=True, stdout=out)
        self.assertIn('Dry run: 1', out.getvalue())
        # Should not have sent
        rr = ReviewRequest.objects.first()
        self.assertEqual(rr.status, 'pending')


# =====================================================================
# Owner Settings Tab Tests
# =====================================================================

@override_settings(**TEST_SETTINGS)
class OwnerSettingsReviewsTabTests(TestCase):
    """Test the Reviews tab on the owner settings page."""

    def setUp(self):
        data = make_tenant()
        self.tenant = data['tenant']
        self.user = data['user']
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_reviews_tab_loads(self):
        response = self.client.get('/owner/settings/?tab=reviews')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Review Request Settings')
        self.assertContains(response, 'google_review_url')

    def test_save_review_settings(self):
        response = self.client.post('/owner/settings/', {
            'form_type': 'review_settings',
            'review_enabled': 'on',
            'google_review_url': 'https://g.page/myshop/review',
            'email_subject': 'Rate us, {shop_name}!',
            'email_body_template': 'Thanks for your business.',
        })
        self.assertEqual(response.status_code, 302)
        config = ReviewConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.is_enabled)
        self.assertEqual(config.google_review_url, 'https://g.page/myshop/review')
        self.assertEqual(config.email_subject, 'Rate us, {shop_name}!')
        self.assertEqual(config.email_body_template, 'Thanks for your business.')
        # Fleet toggle not posted → stays off
        self.assertFalse(config.send_to_fleet)

    def test_save_fleet_toggle(self):
        response = self.client.post('/owner/settings/', {
            'form_type': 'review_settings',
            'review_enabled': 'on',
            'review_send_to_fleet': 'on',
            'google_review_url': 'https://g.page/myshop/review',
            'email_subject': '',
            'email_body_template': '',
        })
        self.assertEqual(response.status_code, 302)
        config = ReviewConfig.get_for_tenant(self.tenant)
        self.assertTrue(config.send_to_fleet)

    def test_disable_review_settings(self):
        config = ReviewConfig.get_for_tenant(self.tenant)
        config.is_enabled = True
        config.save()
        response = self.client.post('/owner/settings/', {
            'form_type': 'review_settings',
            'google_review_url': '',
            'email_subject': '',
            'email_body_template': '',
        })
        self.assertEqual(response.status_code, 302)
        config.refresh_from_db()
        self.assertFalse(config.is_enabled)

    def test_recent_requests_shown(self):
        config = ReviewConfig.get_for_tenant(self.tenant)
        data = make_tenant(name='Tab Shop', owner_username='tabowner')
        # Use self.tenant for the review request
        customer = Customer.objects.create(
            tenant=self.tenant, name='TabCustomer', customer_type='RETAIL',
        )
        repair = make_completed_repair(self.tenant, customer, data['tech'])
        ReviewRequest.objects.create(
            tenant=self.tenant, customer=customer,
            repair=repair, status='sent',
            scheduled_at=timezone.now(), sent_at=timezone.now(),
        )
        response = self.client.get('/owner/settings/?tab=reviews')
        self.assertContains(response, 'TabCustomer')
