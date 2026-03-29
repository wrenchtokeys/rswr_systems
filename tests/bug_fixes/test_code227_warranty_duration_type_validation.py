"""
CODE-227: WarrantyPolicy duration_type not validated before save.

owner_warranty_create and owner_warranty_edit in apps/saas/views.py accepted
any string for duration_type without checking against WarrantyPolicy.WARRANTY_DURATION_CHOICES.
A forged POST with duration_type='bogus' would save to the DB and break
warranty_service.py + invoice PDF logic which branch on 'lifetime'/'custom_days'/'none'.

Same gap in technician portal create_warranty_policy and update_warranty_policy.

Regression tests:
  - Invalid duration_type is rejected (400/redirect) in owner create
  - Invalid duration_type is rejected in owner edit
  - Valid duration_types are accepted
  - Invalid duration_type is rejected in tech portal create
  - Invalid duration_type is rejected in tech portal update
  - Invalid applies_to still rejected (existing guard still works)
"""
import json
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from apps.technician_portal.models import WarrantyPolicy, Technician
from apps.tenants.models import Tenant, TenantMembership


def _make_tenant_and_owner(username):
    user = User.objects.create_user(username=username, password='pw', email=f'{username}@test.com')
    tenant = Tenant.objects.create(name=f'Shop {username}', slug=username, is_active=True, owner=user)
    TenantMembership.objects.create(user=user, tenant=tenant, role='owner', is_active=True)
    return tenant, user


class OwnerWarrantyCreateDurationTypeValidationTest(TestCase):
    """Owner portal: duration_type must be validated in warranty create."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_and_owner('warr_owner1')
        self.client.login(username='warr_owner1', password='pw')

    def test_invalid_duration_type_rejected(self):
        """POST with duration_type='bogus' should redirect back with error, not save."""
        response = self.client.post('/owner/settings/warranty/create/', {
            'name': 'Malicious Policy',
            'applies_to': 'all_repairs',
            'duration_type': 'bogus_value',
            'duration_days': '365',
            'coverage_description': '',
            'is_active': 'on',
        }, follow=True)
        # Should not have created the policy
        self.assertFalse(
            WarrantyPolicy.objects.filter(tenant=self.tenant, name='Malicious Policy').exists(),
            'Invalid duration_type should not be saved'
        )

    def test_valid_duration_type_lifetime_accepted(self):
        response = self.client.post('/owner/settings/warranty/create/', {
            'name': 'Lifetime Policy',
            'applies_to': 'all_repairs',
            'duration_type': 'lifetime',
            'duration_days': '0',
            'coverage_description': 'covers everything',
            'is_active': 'on',
        }, follow=True)
        self.assertTrue(
            WarrantyPolicy.objects.filter(tenant=self.tenant, name='Lifetime Policy').exists(),
            'Valid duration_type=lifetime should be accepted'
        )

    def test_valid_duration_type_custom_days_accepted(self):
        response = self.client.post('/owner/settings/warranty/create/', {
            'name': 'Custom Days Policy',
            'applies_to': 'all_repairs',
            'duration_type': 'custom_days',
            'duration_days': '180',
            'coverage_description': '',
            'is_active': 'on',
        }, follow=True)
        self.assertTrue(
            WarrantyPolicy.objects.filter(tenant=self.tenant, name='Custom Days Policy').exists()
        )

    def test_valid_duration_type_none_accepted(self):
        response = self.client.post('/owner/settings/warranty/create/', {
            'name': 'No Warranty Policy',
            'applies_to': 'all_repairs',
            'duration_type': 'none',
            'duration_days': '0',
            'coverage_description': '',
        }, follow=True)
        self.assertTrue(
            WarrantyPolicy.objects.filter(tenant=self.tenant, name='No Warranty Policy').exists()
        )

    def test_invalid_applies_to_still_rejected(self):
        """Existing applies_to guard must still work."""
        response = self.client.post('/owner/settings/warranty/create/', {
            'name': 'Bad Applies To',
            'applies_to': 'invalid_choice',
            'duration_type': 'custom_days',
            'duration_days': '365',
            'is_active': 'on',
        }, follow=True)
        self.assertFalse(
            WarrantyPolicy.objects.filter(tenant=self.tenant, name='Bad Applies To').exists()
        )


class OwnerWarrantyEditDurationTypeValidationTest(TestCase):
    """Owner portal: duration_type must be validated in warranty edit."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_and_owner('warr_owner2')
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Original Policy',
            applies_to='all_repairs',
            duration_type='custom_days',
            duration_days=365,
            is_active=True,
        )
        self.client.login(username='warr_owner2', password='pw')

    def test_invalid_duration_type_rejected_on_edit(self):
        response = self.client.post(
            f'/owner/settings/warranty/{self.policy.pk}/edit/', {
                'name': 'Original Policy',
                'applies_to': 'all_repairs',
                'duration_type': 'INVALID',
                'duration_days': '365',
            }, follow=True
        )
        self.policy.refresh_from_db()
        self.assertEqual(
            self.policy.duration_type, 'custom_days',
            'Invalid duration_type should not overwrite existing value'
        )

    def test_valid_duration_type_accepted_on_edit(self):
        response = self.client.post(
            f'/owner/settings/warranty/{self.policy.pk}/edit/', {
                'name': 'Updated Policy',
                'applies_to': 'all_repairs',
                'duration_type': 'lifetime',
                'duration_days': '0',
            }, follow=True
        )
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.duration_type, 'lifetime')
        self.assertEqual(self.policy.name, 'Updated Policy')


class TechPortalWarrantyCreateDurationTypeValidationTest(TestCase):
    """Technician portal: duration_type must be validated in warranty create."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_and_owner('warr_tech1')
        self.tech = Technician.objects.create(
            user=self.owner,
            tenant=self.tenant,
            is_manager=True,
            is_active=True,
        )
        self.client.login(username='warr_tech1', password='pw')

    def _post_create(self, data):
        return self.client.post(
            '/tech/settings/api/warranty/create/',
            data=json.dumps(data),
            content_type='application/json',
        )

    def test_invalid_duration_type_rejected(self):
        resp = self._post_create({
            'name': 'Bad Tech Policy',
            'applies_to': 'all_repairs',
            'duration_type': 'bogus',
        })
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.content)
        self.assertFalse(body.get('success'))
        self.assertIn('Duration Type', body.get('error', ''))
        self.assertFalse(
            WarrantyPolicy.objects.filter(tenant=self.tenant, name='Bad Tech Policy').exists()
        )

    def test_invalid_applies_to_rejected(self):
        resp = self._post_create({
            'name': 'Bad Applies Policy',
            'applies_to': 'bad_choice',
            'duration_type': 'custom_days',
        })
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.content)
        self.assertFalse(body.get('success'))
        self.assertIn('Applies To', body.get('error', ''))

    def test_valid_payload_accepted(self):
        resp = self._post_create({
            'name': 'Good Policy',
            'applies_to': 'all_repairs',
            'duration_type': 'custom_days',
            'duration_days': 180,
        })
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertTrue(body.get('success'))


class TechPortalWarrantyUpdateDurationTypeValidationTest(TestCase):
    """Technician portal: duration_type must be validated in warranty update."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_and_owner('warr_tech2')
        self.tech = Technician.objects.create(
            user=self.owner,
            tenant=self.tenant,
            is_manager=True,
            is_active=True,
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Existing Policy',
            applies_to='all_repairs',
            duration_type='custom_days',
            duration_days=365,
        )
        self.client.login(username='warr_tech2', password='pw')

    def _post_update(self, data):
        return self.client.post(
            f'/tech/settings/api/warranty/{self.policy.pk}/update/',
            data=json.dumps(data),
            content_type='application/json',
        )

    def test_invalid_duration_type_rejected_on_update(self):
        resp = self._post_update({'duration_type': 'bad_type'})
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.content)
        self.assertFalse(body.get('success'))
        self.assertIn('Duration Type', body.get('error', ''))
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.duration_type, 'custom_days')

    def test_invalid_applies_to_rejected_on_update(self):
        resp = self._post_update({'applies_to': 'garbage'})
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.content)
        self.assertFalse(body.get('success'))

    def test_valid_duration_type_accepted_on_update(self):
        resp = self._post_update({'duration_type': 'none'})
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.content)
        self.assertTrue(body.get('success'))
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.duration_type, 'none')
