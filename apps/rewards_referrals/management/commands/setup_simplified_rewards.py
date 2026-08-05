from django.core.management.base import BaseCommand, CommandError

from apps.rewards_referrals.models import RewardOption, RewardType
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        'Seed the 4 default reward options for ONE tenant. '
        'Requires --tenant <slug>; never touches other tenants\' options.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            required=True,
            help='Slug of the tenant to seed reward options for.',
        )
        parser.add_argument(
            '--reset',
            action='store_true',
            help="Delete the tenant's existing reward options before seeding "
                 '(default: keep them and only add missing ones).',
        )

    def handle(self, *args, **options):
        try:
            tenant = Tenant.objects.get(slug=options['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f"No tenant with slug '{options['tenant']}'.")

        self.stdout.write(f'Seeding reward options for {tenant.name}...')

        if options['reset']:
            deleted, _ = RewardOption.objects.filter(tenant=tenant).delete()
            self.stdout.write(f'Cleared {deleted} existing reward option(s) for this tenant.')

        # Create or get reward types (shared, non-tenant lookup table)
        repair_discount_type, _ = RewardType.objects.get_or_create(
            name="Repair Service Discount",
            category="REPAIR_DISCOUNT",
            defaults={
                'discount_type': 'PERCENTAGE',
                'discount_value': 50,
                'description': 'Percentage discount on repair services'
            }
        )

        free_service_type, _ = RewardType.objects.get_or_create(
            name="Free Service",
            category="FREE_SERVICE",
            defaults={
                'discount_type': 'FREE',
                'discount_value': 0,
                'description': 'Complimentary repair services'
            }
        )

        office_treats_type, _ = RewardType.objects.get_or_create(
            name="Office Treats",
            category="MERCHANDISE",
            defaults={
                'discount_type': 'NONE',
                'discount_value': 0,
                'description': 'Complimentary office treats and team activities'
            }
        )

        # Create simplified reward options (only 4 professional options)
        reward_options = [
            {
                'name': '50% Off Next Repair',
                'description': 'Get 50% discount on your next windshield repair service',
                'points_required': 2000,
                'reward_type': repair_discount_type
            },
            {
                'name': 'Free Windshield Repair',
                'description': 'Get one completely free windshield repair service',
                'points_required': 3500,
                'reward_type': free_service_type
            },
            {
                'name': '5 Dozen Donuts for the Office',
                'description': 'Fresh donuts delivered to your office team (5 dozen assorted)',
                'points_required': 1500,
                'reward_type': office_treats_type
            },
            {
                'name': '5 Large Pizzas for Team',
                'description': 'Pizza party for your office (5 large pizzas with variety of toppings)',
                'points_required': 2500,
                'reward_type': office_treats_type
            }
        ]

        # Create the reward options for this tenant
        created_count = 0
        for option_data in reward_options:
            option, created = RewardOption.objects.get_or_create(
                tenant=tenant,
                name=option_data['name'],
                defaults=option_data,
            )
            if created:
                created_count += 1
                self.stdout.write(f"Created reward option: {option.name} ({option.points_required} points)")

        total = RewardOption.objects.filter(tenant=tenant).count()
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully created {created_count} reward option(s) for {tenant.name}. '
                f'This tenant now has {total} option(s).'
            )
        )
