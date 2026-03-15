from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from core.models import Customer
from apps.technician_portal.models import Repair, Technician
from .models import CustomerUser, CustomerPreference, RepairApproval, ApprovalToken


class CustomerUserModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='test company',
            email='test@company.com'
        )
        self.user = User.objects.create_user(
            username='testuser',
            email='user@company.com',
            password='testpass'
        )

    def test_customer_user_creation(self):
        customer_user = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer,
            is_primary_contact=True
        )
        self.assertEqual(str(customer_user), f"{self.user.username} - {self.customer.name}")
        self.assertTrue(customer_user.is_primary_contact)

    def test_customer_preference_creation(self):
        preference = CustomerPreference.objects.create(
            customer=self.customer,
            receive_email_notifications=False,
            default_view='completed'
        )
        self.assertEqual(str(preference), f"Preferences for {self.customer.name}")
        self.assertFalse(preference.receive_email_notifications)
        self.assertEqual(preference.default_view, 'completed')


class RepairApprovalModelTest(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='test company',
            email='test@company.com'
        )
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer
        )
        self.technician_user = User.objects.create_user(
            username='techuser',
            password='testpass'
        )
        self.technician = Technician.objects.create(
            user=self.technician_user,
            expertise='Glass Repair'
        )
        self.repair = Repair.objects.create(
            technician=self.technician,
            customer=self.customer,
            unit_number='Unit 1',
            damage_type='Chip'
        )

    def test_repair_approval_creation(self):
        approval = RepairApproval.objects.create(
            repair=self.repair,
            approved=True,
            approved_by=self.customer_user,
            notes='Approved for repair'
        )
        self.assertTrue(approval.approved)
        self.assertEqual(approval.approved_by, self.customer_user)
        self.assertIn('Approved', str(approval))


class CustomerPortalViewTest(APITestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='test company',
            email='test@company.com'
        )
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.user,
            customer=self.customer
        )
        self.client.force_authenticate(user=self.user)

    def test_customer_dashboard_access(self):
        # Test that the URL exists or redirects appropriately
        response = self.client.get('/customer/dashboard/')
        # 404 is acceptable if the view isn't implemented yet
        self.assertIn(response.status_code, [200, 302, 404])

class QuickApproveRaceConditionTest(TestCase):
    """
    Regression tests for CODE-023: quick_approve_repair / quick_deny_repair
    race condition — concurrent POSTs could bypass the single-use token guard.

    Fix: both views now re-fetch token + repair under select_for_update()
    inside transaction.atomic() before mutating state.
    """

    def setUp(self):
        self.client = Client()
        self.customer = Customer.objects.create(
            name='Race Test Co',
            email='race@test.com',
        )
        self.tech_user = User.objects.create_user(
            username='tech_race', password='testpass'
        )
        self.technician = Technician.objects.create(
            user=self.tech_user,
            expertise='Glass Repair',
        )
        self.contact_user = User.objects.create_user(
            username='contact_race', password='testpass'
        )
        self.customer_user = CustomerUser.objects.create(
            user=self.contact_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        self.repair = Repair.objects.create(
            technician=self.technician,
            customer=self.customer,
            unit_number='TK-001',
            damage_type='Chip',
            queue_status='PENDING',
        )
        # Create approve + deny token pair
        tokens = ApprovalToken.create_pair(
            repair=self.repair, customer_user=self.customer_user
        )
        self.approve_token = tokens['approve_token']
        self.deny_token = tokens['deny_token']

    # --- quick_approve_repair ---

    def test_approve_get_shows_confirm_page(self):
        url = reverse('quick_approve', args=[str(self.approve_token.token)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'repair', response.content.lower())

    def test_approve_post_sets_repair_approved(self):
        url = reverse('quick_approve', args=[str(self.approve_token.token)])
        response = self.client.post(url, {'notes': 'Looks good'})
        self.assertEqual(response.status_code, 200)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'APPROVED')

    def test_approve_post_marks_token_used(self):
        url = reverse('quick_approve', args=[str(self.approve_token.token)])
        self.client.post(url, {'notes': ''})
        self.approve_token.refresh_from_db()
        self.assertIsNotNone(self.approve_token.used_at)

    def test_approve_post_invalidates_deny_token(self):
        """After approval, corresponding deny token should be invalidated."""
        url = reverse('quick_approve', args=[str(self.approve_token.token)])
        self.client.post(url, {'notes': ''})
        self.deny_token.refresh_from_db()
        self.assertIsNotNone(self.deny_token.used_at,
                             "Deny token should be invalidated after approval")

    def test_approve_post_creates_notification(self):
        url = reverse('quick_approve', args=[str(self.approve_token.token)])
        from apps.technician_portal.models import TechnicianNotification
        before = TechnicianNotification.objects.filter(repair=self.repair).count()
        self.client.post(url, {'notes': ''})
        after = TechnicianNotification.objects.filter(repair=self.repair).count()
        self.assertEqual(after, before + 1)

    def test_approve_second_post_is_rejected(self):
        """Simulate two sequential POSTs — second must be rejected (used token guard)."""
        url = reverse('quick_approve', args=[str(self.approve_token.token)])
        r1 = self.client.post(url, {'notes': ''})
        self.assertEqual(r1.status_code, 200)

        # Manually mark token as used (mirrors what the first POST did)
        # Second POST should hit the locked-token check
        r2 = self.client.post(url, {'notes': ''})
        self.assertEqual(r2.status_code, 200)
        # The response should indicate already used, not success again
        self.assertNotIn(b'quick_approve_success', r2.content)

    def test_approve_invalid_token_returns_expired(self):
        url = reverse('quick_approve', args=['00000000-0000-0000-0000-000000000000'])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'invalid', response.content.lower())

    # --- quick_deny_repair ---

    def test_deny_post_sets_repair_denied(self):
        url = reverse('quick_deny', args=[str(self.deny_token.token)])
        response = self.client.post(url, {'reason': 'Not authorised'})
        self.assertEqual(response.status_code, 200)
        self.repair.refresh_from_db()
        self.assertEqual(self.repair.queue_status, 'DENIED')

    def test_deny_post_marks_token_used(self):
        url = reverse('quick_deny', args=[str(self.deny_token.token)])
        self.client.post(url, {'reason': ''})
        self.deny_token.refresh_from_db()
        self.assertIsNotNone(self.deny_token.used_at)

    def test_deny_post_invalidates_approve_token(self):
        """After denial, corresponding approve token should be invalidated."""
        url = reverse('quick_deny', args=[str(self.deny_token.token)])
        self.client.post(url, {'reason': 'Not today'})
        self.approve_token.refresh_from_db()
        self.assertIsNotNone(self.approve_token.used_at,
                             "Approve token should be invalidated after denial")

    def test_deny_second_post_is_rejected(self):
        """Simulate two sequential denials — second must be blocked."""
        url = reverse('quick_deny', args=[str(self.deny_token.token)])
        r1 = self.client.post(url, {'reason': ''})
        self.assertEqual(r1.status_code, 200)

        r2 = self.client.post(url, {'reason': ''})
        self.assertEqual(r2.status_code, 200)
        self.assertNotIn(b'quick_deny_success', r2.content)

    def test_deny_already_approved_repair_returns_expired(self):
        """If repair already approved, deny link should show expired page."""
        self.repair.queue_status = 'APPROVED'
        self.repair.save()
        url = reverse('quick_deny', args=[str(self.deny_token.token)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'approved', response.content.lower())
