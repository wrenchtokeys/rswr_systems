"""
Pricing page correctness (IMPROVEMENT_SESSIONS C2).

Two things a prospect comparing plans must not be misled by: a feature flag
that a plan row simply lacks (rendered as "not included"), and the plan
limit called two different things on two pages.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.tenants.models import SubscriptionPlan


class SeedPlansKeepsRowsButFillsFlagsTests(TestCase):
    def test_existing_plan_gains_missing_feature_keys_and_keeps_its_own_values(self):
        # A migration may already have seeded the plans; either way the row
        # here is the "older seed" shape: a price of its own and only two flags.
        SubscriptionPlan.objects.update_or_create(
            slug='starter', defaults=dict(
                name='Starter', monthly_price=59, display_order=1,
                features={'rewards': False, 'invoicing': True},
            ),
        )
        out = StringIO()
        call_command('seed_plans', stdout=out)
        plan = SubscriptionPlan.objects.get(slug='starter')
        # Price untouched, the shop's own flag values untouched…
        self.assertEqual(plan.monthly_price, 59)
        self.assertFalse(plan.features['rewards'])
        # …and the keys the row never had are now present.
        self.assertTrue(plan.features['customer_portal'])
        self.assertIn('support', plan.features)
        self.assertIn("added missing feature flag(s)", out.getvalue())
        # A second run has nothing to add and says so.
        out = StringIO()
        call_command('seed_plans', stdout=out)
        self.assertIn("Skipped 'starter'", out.getvalue())


class PricingPageWordingTests(TestCase):
    def test_the_monthly_cap_is_called_jobs_everywhere(self):
        call_command('seed_plans', stdout=StringIO())
        resp = self.client.get(reverse('pricing'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Jobs per month')
        self.assertNotContains(resp, 'Repairs per month')
        # Every plan on the table has the portal.
        self.assertEqual(resp.content.decode().count('Customer portal'), 1)
