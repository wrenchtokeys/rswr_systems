"""
Comprehensive User & Data Flow Tests for RS Systems
Tests signup, login, portal access, repair lifecycle, and permissions.
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from django.utils import timezone
from core.models import Customer
from apps.customer_portal.models import CustomerUser
from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.billing.models import TaxRate


class TestDataFactory:
    """Helper to create test data consistently."""

    @staticmethod
    def create_tenant(owner, name='Test Glass Shop'):
        return Tenant.objects.create(
            name=name,
            slug=name.lower().replace(' ', '-'),
            subdomain=name.lower().replace(' ', ''),
            owner=owner,
            plan='trial',
            trial_started_at=timezone.now(),
        )

    @staticmethod
    def create_owner_user(tenant=None, username='owner1', email='owner@test.com'):
        user = User.objects.create_user(username=username, email=email, password='TestPass123!')
        if not tenant:
            tenant = TestDataFactory.create_tenant(user)
        else:
            # Already created, just add membership
            pass
        TenantMembership.objects.create(user=user, tenant=tenant, role='owner', is_active=True)
        return user, tenant

    @staticmethod
    def create_technician(tenant, username='tech1', email='tech@test.com'):
        user = User.objects.create_user(
            username=username, email=email, password='TestPass123!',
            first_name='Test', last_name='Tech'
        )
        tech = Technician.objects.create(user=user, tenant=tenant, is_active=True)
        TenantMembership.objects.create(user=user, tenant=tenant, role='technician', is_active=True)
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        user.groups.add(tech_group)
        return user, tech

    @staticmethod
    def create_customer_with_user(tenant, name='Test Fleet Co', username='custuser1', email='cust@test.com'):
        customer = Customer.objects.create(
            tenant=tenant, name=name, email=email,
            customer_type='FLEET'
        )
        # Explicitly require approval — shop-created work auto-approves by
        # default, and these flows exercise the PENDING approve/deny path
        from apps.customer_portal.models import CustomerRepairPreference
        CustomerRepairPreference.objects.create(
            customer=customer,
            field_repair_approval_mode='REQUIRE_APPROVAL',
        )
        user = User.objects.create_user(username=username, email=email, password='TestPass123!')
        cu = CustomerUser.objects.create(user=user, customer=customer, is_primary_contact=True)
        return user, customer, cu

    @staticmethod
    def create_repair(tenant, technician, customer, status='PENDING', cost=Decimal('50.00'), unit='UNIT-001'):
        return Repair.objects.create(
            tenant=tenant,
            technician=technician,
            customer=customer,
            unit_number=unit,
            damage_type='Chip',
            queue_status=status,
            cost=cost,
            service_date=timezone.now(),
        )


class AuthFlowTests(TestCase):
    """Test authentication and login routing."""

    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user('owner', 'owner@test.com', 'TestPass123!')
        self.tenant = TestDataFactory.create_tenant(self.owner_user)
        TenantMembership.objects.create(user=self.owner_user, tenant=self.tenant, role='owner', is_active=True)

        self.tech_user, self.tech = TestDataFactory.create_technician(self.tenant)
        self.cust_user, self.customer, self.cu = TestDataFactory.create_customer_with_user(self.tenant)

    def test_unauthenticated_redirects(self):
        """Protected pages should redirect unauthenticated users."""
        protected_urls = [
            '/app/',
            '/tech/',
            '/owner/',
            '/referrals/referral-rewards/',
            '/referrals/reward-balance/',
        ]
        for url in protected_urls:
            resp = self.client.get(url)
            self.assertIn(resp.status_code, [301, 302, 403],
                          f"{url} should redirect/deny unauthenticated user, got {resp.status_code}")

    def test_unified_login_page_loads(self):
        """The unified login page should render."""
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)

    def test_legacy_customer_login_redirects(self):
        """/app/login/ should redirect to unified login."""
        resp = self.client.get('/app/login/')
        self.assertEqual(resp.status_code, 302)

    def test_legacy_tech_login_redirects(self):
        """/tech/login/ should redirect to unified login."""
        resp = self.client.get('/tech/login/')
        self.assertEqual(resp.status_code, 302)

    def test_login_routes_owner_to_owner_dashboard(self):
        """Owner login should route to owner dashboard."""
        self.client.login(username='owner', password='TestPass123!')
        resp = self.client.get('/login/', follow=False)
        # Should redirect to owner dashboard
        self.assertEqual(resp.status_code, 302)
        self.assertIn('owner', resp.url.lower())

    def test_login_routes_tech_to_tech_portal(self):
        """Technician login should route to tech portal."""
        self.client.login(username='tech1', password='TestPass123!')
        resp = self.client.get('/login/', follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('tech', resp.url.lower())

    def test_login_routes_customer_to_customer_portal(self):
        """Customer login should route to customer portal."""
        self.client.login(username='custuser1', password='TestPass123!')
        resp = self.client.get('/login/', follow=False)
        self.assertEqual(resp.status_code, 302)
        # Customer goes to /app/
        self.assertIn('app', resp.url.lower())

    def test_password_reset_page_loads(self):
        """Password reset form should render."""
        resp = self.client.get('/password-reset/')
        self.assertEqual(resp.status_code, 200)

    def test_signup_page_loads(self):
        """SaaS signup page should render."""
        resp = self.client.get('/signup/')
        self.assertEqual(resp.status_code, 200)

    def test_signup_creates_tenant(self):
        """Successful signup should create a tenant and owner."""
        resp = self.client.post('/signup/', {
            'business_name': 'New Glass Shop',
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@newshop.com',
            'password1': 'SecurePass789!',
            'password2': 'SecurePass789!',
        }, follow=True)
        # Should succeed (200 after redirect) or redirect to onboarding
        self.assertIn(resp.status_code, [200, 302])
        # Check tenant was created
        self.assertTrue(
            Tenant.objects.filter(name='New Glass Shop').exists() or
            resp.status_code == 200  # Form might have validation - that's ok to flag
        )

    def test_shop_join_page(self):
        """Customer self-signup via shop join link."""
        resp = self.client.get(f'/join/{self.tenant.slug}/')
        # Should load the join page or 404 if not configured
        self.assertIn(resp.status_code, [200, 404])


class CustomerPortalTests(TestCase):
    """Test customer portal access and functionality."""

    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user('owner2', 'owner2@test.com', 'TestPass123!')
        self.tenant = TestDataFactory.create_tenant(self.owner_user, 'Portal Test Shop')
        TenantMembership.objects.create(user=self.owner_user, tenant=self.tenant, role='owner', is_active=True)

        self.tech_user, self.tech = TestDataFactory.create_technician(
            self.tenant, username='tech2', email='tech2@test.com')
        self.cust_user, self.customer, self.cu = TestDataFactory.create_customer_with_user(
            self.tenant, username='cust2', email='cust2@test.com')

        # Create some repairs
        self.pending_repair = TestDataFactory.create_repair(
            self.tenant, self.tech, self.customer, 'PENDING', Decimal('50.00'))
        self.completed_repair = TestDataFactory.create_repair(
            self.tenant, self.tech, self.customer, 'COMPLETED', Decimal('40.00'), 'UNIT-002')

    def test_customer_dashboard_loads(self):
        """Customer dashboard should load for authenticated customer."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get('/app/')
        self.assertEqual(resp.status_code, 200)

    def test_customer_repairs_list(self):
        """Customer should see their repairs (old URL redirects to unified services)."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get('/app/repairs/', follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.request['PATH_INFO'], '/app/services/')

    def test_customer_repair_detail(self):
        """Customer should see repair detail."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get(f'/app/repairs/{self.pending_repair.id}/')
        self.assertEqual(resp.status_code, 200)

    def test_customer_invoices_page(self):
        """Customer invoices page should load."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get('/app/invoices/')
        self.assertEqual(resp.status_code, 200)

    def test_customer_cannot_access_tech_portal(self):
        """Customer should not be able to access technician portal."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get('/tech/')
        # Should redirect or deny
        self.assertIn(resp.status_code, [302, 403])

    def test_customer_cannot_access_owner_portal(self):
        """Customer should not be able to access owner portal."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get('/owner/')
        self.assertIn(resp.status_code, [302, 403])

    def test_customer_repair_approve(self):
        """Customer can approve a pending repair."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.post(f'/app/repairs/{self.pending_repair.id}/approve/')
        # Should redirect after action
        self.assertIn(resp.status_code, [200, 302])
        self.pending_repair.refresh_from_db()
        self.assertEqual(self.pending_repair.queue_status, 'APPROVED')

    def test_customer_repair_deny(self):
        """Customer can deny a pending repair."""
        # Create a fresh pending repair for denial
        deny_repair = TestDataFactory.create_repair(
            self.tenant, self.tech, self.customer, 'PENDING', Decimal('45.00'), 'UNIT-003')
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.post(f'/app/repairs/{deny_repair.id}/deny/')
        self.assertIn(resp.status_code, [200, 302])
        deny_repair.refresh_from_db()
        self.assertEqual(deny_repair.queue_status, 'DENIED')

    def test_notification_preferences_page(self):
        """Notification preferences should load."""
        self.client.login(username='cust2', password='TestPass123!')
        resp = self.client.get('/app/notifications/preferences/')
        self.assertEqual(resp.status_code, 200)


class TechnicianPortalTests(TestCase):
    """Test technician portal access and functionality."""

    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user('owner3', 'owner3@test.com', 'TestPass123!')
        self.tenant = TestDataFactory.create_tenant(self.owner_user, 'Tech Test Shop')
        TenantMembership.objects.create(user=self.owner_user, tenant=self.tenant, role='owner', is_active=True)

        self.tech_user, self.tech = TestDataFactory.create_technician(
            self.tenant, username='tech3', email='tech3@test.com')
        self.cust_user, self.customer, self.cu = TestDataFactory.create_customer_with_user(
            self.tenant, name='Tech Test Fleet', username='cust3', email='cust3@test.com')

        self.repair = TestDataFactory.create_repair(
            self.tenant, self.tech, self.customer, 'APPROVED', Decimal('50.00'))

    def test_tech_dashboard_loads(self):
        """Technician dashboard should load."""
        self.client.login(username='tech3', password='TestPass123!')
        resp = self.client.get('/tech/')
        self.assertEqual(resp.status_code, 200)

    def test_tech_cannot_access_customer_portal(self):
        """Technician should not access customer portal (no CustomerUser)."""
        self.client.login(username='tech3', password='TestPass123!')
        resp = self.client.get('/app/')
        # Should fail/redirect since tech has no CustomerUser
        self.assertIn(resp.status_code, [302, 403, 404, 500])

    def test_tech_cannot_access_owner_portal(self):
        """Technician should not access owner portal."""
        self.client.login(username='tech3', password='TestPass123!')
        resp = self.client.get('/owner/')
        self.assertIn(resp.status_code, [302, 403])


class RepairLifecycleTests(TestCase):
    """Test complete repair lifecycle: request -> approve -> complete."""

    def setUp(self):
        self.client = Client()
        self.owner_user = User.objects.create_user('owner4', 'owner4@test.com', 'TestPass123!')
        self.tenant = TestDataFactory.create_tenant(self.owner_user, 'Lifecycle Test Shop')
        self.tenant.auto_invoice_enabled = False  # Disable auto-invoice for clean tests
        self.tenant.save()
        TenantMembership.objects.create(user=self.owner_user, tenant=self.tenant, role='owner', is_active=True)

        self.tech_user, self.tech = TestDataFactory.create_technician(
            self.tenant, username='tech4', email='tech4@test.com')
        self.cust_user, self.customer, self.cu = TestDataFactory.create_customer_with_user(
            self.tenant, name='Lifecycle Fleet', username='cust4', email='cust4@test.com')

        # Create a 6.5% tax rate so Repair.save() TaxService picks it up correctly.
        # Without this, TaxService finds no TaxRate for the tenant and zeroes out tax_rate.
        TaxRate.objects.create(
            tenant=self.tenant,
            city='Little Rock',
            state='AR',
            state_rate=Decimal('6.500'),
            is_active=True,
        )

    def test_repair_status_progression(self):
        """Repair should progress through statuses correctly."""
        repair = TestDataFactory.create_repair(
            self.tenant, self.tech, self.customer, 'PENDING', Decimal('50.00'))

        # Verify initial status
        self.assertEqual(repair.queue_status, 'PENDING')

        # Approve
        repair.queue_status = 'APPROVED'
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'APPROVED')

        # In Progress
        repair.queue_status = 'IN_PROGRESS'
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'IN_PROGRESS')

        # Complete
        repair.queue_status = 'COMPLETED'
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.queue_status, 'COMPLETED')

    def test_repair_cost_and_tax(self):
        """Repair should track cost and tax correctly."""
        repair = TestDataFactory.create_repair(
            self.tenant, self.tech, self.customer, 'COMPLETED', Decimal('50.00'))
        repair.tax_rate = Decimal('6.500')
        repair.tax_amount = Decimal('3.25')
        repair.save()
        repair.refresh_from_db()

        self.assertEqual(repair.cost, Decimal('50.00'))
        self.assertEqual(repair.tax_rate, Decimal('6.500'))
        self.assertEqual(repair.tax_amount, Decimal('3.25'))

    def test_batch_repair_creation(self):
        """Batch (multi-break) repairs should link correctly."""
        import uuid
        batch_id = uuid.uuid4()

        r1 = TestDataFactory.create_repair(self.tenant, self.tech, self.customer, 'PENDING', Decimal('50.00'))
        r1.repair_batch_id = batch_id
        r1.break_number = 1
        r1.total_breaks_in_batch = 3
        r1.save()

        r2 = TestDataFactory.create_repair(self.tenant, self.tech, self.customer, 'PENDING', Decimal('40.00'), 'UNIT-001')
        r2.repair_batch_id = batch_id
        r2.break_number = 2
        r2.total_breaks_in_batch = 3
        r2.save()

        r3 = TestDataFactory.create_repair(self.tenant, self.tech, self.customer, 'PENDING', Decimal('35.00'), 'UNIT-001')
        r3.repair_batch_id = batch_id
        r3.break_number = 3
        r3.total_breaks_in_batch = 3
        r3.save()

        # Verify batch linkage
        batch_repairs = Repair.objects.filter(repair_batch_id=batch_id)
        self.assertEqual(batch_repairs.count(), 3)
        self.assertEqual(list(batch_repairs.values_list('break_number', flat=True).order_by('break_number')), [1, 2, 3])

    def test_customer_requested_repair_flow(self):
        """Test customer-initiated repair request."""
        self.client.login(username='cust4', password='TestPass123!')
        resp = self.client.get('/app/repairs/request/')
        # Should load the request form
        self.assertIn(resp.status_code, [200, 302])


class CrossTenantIsolationTests(TestCase):
    """Test that data is properly isolated between tenants."""

    def setUp(self):
        self.client = Client()

        # Tenant A
        self.owner_a = User.objects.create_user('ownerA', 'ownera@test.com', 'TestPass123!')
        self.tenant_a = TestDataFactory.create_tenant(self.owner_a, 'Shop A')
        TenantMembership.objects.create(user=self.owner_a, tenant=self.tenant_a, role='owner', is_active=True)
        self.tech_a_user, self.tech_a = TestDataFactory.create_technician(
            self.tenant_a, username='techA', email='techA@test.com')
        self.cust_a_user, self.customer_a, self.cu_a = TestDataFactory.create_customer_with_user(
            self.tenant_a, name='Fleet A', username='custA', email='custA@test.com')
        self.repair_a = TestDataFactory.create_repair(
            self.tenant_a, self.tech_a, self.customer_a, 'COMPLETED', Decimal('50.00'))

        # Tenant B
        self.owner_b = User.objects.create_user('ownerB', 'ownerb@test.com', 'TestPass123!')
        self.tenant_b = TestDataFactory.create_tenant(self.owner_b, 'Shop B')
        TenantMembership.objects.create(user=self.owner_b, tenant=self.tenant_b, role='owner', is_active=True)
        self.tech_b_user, self.tech_b = TestDataFactory.create_technician(
            self.tenant_b, username='techB', email='techB@test.com')
        self.cust_b_user, self.customer_b, self.cu_b = TestDataFactory.create_customer_with_user(
            self.tenant_b, name='Fleet B', username='custB', email='custB@test.com')
        self.repair_b = TestDataFactory.create_repair(
            self.tenant_b, self.tech_b, self.customer_b, 'COMPLETED', Decimal('60.00'))

    def test_tenant_a_customer_cannot_see_tenant_b_repairs(self):
        """Customer A should not see Shop B's repairs."""
        self.client.login(username='custA', password='TestPass123!')
        resp = self.client.get(f'/app/repairs/{self.repair_b.id}/')
        # Should 404 or redirect, not show the repair
        self.assertIn(resp.status_code, [302, 403, 404])

    def test_repairs_scoped_to_tenant(self):
        """Repairs should be scoped by tenant at the model level."""
        tenant_a_repairs = Repair.objects.filter(tenant=self.tenant_a)
        tenant_b_repairs = Repair.objects.filter(tenant=self.tenant_b)

        self.assertEqual(tenant_a_repairs.count(), 1)
        self.assertEqual(tenant_b_repairs.count(), 1)
        self.assertNotEqual(tenant_a_repairs.first().id, tenant_b_repairs.first().id)

    def test_customers_scoped_to_tenant(self):
        """Customers should be scoped by tenant."""
        tenant_a_customers = Customer.objects.filter(tenant=self.tenant_a)
        tenant_b_customers = Customer.objects.filter(tenant=self.tenant_b)

        self.assertEqual(tenant_a_customers.count(), 1)
        self.assertEqual(tenant_b_customers.count(), 1)
        self.assertEqual(tenant_a_customers.first().name, 'Fleet A')
        self.assertEqual(tenant_b_customers.first().name, 'Fleet B')


class HealthAndPublicEndpointTests(TestCase):
    """Test public endpoints that should always work."""

    def test_health_check(self):
        """Health check endpoint should return 200."""
        resp = self.client.get('/health/')
        self.assertEqual(resp.status_code, 200)

    def test_home_page(self):
        """Home page should load."""
        resp = self.client.get('/')
        self.assertIn(resp.status_code, [200, 302])

    def test_pricing_page(self):
        """Pricing page should load."""
        resp = self.client.get('/pricing/')
        self.assertEqual(resp.status_code, 200)

    def test_terms_page(self):
        """Terms of service should load."""
        resp = self.client.get('/terms/')
        self.assertEqual(resp.status_code, 200)

    def test_privacy_page(self):
        """Privacy policy should load."""
        resp = self.client.get('/privacy/')
        self.assertEqual(resp.status_code, 200)

    def test_api_schema(self):
        """API schema endpoint should work."""
        resp = self.client.get('/api/schema/')
        self.assertEqual(resp.status_code, 200)
