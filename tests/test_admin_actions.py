"""
Admin Bulk Action Tests — Repair & Replacement

Tests bulk approve, deny, reset-to-pending, and reassign actions
for RepairAdmin and ReplacementAdmin.

Run with:
    python manage.py test tests.test_admin_actions -v 2
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from apps.technician_portal.models import Technician, Repair, Replacement, Customer
from apps.tenants.models import Tenant, SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner


class AdminActionTestBase(TestCase):
    """Shared setup for admin action tests."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_superuser(
            username='action_admin', email='admin@test.com', password='Test1234!'
        )
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Test Shop', email='owner@test.com',
            password='testpass123!', first_name='Test', last_name='Owner',
        )
        cls.tenant = result['tenant']
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, name='Fleet Co', email='fleet@test.com',
        )

        # Technician 1
        user1 = User.objects.create_user(
            username='tech1', email='tech1@test.com', password='Test1234!',
            first_name='Alice', last_name='Smith',
        )
        cls.tech1 = Technician.objects.create(
            user=user1, tenant=cls.tenant, is_active=True,
        )

        # Technician 2
        user2 = User.objects.create_user(
            username='tech2', email='tech2@test.com', password='Test1234!',
            first_name='Bob', last_name='Jones',
        )
        cls.tech2 = Technician.objects.create(
            user=user2, tenant=cls.tenant, is_active=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin_user)


class RepairAdminActionTests(AdminActionTestBase):
    """Tests for RepairAdmin bulk actions."""

    def _repair_url(self):
        return reverse('admin:technician_portal_repair_changelist')

    def _create_repair(self, status='PENDING', technician=None):
        return Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=technician or self.tech1,
            unit_number='U100',
            queue_status=status,
            cost=Decimal('50.00'),
        )

    def test_bulk_approve_repairs(self):
        r1 = self._create_repair(status='PENDING')
        r2 = self._create_repair(status='PENDING')
        r3 = self._create_repair(status='REQUESTED')

        response = self.client.post(self._repair_url(), {
            'action': 'bulk_approve',
            '_selected_action': [r1.pk, r2.pk, r3.pk],
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        for r in [r1, r2, r3]:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'APPROVED')

    def test_bulk_deny_repairs(self):
        r1 = self._create_repair(status='REQUESTED')
        r2 = self._create_repair(status='REQUESTED')

        response = self.client.post(self._repair_url(), {
            'action': 'bulk_deny',
            '_selected_action': [r1.pk, r2.pk],
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        for r in [r1, r2]:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'DENIED')

    def test_bulk_reset_repairs_skips_completed(self):
        r_approved = self._create_repair(status='APPROVED')
        r_completed = self._create_repair(status='COMPLETED')

        response = self.client.post(self._repair_url(), {
            'action': 'bulk_reset_to_pending',
            '_selected_action': [r_approved.pk, r_completed.pk],
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        r_approved.refresh_from_db()
        self.assertEqual(r_approved.queue_status, 'PENDING')

        r_completed.refresh_from_db()
        self.assertEqual(r_completed.queue_status, 'COMPLETED')

    def test_bulk_reassign_repairs(self):
        r1 = self._create_repair(technician=self.tech1)
        r2 = self._create_repair(technician=self.tech1)

        # First POST shows the intermediate page
        response = self.client.post(self._repair_url(), {
            'action': 'bulk_reassign_technician',
            '_selected_action': [r1.pk, r2.pk],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reassign')

        # Second POST with 'apply' does the reassignment
        response = self.client.post(self._repair_url(), {
            'action': 'bulk_reassign_technician',
            '_selected_action': [r1.pk, r2.pk],
            'technician_id': self.tech2.pk,
            'apply': 'Reassign',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        for r in [r1, r2]:
            r.refresh_from_db()
            self.assertEqual(r.technician, self.tech2)


class ReplacementAdminActionTests(AdminActionTestBase):
    """Tests for ReplacementAdmin bulk actions."""

    def _replacement_url(self):
        return reverse('admin:technician_portal_replacement_changelist')

    def _create_replacement(self, status='PENDING', technician=None):
        return Replacement.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=technician or self.tech1,
            unit_number='U200',
            queue_status=status,
            cost=Decimal('300.00'),
            parts_cost=Decimal('200.00'),
            labor_cost=Decimal('100.00'),
        )

    def test_bulk_approve_replacements(self):
        r1 = self._create_replacement(status='PENDING')
        r2 = self._create_replacement(status='REQUESTED')

        response = self.client.post(self._replacement_url(), {
            'action': 'bulk_approve',
            '_selected_action': [r1.pk, r2.pk],
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        for r in [r1, r2]:
            r.refresh_from_db()
            self.assertEqual(r.queue_status, 'APPROVED')

    def test_bulk_reassign_replacements(self):
        r1 = self._create_replacement(technician=self.tech1)

        # Intermediate page
        response = self.client.post(self._replacement_url(), {
            'action': 'bulk_reassign_technician',
            '_selected_action': [r1.pk],
        })
        self.assertEqual(response.status_code, 200)

        # Apply reassignment
        response = self.client.post(self._replacement_url(), {
            'action': 'bulk_reassign_technician',
            '_selected_action': [r1.pk],
            'technician_id': self.tech2.pk,
            'apply': 'Reassign',
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        r1.refresh_from_db()
        self.assertEqual(r1.technician, self.tech2)
