"""
CODE-264: Naive datetime warnings when filtering DateTimeField with date objects.

Bug: customer_repairs() and repair_list() used naive date objects
(timezone.now().date().replace(day=1) and datetime.strptime().date()) to filter
Repair.service_date (a DateTimeField).  Django coerces the date into a naive
datetime (midnight, no tzinfo), which:
  1. Triggers RuntimeWarning in Django 5.x (and will be an error in 6.0)
  2. Can produce incorrect results when the DB timezone ≠ UTC

Fix: Use timezone.make_aware(datetime.combine(date, time.min)) for aggregate
month/week start comparisons, and __date lookup for user-supplied date filters.

Tests confirm both portals render without RuntimeWarning.
"""
import warnings
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.utils import timezone
from django.contrib.auth.models import User, Group

from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


@override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
)
class NaiveDatetimeFilterTests(TestCase):
    """Verify repairs list views don't emit naive-datetime RuntimeWarnings."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('dt_owner', 'dt@test.com', 'pass')
        cls.tenant = Tenant.objects.create(
            name='Datetime Test Shop',
            slug='datetime-test',
            subscription_status='active',
            owner=cls.owner,
        )
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.owner, role='owner', is_active=True,
        )
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        cls.owner.groups.add(tech_group)
        cls.tech = Technician.objects.create(
            user=cls.owner, tenant=cls.tenant, is_manager=True, is_active=True,
        )
        cls.customer = Customer.objects.create(
            name='DT Customer', tenant=cls.tenant,
        )
        # Create a completed repair with aware datetime
        Repair.objects.create(
            tenant=cls.tenant,
            customer=cls.customer,
            technician=cls.tech,
            queue_status='COMPLETED',
            service_date=timezone.now() - timedelta(days=3),
            cost=Decimal('75.00'),
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.owner)
        # Promote RuntimeWarning to error so any naive datetime triggers a test failure
        self._warning_ctx = warnings.catch_warnings()
        self._warning_ctx.__enter__()
        warnings.simplefilter('error', RuntimeWarning)

    def tearDown(self):
        self._warning_ctx.__exit__(None, None, None)

    def test_customer_repairs_no_naive_warning(self):
        """GET /app/repairs/ should not emit a naive-datetime RuntimeWarning."""
        from apps.customer_portal.models import CustomerUser
        cu = CustomerUser.objects.create(
            user=self.owner, customer=self.customer, is_primary_contact=True,
        )
        resp = self.client.get('/app/repairs/')
        self.assertIn(resp.status_code, (200, 302))

    def test_customer_repairs_date_filter_no_naive_warning(self):
        """GET /app/repairs/?date_from=...&date_to=... should not emit a naive-datetime warning."""
        from apps.customer_portal.models import CustomerUser
        # Use get_or_create since test_customer_repairs_no_naive_warning may have created it
        cu, _ = CustomerUser.objects.get_or_create(
            user=self.owner, customer=self.customer,
            defaults={'is_primary_contact': True},
        )
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        resp = self.client.get(f'/app/repairs/?date_from={week_ago}&date_to={today}')
        self.assertIn(resp.status_code, (200, 302))

    def test_tech_repair_list_no_naive_warning(self):
        """GET /tech/repairs/ should not emit a naive-datetime RuntimeWarning."""
        resp = self.client.get('/tech/repairs/')
        self.assertIn(resp.status_code, (200, 302))

    def test_tech_repair_list_date_filter_no_naive_warning(self):
        """GET /tech/repairs/?date_from=...&date_to=... should not emit a naive-datetime warning."""
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        resp = self.client.get(f'/tech/repairs/?date_from={week_ago}&date_to={today}')
        self.assertIn(resp.status_code, (200, 302))
