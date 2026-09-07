"""Seed a realistic, fictional shop for product screenshots and manual QA.

    python manage.py seed_demo_shop            # create (no-op if it exists)
    python manage.py seed_demo_shop --reset    # tear it down and rebuild

Why this exists (IMPROVEMENT_SESSIONS C1 / UI_MAGIC S14): the landing page
used to show a hand-built HTML imitation of the owner dashboard, and it
drifted from the real thing twice without anyone touching either file. The
screenshots that replaced it are captured from a running app by
``scripts/landing_shots.py``, and that script needs a shop with enough real
data on it to look like a shop. This command is that shop.

Everything here is fictional and deterministic (seeded RNG, dates relative to
today), so re-running the capture on any machine produces the same pictures
apart from the calendar. Nothing in it is a real customer, address, or plate.

Refuses to run against production: it creates users with known passwords.
"""

from datetime import timedelta
from decimal import Decimal
import random

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.billing.models import BillingConfig, Invoice, Payment, TaxRate
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.tenants.models import OnboardingState, SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner
from core.models import Customer


DEMO_SLUG = 'clearview-auto-glass'
DEMO_DOMAIN = 'clearview-demo.test'
DEMO_PASSWORD = 'demo-shop-pass-2026'

OWNER = dict(first_name='Sam', last_name='Reyes', email=f'sam@{DEMO_DOMAIN}')
TECHS = [
    dict(first_name='Marcus', last_name='Hill', username='demo_marcus'),
    dict(first_name='Jenna', last_name='Cole', username='demo_jenna'),
]

# (name, city, unit prefix, unit count)
FLEETS = [
    ('Arkansas Freight Lines', 'Little Rock', 'AFL', 14),
    ('Metro Rentals', 'North Little Rock', 'MR', 9),
    ('Capitol City Plumbing', 'Little Rock', 'CCP', 6),
    ('Riverside Landscaping', 'Maumelle', 'RL', 5),
    ('Ozark Delivery Co.', 'Conway', 'ODC', 8),
]

# (name, phone, year, make, model)
INDIVIDUALS = [
    ('Dana Whitfield', '501-555-0142', 2021, 'Toyota', 'RAV4'),
    ('Luis Ortega', '501-555-0167', 2018, 'Ford', 'F-150'),
    ('Priya Nair', '501-555-0113', 2022, 'Honda', 'Civic'),
    ('Tom Bradshaw', '501-555-0190', 2016, 'Chevrolet', 'Silverado'),
    ('Kelsey Monroe', '501-555-0128', 2020, 'Subaru', 'Outback'),
    ('Andre Pickett', '501-555-0155', 2019, 'Jeep', 'Wrangler'),
    ('Maria Santos', '501-555-0171', 2023, 'Hyundai', 'Tucson'),
]

DAMAGE_TYPES = ['Chip', 'Chip', 'Chip', 'Crack', 'Half-Moon']


class Command(BaseCommand):
    help = 'Create (or rebuild) the fictional Clearview Auto Glass demo shop.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Delete the demo shop first, then rebuild it.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'seed_demo_shop creates users with a known password and only '
                'runs with DEBUG=True. It is for screenshots and local QA.')

        self.rng = random.Random(2026)
        self.now = timezone.now()

        existing = Tenant.objects.filter(slug=DEMO_SLUG).first()
        if existing and not options['reset']:
            self.stdout.write(self.style.WARNING(
                f"Demo shop '{existing.name}' already exists (tenant {existing.pk}). "
                'Pass --reset to rebuild it.'))
            return
        if existing:
            self._teardown(existing)

        with transaction.atomic():
            tenant = self._make_shop()
            techs = self._make_team(tenant)
            fleets, individuals = self._make_customers(tenant, techs)
            jobs = self._make_jobs(tenant, techs, fleets, individuals)
            self._make_invoices(tenant, jobs)
            self._make_portal_user(fleets[0])

        self.stdout.write(self.style.SUCCESS(
            f"Demo shop ready: '{tenant.name}' (tenant {tenant.pk}). "
            f"Owner {OWNER['email']} / {DEMO_PASSWORD}; "
            f"portal contact fleet@{DEMO_DOMAIN} / {DEMO_PASSWORD}."))

    # ------------------------------------------------------------------ teardown

    def _teardown(self, tenant):
        """Invoices → jobs → customers → users → tenant.

        Payments PROTECT their invoice, invoice lines PROTECT their jobs, and
        the soft-delete managers hide trashed rows, so this goes through
        ``all_objects`` in that order.
        """
        self.stdout.write(f'Removing existing demo shop (tenant {tenant.pk})...')
        Payment.objects.filter(invoice__tenant=tenant).delete()
        Invoice.all_objects.filter(tenant=tenant).delete()
        Repair.all_objects.filter(tenant=tenant).delete()
        Replacement.all_objects.filter(tenant=tenant).delete()
        portal_users = list(User.objects.filter(customeruser__customer__tenant=tenant))
        Customer.all_objects.filter(tenant=tenant).delete()
        member_users = list(User.objects.filter(tenant_memberships__tenant=tenant))
        tenant.delete()
        for user in portal_users + member_users:
            user.delete()

    # --------------------------------------------------------------------- shop

    def _make_shop(self):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            slug='trial', defaults={'name': 'Trial', 'monthly_price': 0,
                                    'trial_days': 30, 'is_active': True})
        result = create_tenant_with_owner(
            business_name='Clearview Auto Glass', email=OWNER['email'],
            password=DEMO_PASSWORD, first_name=OWNER['first_name'],
            last_name=OWNER['last_name'])
        tenant = result['tenant']
        tenant.slug = DEMO_SLUG
        tenant.business_phone = '(501) 555-0100'
        tenant.business_email = f'hello@{DEMO_DOMAIN}'
        tenant.business_address = '4100 Cantrell Rd, Little Rock, AR 72202'
        tenant.services_offered = 'both'
        tenant.trial_started_at = self.now - timedelta(days=200)

        pro = SubscriptionPlan.objects.filter(slug='pro').first()
        if pro is not None:
            tenant.plan = 'pro'
            tenant.subscription_plan = pro
        tenant.subscription_status = 'active'
        tenant.save()
        tenant.mark_subscription_active()

        owner_tech = Technician.objects.get(user=result['user'])
        owner_tech.can_replace = True
        owner_tech.phone_number = '501-555-0100'
        owner_tech.save()

        # An established shop has long since finished (and dismissed) the
        # setup checklist and the trial banner.
        OnboardingState.objects.update_or_create(tenant=tenant, defaults={
            'wizard_completed_at': self.now - timedelta(days=199),
            'checklist_dismissed_at': self.now - timedelta(days=190),
            'trial_banner_dismissed_at': self.now - timedelta(days=199),
        })

        config = BillingConfig.get_for_tenant(tenant)
        config.tax_enabled = True
        config.tax_configured = True
        config.save()
        TaxRate.objects.create(
            tenant=tenant, city='Little Rock', state='AR',
            state_rate=Decimal('6.500'), is_active=True)
        return tenant

    def _make_team(self, tenant):
        techs = [Technician.objects.get(tenant=tenant, user__email=OWNER['email'])]
        group, _ = Group.objects.get_or_create(name='Technicians')
        for spec in TECHS:
            user = User.objects.create_user(
                spec['username'], f"{spec['username']}@{DEMO_DOMAIN}", DEMO_PASSWORD,
                first_name=spec['first_name'], last_name=spec['last_name'])
            user.groups.add(group)
            TenantMembership.objects.create(
                tenant=tenant, user=user, role='technician', is_active=True)
            techs.append(Technician.objects.create(
                tenant=tenant, user=user, is_active=True,
                can_repair=True, can_replace=(spec['username'] == 'demo_marcus'),
                phone_number='501-555-01%02d' % self.rng.randint(10, 99)))
        return techs

    # ---------------------------------------------------------------- customers

    def _make_customers(self, tenant, techs):
        fleets = []
        for i, (name, city, prefix, count) in enumerate(FLEETS):
            fleets.append(Customer.objects.create(
                tenant=tenant, customer_type='FLEET', name=name,
                email=f"{prefix.lower()}-fleet@{DEMO_DOMAIN}",
                phone='501-555-02%02d' % (10 + i),
                address=f'{1200 + 310 * i} Industrial Dr', city=city,
                state='AR', zip_code='722%02d' % (i + 1),
                primary_technician=techs[i % len(techs)]))
            fleets[-1]._units = [f'{prefix}-{n:03d}' for n in range(101, 101 + count)]
        individuals = []
        for i, (name, phone, year, make, model) in enumerate(INDIVIDUALS):
            first = name.split()[0].lower()
            individuals.append(Customer.objects.create(
                tenant=tenant, customer_type='RETAIL', name=name,
                email=f'{first}@{DEMO_DOMAIN}', phone=phone,
                city='Little Rock', state='AR', zip_code='72205'))
            individuals[-1]._vehicle = (year, make, model)
        return fleets, individuals

    # --------------------------------------------------------------------- jobs

    def _service_time(self, days_ago):
        """A workday-ish timestamp `days_ago` days back."""
        base = self.now - timedelta(days=days_ago)
        return base.replace(hour=self.rng.randint(8, 16),
                            minute=self.rng.choice([0, 15, 30, 45]),
                            second=0, microsecond=0)

    def _make_jobs(self, tenant, techs, fleets, individuals):
        """~45 repairs and ~9 replacements over the last 60 days.

        Yesterday and today hold a spread of live statuses so the dashboard's
        queue and the jobs list both have something in flight.
        """
        jobs = []
        rng = self.rng

        def repair(customer, days_ago, status, tech, **extra):
            job = Repair.objects.create(
                tenant=tenant, customer=customer, technician=tech,
                damage_type=rng.choice(DAMAGE_TYPES), queue_status=status,
                service_date=self._service_time(days_ago),
                windshield_temperature=rng.choice([68.0, 72.0, 77.0, 84.0]),
                **extra)
            jobs.append(job)
            return job

        def replacement(customer, days_ago, status, tech, **extra):
            job = Replacement.objects.create(
                tenant=tenant, customer=customer, technician=tech,
                glass_position='WINDSHIELD', queue_status=status,
                glass_type=rng.choice(['OEM', 'AFTERMARKET']),
                parts_cost=Decimal(rng.choice(['185.00', '240.00', '312.00', '395.00'])),
                labor_cost=Decimal(rng.choice(['120.00', '150.00'])),
                service_date=self._service_time(days_ago),
                **extra)
            jobs.append(job)
            return job

        replace_techs = [t for t in techs if t.can_replace]

        # History: completed work, oldest first so repair counts climb naturally.
        for days_ago in range(60, 1, -1):
            for _ in range(rng.choice([0, 0, 1, 1, 1, 2])):
                if rng.random() < 0.72:
                    fleet = rng.choice(fleets)
                    repair(fleet, days_ago, 'COMPLETED', rng.choice(techs),
                           unit_number=rng.choice(fleet._units))
                else:
                    person = rng.choice(individuals)
                    year, make, model = person._vehicle
                    repair(person, days_ago, 'COMPLETED', rng.choice(techs),
                           vehicle_year=year, vehicle_make=make, vehicle_model=model)
            if days_ago % 7 == 3:
                fleet = rng.choice(fleets)
                replacement(fleet, days_ago, 'COMPLETED', rng.choice(replace_techs),
                            unit_number=rng.choice(fleet._units))

        # Yesterday: two done, one still open.
        repair(fleets[0], 1, 'COMPLETED', techs[1], unit_number=fleets[0]._units[3])
        year, make, model = individuals[2]._vehicle
        repair(individuals[2], 1, 'COMPLETED', techs[0],
               vehicle_year=year, vehicle_make=make, vehicle_model=model)
        replacement(individuals[3], 1, 'IN_PROGRESS', replace_techs[0],
                    vehicle_year=individuals[3]._vehicle[0],
                    vehicle_make=individuals[3]._vehicle[1],
                    vehicle_model=individuals[3]._vehicle[2])

        # Today: the live queue.
        repair(fleets[1], 0, 'COMPLETED', techs[2], unit_number=fleets[1]._units[0])
        repair(fleets[1], 0, 'IN_PROGRESS', techs[2], unit_number=fleets[1]._units[1])
        repair(fleets[4], 0, 'APPROVED', techs[1], unit_number=fleets[4]._units[2],
               scheduled_for=self.now.replace(hour=14, minute=0, second=0, microsecond=0))
        year, make, model = individuals[0]._vehicle
        repair(individuals[0], 0, 'APPROVED', techs[0],
               vehicle_year=year, vehicle_make=make, vehicle_model=model,
               scheduled_for=self.now.replace(hour=15, minute=30, second=0, microsecond=0))
        replacement(fleets[2], 0, 'REQUESTED', replace_techs[0],
                    unit_number=fleets[2]._units[1],
                    customer_notes='Rock hit on I-30 this morning, crack is spreading '
                                   'across the driver side.')

        # The portal contact's fleet (fleets[0]) has one job in progress and
        # one priced replacement waiting on their approval, so the customer
        # portal has something in flight to show.
        repair(fleets[0], 0, 'IN_PROGRESS', techs[1], unit_number=fleets[0]._units[7])
        awaiting = replacement(fleets[0], 0, 'APPROVED', replace_techs[0],
                               unit_number=fleets[0]._units[9])
        # Shop-created jobs auto-approve on save (resolve_initial_shop_status);
        # this one is meant to sit in the customer's approval queue.
        Replacement.objects.filter(pk=awaiting.pk).update(queue_status='PENDING')
        return jobs

    # ----------------------------------------------------------------- invoices

    def _make_invoices(self, tenant, jobs):
        """Invoice completed work per customer per week; most get paid.

        A couple are left SENT and one overdue so the receivables card has
        something to say.
        """
        rng = self.rng
        service = InvoiceTrackingService(tenant=tenant)
        completed = [j for j in jobs if j.queue_status == 'COMPLETED'
                     and j.service_date < self.now - timedelta(days=1)]

        buckets = {}
        for job in completed:
            week = (self.now.date() - job.service_date.date()).days // 7
            buckets.setdefault((job.customer_id, week), []).append(job)

        for (customer_id, week), batch in sorted(buckets.items(), key=lambda kv: -kv[0][1]):
            invoice = service.create_invoice_from_services(
                customer=batch[0].customer, services=batch)
            invoiced_on = max(j.service_date for j in batch) + timedelta(days=1)
            Invoice.objects.filter(pk=invoice.pk).update(
                invoice_date=invoiced_on.date(),
                due_date=invoiced_on.date() + timedelta(days=30),
                created_at=invoiced_on)
            invoice.refresh_from_db()
            invoice.mark_sent()
            Invoice.objects.filter(pk=invoice.pk).update(sent_at=invoiced_on)

            age_days = (self.now - invoiced_on).days
            if age_days > 40 and rng.random() < 0.85 or 8 < age_days <= 40 and rng.random() < 0.7:
                paid_on = invoiced_on + timedelta(days=rng.randint(2, 21))
                service.record_payment(
                    invoice, invoice.total,
                    payment_method=rng.choice(['CREDIT_CARD', 'CHECK', 'ACH']),
                    payment_date=min(paid_on, self.now))

    # -------------------------------------------------------------- portal user

    def _make_portal_user(self, fleet):
        user = User.objects.create_user(
            'demo_fleet_contact', f'fleet@{DEMO_DOMAIN}', DEMO_PASSWORD,
            first_name='Renee', last_name='Park')
        CustomerUser.objects.create(user=user, customer=fleet, is_primary_contact=True)
