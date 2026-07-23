"""
Customer replacement request flow (/app/replacements/request/).

Customers of replacement-focused shops previously had no way to request a
glass replacement — the only request flow created Repairs. This covers the
new request_replacement view end-to-end: form render, creation with
REQUESTED status and no pricing, technician assignment (including the
fallback when no tech has can_replace=True), shop notification, owner
visibility, and validation.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, Client, override_settings

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Replacement, TechnicianNotification
from core.models import Customer
from apps.customer_portal.models import CustomerUser


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        },
    )
    user = User.objects.create_user(
        owner_username, f'{owner_username}@test.com', 'testpass123',
        first_name='Test', last_name='Owner',
    )
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        plan='trial',
        subscription_status='trialing',
    )
    TenantMembership.objects.create(tenant=tenant, user=user, role='owner')
    return user, tenant


@override_settings(**TEST_SETTINGS)
class CustomerRequestReplacementTests(TestCase):

    def setUp(self):
        self.owner, self.tenant = make_tenant('Duncan Auto Glass', 'repl_owner')
        # Owner doubles as the shop's only technician; can_replace defaults
        # to False — the assignment fallback must still pick them.
        self.technician = Technician.objects.create(
            user=self.owner, tenant=self.tenant, is_active=True, is_manager=True,
        )
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        self.cust_user = User.objects.create_user(
            'fleet_contact', 'contact@fleetco.com', 'testpass123',
            first_name='Pat', last_name='Contact',
        )
        CustomerUser.objects.create(
            user=self.cust_user, customer=self.customer, is_primary_contact=True,
        )
        self.client = Client()
        self.client.force_login(self.cust_user)

    def test_get_renders_form(self):
        response = self.client.get('/app/replacements/request/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Request Glass Replacement')
        self.assertContains(response, 'Windshield')

    def test_post_creates_requested_replacement_without_pricing(self):
        response = self.client.post('/app/replacements/request/', {
            'unit_number': 'Truck 12',
            'glass_position': 'WINDSHIELD',
            'description': 'Rock chip spread into a crack',
        })
        self.assertRedirects(response, '/app/', fetch_redirect_response=False)

        replacement = Replacement.objects.get(customer=self.customer)
        self.assertEqual(replacement.queue_status, 'REQUESTED')
        self.assertEqual(replacement.tenant, self.tenant)
        self.assertEqual(replacement.unit_number, 'Truck 12')
        self.assertEqual(replacement.glass_position, 'WINDSHIELD')
        self.assertEqual(replacement.customer_notes, 'Rock chip spread into a crack')
        self.assertEqual(replacement.cost, Decimal('0.00'))
        self.assertEqual(replacement.tax_amount, Decimal('0.00'))
        self.assertIsNotNone(replacement.technician)

    def test_fallback_assignment_when_no_tech_can_replace(self):
        """A shop whose only tech has can_replace=False must not dead-end."""
        self.assertFalse(self.technician.can_replace)
        self.client.post('/app/replacements/request/', {
            'unit_number': 'Van 3',
            'glass_position': 'REAR',
        })
        replacement = Replacement.objects.get(customer=self.customer)
        self.assertEqual(replacement.technician, self.technician)

    def test_prefers_tech_with_can_replace(self):
        replace_user = User.objects.create_user(
            'repl_tech', 'tech@duncan.com', 'testpass123',
            first_name='Glass', last_name='Tech',
        )
        replace_tech = Technician.objects.create(
            user=replace_user, tenant=self.tenant, is_active=True, can_replace=True,
        )
        self.client.post('/app/replacements/request/', {
            'unit_number': 'Truck 9',
            'glass_position': 'WINDSHIELD',
        })
        replacement = Replacement.objects.get(customer=self.customer)
        self.assertEqual(replacement.technician, replace_tech)

    def test_shop_is_notified(self):
        self.client.post('/app/replacements/request/', {
            'unit_number': 'Truck 12',
            'glass_position': 'WINDSHIELD',
        })
        replacement = Replacement.objects.get(customer=self.customer)

        notification = TechnicianNotification.objects.filter(
            technician=replacement.technician,
            message__icontains='replacement request',
        ).first()
        self.assertIsNotNone(notification)
        self.assertIn('Fleet Co', notification.message)

        self.assertGreaterEqual(len(mail.outbox), 1)
        shop_email = mail.outbox[-1]
        self.assertIn(self.owner.email, shop_email.to)
        self.assertIn('Fleet Co', shop_email.subject)

    def test_owner_sees_requested_replacement_in_list(self):
        self.client.post('/app/replacements/request/', {
            'unit_number': 'Truck 12',
            'glass_position': 'WINDSHIELD',
        })
        owner_client = Client()
        owner_client.force_login(self.owner)
        session = owner_client.session
        session['tenant_id'] = self.tenant.id
        session.save()
        response = owner_client.get('/tech/replacements/?status=REQUESTED', follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Truck 12')

    def test_missing_unit_number_creates_nothing(self):
        response = self.client.post('/app/replacements/request/', {
            'unit_number': '',
            'glass_position': 'WINDSHIELD',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Replacement.objects.count(), 0)
        self.assertContains(response, 'required')

    def test_invalid_glass_position_defaults_to_windshield(self):
        self.client.post('/app/replacements/request/', {
            'unit_number': 'Truck 12',
            'glass_position': 'NOT_A_POSITION',
        })
        replacement = Replacement.objects.get(customer=self.customer)
        self.assertEqual(replacement.glass_position, 'WINDSHIELD')
