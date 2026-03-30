"""
Subscription Email Polish Tests

Tests for:
- Payment failed email contains attempt count / retry text
- Payment failed email button URL points to /owner/update-payment-method/
- Payment recovered email sent on past_due → active transition
- Payment recovered email NOT sent on normal active renewal
- update-payment-method view redirects to Stripe portal URL
- update-payment-method view requires login and owner role
"""

from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from unittest.mock import patch, MagicMock

from apps.tenants.models import SubscriptionPlan, Tenant, TenantMembership
from apps.tenants.services.signup_service import create_tenant_with_owner


class PaymentFailedEmailTests(TestCase):
    """Test payment_failed email content and URL."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Email Test Shop',
            email='owner@emailtest.com',
            password='testpass123!',
            first_name='Test',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.tenant.stripe_customer_id = 'cus_test123'
        self.tenant.stripe_subscription_id = 'sub_test123'
        self.tenant.save()

    @patch('core.email_utils.send_branded_email')
    def test_payment_failed_email_contains_retry_text(self, mock_email):
        """Payment failed email includes attempt count and retry info."""
        from apps.tenants.webhooks import _handle_invoice_payment_failed

        invoice = {
            'id': 'inv_test',
            'customer': 'cus_test123',
            'subscription': 'sub_test123',
            'attempt_count': 2,
        }
        _handle_invoice_payment_failed(invoice)

        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1] if mock_email.call_args[1] else {}
        if not call_kwargs:
            call_kwargs = dict(zip(
                ['subject', 'recipient_list', 'headline', 'body_paragraphs'],
                mock_email.call_args[0],
            ))
            call_kwargs.update(mock_email.call_args[1])

        body = ' '.join(call_kwargs['body_paragraphs'])
        self.assertIn('attempt 2 of 4', body)
        self.assertIn('Stripe will retry automatically', body)

    @patch('core.email_utils.send_branded_email')
    def test_payment_failed_email_url_points_to_update_payment_method(self, mock_email):
        """Payment failed email button links to /owner/update-payment-method/."""
        from apps.tenants.webhooks import _handle_invoice_payment_failed

        invoice = {
            'id': 'inv_test',
            'customer': 'cus_test123',
            'subscription': 'sub_test123',
            'attempt_count': 1,
        }
        _handle_invoice_payment_failed(invoice)

        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1] if mock_email.call_args[1] else {}
        if not call_kwargs:
            call_kwargs = dict(zip(
                ['subject', 'recipient_list', 'headline', 'body_paragraphs'],
                mock_email.call_args[0],
            ))
            call_kwargs.update(mock_email.call_args[1])

        self.assertIn('/owner/update-payment-method/', call_kwargs['button_url'])
        self.assertNotIn('/owner/billing/', call_kwargs['button_url'])


class PaymentRecoveredEmailTests(TestCase):
    """Test payment_recovered email is sent on past_due → active transition."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='Recovery Test Shop',
            email='owner@recoverytest.com',
            password='testpass123!',
            first_name='Recovery',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.tenant.stripe_customer_id = 'cus_recovery'
        self.tenant.stripe_subscription_id = 'sub_recovery'
        self.tenant.save()

    @patch('core.email_utils.send_branded_email')
    def test_payment_recovered_email_sent_on_past_due_to_active(self, mock_email):
        """Payment recovered email fires when transitioning past_due → active."""
        from apps.tenants.webhooks import _handle_invoice_paid

        self.tenant.subscription_status = 'past_due'
        self.tenant.save(update_fields=['subscription_status'])

        invoice = {
            'id': 'inv_recovered',
            'customer': 'cus_recovery',
            'subscription': 'sub_recovery',
        }
        _handle_invoice_paid(invoice)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')

        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1] if mock_email.call_args[1] else {}
        if not call_kwargs:
            call_kwargs = dict(zip(
                ['subject', 'recipient_list', 'headline', 'body_paragraphs'],
                mock_email.call_args[0],
            ))
            call_kwargs.update(mock_email.call_args[1])

        self.assertIn('Good news', call_kwargs['headline'])
        body = ' '.join(call_kwargs['body_paragraphs'])
        self.assertIn('successfully processed', body)

    @patch('core.email_utils.send_branded_email')
    def test_no_recovered_email_for_normal_active_renewal(self, mock_email):
        """No payment recovered email for normal active → active renewal."""
        from apps.tenants.webhooks import _handle_invoice_paid

        self.tenant.subscription_status = 'active'
        self.tenant.save(update_fields=['subscription_status'])

        invoice = {
            'id': 'inv_renewal',
            'customer': 'cus_recovery',
            'subscription': 'sub_recovery',
        }
        _handle_invoice_paid(invoice)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        mock_email.assert_not_called()


class UpdatePaymentMethodViewTests(TestCase):
    """Test the /owner/update-payment-method/ view."""

    def setUp(self):
        SubscriptionPlan.objects.get_or_create(
            slug='trial',
            defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
        )
        result = create_tenant_with_owner(
            business_name='View Test Shop',
            email='owner@viewtest.com',
            password='testpass123!',
            first_name='View',
            last_name='Owner',
        )
        self.user = result['user']
        self.tenant = result['tenant']
        self.tenant.stripe_customer_id = 'cus_viewtest'
        self.tenant.stripe_subscription_id = 'sub_viewtest'
        self.tenant.save()

    def test_requires_login(self):
        """Unauthenticated users are redirected to login."""
        resp = self.client.get('/owner/update-payment-method/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url)

    def test_requires_owner_or_manager_role(self):
        """Non-owner/manager users are denied access."""
        tech_user = User.objects.create_user(
            username='techuser', password='testpass123!',
        )
        TenantMembership.objects.create(
            user=tech_user, tenant=self.tenant, role='technician', is_active=True,
        )
        self.client.force_login(tech_user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        resp = self.client.get('/owner/update-payment-method/')
        # Should redirect away (not a 200) since technicians can't access owner views
        self.assertNotEqual(resp.status_code, 200)

    @patch('apps.tenants.services.subscription_service.SubscriptionService.create_billing_portal_session')
    def test_redirects_to_stripe_portal(self, mock_portal):
        """Owner is redirected to Stripe billing portal URL."""
        mock_portal.return_value = 'https://billing.stripe.com/session/test_sess'

        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        resp = self.client.get('/owner/update-payment-method/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, 'https://billing.stripe.com/session/test_sess')
        mock_portal.assert_called_once()
