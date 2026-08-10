"""
Internal notes on job tickets stay shop-only.

Repairs and Replacements have an `internal_notes` field for private shop
notes. Unlike `technician_notes` (repairs) and `description` (replacements),
which flow onto the customer's invoice line description and customer portal,
internal notes must never appear anywhere a customer can see:
- invoice line item descriptions (both invoicing paths)
- customer portal templates
- email templates
"""

import os

from decimal import Decimal

from django.conf import settings
from django.test import TestCase, Client, override_settings

from apps.tenants.models import SubscriptionPlan
from apps.tenants.services.signup_service import create_tenant_with_owner
from apps.technician_portal.models import Repair, Replacement, Technician
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}

INTERNAL_TEXT = 'SECRET-SHOP-NOTE do not show customer'


def make_shop(business_name='Notes Shop', email='notes_owner@test.com'):
    SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={'name': 'Trial', 'monthly_price': 0, 'trial_days': 30, 'is_active': True},
    )
    return create_tenant_with_owner(
        business_name=business_name, email=email,
        password='testpass123!', first_name='Notes', last_name='Owner',
    )


@override_settings(**TEST_SETTINGS)
class InternalNotesFieldTests(TestCase):
    """The field exists on both service types and saves round-trip."""

    def setUp(self):
        result = make_shop()
        self.user = result['user']
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(tenant=self.tenant, user=self.user)
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Co', email='fleet@test.com',
        )

    def test_repair_saves_internal_notes(self):
        repair = Repair.objects.create(
            tenant=self.tenant, technician=self.technician,
            customer=self.customer, unit_number='T-1',
            internal_notes=INTERNAL_TEXT,
        )
        repair.refresh_from_db()
        self.assertEqual(repair.internal_notes, INTERNAL_TEXT)

    def test_replacement_saves_internal_notes(self):
        replacement = Replacement.objects.create(
            tenant=self.tenant, technician=self.technician,
            customer=self.customer, unit_number='T-2',
            parts_cost=Decimal('200.00'), labor_cost=Decimal('100.00'),
            internal_notes=INTERNAL_TEXT,
        )
        replacement.refresh_from_db()
        self.assertEqual(replacement.internal_notes, INTERNAL_TEXT)


@override_settings(**TEST_SETTINGS)
class QuickJobFormInternalNotesTests(TestCase):
    """The unified job form saves internal notes on create."""

    def setUp(self):
        result = make_shop('Quick Shop', 'quick_owner@test.com')
        self.user = result['user']
        self.tenant = result['tenant']
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Quick Fleet', email='qf@test.com',
        )
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def test_quick_job_saves_internal_notes(self):
        response = self.client.post('/tech/jobs/new/', {
            'service_type': 'repair',
            'customer': self.customer.id,
            'unit_number': 'T-9',
            'work_done': 'Chip repair',
            'price': '50.00',
            'internal_notes': INTERNAL_TEXT,
        })
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context.get('form') and response.context['form'].errors)
        repair = Repair.objects.get(tenant=self.tenant, unit_number='T-9')
        self.assertEqual(repair.internal_notes, INTERNAL_TEXT)


@override_settings(**TEST_SETTINGS)
class InternalNotesNeverInvoicedTests(TestCase):
    """Invoice line descriptions never contain internal notes.

    technician_notes/description are intentionally customer-facing;
    internal_notes is the private one.
    """

    def setUp(self):
        result = make_shop('Invoice Shop', 'invoice_owner@test.com')
        self.tenant = result['tenant']
        self.technician = Technician.objects.get(tenant=self.tenant, user=result['user'])
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Billed Fleet', email='bf@test.com',
        )

    def test_record_first_invoice_path_excludes_internal_notes(self):
        repair = Repair.objects.create(
            tenant=self.tenant, technician=self.technician,
            customer=self.customer, unit_number='T-10',
            queue_status='COMPLETED',
            technician_notes='Resin injected, cured 15 min',
            internal_notes=INTERNAL_TEXT,
        )
        replacement = Replacement.objects.create(
            tenant=self.tenant, technician=self.technician,
            customer=self.customer, unit_number='T-11',
            queue_status='COMPLETED',
            parts_cost=Decimal('250.00'), labor_cost=Decimal('150.00'),
            description='OEM windshield installed',
            internal_notes=INTERNAL_TEXT,
        )
        service = InvoiceTrackingService(tenant=self.tenant)
        invoice = service.create_invoice_from_services(
            self.customer, [repair, replacement],
        )
        for line in invoice.line_items.all():
            self.assertNotIn(INTERNAL_TEXT, line.description)
            self.assertNotIn('SECRET-SHOP-NOTE', line.description)

    def test_legacy_line_item_builder_excludes_internal_notes(self):
        from apps.billing.services.invoice_service import InvoiceService

        repair = Repair.objects.create(
            tenant=self.tenant, technician=self.technician,
            customer=self.customer, unit_number='T-12',
            queue_status='COMPLETED',
            technician_notes='Visible work note',
            internal_notes=INTERNAL_TEXT,
        )
        line = InvoiceService(tenant=self.tenant)._build_line_item(repair)
        self.assertIn('Visible work note', line.description)
        self.assertNotIn(INTERNAL_TEXT, line.description)


class CustomerFacingTemplateGuardTests(TestCase):
    """No customer-facing template may ever reference internal_notes.

    Shop-side templates (technician_portal, saas) do render it — that is the
    point. Customer portal pages, emails, and invoice PDFs must not.
    """

    CUSTOMER_FACING_DIRS = [
        'templates/customer_portal',
        'templates/emails',
        'templates/billing',
    ]

    def test_internal_notes_not_referenced(self):
        base = settings.BASE_DIR
        offenders = []
        for rel_dir in self.CUSTOMER_FACING_DIRS:
            root_dir = os.path.join(base, rel_dir)
            if not os.path.isdir(root_dir):
                continue
            for dirpath, _dirnames, filenames in os.walk(root_dir):
                for filename in filenames:
                    if not filename.endswith('.html'):
                        continue
                    path = os.path.join(dirpath, filename)
                    with open(path, encoding='utf-8') as f:
                        if 'internal_notes' in f.read():
                            offenders.append(os.path.relpath(path, base))
        self.assertEqual(
            offenders, [],
            f'internal_notes leaked into customer-facing templates: {offenders}',
        )
