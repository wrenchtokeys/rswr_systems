from django.contrib.auth.models import User
from django.test import TestCase


class PlatformFeesAdminPageTests(TestCase):
    """The fee report must render and stay superuser-only."""

    def setUp(self):
        self.su = User.objects.create_superuser(
            username='su', email='su@test.com', password='pw123!')
        self.staff = User.objects.create_user(
            username='staff', email='staff@test.com', password='pw123!',
            is_staff=True)

    def test_renders_for_superuser(self):
        self.client.force_login(self.su)
        resp = self.client.get('/admin/platform-fees/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Platform Fees Collected')
        self.assertContains(resp, 'currently OFF')

    def test_forbidden_for_non_superuser_staff(self):
        """Platform-wide financial data must not leak to shop staff."""
        self.client.force_login(self.staff)
        resp = self.client.get('/admin/platform-fees/')
        self.assertIn(resp.status_code, (302, 403))

    def test_config_page_exposes_master_switch(self):
        self.client.force_login(self.su)
        resp = self.client.get('/admin/platform-config/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'fee_enabled')
        self.assertContains(resp, 'default_fee_fixed_cents')

    def test_master_switch_can_be_toggled(self):
        from apps.billing.models import PlatformConfig
        self.client.force_login(self.su)
        self.client.post('/admin/platform-config/', {
            'fee_enabled': 'on',
            'default_fee_percent': '2.50',
            'default_fee_fixed_cents': '30',
        })
        config = PlatformConfig.get_solo()
        self.assertTrue(config.fee_enabled)
        self.assertEqual(config.default_fee_fixed_cents, 30)
