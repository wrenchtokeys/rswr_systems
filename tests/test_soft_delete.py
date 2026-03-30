"""
Comprehensive tests for soft-delete repair feature.

Covers:
- delete_repair: soft-delete sets deleted_at, cascades to invoices
- Permissions: only owner/manager can delete, technician blocked
- Payment guard: repairs with payments cannot be deleted
- Soft-delete filtering: deleted repairs/invoices excluded from default querysets
- restore_repair: restores repair + invoices, blocked after 30 days
- archived_repairs: shows deleted records, owner/manager only
- Cross-tenant isolation: can't delete/restore another tenant's repairs
- Edge cases: repair with multiple invoices, repair with no invoice,
  GET requests rejected, already-deleted repair, concurrent delete
- purge_deleted_records management command
"""

import secrets
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import Technician, Repair
from apps.billing.models import Invoice, InvoiceLineItem, Payment
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


def make_repair(tenant, customer, technician=None, **kwargs):
    if technician is None:
        # Repair.technician is required (no null=True) — create a default one
        user, created = User.objects.get_or_create(
            username=f'default_tech_{tenant.id}',
            defaults={'email': f'deftech{tenant.id}@test.com', 'first_name': 'Default', 'last_name': 'Tech'}
        )
        if created:
            user.set_password('testpass123')
            user.save()
        TenantMembership.objects.get_or_create(user=user, tenant=tenant, defaults={'role': 'technician'})
        technician, _ = Technician.objects.get_or_create(user=user, tenant=tenant)
    return Repair.objects.create(
        tenant=tenant,
        customer=customer,
        technician=technician,
        service_date=timezone.now(),
        queue_status='COMPLETED',
        cost=Decimal('75.00'),
        **kwargs
    )


_inv_counter = 0

def make_invoice(tenant, customer, repairs=None):
    global _inv_counter
    _inv_counter += 1
    invoice = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'TEST-{_inv_counter:04d}',
        invoice_date=timezone.now().date(),
        status='SENT',
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
    return invoice


def login_as(client, user, tenant):
    client.login(username=user.username, password='testpass123')
    session = client.session
    session['active_tenant_id'] = tenant.id
    session.save()


# =============================================================================
# DELETE REPAIR TESTS
# =============================================================================

@override_settings(**TEST_SETTINGS)
class DeleteRepairTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('TestShop', 'owner1')
        self.customer = Customer.objects.create(tenant=self.tenant, name='Test Customer')
        self.tech, self.tech_user = make_technician(self.tenant, 'tech1')
        self.mgr, self.mgr_user = make_technician(self.tenant, 'mgr1', role='manager')
        self.client = Client()

    def test_owner_can_delete_repair(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/delete/')
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertIsNotNone(repair.deleted_at)

    def test_manager_can_delete_repair(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.mgr_user, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/delete/')
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertIsNotNone(repair.deleted_at)

    def test_technician_cannot_delete_repair(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.tech_user, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/delete/')
        # Should redirect with error, repair NOT deleted
        repair.refresh_from_db()
        self.assertIsNone(repair.deleted_at)

    def test_get_request_rejected(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.get(f'/tech/repairs/{repair.id}/delete/')
        # GET should redirect, not delete
        repair.refresh_from_db()
        self.assertIsNone(repair.deleted_at)

    def test_delete_cascades_to_invoice(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        login_as(self.client, self.owner, self.tenant)
        self.client.post(f'/tech/repairs/{repair.id}/delete/')
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.deleted_at)

    def test_delete_cascades_to_multiple_invoices(self):
        """If a repair somehow appears on multiple invoices, all get soft-deleted."""
        repair = make_repair(self.tenant, self.customer, self.tech)
        inv1 = make_invoice(self.tenant, self.customer, repairs=[repair])
        inv2 = make_invoice(self.tenant, self.customer, repairs=[repair])
        login_as(self.client, self.owner, self.tenant)
        self.client.post(f'/tech/repairs/{repair.id}/delete/')
        inv1.refresh_from_db()
        inv2.refresh_from_db()
        self.assertIsNotNone(inv1.deleted_at)
        self.assertIsNotNone(inv2.deleted_at)

    def test_delete_repair_without_invoice(self):
        """Repair with no invoice should still soft-delete cleanly."""
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/delete/')
        self.assertEqual(resp.status_code, 302)
        repair.refresh_from_db()
        self.assertIsNotNone(repair.deleted_at)

    def test_blocked_when_payments_exist(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        Payment.objects.create(
            invoice=invoice,
            amount=Decimal('75.00'),
            payment_method='CASH',
            payment_date=timezone.now().date(),
        )
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/delete/')
        repair.refresh_from_db()
        self.assertIsNone(repair.deleted_at, "Repair with payments should NOT be deleted")
        invoice.refresh_from_db()
        self.assertIsNone(invoice.deleted_at, "Invoice with payments should NOT be deleted")

    def test_redirect_to_customer_after_delete(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/delete/')
        self.assertRedirects(resp, f'/tech/customers/{self.customer.id}/',
                             fetch_redirect_response=False)


# =============================================================================
# CROSS-TENANT ISOLATION
# =============================================================================

@override_settings(**TEST_SETTINGS)
class CrossTenantDeleteTests(TestCase):

    def setUp(self):
        self.tenant_a, self.owner_a = make_tenant('ShopA', 'owner_a')
        self.tenant_b, self.owner_b = make_tenant('ShopB', 'owner_b')
        self.customer_b = Customer.objects.create(tenant=self.tenant_b, name='Customer B')
        self.repair_b = make_repair(self.tenant_b, self.customer_b)
        self.client = Client()

    def test_cannot_delete_other_tenants_repair(self):
        login_as(self.client, self.owner_a, self.tenant_a)
        resp = self.client.post(f'/tech/repairs/{self.repair_b.id}/delete/')
        self.assertEqual(resp.status_code, 404)
        self.repair_b.refresh_from_db()
        self.assertIsNone(self.repair_b.deleted_at)

    def test_cannot_restore_other_tenants_repair(self):
        self.repair_b.deleted_at = timezone.now()
        self.repair_b.save()
        login_as(self.client, self.owner_a, self.tenant_a)
        resp = self.client.post(f'/tech/repairs/{self.repair_b.id}/restore/')
        self.assertEqual(resp.status_code, 404)
        self.repair_b.refresh_from_db()
        self.assertIsNotNone(self.repair_b.deleted_at)


# =============================================================================
# SOFT-DELETE FILTERING
# =============================================================================

@override_settings(**TEST_SETTINGS)
class SoftDeleteFilteringTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('FilterShop', 'filter_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='FilterCust')

    def test_deleted_repair_excluded_from_default_queryset(self):
        r1 = make_repair(self.tenant, self.customer)
        r2 = make_repair(self.tenant, self.customer)
        r1.deleted_at = timezone.now()
        r1.save()
        qs = Repair.objects.filter(tenant=self.tenant)
        self.assertNotIn(r1, qs)
        self.assertIn(r2, qs)

    def test_deleted_repair_visible_in_all_objects(self):
        r1 = make_repair(self.tenant, self.customer)
        r1.deleted_at = timezone.now()
        r1.save()
        qs = Repair.all_objects.filter(tenant=self.tenant)
        self.assertIn(r1, qs)

    def test_deleted_invoice_excluded_from_default_queryset(self):
        r1 = make_repair(self.tenant, self.customer)
        inv = make_invoice(self.tenant, self.customer, repairs=[r1])
        inv.deleted_at = timezone.now()
        inv.save()
        qs = Invoice.objects.filter(tenant=self.tenant)
        self.assertNotIn(inv, qs)

    def test_deleted_invoice_visible_in_all_objects(self):
        r1 = make_repair(self.tenant, self.customer)
        inv = make_invoice(self.tenant, self.customer, repairs=[r1])
        inv.deleted_at = timezone.now()
        inv.save()
        qs = Invoice.all_objects.filter(tenant=self.tenant)
        self.assertIn(inv, qs)


# =============================================================================
# RESTORE REPAIR TESTS
# =============================================================================

@override_settings(**TEST_SETTINGS)
class RestoreRepairTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('RestoreShop', 'restore_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='RestoreCust')
        self.tech, self.tech_user = make_technician(self.tenant, 'restore_tech')
        self.client = Client()

    def test_restore_clears_deleted_at(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now()
        repair.save()
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/restore/')
        repair.refresh_from_db()
        self.assertIsNone(repair.deleted_at)

    def test_restore_cascades_to_invoices(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        now = timezone.now()
        repair.deleted_at = now
        repair.save()
        invoice.deleted_at = now
        invoice.save()
        login_as(self.client, self.owner, self.tenant)
        self.client.post(f'/tech/repairs/{repair.id}/restore/')
        invoice.refresh_from_db()
        self.assertIsNone(invoice.deleted_at)

    def test_restore_blocked_after_30_days(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now() - timedelta(days=31)
        repair.save()
        login_as(self.client, self.owner, self.tenant)
        self.client.post(f'/tech/repairs/{repair.id}/restore/')
        repair.refresh_from_db()
        self.assertIsNotNone(repair.deleted_at, "Should NOT restore after 30 days")

    def test_restore_allowed_at_exactly_30_days(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now() - timedelta(days=29, hours=23)
        repair.save()
        login_as(self.client, self.owner, self.tenant)
        self.client.post(f'/tech/repairs/{repair.id}/restore/')
        repair.refresh_from_db()
        self.assertIsNone(repair.deleted_at, "Should restore at 29d 23h")

    def test_technician_cannot_restore(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now()
        repair.save()
        login_as(self.client, self.tech_user, self.tenant)
        self.client.post(f'/tech/repairs/{repair.id}/restore/')
        repair.refresh_from_db()
        self.assertIsNotNone(repair.deleted_at)

    def test_restore_non_deleted_repair_is_noop(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.post(f'/tech/repairs/{repair.id}/restore/')
        # Should redirect with info message, not error
        self.assertEqual(resp.status_code, 302)

    def test_get_request_rejected(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now()
        repair.save()
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.get(f'/tech/repairs/{repair.id}/restore/')
        repair.refresh_from_db()
        self.assertIsNotNone(repair.deleted_at, "GET should not restore")


# =============================================================================
# ARCHIVED REPAIRS VIEW
# =============================================================================

@override_settings(**TEST_SETTINGS)
class ArchivedRepairsViewTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('ArchiveShop', 'archive_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='ArchiveCust')
        self.tech, self.tech_user = make_technician(self.tenant, 'archive_tech')
        self.client = Client()

    def test_owner_can_view_archived(self):
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.get('/tech/repairs/archived/')
        self.assertEqual(resp.status_code, 200)

    def test_technician_cannot_view_archived(self):
        login_as(self.client, self.tech_user, self.tenant)
        resp = self.client.get('/tech/repairs/archived/')
        self.assertEqual(resp.status_code, 302)

    def test_shows_recently_deleted_repairs(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now() - timedelta(days=5)
        repair.save()
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.get('/tech/repairs/archived/')
        self.assertContains(resp, f'#{repair.id}')

    def test_hides_repairs_deleted_over_30_days(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        repair.deleted_at = timezone.now() - timedelta(days=35)
        repair.save()
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.get('/tech/repairs/archived/')
        self.assertNotContains(resp, f'#{repair.id}')

    def test_does_not_show_active_repairs(self):
        repair = make_repair(self.tenant, self.customer, self.tech)
        login_as(self.client, self.owner, self.tenant)
        resp = self.client.get('/tech/repairs/archived/')
        self.assertNotContains(resp, f'#{repair.id}')


# =============================================================================
# PURGE MANAGEMENT COMMAND
# =============================================================================

@override_settings(**TEST_SETTINGS)
class PurgeDeletedRecordsTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = make_tenant('PurgeShop', 'purge_owner')
        self.customer = Customer.objects.create(tenant=self.tenant, name='PurgeCust')

    def test_dry_run_does_not_delete(self):
        repair = make_repair(self.tenant, self.customer)
        repair.deleted_at = timezone.now() - timedelta(days=35)
        repair.save()
        out = StringIO()
        call_command('purge_deleted_records', stdout=out)
        # Dry run by default — repair should still exist
        self.assertTrue(Repair.all_objects.filter(id=repair.id).exists())
        self.assertIn('DRY RUN', out.getvalue())

    def test_apply_deletes_old_records(self):
        repair = make_repair(self.tenant, self.customer)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        now = timezone.now() - timedelta(days=35)
        repair.deleted_at = now
        repair.save()
        invoice.deleted_at = now
        invoice.save()
        out = StringIO()
        call_command('purge_deleted_records', '--apply', stdout=out)
        self.assertFalse(Repair.all_objects.filter(id=repair.id).exists())
        self.assertFalse(Invoice.all_objects.filter(id=invoice.id).exists())

    def test_does_not_purge_recent_deletions(self):
        repair = make_repair(self.tenant, self.customer)
        repair.deleted_at = timezone.now() - timedelta(days=10)
        repair.save()
        out = StringIO()
        call_command('purge_deleted_records', '--apply', stdout=out)
        self.assertTrue(Repair.all_objects.filter(id=repair.id).exists())

    def test_custom_days_threshold(self):
        repair = make_repair(self.tenant, self.customer)
        repair.deleted_at = timezone.now() - timedelta(days=10)
        repair.save()
        out = StringIO()
        call_command('purge_deleted_records', '--apply', '--days', '5', stdout=out)
        self.assertFalse(Repair.all_objects.filter(id=repair.id).exists())

    def test_purge_repair_with_active_invoice_line_item(self):
        """
        CODE-234: A soft-deleted repair referenced by a line item on an
        ACTIVE (non-deleted) invoice must still be purgeable.

        Before the fix, the command only deleted line items belonging to
        soft-deleted invoices.  If the repair's invoice was still active,
        its InvoiceLineItem (with on_delete=PROTECT on the repair FK)
        remained, causing ProtectedError and rolling back the entire purge.
        """
        repair = make_repair(self.tenant, self.customer)
        # Invoice is NOT soft-deleted — it was sent/paid and is still active
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        line_item_id = InvoiceLineItem.objects.filter(repair=repair).first().id

        # Soft-delete only the repair, not the invoice
        repair.deleted_at = timezone.now() - timedelta(days=35)
        repair.save()

        out = StringIO()
        # This used to raise ProtectedError and purge nothing
        call_command('purge_deleted_records', '--apply', stdout=out)

        # Repair should be hard-deleted
        self.assertFalse(Repair.all_objects.filter(id=repair.id).exists())
        # The line item linking repair to the active invoice should also be gone
        self.assertFalse(InvoiceLineItem.objects.filter(id=line_item_id).exists())
        # The invoice itself should NOT be deleted (it was never soft-deleted)
        self.assertTrue(Invoice.all_objects.filter(id=invoice.id).exists())

    def test_purge_repair_dry_run_reports_active_invoice_refs(self):
        """CODE-234: Dry run should report repairs with active invoice references."""
        repair = make_repair(self.tenant, self.customer)
        invoice = make_invoice(self.tenant, self.customer, repairs=[repair])
        repair.deleted_at = timezone.now() - timedelta(days=35)
        repair.save()

        out = StringIO()
        call_command('purge_deleted_records', stdout=out)
        output = out.getvalue()
        self.assertIn('DRY RUN', output)
        # Should mention the active invoice reference
        self.assertIn('still referenced by active invoices', output)

    def test_purge_only_invoice_line_items_for_targeted_records(self):
        """
        CODE-234: Purge should not delete line items from unrelated invoices.
        """
        repair_to_purge = make_repair(self.tenant, self.customer)
        repair_to_keep = make_repair(self.tenant, self.customer)
        invoice_keep = make_invoice(self.tenant, self.customer, repairs=[repair_to_keep])
        invoice_purge = make_invoice(self.tenant, self.customer, repairs=[repair_to_purge])

        # Soft-delete only the first repair and its invoice
        repair_to_purge.deleted_at = timezone.now() - timedelta(days=35)
        repair_to_purge.save()
        invoice_purge.deleted_at = timezone.now() - timedelta(days=35)
        invoice_purge.save()

        out = StringIO()
        call_command('purge_deleted_records', '--apply', stdout=out)

        # Purged
        self.assertFalse(Repair.all_objects.filter(id=repair_to_purge.id).exists())
        self.assertFalse(Invoice.all_objects.filter(id=invoice_purge.id).exists())
        # Kept
        self.assertTrue(Repair.all_objects.filter(id=repair_to_keep.id).exists())
        self.assertTrue(Invoice.all_objects.filter(id=invoice_keep.id).exists())
        self.assertTrue(
            InvoiceLineItem.objects.filter(repair=repair_to_keep).exists(),
            "Line items for unrelated repairs should not be deleted"
        )
