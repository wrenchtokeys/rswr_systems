"""
CODE-241 — customer_bulk_action success message indented inside notification loop

The success toast (messages.success) was indented inside the
`for notif in notifications_to_create:` loop. This caused one success toast
per technician notification instead of one overall. Bulk-approving 3 repairs
would show 3 identical "Successfully approved 3 repairs." toasts.

The fix de-indents the success message to execute once, after the loop.

Tests:
  1. Bulk approve 3 repairs → exactly one success message (not 3)
  2. Bulk approve 1 repair → exactly one success message, singular text
  3. Bulk deny 2 repairs → exactly one success message
  4. Bulk deny 1 repair → exactly one success message, singular text
  5. Bulk approve confirms correct count in message
  6. Bulk deny confirms correct count in message
"""
from decimal import Decimal

from django.contrib.auth.models import User, Group
from django.contrib.messages import get_messages
from django.test import TestCase
from django.utils import timezone

from apps.technician_portal.models import Technician, Repair
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class BulkActionSuccessMessageBase(TestCase):
    """Shared setup for CODE-241 tests."""

    @classmethod
    def setUpTestData(cls):
        cls.owner_user = User.objects.create_user(
            username='owner241', email='owner241@test.com', password='testpass123'
        )
        cls.tenant = Tenant.objects.create(
            name='Test Shop 241',
            slug='test-shop-241',
            plan='professional',
            owner=cls.owner_user,
        )
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.owner_user, role='owner', is_active=True
        )

        # Technician
        cls.tech_user = User.objects.create_user(
            username='tech241', email='tech241@test.com', password='testpass123'
        )
        tech_group, _ = Group.objects.get_or_create(name='Technicians')
        cls.tech_user.groups.add(tech_group)
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.tech_user, role='technician', is_active=True
        )
        cls.technician = Technician.objects.create(
            user=cls.tech_user, tenant=cls.tenant, is_active=True
        )

        # Customer + CustomerUser
        cls.customer = Customer.objects.create(
            name='MSG Test Fleet', tenant=cls.tenant
        )
        cls.cust_user = User.objects.create_user(
            username='cust241', email='cust241@test.com', password='testpass123'
        )
        TenantMembership.objects.create(
            tenant=cls.tenant, user=cls.cust_user, role='viewer', is_active=True
        )
        cls.customer_user = CustomerUser.objects.create(
            user=cls.cust_user, customer=cls.customer
        )

    def _create_repair(self, status='PENDING'):
        return Repair.objects.create(
            customer=self.customer,
            tenant=self.tenant,
            technician=self.technician,
            unit_number='UNIT-241',
            damage_type='CHIP',
            queue_status=status,
            cost=Decimal('50.00'),
            service_date=timezone.now().date(),
        )

    def _post_bulk(self, action, repair_ids):
        self.client.login(username='cust241', password='testpass123')
        data = {'action': action, 'repair_ids': [str(rid) for rid in repair_ids]}
        return self.client.post(
            '/app/repairs/bulk-action/',
            data,
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def _get_success_messages(self, response):
        """Extract success-level messages from the response."""
        msgs = list(get_messages(response.wsgi_request))
        return [m for m in msgs if m.level_tag == 'success']


class TestBulkApproveThreeRepairsOneMessage(BulkActionSuccessMessageBase):
    """CODE-241: Bulk approve 3 repairs → exactly ONE success toast, not 3."""

    def test_one_success_message_for_three_repairs(self):
        r1 = self._create_repair()
        r2 = self._create_repair()
        r3 = self._create_repair()

        response = self._post_bulk('approve', [r1.id, r2.id, r3.id])
        success_msgs = self._get_success_messages(response)

        self.assertEqual(
            len(success_msgs), 1,
            f"Expected exactly 1 success message, got {len(success_msgs)}: "
            f"{[str(m) for m in success_msgs]}"
        )
        self.assertIn('3 repairs', str(success_msgs[0]))
        self.assertIn('approved', str(success_msgs[0]))


class TestBulkApproveSingleRepairSingular(BulkActionSuccessMessageBase):
    """Bulk approve 1 repair → message says 'repair' not 'repairs'."""

    def test_singular_message(self):
        r1 = self._create_repair()

        response = self._post_bulk('approve', [r1.id])
        success_msgs = self._get_success_messages(response)

        self.assertEqual(len(success_msgs), 1)
        msg_text = str(success_msgs[0])
        self.assertIn('1 repair', msg_text)
        # Singular: "1 repair" not "1 repairs"
        self.assertNotIn('1 repairs', msg_text)


class TestBulkDenyTwoRepairsOneMessage(BulkActionSuccessMessageBase):
    """Bulk deny 2 repairs → exactly ONE success toast."""

    def test_one_success_message_deny(self):
        r1 = self._create_repair()
        r2 = self._create_repair()

        response = self._post_bulk('deny', [r1.id, r2.id])
        success_msgs = self._get_success_messages(response)

        self.assertEqual(
            len(success_msgs), 1,
            f"Expected exactly 1 success message, got {len(success_msgs)}: "
            f"{[str(m) for m in success_msgs]}"
        )
        self.assertIn('denied', str(success_msgs[0]))
        self.assertIn('2 repairs', str(success_msgs[0]))


class TestBulkDenySingleRepairSingular(BulkActionSuccessMessageBase):
    """Bulk deny 1 repair → singular message."""

    def test_singular_deny_message(self):
        r1 = self._create_repair()

        response = self._post_bulk('deny', [r1.id])
        success_msgs = self._get_success_messages(response)

        self.assertEqual(len(success_msgs), 1)
        msg_text = str(success_msgs[0])
        self.assertIn('denied', msg_text)
        self.assertIn('1 repair', msg_text)
        self.assertNotIn('1 repairs', msg_text)


class TestBulkApproveFiveRepairsOneMessage(BulkActionSuccessMessageBase):
    """Larger batch: 5 repairs → still exactly one success message."""

    def test_five_repairs_one_message(self):
        repairs = [self._create_repair() for _ in range(5)]

        response = self._post_bulk('approve', [r.id for r in repairs])
        success_msgs = self._get_success_messages(response)

        self.assertEqual(
            len(success_msgs), 1,
            f"Expected exactly 1 success message, got {len(success_msgs)}: "
            f"{[str(m) for m in success_msgs]}"
        )
        self.assertIn('5 repairs', str(success_msgs[0]))


class TestBulkApproveMessageNotDuplicated(BulkActionSuccessMessageBase):
    """
    The core regression: before CODE-241, N repairs with technicians
    produced N identical success toasts. After the fix, it's always 1.
    """

    def test_no_duplicate_messages(self):
        r1 = self._create_repair()
        r2 = self._create_repair()

        response = self._post_bulk('approve', [r1.id, r2.id])
        all_msgs = list(get_messages(response.wsgi_request))
        success_msgs = [m for m in all_msgs if m.level_tag == 'success']

        # The critical assertion: exactly 1, never 2+
        self.assertEqual(len(success_msgs), 1,
            "Duplicate success messages detected — the notification loop "
            "indentation bug (CODE-241) may have regressed."
        )
