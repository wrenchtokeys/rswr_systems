"""
Tenant-scoped email branding.

Customer-facing email (invitations, lifecycle notifications, payment
receipts) renders {{ branding.company_name }} in the header/footer of
emails/base.html. That value used to come from the platform-wide
EmailBrandingConfig singleton, so every shop's customers saw the
platform-owner tenant's name ("Rockstar Windshield Repair") instead of
the shop they actually do business with.

Covers:
  1. EmailBrandingConfig.get_tenant_context(None) — singleton passthrough
  2. get_tenant_context(tenant) — tenant identity overrides the singleton
  3. Invitation email end-to-end — header shows the shop, never the platform tenant
  4. NotificationService.create_notification — injects tenant branding into context
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from core.models import Customer
from core.models.email_branding import EmailBrandingConfig
from apps.customer_portal.models import CustomerUser
from apps.customer_portal.services.invitation_service import CustomerInvitationService


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
class GetTenantContextTests(TestCase):
    """EmailBrandingConfig.get_tenant_context()"""

    def setUp(self):
        config = EmailBrandingConfig.get_instance()
        config.company_name = 'Rockstar Windshield Repair'
        config.support_email = 'support@rockstar.example.com'
        config.website_url = 'https://rockstar.example.com'
        config.save()
        self.owner, self.tenant = make_tenant('Duncan Auto Glass', 'branding_owner')
        self.tenant.business_email = 'shop@duncanautoglass.com'
        self.tenant.business_phone = '+15015551234'
        self.tenant.business_address = '123 Main St, Little Rock, AR'
        self.tenant.save()

    def test_no_tenant_returns_singleton_values(self):
        ctx = EmailBrandingConfig.get_tenant_context(None)
        self.assertEqual(ctx['company_name'], 'Rockstar Windshield Repair')
        self.assertEqual(ctx['support_email'], 'support@rockstar.example.com')

    def test_tenant_identity_overrides_singleton(self):
        ctx = EmailBrandingConfig.get_tenant_context(self.tenant)
        self.assertEqual(ctx['company_name'], 'Duncan Auto Glass')
        self.assertEqual(ctx['support_email'], 'shop@duncanautoglass.com')
        self.assertEqual(ctx['support_phone'], '+15015551234')
        self.assertEqual(ctx['company_address'], '123 Main St, Little Rock, AR')
        self.assertIn('Duncan Auto Glass', ctx['footer_text'])
        # Platform links/logo must not leak onto another shop's email
        self.assertEqual(ctx['website_url'], '')
        self.assertEqual(ctx['logo_url'], '')

    def test_tenant_context_keeps_visual_identity(self):
        singleton_ctx = EmailBrandingConfig.get_instance().to_template_context()
        ctx = EmailBrandingConfig.get_tenant_context(self.tenant)
        self.assertEqual(ctx['primary_color'], singleton_ctx['primary_color'])
        self.assertEqual(ctx['body_font'], singleton_ctx['body_font'])

    def test_tenant_context_is_json_serializable(self):
        import json
        json.dumps(EmailBrandingConfig.get_tenant_context(self.tenant))


@override_settings(**TEST_SETTINGS)
class InvitationEmailBrandingTests(TestCase):
    """The invitation email header must show the shop, not the platform tenant."""

    def setUp(self):
        config = EmailBrandingConfig.get_instance()
        config.company_name = 'Rockstar Windshield Repair'
        config.save()
        self.owner, self.tenant = make_tenant('Duncan Auto Glass', 'invite_owner')
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)

    def test_invitation_email_uses_shop_name_not_platform_name(self):
        invitation = CustomerInvitationService.create_invitation(
            customer=self.customer,
            email='contact@fleetco.com',
            invited_by=self.owner,
            first_name='Pat',
        )
        sent = CustomerInvitationService.send_invitation_email(invitation)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        html_body = message.alternatives[0][0]
        self.assertIn('Duncan Auto Glass', html_body)
        self.assertNotIn('Rockstar', html_body)
        self.assertNotIn('Rockstar', message.body)
        self.assertIn('Duncan Auto Glass', message.subject)


@override_settings(**TEST_SETTINGS)
class NotificationBrandingInjectionTests(TestCase):
    """create_notification() injects tenant branding for base.html emails."""

    def setUp(self):
        config = EmailBrandingConfig.get_instance()
        config.company_name = 'Rockstar Windshield Repair'
        config.save()
        self.owner, self.tenant = make_tenant('Duncan Auto Glass', 'notify_owner')
        self.customer = Customer.objects.create(name='Fleet Co', tenant=self.tenant)
        cust_user = User.objects.create_user(
            'fleet_contact', 'contact@fleetco.com', 'testpass123',
            first_name='Pat', last_name='Contact',
        )
        self.customer_user = CustomerUser.objects.create(
            user=cust_user, customer=self.customer, is_primary_contact=True,
        )

        from core.models.notification_template import NotificationTemplate
        self.template = NotificationTemplate.objects.create(
            name='test_branding_template',
            category='repair',
            title_template='Test {{ customer_name }}',
            message_template='Hello from the shop.',
            active=True,
        )

    def test_branding_injected_from_customer_tenant(self):
        from core.services.notification_service import NotificationService
        # Schedule for the future so delivery (email/SMS) is not attempted;
        # we only care about the persisted template_context.
        notification = NotificationService.create_notification(
            recipient=self.customer_user,
            template_name='test_branding_template',
            context={'customer_name': self.customer.name},
            customer=self.customer,
            scheduled_for=timezone.now() + timedelta(hours=1),
        )
        self.assertIsNotNone(notification)
        branding = notification.template_context.get('branding')
        self.assertIsNotNone(branding)
        self.assertEqual(branding['company_name'], 'Duncan Auto Glass')

    def test_explicit_branding_not_overwritten(self):
        from core.services.notification_service import NotificationService
        notification = NotificationService.create_notification(
            recipient=self.customer_user,
            template_name='test_branding_template',
            context={'customer_name': self.customer.name, 'branding': {'company_name': 'Custom'}},
            customer=self.customer,
            scheduled_for=timezone.now() + timedelta(hours=1),
        )
        self.assertEqual(notification.template_context['branding']['company_name'], 'Custom')
