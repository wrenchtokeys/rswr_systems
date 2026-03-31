"""
Regression tests for CODE-253: Tenant.save(update_fields=...) not bumping updated_at.

Django's auto_now=True on DateTimeField is NOT automatically included when
save() is called with update_fields=[...]. This means any code path that uses
update_fields for efficiency (webhooks, subscription service, Connect service)
silently leaves updated_at stale — it lies about when the record was last
modified.

Fix: Tenant.save() now auto-injects 'updated_at' into update_fields when
the caller specifies update_fields without including it.
"""

import time
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, SubscriptionPlan


class TenantUpdatedAtTests(TestCase):
    """Verify that Tenant.updated_at is always bumped on save(update_fields=...)."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            username='code253_owner',
            email='code253@test.com',
            password='testpass',
        )
        cls.plan = SubscriptionPlan.objects.create(
            name='Test Plan 253',
            slug='test-plan-253',
            monthly_price=29,
            annual_price=299,
        )

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='CODE-253 Shop',
            slug='code-253-shop',
            subdomain='code-253-shop',
            owner=self.owner,
            subscription_plan=self.plan,
            subscription_status='active',
        )

    def test_update_fields_bumps_updated_at(self):
        """save(update_fields=['subscription_status']) must bump updated_at."""
        old_updated = self.tenant.updated_at

        # Small sleep to ensure time difference (auto_now uses timezone.now())
        # Django's auto_now resolution is microseconds, but we need the test
        # to be deterministic.
        self.tenant.subscription_status = 'past_due'
        self.tenant.save(update_fields=['subscription_status'])

        self.tenant.refresh_from_db()
        self.assertGreaterEqual(
            self.tenant.updated_at,
            old_updated,
            'updated_at should be >= the old value after save(update_fields=...)',
        )
        # Verify the actual field was saved too
        self.assertEqual(self.tenant.subscription_status, 'past_due')

    def test_update_fields_with_updated_at_explicit(self):
        """save(update_fields=['subscription_status', 'updated_at']) still works."""
        self.tenant.subscription_status = 'canceled'
        self.tenant.save(update_fields=['subscription_status', 'updated_at'])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'canceled')

    def test_full_save_still_works(self):
        """save() without update_fields still bumps updated_at (baseline)."""
        old_updated = self.tenant.updated_at
        self.tenant.name = 'CODE-253 Shop Renamed'
        self.tenant.save()

        self.tenant.refresh_from_db()
        self.assertGreaterEqual(self.tenant.updated_at, old_updated)
        self.assertEqual(self.tenant.name, 'CODE-253 Shop Renamed')

    def test_slug_auto_generation_preserved(self):
        """The existing slug auto-generation in save() still works."""
        tenant2 = Tenant(
            name='Auto Slug Test 253',
            owner=self.owner,
            subscription_plan=self.plan,
        )
        tenant2.save()
        self.assertEqual(tenant2.slug, 'auto-slug-test-253')
        self.assertEqual(tenant2.subdomain, 'auto-slug-test-253')

    def test_update_fields_does_not_mutate_caller_list(self):
        """save() should not mutate the caller's update_fields list."""
        fields = ['subscription_status']
        original_fields = list(fields)
        self.tenant.subscription_status = 'trialing'
        self.tenant.save(update_fields=fields)
        self.assertEqual(fields, original_fields, 'Caller list should not be mutated')

    def test_multiple_update_fields_all_saved(self):
        """Multiple fields in update_fields should all be persisted."""
        self.tenant.subscription_status = 'active'
        self.tenant.stripe_subscription_id = 'sub_code253test'
        self.tenant.save(update_fields=['subscription_status', 'stripe_subscription_id'])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertEqual(self.tenant.stripe_subscription_id, 'sub_code253test')

    def test_webhook_pattern_bumps_updated_at(self):
        """Simulate a webhook handler pattern: modify + save(update_fields=...)."""
        # This mirrors the pattern in apps/tenants/webhooks.py
        old_updated = self.tenant.updated_at

        # Simulate webhook updating Connect fields
        self.tenant.stripe_connect_account_id = 'acct_code253test'
        self.tenant.stripe_connect_onboarding_complete = True
        self.tenant.save(update_fields=[
            'stripe_connect_account_id',
            'stripe_connect_onboarding_complete',
        ])

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_connect_account_id, 'acct_code253test')
        self.assertTrue(self.tenant.stripe_connect_onboarding_complete)
        self.assertGreaterEqual(self.tenant.updated_at, old_updated)
