"""The trial has to fit a real month of work.

The landing page invites a shop to "run both for a month, free" beside their
old system, and to send over their customer list. The trial permitted 10
customers and 50 jobs a month as HARD BLOCKS at creation -- numbers a 1-5 tech
shop passes inside week one, so the shop hit the wall mid-evaluation at the
exact moment they had committed effort.

Trial limits now match Starter. Time is the only limit.
"""

from django.test import TestCase

from apps.tenants.management.commands.seed_plans import PLANS

FLOOR = {
    'max_repairs_per_month': 200,
    'max_technicians': 5,
    'max_customers': 50,
    'max_storage_mb': 500,
}


def plan(slug):
    return next(p for p in PLANS if p['slug'] == slug)


class TrialPlanSizeTests(TestCase):
    def test_trial_limits_match_starter(self):
        """A trial smaller than the entry plan is a trial nobody can finish."""
        trial, starter = plan('trial'), plan('starter')
        for field in FLOOR:
            self.assertEqual(
                trial[field], starter[field],
                f'trial {field} ({trial[field]}) does not match starter ({starter[field]})',
            )

    def test_trial_is_still_time_limited(self):
        self.assertEqual(plan('trial')['trial_days'], 30)
        self.assertEqual(plan('trial')['monthly_price'], 0)

    def test_a_months_real_work_fits_inside_the_trial(self):
        """The shape the landing page promises: ~50 jobs a week, fleet accounts."""
        trial = plan('trial')
        self.assertGreaterEqual(trial['max_repairs_per_month'], 200)
        self.assertGreaterEqual(trial['max_customers'], 50)


class TrialLimitMigrationTests(TestCase):
    """The deployed row, not just the dict.

    `seed_plans` never rewrites limits on an existing plan without --force, so
    without migration 0028 every deployed database would keep the old caps.
    """

    def test_the_seeded_trial_row_carries_the_raised_limits(self):
        from django.core.management import call_command

        from apps.tenants.models import SubscriptionPlan

        call_command('seed_plans', verbosity=0)
        row = SubscriptionPlan.objects.get(slug='trial')
        for field, floor in FLOOR.items():
            value = getattr(row, field)
            self.assertTrue(
                value is None or value >= floor,
                f'trial row {field} is {value}, below the {floor} floor',
            )

    def test_the_migration_only_ever_raises(self):
        """A hand-tuned higher cap must survive a deploy."""
        import importlib

        from apps.tenants.models import SubscriptionPlan

        _0028 = importlib.import_module(
            'apps.tenants.migrations.0028_raise_trial_plan_limits'
        )

        SubscriptionPlan.objects.update_or_create(
            slug='trial',
            defaults={
                'name': 'Trial', 'monthly_price': 0, 'trial_days': 30,
                'is_active': True, 'max_customers': 9999,
                'max_repairs_per_month': 10, 'max_technicians': 5,
                'max_storage_mb': 500,
            },
        )

        class FakeApps:
            @staticmethod
            def get_model(app, model):
                return SubscriptionPlan

        _0028.raise_trial_limits(FakeApps, None)
        row = SubscriptionPlan.objects.get(slug='trial')
        self.assertEqual(row.max_customers, 9999, 'a higher hand-tuned cap was walked back down')
        self.assertEqual(row.max_repairs_per_month, 200, 'a lower cap was not raised')
