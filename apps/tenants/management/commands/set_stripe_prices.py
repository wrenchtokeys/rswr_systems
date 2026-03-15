"""One-time command to set Stripe price IDs on subscription plans."""
from django.core.management.base import BaseCommand
from apps.tenants.models import SubscriptionPlan


PRICE_MAP = {
    'starter': 'price_1TBOVk0zbBWahwkNapnUrfVx',
    'pro': 'price_1TBOVn0zbBWahwkNgDKWvEe4',
    'enterprise': 'price_1TBOVq0zbBWahwkN1uZvyhin',
}


class Command(BaseCommand):
    help = 'Set Stripe price IDs on subscription plans'

    def handle(self, *args, **options):
        for slug, price_id in PRICE_MAP.items():
            try:
                plan = SubscriptionPlan.objects.get(slug=slug)
                plan.stripe_price_id = price_id
                plan.save(update_fields=['stripe_price_id'])
                self.stdout.write(self.style.SUCCESS(
                    f'  ✅ {plan.name}: {price_id}'
                ))
            except SubscriptionPlan.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠️  Plan "{slug}" not found'
                ))
