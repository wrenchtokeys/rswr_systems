"""
Regression tests for CODE-283 — no way to add an email at send time from the
job flows.

Field report: "Could not add email to send invoice — had to manually go to
customer and edit and then add email."

The shared send-confirm modal (invoice_send_confirm_modal.html) silently
downgraded to "Save as Draft" when the customer had no email; only the
owner invoice page's own draft modal offered an inline email field. The
modal now shows the same inline input, and the job/repair/replacement
send endpoints forward the typed address as submitted_email so
InvoiceSendService validates it, saves it onto the customer, and sends —
one step, fixed for next time too.
"""

from decimal import Decimal
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from apps.billing.models import Invoice
from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Technician, Replacement
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

SEND_EMAIL = 'apps.billing.services.invoice_email_service.InvoiceEmailService.send_invoice_email'


def make_shop(business_name, email):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    result = create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name='Test', last_name='Owner',
        services_offered='both',
    )
    return result['user'], result['tenant']


@override_settings(**TEST_SETTINGS)
class SendTimeEmailCaptureTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.user, self.tenant = make_shop('Capture Shop', 'capture@test.com')
        self.tech = Technician.objects.get(user=self.user, tenant=self.tenant)
        # No email on file — the field scenario.
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Jane Driver', customer_type='RETAIL',
        )
        self.replacement = Replacement.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='Silver Camry', glass_position='WINDSHIELD',
            queue_status='APPROVED', cost_override=Decimal('300.00'),
        )
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _complete_and_invoice(self, **extra):
        return self.client.post(
            reverse('replacement_complete_and_invoice', args=[self.replacement.pk]),
            data=extra,
        )

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_typed_email_saved_and_invoice_sent(self, mock_send):
        response = self._complete_and_invoice(email='jane@driver.test')
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'jane@driver.test')
        invoice = Invoice.objects.get(tenant=self.tenant)
        self.assertEqual(invoice.status, 'SENT')

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_no_email_still_saves_draft(self, mock_send):
        self._complete_and_invoice()
        invoice = Invoice.objects.get(tenant=self.tenant)
        self.assertEqual(invoice.status, 'DRAFT')
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.email)

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_invalid_email_leaves_draft_and_customer_untouched(self, mock_send):
        self._complete_and_invoice(email='not-an-email')
        invoice = Invoice.objects.get(tenant=self.tenant)
        self.assertEqual(invoice.status, 'DRAFT')
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.email)

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_another_customers_email_is_refused(self, mock_send):
        Customer.objects.create(
            tenant=self.tenant, name='Other Co', customer_type='FLEET',
            email='taken@test.com',
        )
        self._complete_and_invoice(email='taken@test.com')
        invoice = Invoice.objects.get(tenant=self.tenant)
        self.assertEqual(invoice.status, 'DRAFT')
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.email)

    @patch(SEND_EMAIL, return_value=(True, 'ok'))
    def test_existing_email_wins_over_submitted(self, mock_send):
        """Only-when-missing by design: a typed address never overrides an
        email already on file."""
        self.customer.email = 'onfile@test.com'
        self.customer.save(update_fields=['email'])
        self._complete_and_invoice(email='other@test.com')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.email, 'onfile@test.com')
        invoice = Invoice.objects.get(tenant=self.tenant)
        self.assertEqual(invoice.status, 'SENT')

    def test_modal_template_has_inline_email_input(self):
        html = render_to_string('includes/invoice_send_confirm_modal.html', {})
        self.assertIn('sim-new-email', html)
        self.assertIn("inp.name = 'email'", html)
