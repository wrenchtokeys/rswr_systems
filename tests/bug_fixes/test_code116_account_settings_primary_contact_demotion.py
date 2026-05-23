"""
CODE-116 regression tests: account_settings must demote existing primary
contact before promoting a new one.

Bug: The customer portal's account_settings view set
    customer_user.is_primary_contact = is_primary_contact
without first clearing is_primary_contact on any other CustomerUser for the
same customer. This allowed multiple CustomerUsers to simultaneously have
is_primary_contact=True, causing ambiguous notification routing (repairs.py
filters on is_primary_contact=True to find the approval contact).

Fix: Added a demotion step before assigning primary status:
    if is_primary_contact and not customer_user.is_primary_contact:
        CustomerUser.objects.filter(
            customer=customer, is_primary_contact=True
        ).exclude(pk=customer_user.pk).update(is_primary_contact=False)

This mirrors the pattern already used in:
- owner portal set_primary_contact()
- accept_customer_invitation() (both the existing-user and new-user branches)
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer


class AccountSettingsPrimaryContactDemotionTests(TestCase):
    """Claiming primary contact in account_settings must demote existing primary."""

    def setUp(self):
        # Owner user must exist before Tenant (owner FK)
        self.owner = User.objects.create_user(
            username='owner_116', password='pass', email='owner116@test.com'
        )
        self.tenant = Tenant.objects.create(
            name='Shop 116', slug='shop-116', owner=self.owner, is_active=True
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant, role='owner', is_active=True
        )

        self.customer = Customer.objects.create(
            name='Acme Trucking 116', tenant=self.tenant, email='acme116@test.com'
        )

        # Alice — current primary contact
        self.alice = User.objects.create_user(
            username='alice_116', password='testpass', email='alice116@test.com'
        )
        self.alice_cu = CustomerUser.objects.create(
            user=self.alice, customer=self.customer, is_primary_contact=True
        )
        TenantMembership.objects.create(
            user=self.alice, tenant=self.tenant, role='viewer', is_active=True
        )

        # Bob — non-primary team member
        self.bob = User.objects.create_user(
            username='bob_116', password='testpass', email='bob116@test.com',
            first_name='Bob', last_name='Smith',
        )
        self.bob_cu = CustomerUser.objects.create(
            user=self.bob, customer=self.customer, is_primary_contact=False
        )
        TenantMembership.objects.create(
            user=self.bob, tenant=self.tenant, role='viewer', is_active=True
        )

        self.client = Client()

    def _post_settings(self, user, customer_user, is_primary):
        """Log in as user and POST account_settings with the given primary flag."""
        self.client.force_login(user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        return self.client.post(
            reverse('customer_account_settings'),
            data={
                'first_name': user.first_name or 'Test',
                'last_name': user.last_name or 'User',
                'email': user.email,
                'is_primary_contact': 'on' if is_primary else '',
            },
            follow=True,
        )

    def test_promote_bob_demotes_alice(self):
        """When Bob claims primary, Alice must be demoted."""
        response = self._post_settings(self.bob, self.bob_cu, is_primary=True)
        self.assertEqual(response.status_code, 200)

        self.alice_cu.refresh_from_db()
        self.bob_cu.refresh_from_db()

        self.assertTrue(self.bob_cu.is_primary_contact, "Bob should now be primary")
        self.assertFalse(self.alice_cu.is_primary_contact,
                         "Alice should be demoted when Bob claims primary")

    def test_only_one_primary_after_promotion(self):
        """Exactly one CustomerUser should be primary after Bob's promotion."""
        self._post_settings(self.bob, self.bob_cu, is_primary=True)

        primary_count = CustomerUser.objects.filter(
            customer=self.customer, is_primary_contact=True
        ).count()
        self.assertEqual(primary_count, 1,
                         "Exactly one primary contact must exist after promotion")

    def test_demoting_self_does_not_raise(self):
        """Alice unchecking primary should succeed without errors."""
        response = self._post_settings(self.alice, self.alice_cu, is_primary=False)
        self.assertEqual(response.status_code, 200)

        self.alice_cu.refresh_from_db()
        self.assertFalse(self.alice_cu.is_primary_contact,
                         "Alice should not be primary after unchecking")

    def test_already_primary_stays_primary(self):
        """Alice re-saving with primary=True should keep her primary (no demotion of self)."""
        response = self._post_settings(self.alice, self.alice_cu, is_primary=True)
        self.assertEqual(response.status_code, 200)

        self.alice_cu.refresh_from_db()
        self.bob_cu.refresh_from_db()

        self.assertTrue(self.alice_cu.is_primary_contact, "Alice should remain primary")
        self.assertFalse(self.bob_cu.is_primary_contact, "Bob should not change")

    def test_cross_customer_primary_unaffected(self):
        """Promoting Bob must not touch primary contacts for a different customer."""
        other_customer = Customer.objects.create(
            name='Other Corp 116', tenant=self.tenant, email='other116@test.com'
        )
        carol = User.objects.create_user(
            username='carol_116', password='testpass', email='carol116@test.com'
        )
        carol_cu = CustomerUser.objects.create(
            user=carol, customer=other_customer, is_primary_contact=True
        )

        self._post_settings(self.bob, self.bob_cu, is_primary=True)

        carol_cu.refresh_from_db()
        self.assertTrue(carol_cu.is_primary_contact,
                        "Carol's primary status at other_customer must not be affected")

    def test_multi_primary_existing_data_fixed_on_promotion(self):
        """
        If the DB already has two primaries (pre-fix data), promoting a third
        user should clear BOTH existing primaries.
        """
        # Simulate pre-fix corrupt state: Alice and Bob both primary
        self.bob_cu.is_primary_contact = True
        self.bob_cu.save(update_fields=['is_primary_contact'])

        # Carol joins; she claims primary
        carol = User.objects.create_user(
            username='carol2_116', password='testpass', email='carol2_116@test.com'
        )
        carol_cu = CustomerUser.objects.create(
            user=carol, customer=self.customer, is_primary_contact=False
        )
        TenantMembership.objects.create(
            user=carol, tenant=self.tenant, role='viewer', is_active=True
        )

        self._post_settings(carol, carol_cu, is_primary=True)

        self.alice_cu.refresh_from_db()
        self.bob_cu.refresh_from_db()
        carol_cu.refresh_from_db()

        self.assertFalse(self.alice_cu.is_primary_contact, "Alice should be demoted")
        self.assertFalse(self.bob_cu.is_primary_contact, "Bob should be demoted")
        self.assertTrue(carol_cu.is_primary_contact, "Carol should be primary")

        primary_count = CustomerUser.objects.filter(
            customer=self.customer, is_primary_contact=True
        ).count()
        self.assertEqual(primary_count, 1, "Exactly one primary after fix")
