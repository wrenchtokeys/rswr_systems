"""
Tests for the delete-anything flows (prod test-data cleanup).

Everything soft-deletes with a 30-day restore window:
- Owner invoice delete (single endpoint + bulk action) for ANY status,
  payments kept intact for restore; jobs become re-invoicable immediately
- Replacement delete soft-deletes the replacement + linked invoices
- Customer delete cascades: jobs + invoices soft-deleted, portal logins
  deactivated; restore brings back exactly what was deleted with them
- Portal user removal deactivates the login (restorable)
- purge_deleted_records hard-deletes everything after the window
"""

import json
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair, Replacement
from apps.billing.models import Invoice, InvoiceLineItem, Payment
from apps.billing.services.invoice_tracking_service import InvoiceTrackingService
from apps.customer_portal.models import CustomerUser
from core.models import Customer


TEST_SETTINGS = {
    'EMAIL_BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
}


def make_tenant(name, username):
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='trial',
        defaults={
            'name': 'Trial',
            'monthly_price': Decimal('0.00'),
            'trial_days': 30,
            'display_order': 0,
        }
    )
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name='Owner', last_name='User')
    tenant = Tenant.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        subdomain=name.lower().replace(' ', '-'),
        owner=user,
        subscription_plan=plan,
        subscription_status='active',
    )
    TenantMembership.objects.create(user=user, tenant=tenant, role='owner')
    return tenant, user


def make_technician(tenant, username, role='technician'):
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name=username.title(), last_name='User')
    TenantMembership.objects.create(user=user, tenant=tenant, role=role)
    tech = Technician.objects.create(user=user, tenant=tenant)
    return tech, user


def make_repair(tenant, customer, technician, **kwargs):
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        service_date=timezone.now(),
        queue_status='COMPLETED',
        cost=Decimal('75.00'),
        **kwargs
    )


def make_replacement(tenant, customer, technician, **kwargs):
    return Replacement.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        service_date=timezone.now(),
        queue_status='COMPLETED',
        cost=Decimal('350.00'),
        glass_position='WINDSHIELD',
        parts_cost=Decimal('250.00'),
        labor_cost=Decimal('100.00'),
        **kwargs
    )


_inv_counter = 0


def make_invoice(tenant, customer, repairs=None, replacements=None, status='SENT'):
    global _inv_counter
    _inv_counter += 1
    invoice = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'DELFLOW-{_inv_counter:04d}',
        invoice_date=timezone.now().date(),
        status=status,
        subtotal=Decimal('75.00'),
        total=Decimal('75.00'),
        amount_paid=Decimal('0.00'),
        payment_terms='COD',
    )
    for repair in (repairs or []):
        InvoiceLineItem.objects.create(
            invoice=invoice,
            repair=repair,
            description=f'Repair #{repair.id}',
            quantity=1,
            unit_price=repair.cost,
        )
    for replacement in (replacements or []):
        InvoiceLineItem.objects.create(
            invoice=invoice,
            replacement=replacement,
            description=f'Replacement #{replacement.id}',
            quantity=1,
            unit_price=replacement.cost,
        )
    return invoice


def make_payment(invoice, amount=Decimal('75.00')):
    return Payment.objects.create(
        invoice=invoice,
        amount=amount,
        payment_method='CASH',
        payment_date=timezone.now().date(),
    )


def make_portal_user(customer, username):
    user = User.objects.create_user(username, f'{username}@test.com', 'testpass123',
                                    first_name=username.title(), last_name='Portal')
    cu = CustomerUser.objects.create(user=user, customer=customer)
    return cu, user


def login_as(client, user, tenant):
    client.force_login(user)
    session = client.session
    session['tenant_id'] = tenant.id
    session.save()


def refresh_all(*objs):
    for obj in objs:
        obj.refresh_from_db()


# =============================================================================
# INVOICE DELETE (single + bulk, any status, soft)
# =============================================================================

@override_settings(**TEST_SETTINGS)
class InvoiceDeleteTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('InvDelShop', 'invdel_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='InvDel Customer')
        self.tech, self.tech_user = make_technician(self.tenant, 'invdel_tech')
        self.client = Client()
        login_as(self.client, self.owner, self.tenant)

    def test_single_delete_sent_invoice_with_payment(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        payment = make_payment(invoice)

        resp = self.client.post(f'/owner/invoices/{invoice.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

        # Soft-deleted: hidden from default queryset, row + payment intact
        self.assertFalse(Invoice.objects.filter(id=invoice.id).exists())
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.deleted_at)
        self.assertTrue(Payment.objects.filter(id=payment.id).exists(),
                        "Payments must survive for restore")

        # The repair is re-invoicable while the invoice sits in the trash
        uninvoiced = InvoiceTrackingService(tenant=self.tenant).get_uninvoiced_repairs(self.customer)
        self.assertIn(repair, uninvoiced)

    def test_restore_invoice(self):
        invoice = make_invoice(self.tenant, self.customer)
        invoice.deleted_at = timezone.now()
        invoice.save(update_fields=['deleted_at'])

        resp = self.client.post(f'/tech/invoices/{invoice.id}/restore/')
        self.assertEqual(resp.status_code, 302)
        invoice.refresh_from_db()
        self.assertIsNone(invoice.deleted_at)

    def test_restore_invoice_blocked_after_30_days(self):
        invoice = make_invoice(self.tenant, self.customer)
        invoice.deleted_at = timezone.now() - timezone.timedelta(days=31)
        invoice.save(update_fields=['deleted_at'])

        self.client.post(f'/tech/invoices/{invoice.id}/restore/')
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.deleted_at)

    def test_single_delete_requires_post(self):
        invoice = make_invoice(self.tenant, self.customer)
        resp = self.client.get(f'/owner/invoices/{invoice.id}/delete/')
        self.assertEqual(resp.status_code, 405)
        invoice.refresh_from_db()
        self.assertIsNone(invoice.deleted_at)

    def test_single_delete_cross_tenant_blocked(self):
        other_tenant, other_owner = make_tenant('OtherInvShop', 'other_inv_owner')
        other_customer = Customer.objects.create(tenant=other_tenant, name='Other Cust')
        other_invoice = make_invoice(other_tenant, other_customer)

        resp = self.client.post(f'/owner/invoices/{other_invoice.id}/delete/')
        self.assertEqual(resp.status_code, 404)
        other_invoice.refresh_from_db()
        self.assertIsNone(other_invoice.deleted_at)

    def test_bulk_delete_any_status(self):
        inv_sent = make_invoice(self.tenant, self.customer, status='SENT')
        inv_paid = make_invoice(self.tenant, self.customer, status='PAID')
        payment = make_payment(inv_paid)
        inv_draft = make_invoice(self.tenant, self.customer, status='DRAFT')

        resp = self.client.post(
            '/owner/invoices/bulk/',
            data=json.dumps({'action': 'delete',
                             'invoice_ids': [inv_sent.id, inv_paid.id, inv_draft.id]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('3 invoice(s) deleted', data['message'])

        refresh_all(inv_sent, inv_paid, inv_draft)
        self.assertIsNotNone(inv_sent.deleted_at)
        self.assertIsNotNone(inv_paid.deleted_at)
        self.assertIsNotNone(inv_draft.deleted_at)
        self.assertTrue(Payment.objects.filter(id=payment.id).exists())

    def test_bulk_delete_scoped_to_tenant(self):
        other_tenant, _ = make_tenant('OtherBulkShop', 'other_bulk_owner')
        other_customer = Customer.objects.create(tenant=other_tenant, name='Other Bulk Cust')
        other_invoice = make_invoice(other_tenant, other_customer)

        resp = self.client.post(
            '/owner/invoices/bulk/',
            data=json.dumps({'action': 'delete', 'invoice_ids': [other_invoice.id]}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        other_invoice.refresh_from_db()
        self.assertIsNone(other_invoice.deleted_at)


# =============================================================================
# REPLACEMENT DELETE (soft) + RESTORE
# =============================================================================

@override_settings(**TEST_SETTINGS)
class ReplacementDeleteTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('RepDelShop', 'repdel_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='RepDel Customer')
        self.tech, self.tech_user = make_technician(self.tenant, 'repdel_tech')
        self.client = Client()

    def test_owner_can_delete_replacement_with_paid_invoice(self):
        replacement = make_replacement(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, replacements=[replacement])
        payment = make_payment(invoice)

        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/replacement/{replacement.id}/delete/')
        self.assertEqual(resp.status_code, 302)

        # Soft-deleted, hidden from default querysets, payments intact
        self.assertFalse(Replacement.objects.filter(id=replacement.id).exists())
        refresh_all(replacement, invoice)
        self.assertIsNotNone(replacement.deleted_at)
        self.assertIsNotNone(invoice.deleted_at)
        self.assertTrue(Payment.objects.filter(id=payment.id).exists())

    def test_restore_replacement_restores_invoice(self):
        replacement = make_replacement(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, replacements=[replacement])
        now = timezone.now()
        replacement.deleted_at = now
        replacement.save(update_fields=['deleted_at'])
        invoice.deleted_at = now
        invoice.save(update_fields=['deleted_at'])

        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/replacements/{replacement.id}/restore/')
        self.assertEqual(resp.status_code, 302)
        refresh_all(replacement, invoice)
        self.assertIsNone(replacement.deleted_at)
        self.assertIsNone(invoice.deleted_at)

    def test_technician_cannot_delete_replacement(self):
        replacement = make_replacement(self.tenant, self.customer, self.tech)
        login_as(self.client, self.tech_user, self.tenant)
        self.client.post(f'/tech/replacement/{replacement.id}/delete/')
        replacement.refresh_from_db()
        self.assertIsNone(replacement.deleted_at)

    def test_cross_tenant_delete_blocked(self):
        other_tenant, other_owner = make_tenant('OtherRepShop', 'other_rep_owner')
        login_as(self.client, other_owner, other_tenant)
        replacement = make_replacement(self.tenant, self.customer, self.tech)
        self.client.post(f'/tech/replacement/{replacement.id}/delete/')
        replacement.refresh_from_db()
        self.assertIsNone(replacement.deleted_at)


# =============================================================================
# CUSTOMER CASCADE DELETE (soft) + RESTORE
# =============================================================================

@override_settings(**TEST_SETTINGS)
class CustomerCascadeDeleteTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('CustDelShop', 'custdel_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='CustDel Customer')
        self.tech, self.tech_user = make_technician(self.tenant, 'custdel_tech')
        self.client = Client()

    def test_delete_customer_with_full_history(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        replacement = make_replacement(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer,
                               repairs=[repair], replacements=[replacement])
        payment = make_payment(invoice)
        cu, portal_user = make_portal_user(self.customer, 'custdel_portal')

        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/customers/{self.customer.id}/delete/')
        self.assertEqual(resp.status_code, 302)

        # Everything soft-deleted / deactivated; nothing hard-deleted
        refresh_all(self.customer, repair, replacement, invoice, cu, portal_user)
        self.assertIsNotNone(self.customer.deleted_at)
        self.assertIsNotNone(repair.deleted_at)
        self.assertIsNotNone(replacement.deleted_at)
        self.assertIsNotNone(invoice.deleted_at)
        self.assertIsNotNone(cu.deactivated_at)
        self.assertFalse(portal_user.is_active)
        self.assertTrue(Payment.objects.filter(id=payment.id).exists())

        # Hidden from normal querysets
        self.assertFalse(Customer.objects.filter(id=self.customer.id).exists())
        self.assertFalse(Repair.objects.filter(id=repair.id).exists())
        self.assertFalse(Replacement.objects.filter(id=replacement.id).exists())
        self.assertFalse(Invoice.objects.filter(id=invoice.id).exists())

    def test_restore_customer_restores_cascade(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        cu, portal_user = make_portal_user(self.customer, 'custdel_portal2')

        # A repair deleted BEFORE the customer keeps its own (older) stamp
        old_repair = make_repair(self.tenant, self.customer, self.tech)
        old_repair.deleted_at = timezone.now() - timezone.timedelta(days=3)
        old_repair.save(update_fields=['deleted_at'])

        login_as(self.client, self.owner, self.tenant)
        self.client.post(f'/tech/customers/{self.customer.id}/delete/')
        resp = self.client.post(f'/tech/customers/{self.customer.id}/restore/')
        self.assertEqual(resp.status_code, 302)

        refresh_all(self.customer, repair, invoice, cu, portal_user, old_repair)
        self.assertIsNone(self.customer.deleted_at)
        self.assertIsNone(repair.deleted_at)
        self.assertIsNone(invoice.deleted_at)
        self.assertIsNone(cu.deactivated_at)
        self.assertTrue(portal_user.is_active)
        # The separately-deleted repair stays in the trash
        self.assertIsNotNone(old_repair.deleted_at)

    def test_can_recreate_fleet_name_while_deleted(self):
        """The FLEET unique-name constraint ignores soft-deleted customers."""
        fleet = Customer.objects.create(
            tenant=self.tenant, name='Penske Test', customer_type='FLEET')
        fleet.deleted_at = timezone.now()
        fleet.save(update_fields=['deleted_at'])

        # Recreating the same name must not raise IntegrityError
        again = Customer.objects.create(
            tenant=self.tenant, name='Penske Test', customer_type='FLEET')
        self.assertIsNotNone(again.id)

    def test_technician_cannot_delete_customer(self):
        login_as(self.client, self.tech_user, self.tenant)
        self.client.post(f'/tech/customers/{self.customer.id}/delete/')
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.deleted_at)

    def test_cross_tenant_delete_blocked(self):
        other_tenant, other_owner = make_tenant('OtherCustShop', 'other_cust_owner')
        login_as(self.client, other_owner, other_tenant)
        self.client.post(f'/tech/customers/{self.customer.id}/delete/')
        self.customer.refresh_from_db()
        self.assertIsNone(self.customer.deleted_at)


# =============================================================================
# PORTAL USER REMOVAL (deactivate + restore)
# =============================================================================

@override_settings(**TEST_SETTINGS)
class RemovePortalUserTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('PuDelShop', 'pudel_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='PuDel Customer')
        self.tech, self.tech_user = make_technician(self.tenant, 'pudel_tech')
        self.client = Client()

    def test_owner_can_remove_and_restore_portal_user(self):
        cu, portal_user = make_portal_user(self.customer, 'pudel_portal')
        login_as(self.client, self.owner, self.tenant)

        resp = self.client.post(
            f'/tech/customers/{self.customer.id}/portal-users/{cu.id}/remove/')
        self.assertEqual(resp.status_code, 302)
        refresh_all(cu, portal_user)
        self.assertIsNotNone(cu.deactivated_at)
        self.assertFalse(portal_user.is_active)
        # Not hard-deleted
        self.assertTrue(User.objects.filter(id=portal_user.id).exists())

        resp = self.client.post(
            f'/tech/customers/{self.customer.id}/portal-users/{cu.id}/restore/')
        self.assertEqual(resp.status_code, 302)
        refresh_all(cu, portal_user)
        self.assertIsNone(cu.deactivated_at)
        self.assertTrue(portal_user.is_active)

    def test_plain_technician_cannot_remove_portal_user(self):
        cu, portal_user = make_portal_user(self.customer, 'pudel_portal2')
        login_as(self.client, self.tech_user, self.tenant)
        self.client.post(
            f'/tech/customers/{self.customer.id}/portal-users/{cu.id}/remove/')
        refresh_all(cu, portal_user)
        self.assertIsNone(cu.deactivated_at)
        self.assertTrue(portal_user.is_active)


# =============================================================================
# PURGE AFTER 30 DAYS
# =============================================================================

@override_settings(**TEST_SETTINGS)
class PurgeExtendedTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('PurgeExtShop', 'purgeext_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='PurgeExt Customer')
        self.tech, self.tech_user = make_technician(self.tenant, 'purgeext_tech')

    def test_purge_full_cascade_after_window(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        replacement = make_replacement(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer,
                               repairs=[repair], replacements=[replacement])
        payment = make_payment(invoice)
        cu, portal_user = make_portal_user(self.customer, 'purgeext_portal')

        stamp = timezone.now() - timezone.timedelta(days=35)
        for obj in (repair, replacement, invoice, self.customer):
            obj.deleted_at = stamp
            obj.save(update_fields=['deleted_at'])
        cu.deactivated_at = stamp
        cu.save(update_fields=['deactivated_at'])
        portal_user.is_active = False
        portal_user.save(update_fields=['is_active'])

        out = StringIO()
        call_command('purge_deleted_records', '--apply', stdout=out)

        self.assertFalse(Invoice.all_objects.filter(id=invoice.id).exists())
        self.assertFalse(Payment.objects.filter(id=payment.id).exists())
        self.assertFalse(Repair.all_objects.filter(id=repair.id).exists())
        self.assertFalse(Replacement.all_objects.filter(id=replacement.id).exists())
        self.assertFalse(Customer.all_objects.filter(id=self.customer.id).exists())
        self.assertFalse(User.objects.filter(id=portal_user.id).exists())

    def test_purge_keeps_recent_deletions(self):
        invoice = make_invoice(self.tenant, self.customer)
        invoice.deleted_at = timezone.now() - timezone.timedelta(days=5)
        invoice.save(update_fields=['deleted_at'])
        self.customer.deleted_at = timezone.now() - timezone.timedelta(days=5)
        self.customer.save(update_fields=['deleted_at'])

        out = StringIO()
        call_command('purge_deleted_records', '--apply', stdout=out)

        self.assertTrue(Invoice.all_objects.filter(id=invoice.id).exists())
        self.assertTrue(Customer.all_objects.filter(id=self.customer.id).exists())

    def test_purge_skips_customer_with_active_invoice(self):
        invoice = make_invoice(self.tenant, self.customer)  # active, not deleted
        self.customer.deleted_at = timezone.now() - timezone.timedelta(days=35)
        self.customer.save(update_fields=['deleted_at'])

        out = StringIO()
        call_command('purge_deleted_records', '--apply', stdout=out)

        self.assertTrue(Customer.all_objects.filter(id=self.customer.id).exists())
        self.assertTrue(Invoice.all_objects.filter(id=invoice.id).exists())
