"""Set or verify Stripe price IDs on subscription plans.

Historic versions hardcoded price IDs from a Stripe account that does not
match the ones migration 0013 applied — running it would have broken every
checkout with "No such price". Price IDs are now passed explicitly, and
--verify cross-checks each plan's stripe_price_id against Stripe so the DB
monthly_price and the amount Stripe actually charges can never silently
diverge.

Usage:
    python manage.py set_stripe_prices --verify
    python manage.py set_stripe_prices --plan pro --price price_XXX
    python manage.py set_stripe_prices --plan pro --annual-price price_YYY
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.tenants.models import SubscriptionPlan


class Command(BaseCommand):
    help = 'Set or verify Stripe price IDs on subscription plans'

    def add_arguments(self, parser):
        parser.add_argument('--plan', help='Plan slug (e.g. starter, pro, enterprise)')
        parser.add_argument('--price', help='Stripe monthly price ID (price_...)')
        parser.add_argument('--annual-price', help='Stripe annual price ID (price_...)')
        parser.add_argument(
            '--verify', action='store_true',
            help='Fetch each plan\'s price from Stripe and check the amount '
                 'matches the plan\'s monthly_price/annual_price in the DB',
        )

    def handle(self, *args, **options):
        if options['verify']:
            self._verify()
            return

        slug = options['plan']
        price = options['price']
        annual = options['annual_price']
        if not slug or not (price or annual):
            raise CommandError(
                'Pass --plan <slug> with --price and/or --annual-price, '
                'or use --verify. Price IDs are never hardcoded here.'
            )

        try:
            plan = SubscriptionPlan.objects.get(slug=slug)
        except SubscriptionPlan.DoesNotExist:
            raise CommandError(f'Plan "{slug}" not found')

        update_fields = []
        if price:
            plan.stripe_price_id = price
            update_fields.append('stripe_price_id')
        if annual:
            plan.stripe_annual_price_id = annual
            update_fields.append('stripe_annual_price_id')
        plan.save(update_fields=update_fields)
        self.stdout.write(self.style.SUCCESS(f'  ✅ {plan.name}: {", ".join(update_fields)} updated'))
        self.stdout.write('Run with --verify to confirm the amounts match Stripe.')

    def _verify(self):
        import stripe
        api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        if not api_key:
            raise CommandError('STRIPE_SECRET_KEY is not configured')
        stripe.api_key = api_key

        problems = 0
        for plan in SubscriptionPlan.objects.filter(is_active=True).order_by('monthly_price'):
            for field, db_amount, label in (
                ('stripe_price_id', plan.monthly_price, 'monthly'),
                ('stripe_annual_price_id', getattr(plan, 'annual_price', None), 'annual'),
            ):
                price_id = getattr(plan, field, '')
                if not price_id:
                    if plan.monthly_price and field == 'stripe_price_id':
                        self.stdout.write(self.style.WARNING(
                            f'  ⚠️  {plan.slug}: no {field} — checkout for this plan will fail'
                        ))
                        problems += 1
                    continue
                try:
                    stripe_price = stripe.Price.retrieve(price_id)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'  ❌ {plan.slug} {label}: {price_id} not retrievable: {e}'
                    ))
                    problems += 1
                    continue
                stripe_amount = (stripe_price.get('unit_amount') or 0) / 100
                if db_amount is not None and float(db_amount) != stripe_amount:
                    self.stdout.write(self.style.ERROR(
                        f'  ❌ {plan.slug} {label}: DB says ${db_amount}, '
                        f'Stripe {price_id} charges ${stripe_amount}'
                    ))
                    problems += 1
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✅ {plan.slug} {label}: ${stripe_amount} ({price_id})'
                    ))
        if problems:
            raise CommandError(f'{problems} price problem(s) found')
        self.stdout.write(self.style.SUCCESS('All plan prices match Stripe.'))
