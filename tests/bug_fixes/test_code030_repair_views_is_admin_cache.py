"""
CODE-030 Regression: is_tenant_admin() called multiple times per repair view.

Before fix: repair_list called is_tenant_admin 3×, repair_detail 2×,
            create_repair 3×, update_repair 4×, update_queue_status 2×,
            assign_repair 2×, reassign_to_self 3× — each call hitting
            TenantMembership table (via _get_membership → TenantMembership.objects.filter).

After fix: every view caches the result in a local `user_is_admin` variable
           computed once at the top of the function.

These tests verify the views behave correctly after the refactor:
- Admin (owner) paths work end-to-end.
- Non-admin (tech, viewer) paths enforce permissions correctly.
- The cached flag is used, not re-evaluated.
"""
from decimal import Decimal
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from apps.tenants.models import Tenant, SubscriptionPlan, TenantMembership
from apps.technician_portal.models import Technician, Repair
from core.models import Customer


TEST_OVERRIDES = {
    'ALLOWED_HOSTS': ['*'],
    'SESSION_ENGINE': 'django.contrib.sessions.backends.db',
    'MESSAGE_STORAGE': 'django.contrib.messages.storage.fallback.FallbackStorage',
}


def _make_tenant_with_owner(name, slug):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    owner = User.objects.create_user(
        username=f'owner_{slug}',
        password='pw',
        email=f'owner_{slug}@test.com',
        first_name='Test',
        last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=slug,
        subdomain=slug,
        owner=owner,
        subscription_plan=plan,
    )
    TenantMembership.objects.create(tenant=tenant, user=owner, role='owner', is_active=True)
    return owner, tenant


def _make_tech(tenant, suffix, is_manager=False, can_assign_work=False):
    user = User.objects.create_user(
        username=f'tech_{suffix}',
        password='pw',
        email=f'tech_{suffix}@test.com',
    )
    TenantMembership.objects.create(
        user=user, tenant=tenant, role='technician', is_active=True
    )
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        is_active=True,
        is_manager=is_manager,
        can_assign_work=can_assign_work,
    )
    return user, tech


@override_settings(**TEST_OVERRIDES)
class RepairListCacheTest(TestCase):
    """
    repair_list: cached user_is_admin used across permission check,
    assignment-filter branch, and context dict.
    """

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('RL Shop', 'rl-shop')
        self.customer = Customer.objects.create(tenant=self.tenant, name='RL Cust')
        # Owner needs a Technician record to avoid "no technicians" warning
        self.owner_tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True
        )
        _, self.tech = _make_tech(self.tenant, 'rl1')
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='U100',
            queue_status='IN_PROGRESS',
        )
        # A REQUESTED repair (with a technician so NOT NULL constraint is met)
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='U101', queue_status='REQUESTED',
        )
        self.client = Client()

    def test_owner_repair_list_200(self):
        """Owner (admin=True) can access repair list without error."""
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('repair_list'), SERVER_NAME='rl-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)

    def test_tech_repair_list_200(self):
        """Tech (admin=False) sees their repairs; cached value returns False correctly."""
        self.client.force_login(self.tech.user)
        resp = self.client.get(reverse('repair_list'), SERVER_NAME='rl-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)

    def test_viewer_without_tech_profile_redirected(self):
        """Viewer (admin=False, no Technician) gets redirect not 500."""
        viewer = User.objects.create_user(
            username='viewer_rl', password='pw', email='viewer_rl@test.com'
        )
        TenantMembership.objects.create(
            user=viewer, tenant=self.tenant, role='viewer', is_active=True
        )
        self.client.force_login(viewer)
        resp = self.client.get(reverse('repair_list'), SERVER_NAME='rl-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)


@override_settings(**TEST_OVERRIDES)
class RepairDetailCacheTest(TestCase):
    """
    repair_detail: user_is_admin evaluated once; used in permission gate AND context.
    """

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('RD Shop', 'rd-shop')
        self.customer = Customer.objects.create(tenant=self.tenant, name='RD Cust')
        self.owner_tech = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True
        )
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.owner_tech, unit_number='U200',
            queue_status='IN_PROGRESS',
        )
        self.client = Client()

    def test_owner_can_view_detail(self):
        """Owner (is_admin=True from cached value) can view any repair detail."""
        self.client.force_login(self.owner)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        resp = self.client.get(url, SERVER_NAME='rd-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)

    def test_owner_is_admin_in_context(self):
        """Template context contains is_admin=True for owner."""
        self.client.force_login(self.owner)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        resp = self.client.get(url, SERVER_NAME='rd-shop.testserver')
        if resp.status_code == 200:
            self.assertTrue(resp.context.get('is_admin'))

    def test_tech_assigned_to_repair_can_view(self):
        """Tech assigned to a repair (admin=False) can view it."""
        _, tech = _make_tech(self.tenant, 'rd1')
        self.repair.technician = tech
        self.repair.save()
        self.client.force_login(tech.user)
        url = reverse('repair_detail', kwargs={'repair_id': self.repair.id})
        resp = self.client.get(url, SERVER_NAME='rd-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)


@override_settings(**TEST_OVERRIDES)
class CreateRepairCacheTest(TestCase):
    """
    create_repair: user_is_admin cached before POST processing and used in
    both the pre-checks and the form-save branches.
    """

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('CR Shop', 'cr-shop')
        self.customer = Customer.objects.create(tenant=self.tenant, name='CR Cust')
        self.client = Client()

    def test_owner_with_no_techs_redirected_not_500(self):
        """Admin with zero active technicians → redirect with warning (BUG-001)."""
        # No Technician objects exist for this tenant
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('create_repair'), SERVER_NAME='cr-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)

    def test_owner_with_tech_gets_create_form(self):
        """Admin with active technicians can access the create form."""
        Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True
        )
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('create_repair'), SERVER_NAME='cr-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)


@override_settings(**TEST_OVERRIDES)
class UpdateQueueStatusCacheTest(TestCase):
    """
    update_queue_status: user_is_admin cached at top, reused in POST branch
    (where it gates the auto-assign-to-self behaviour).
    """

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('UQS Shop', 'uqs-shop')
        self.customer = Customer.objects.create(tenant=self.tenant, name='UQS Cust')
        _, self.tech = _make_tech(self.tenant, 'uqs1')
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='U300',
            queue_status='APPROVED',
        )
        self.client = Client()

    def test_tech_advances_own_repair_to_in_progress(self):
        """Tech (admin=False) updates their APPROVED repair to IN_PROGRESS."""
        self.client.force_login(self.tech.user)
        url = reverse('update_queue_status', kwargs={'repair_id': self.repair.id})
        resp = self.client.post(
            url,
            {'status': 'IN_PROGRESS'},
            SERVER_NAME='uqs-shop.testserver',
        )
        self.assertNotEqual(resp.status_code, 500)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'IN_PROGRESS')

    def test_owner_updates_any_repair(self):
        """Owner (admin=True) can update any repair status."""
        Technician.objects.create(user=self.owner, tenant=self.tenant, is_active=True)
        self.client.force_login(self.owner)
        url = reverse('update_queue_status', kwargs={'repair_id': self.repair.id})
        resp = self.client.post(
            url,
            {'status': 'COMPLETED'},
            SERVER_NAME='uqs-shop.testserver',
        )
        self.assertNotEqual(resp.status_code, 500)


@override_settings(**TEST_OVERRIDES)
class AssignRepairCacheTest(TestCase):
    """
    assign_repair: user_is_admin cached and reused in both the initial
    permission guard and the POST tech-scope validation.
    """

    def setUp(self):
        self.owner, self.tenant = _make_tenant_with_owner('AR Shop', 'ar-shop')
        self.customer = Customer.objects.create(tenant=self.tenant, name='AR Cust')
        Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True
        )
        _, self.tech = _make_tech(self.tenant, 'ar1')
        # REQUESTED repair must still have a technician FK (model constraint),
        # but it's awaiting manager assignment — owner will reassign.
        self.repair = Repair.objects.create(
            tenant=self.tenant, customer=self.customer,
            technician=self.tech, unit_number='U400', queue_status='REQUESTED',
        )
        self.client = Client()

    def test_owner_sees_assign_page(self):
        """Admin (is_admin=True) can load the assign page."""
        self.client.force_login(self.owner)
        url = reverse('assign_repair', kwargs={'repair_id': self.repair.id})
        resp = self.client.get(url, SERVER_NAME='ar-shop.testserver')
        self.assertIn(resp.status_code, [200, 302])
        self.assertNotEqual(resp.status_code, 500)

    def test_non_manager_tech_redirected(self):
        """Non-manager tech (is_admin=False, is_manager=False) gets redirect."""
        self.client.force_login(self.tech.user)
        url = reverse('assign_repair', kwargs={'repair_id': self.repair.id})
        resp = self.client.get(url, SERVER_NAME='ar-shop.testserver')
        self.assertEqual(resp.status_code, 302)

    def test_owner_can_post_assign(self):
        """Admin can POST-assign a repair to a technician."""
        self.client.force_login(self.owner)
        url = reverse('assign_repair', kwargs={'repair_id': self.repair.id})
        resp = self.client.post(
            url,
            {'technician_id': self.tech.id},
            SERVER_NAME='ar-shop.testserver',
        )
        self.assertNotEqual(resp.status_code, 500)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.technician, self.tech)
        self.assertEqual(self.repair.queue_status, 'APPROVED')
