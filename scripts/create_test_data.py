from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import timedelta
from core.models import Customer
from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser
from apps.rewards_referrals.models import Reward, RewardOption, RewardType, RewardRedemption
import random


class Command(BaseCommand):
    help = 'Create test data for manual testing of the repair system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Clean existing test data before creating new data',
        )

    def handle(self, *args, **options):
        if options['clean']:
            self.clean_test_data()
        
        self.stdout.write(self.style.SUCCESS('Creating test data for repair system...'))
        
        # Create technician group
        tech_group, created = Group.objects.get_or_create(name='Technicians')
        if created:
            self.stdout.write('Created Technicians group')
        
        # Create test customer
        customer, created = Customer.objects.get_or_create(
            email='demo@example.com',
            defaults={
                'name': 'demo fleet services',
                'phone': '555-0100',
                'address': '123 Demo Street',
                'city': 'Demo City',
                'state': 'CA',
                'zip_code': '90210'
            }
        )
        if created:
            self.stdout.write(f'Created customer: {customer.name}')
        
        # Create customer user
        customer_user_obj, created = User.objects.get_or_create(
            username='democustomer',
            defaults={
                'email': 'customer@demo.com',
                'first_name': 'Demo',
                'last_name': 'Customer',
                'is_active': True
            }
        )
        if created:
            customer_user_obj.set_password('demo123')
            customer_user_obj.save()
            self.stdout.write(f'Created customer user: {customer_user_obj.username}')
        
        customer_user, created = CustomerUser.objects.get_or_create(
            user=customer_user_obj,
            defaults={
                'customer': customer,
                'is_primary_contact': True
            }
        )
        if created:
            self.stdout.write(f'Created customer profile for: {customer_user_obj.username}')
        
        # Create technicians
        tech_data = [
            {
                'username': 'tech1',
                'email': 'tech1@demo.com',
                'first_name': 'John',
                'last_name': 'Technician',
                'phone': '555-0101',
                'expertise': 'Windshield Repair'
            },
            {
                'username': 'tech2',
                'email': 'tech2@demo.com',
                'first_name': 'Jane',
                'last_name': 'Specialist',
                'phone': '555-0102',
                'expertise': 'Glass Replacement'
            },
            {
                'username': 'tech3',
                'email': 'tech3@demo.com',
                'first_name': 'Mike',
                'last_name': 'Expert',
                'phone': '555-0103',
                'expertise': 'Advanced Repairs'
            }
        ]
        
        for data in tech_data:
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                    'is_active': True
                }
            )
            if created:
                user.set_password('demo123')
                user.save()
                user.groups.add(tech_group)
                self.stdout.write(f'Created technician user: {user.username}')
            
            technician, created = Technician.objects.get_or_create(
                user=user,
                defaults={
                    'phone_number': data['phone'],
                    'expertise': data['expertise']
                }
            )
            if created:
                self.stdout.write(f'Created technician profile for: {user.username}')
        
        # Create admin user
        admin_user, created = User.objects.get_or_create(
            username='demoadmin',
            defaults={
                'email': 'admin@demo.com',
                'first_name': 'Demo',
                'last_name': 'Admin',
                'is_active': True,
                'is_staff': True,
                'is_superuser': True
            }
        )
        if created:
            admin_user.set_password('demo123')
            admin_user.save()
            self.stdout.write(f'Created admin user: {admin_user.username}')
        
        # Create comprehensive test data
        self.create_additional_customers()
        self.create_comprehensive_repairs()
        self.create_reward_test_data()
        
        self.stdout.write(self.style.SUCCESS('\nComprehensive test data created successfully!'))
        self.stdout.write('\n=== TEST ACCOUNTS ===')
        self.stdout.write('Customer Portal:')
        self.stdout.write('  Username: democustomer, abclogistics, xyztransport, citydelivery')
        self.stdout.write('  Password: demo123')
        self.stdout.write('  URL: /app/login/')
        self.stdout.write('\nTechnician Portal:')
        self.stdout.write('  Username: tech1, tech2, or tech3')
        self.stdout.write('  Password: demo123')
        self.stdout.write('  URL: /tech/login/')
        self.stdout.write('\nAdmin Access:')
        self.stdout.write('  Username: demoadmin')
        self.stdout.write('  Password: demo123')
        self.stdout.write('  URL: /admin/')
        self.stdout.write('\n=== TEST SCENARIOS CREATED ===')
        self.stdout.write('• 4 Fleet customers with 12+ units total')
        self.stdout.write('• 25+ repairs across all status types')
        self.stdout.write('• Multiple repairs per unit (tests grouping & cost calculation)')
        self.stdout.write('• Comprehensive reward system test data')
        self.stdout.write('• Pizza/donut rewards (should NOT apply to repairs)')
        self.stdout.write('• Repair discounts and free services (should apply)')
        self.stdout.write('• Various damage types and repair scenarios')
        self.stdout.write('\n=== KEY TESTING AREAS ===')
        self.stdout.write('1. Reward System Fix: Pizza rewards don\'t affect repair costs')
        self.stdout.write('2. UI Grouping: Repairs organized by customer/unit')
        self.stdout.write('3. Auto-Date: Editing repairs updates timestamp')
        self.stdout.write('4. Photo Management: Upload and delete functionality')
        self.stdout.write('5. Workflow: "Create Another Repair" button')

    def clean_test_data(self):
        """Clean up existing test data"""
        self.stdout.write('Cleaning existing test data...')
        
        # Delete test users (this will cascade to related objects)
        test_usernames = ['democustomer', 'tech1', 'tech2', 'tech3', 'demoadmin']
        for username in test_usernames:
            try:
                user = User.objects.get(username=username)
                user.delete()
                self.stdout.write(f'Deleted user: {username}')
            except User.DoesNotExist:
                pass
        
        # Delete test customers
        test_customer_emails = ['demo@example.com', 'abc@logistics.com', 'xyz@transport.com', 'city@delivery.com']
        for email in test_customer_emails:
            try:
                customer = Customer.objects.get(email=email)
                customer.delete()
                self.stdout.write(f'Deleted test customer: {email}')
            except Customer.DoesNotExist:
                pass
    
    def create_additional_customers(self):
        """Create additional fleet customers for comprehensive testing"""
        customers_data = [
            {
                'name': 'abc logistics',
                'email': 'abc@logistics.com',
                'phone': '555-0200',
                'address': '456 Logistics Ave',
                'city': 'Transport City',
                'state': 'TX',
                'zip_code': '75001',
                'username': 'abclogistics',
                'user_email': 'fleet@abc.com',
                'units': ['FLEET001', 'FLEET002', 'FLEET003', 'FLEET004', 'FLEET005']
            },
            {
                'name': 'xyz transport',
                'email': 'xyz@transport.com', 
                'phone': '555-0300',
                'address': '789 Transport Blvd',
                'city': 'Haul Town',
                'state': 'FL',
                'zip_code': '33101',
                'username': 'xyztransport',
                'user_email': 'manager@xyz.com',
                'units': ['TRUCK101', 'TRUCK102', 'TRUCK103']
            },
            {
                'name': 'city delivery co',
                'email': 'city@delivery.com',
                'phone': '555-0400', 
                'address': '321 Delivery St',
                'city': 'Metro City',
                'state': 'NY',
                'zip_code': '10001',
                'username': 'citydelivery',
                'user_email': 'ops@citydelivery.com',
                'units': ['VAN201', 'VAN202', 'VAN203', 'VAN204']
            }
        ]
        
        for data in customers_data:
            # Create customer
            customer, created = Customer.objects.get_or_create(
                email=data['email'],
                defaults={
                    'name': data['name'],
                    'phone': data['phone'],
                    'address': data['address'],
                    'city': data['city'],
                    'state': data['state'],
                    'zip_code': data['zip_code']
                }
            )
            if created:
                self.stdout.write(f'Created customer: {customer.name}')
            
            # Create customer user
            user_obj, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['user_email'],
                    'first_name': data['name'].split()[0],
                    'last_name': 'Manager',
                    'is_active': True
                }
            )
            if created:
                user_obj.set_password('demo123')
                user_obj.save()
                self.stdout.write(f'Created customer user: {user_obj.username}')
            
            customer_user, created = CustomerUser.objects.get_or_create(
                user=user_obj,
                defaults={
                    'customer': customer,
                    'is_primary_contact': True
                }
            )
            if created:
                self.stdout.write(f'Created customer profile for: {user_obj.username}')

    def create_comprehensive_repairs(self):
        """Create comprehensive repair test data"""
        technicians = list(Technician.objects.all())
        customers = list(Customer.objects.all())
        
        if not technicians or not customers:
            self.stdout.write(self.style.WARNING('No technicians or customers found. Creating basic users first.'))
            return
            
        damage_types = ['CHIP', 'CRACK', 'BULL_EYE', 'STAR_BREAK', 'COMBINATION']
        statuses = ['REQUESTED', 'PENDING', 'APPROVED', 'IN_PROGRESS', 'COMPLETED']
        
        repair_scenarios = [
            # abc logistics - Multiple repairs per unit
            {'customer': 'abc logistics', 'unit': 'FLEET001', 'count': 3, 'statuses': ['COMPLETED', 'IN_PROGRESS', 'PENDING']},
            {'customer': 'abc logistics', 'unit': 'FLEET002', 'count': 2, 'statuses': ['COMPLETED', 'APPROVED']},
            {'customer': 'abc logistics', 'unit': 'FLEET003', 'count': 4, 'statuses': ['COMPLETED', 'COMPLETED', 'IN_PROGRESS', 'REQUESTED']},
            {'customer': 'abc logistics', 'unit': 'FLEET004', 'count': 1, 'statuses': ['PENDING']},
            {'customer': 'abc logistics', 'unit': 'FLEET005', 'count': 2, 'statuses': ['COMPLETED', 'REQUESTED']},
            
            # xyz transport
            {'customer': 'xyz transport', 'unit': 'TRUCK101', 'count': 3, 'statuses': ['COMPLETED', 'COMPLETED', 'IN_PROGRESS']},
            {'customer': 'xyz transport', 'unit': 'TRUCK102', 'count': 1, 'statuses': ['APPROVED']},
            {'customer': 'xyz transport', 'unit': 'TRUCK103', 'count': 2, 'statuses': ['COMPLETED', 'PENDING']},
            
            # city delivery co
            {'customer': 'city delivery co', 'unit': 'VAN201', 'count': 2, 'statuses': ['COMPLETED', 'REQUESTED']},
            {'customer': 'city delivery co', 'unit': 'VAN202', 'count': 1, 'statuses': ['IN_PROGRESS']},
            {'customer': 'city delivery co', 'unit': 'VAN203', 'count': 3, 'statuses': ['COMPLETED', 'COMPLETED', 'APPROVED']},
            {'customer': 'city delivery co', 'unit': 'VAN204', 'count': 1, 'statuses': ['PENDING']},
            
            # demo fleet services - Add some repairs to original customer
            {'customer': 'demo fleet services', 'unit': 'DEMO001', 'count': 2, 'statuses': ['COMPLETED', 'IN_PROGRESS']},
            {'customer': 'demo fleet services', 'unit': 'DEMO002', 'count': 1, 'statuses': ['REQUESTED']},
        ]
        
        repair_count = 0
        for scenario in repair_scenarios:
            try:
                customer = Customer.objects.get(name=scenario['customer'])
                for i in range(scenario['count']):
                    # Vary dates to create realistic timeline
                    days_ago = random.randint(1, 30)
                    repair_date = timezone.now() - timedelta(days=days_ago)
                    
                    repair = Repair.objects.create(
                        technician=random.choice(technicians),
                        customer=customer,
                        unit_number=scenario['unit'],
                        repair_date=repair_date,
                        queue_status=scenario['statuses'][i],
                        damage_type=random.choice(damage_types),
                        drilled_before_repair=random.choice([True, False]),
                        windshield_temperature=random.randint(65, 85),
                        resin_viscosity=random.choice(['LOW', 'MEDIUM', 'HIGH']),
                        customer_notes=f'Test repair #{repair_count + 1} for {scenario["unit"]}. Customer reported windshield damage needs immediate attention.',
                        technician_notes=f'Test repair scenario. Status: {scenario["statuses"][i]}. Damage type: {random.choice(damage_types)}.'
                    )
                    repair_count += 1
                    
            except Customer.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'Customer {scenario["customer"]} not found, skipping repairs'))
        
        self.stdout.write(f'Created {repair_count} comprehensive repair records')

    def create_reward_test_data(self):
        """Create reward system test data to test the pizza/donut bug fix"""
        try:
            # Ensure reward types exist
            repair_discount_type, created = RewardType.objects.get_or_create(
                name='50% Repair Discount',
                defaults={
                    'category': 'REPAIR_DISCOUNT',
                    'description': 'Half-price windshield repair service'
                }
            )
            
            free_service_type, created = RewardType.objects.get_or_create(
                name='Free Windshield Repair',
                defaults={
                    'category': 'FREE_SERVICE',
                    'description': 'Complimentary windshield repair service'
                }
            )
            
            merchandise_pizza_type, created = RewardType.objects.get_or_create(
                name='Team Pizza Party',
                defaults={
                    'category': 'MERCHANDISE',
                    'description': 'Pizza party for your team - delivered to your location'
                }
            )
            
            merchandise_donut_type, created = RewardType.objects.get_or_create(
                name='Office Donuts',
                defaults={
                    'category': 'MERCHANDISE',
                    'description': 'Fresh donuts delivered to your office'
                }
            )
            
            # Create reward options
            RewardOption.objects.get_or_create(
                reward_type=repair_discount_type,
                points_required=2000,
                defaults={'name': '50% Off Repair', 'description': '50% discount on next repair'}
            )
            
            RewardOption.objects.get_or_create(
                reward_type=free_service_type,
                points_required=3500,
                defaults={'name': 'Free Repair Service', 'description': 'One free windshield repair'}
            )
            
            pizza_option, created = RewardOption.objects.get_or_create(
                reward_type=merchandise_pizza_type,
                points_required=2500,
                defaults={'name': 'Pizza Party', 'description': 'Team pizza delivered to your location'}
            )
            
            donut_option, created = RewardOption.objects.get_or_create(
                reward_type=merchandise_donut_type,
                points_required=1500,
                defaults={'name': 'Office Donuts', 'description': 'Fresh donuts for your office'}
            )
            
            # Create some rewards and redemptions for testing
            customer_users = CustomerUser.objects.all()
            for customer_user in customer_users:
                # Give them some points
                reward, created = Reward.objects.get_or_create(
                    customer_user=customer_user,
                    defaults={'points': 5000, 'referral_code': f'REF{customer_user.id:04d}'}
                )
                if created:
                    self.stdout.write(f'Created reward account for {customer_user.user.username} with 5000 points')
                
                # Create some redemptions to test the bug fix
                # This pizza redemption should NOT apply to repair costs
                pizza_redemption, created = RewardRedemption.objects.get_or_create(
                    reward=reward,
                    reward_option=pizza_option,
                    defaults={
                        'status': 'PENDING',
                        'notes': 'Test pizza redemption - should NOT affect repair costs'
                    }
                )
                
                if created:
                    self.stdout.write(f'Created pizza redemption for {customer_user.user.username} (should NOT apply to repairs)')
            
            self.stdout.write('Created comprehensive reward system test data')
            self.stdout.write('🍕 Pizza/donut rewards created - these should NOT apply to repair costs (bug fix test)')
            self.stdout.write('💰 Repair discount rewards available - these SHOULD apply to repairs')
            
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not create reward data: {e}'))