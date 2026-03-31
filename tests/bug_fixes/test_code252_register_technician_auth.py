"""
CODE-252: Legacy register_technician endpoint requires staff/superuser access.

The /admin/register-technician/ endpoint was completely unauthenticated —
any anonymous visitor could create a Django User + Technician record.
This test verifies the authentication guard works.
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from apps.technician_portal.models import Technician


class TestRegisterTechnicianAuth(TestCase):
    """Verify the legacy register_technician endpoint is properly guarded."""

    def setUp(self):
        self.client = Client()
        self.url = '/admin/register-technician/'
        self.form_data = {
            'username': 'newtech',
            'email': 'newtech@example.com',
            'password1': 'SecurePass123!',
            'password2': 'SecurePass123!',
            'first_name': 'New',
            'last_name': 'Tech',
            'phone_number': '+15551234567',
            'expertise': 'Windshield',
        }

    def test_anonymous_get_redirects_to_login(self):
        """Anonymous users should be redirected to login."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_anonymous_post_rejected(self):
        """Anonymous POST should not create any user or technician."""
        user_count_before = User.objects.count()
        tech_count_before = Technician.objects.count()

        response = self.client.post(self.url, self.form_data)

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())
        self.assertEqual(User.objects.count(), user_count_before)
        self.assertEqual(Technician.objects.count(), tech_count_before)

    def test_regular_user_rejected(self):
        """Non-staff authenticated users should be blocked."""
        regular_user = User.objects.create_user(
            username='regular', password='pass123', is_staff=False
        )
        self.client.force_login(regular_user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_regular_user_post_rejected(self):
        """Non-staff POST should not create any user or technician."""
        regular_user = User.objects.create_user(
            username='regular', password='pass123', is_staff=False
        )
        self.client.force_login(regular_user)
        user_count_before = User.objects.count()

        response = self.client.post(self.url, self.form_data)

        self.assertEqual(response.status_code, 302)
        # No new user beyond the one we just created
        self.assertEqual(User.objects.count(), user_count_before)

    def test_staff_user_can_access(self):
        """Staff users should be able to access the registration form."""
        staff_user = User.objects.create_user(
            username='staffuser', password='pass123', is_staff=True
        )
        self.client.force_login(staff_user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Register New Technician')

    def test_superuser_can_access(self):
        """Superusers should be able to access the registration form."""
        admin = User.objects.create_superuser(
            username='admin', password='pass123', email='admin@test.com'
        )
        self.client.force_login(admin)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_staff_user_can_create_technician(self):
        """Staff users should be able to successfully register a technician."""
        staff_user = User.objects.create_user(
            username='staffuser', password='pass123', is_staff=True
        )
        self.client.force_login(staff_user)

        response = self.client.post(self.url, self.form_data)

        # Should redirect to admin on success
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='newtech').exists())
        self.assertTrue(
            Technician.objects.filter(user__username='newtech').exists()
        )
