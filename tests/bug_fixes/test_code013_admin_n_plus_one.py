"""
Regression tests for CODE-013: N+1 queries in admin list views.

Three separate issues:
1. InvoiceAdmin.line_item_count — called obj.line_items.count() per row
2. TechnicianAdmin — missing 'tenant' in list_select_related
3. ReferralCodeAdmin.get_referral_count — called Referral.objects.filter(...).count() per row

All three now use queryset annotations / select_related so the list view
executes a fixed number of queries regardless of page size.

Author: Amelia
"""

from django.test import TestCase, RequestFactory, override_settings
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.billing.admin import InvoiceAdmin
from apps.billing.models import Invoice, InvoiceLineItem, Payment
from apps.rewards_referrals.admin import ReferralCodeAdmin
from apps.rewards_referrals.models import ReferralCode, Referral
from apps.technician_portal.admin import TechnicianAdmin
from apps.technician_portal.models import Technician
from apps.tenants.models import Tenant, TenantMembership
from core.models import Customer

import datetime
from decimal import Decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_superuser(username='su_code013'):
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'is_staff': True, 'is_superuser': True}
    )
    user.set_password('x')
    user.save()
    return user


def _make_tenant(name='CODE013Shop'):
    owner = User.objects.create_user(username=f'owner_{name}', password='x')
    tenant, _ = Tenant.objects.get_or_create(
        slug=f'code013-{name.lower()}',
        defaults={'name': name, 'owner': owner, 'is_active': True}
    )
    return tenant


def _make_invoice(tenant, customer, index=1):
    """Create a draft invoice with a given number of line items."""
    inv = Invoice.objects.create(
        tenant=tenant,
        customer=customer,
        invoice_number=f'INV-C013-{index:04d}',
        invoice_date=datetime.date.today(),
        due_date=datetime.date.today() + datetime.timedelta(days=30),
        payment_terms='NET30',
        status='DRAFT',
        subtotal=Decimal('100.00'),
        total=Decimal('100.00'),
    )
    # Add some line items so the count is non-trivial
    for i in range(index % 3 + 1):
        InvoiceLineItem.objects.create(
            invoice=inv,
            description=f'Line item {i + 1}',
            quantity=1,
            unit_price=Decimal('50.00'),
            amount=Decimal('50.00'),
        )
    return inv


# ---------------------------------------------------------------------------
# 1. InvoiceAdmin — line_item_count uses annotation, not per-row COUNT
# ---------------------------------------------------------------------------

class InvoiceAdminLineItemCountTest(TestCase):

    def setUp(self):
        self.site = AdminSite()
        self.admin = InvoiceAdmin(Invoice, self.site)
        self.factory = RequestFactory()
        self.superuser = _make_superuser('su_inv_c013')
        self.tenant = _make_tenant('InvoiceN1')
        self.customer = Customer.objects.create(
            name='N+1 Test Corp', tenant=self.tenant
        )
        # Create 5 invoices with varying line-item counts
        self.invoices = [_make_invoice(self.tenant, self.customer, i + 1) for i in range(5)]

    def _make_request(self):
        req = self.factory.get('/admin/billing/invoice/')
        req.user = self.superuser
        return req

    def test_get_queryset_has_annotation(self):
        """get_queryset() should annotate each invoice with _line_items_count."""
        req = self._make_request()
        qs = self.admin.get_queryset(req)
        first = qs.filter(id=self.invoices[0].id).first()
        self.assertTrue(
            hasattr(first, '_line_items_count'),
            "Invoice queryset should have _line_items_count annotation"
        )

    def test_line_item_count_uses_annotation(self):
        """line_item_count() should return the annotated value, not do a DB hit."""
        req = self._make_request()
        qs = self.admin.get_queryset(req)
        inv = qs.filter(id=self.invoices[0].id).first()
        # Real line item count from DB
        expected = inv.line_items.count()
        # Admin method should return same value from annotation
        result = self.admin.line_item_count(inv)
        self.assertEqual(result, expected)

    def test_no_extra_query_per_invoice_for_line_item_count(self):
        """
        After annotating the queryset, iterating over N invoices and calling
        line_item_count should NOT fire N additional queries.
        """
        req = self._make_request()
        qs = self.admin.get_queryset(req).filter(
            id__in=[inv.id for inv in self.invoices]
        )
        invoices_list = list(qs)   # materialize

        # Now call line_item_count for each; should use annotation (no DB queries)
        with CaptureQueriesContext(connection) as ctx:
            counts = [self.admin.line_item_count(inv) for inv in invoices_list]

        # Annotation is already resolved; no additional queries should fire
        self.assertEqual(
            len(ctx.captured_queries), 0,
            f"Expected 0 extra queries for line_item_count, got {len(ctx.captured_queries)}"
        )
        # Sanity check: counts are non-negative integers
        for c in counts:
            self.assertIsInstance(c, int)
            self.assertGreaterEqual(c, 0)

    def test_line_item_count_sortable(self):
        """line_item_count should have admin_order_field set for column sorting."""
        self.assertEqual(
            self.admin.line_item_count.admin_order_field, '_line_items_count'
        )


# ---------------------------------------------------------------------------
# 2. TechnicianAdmin — 'tenant' in list_select_related
# ---------------------------------------------------------------------------

class TechnicianAdminSelectRelatedTest(TestCase):

    def test_tenant_in_list_select_related(self):
        """TechnicianAdmin must include 'tenant' in list_select_related."""
        site = AdminSite()
        ta = TechnicianAdmin(Technician, site)
        self.assertIn(
            'tenant', ta.list_select_related,
            "TechnicianAdmin.list_select_related must include 'tenant' to avoid N+1 queries"
        )

    def test_user_still_in_list_select_related(self):
        """TechnicianAdmin must still include 'user' in list_select_related."""
        site = AdminSite()
        ta = TechnicianAdmin(Technician, site)
        self.assertIn('user', ta.list_select_related)


# ---------------------------------------------------------------------------
# 3. ReferralCodeAdmin — get_referral_count uses annotation
# ---------------------------------------------------------------------------

class ReferralCodeAdminReferralCountTest(TestCase):

    def setUp(self):
        self.site = AdminSite()
        self.admin = ReferralCodeAdmin(ReferralCode, self.site)
        self.factory = RequestFactory()
        self.superuser = _make_superuser('su_ref_c013')
        self.tenant = _make_tenant('ReferralN1')
        customer_owner = User.objects.create_user(username='cu_owner_ref', password='x')
        self.customer = Customer.objects.create(
            name='Referral Test Corp', tenant=self.tenant
        )

    def _make_request(self):
        req = self.factory.get('/admin/rewards_referrals/referralcode/')
        req.user = self.superuser
        return req

    def test_get_queryset_has_annotation(self):
        """get_queryset() should annotate each ReferralCode with _referral_count."""
        from apps.customer_portal.models import CustomerUser
        cu_user = User.objects.create_user(username='cu_user_ref_ann', password='x')
        cu = CustomerUser.objects.create(
            user=cu_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        code = ReferralCode.objects.create(customer_user=cu, code='TESTANN')
        req = self._make_request()
        qs = self.admin.get_queryset(req)
        result = qs.filter(id=code.id).first()
        self.assertTrue(
            hasattr(result, '_referral_count'),
            "ReferralCode queryset should have _referral_count annotation"
        )

    def test_referral_count_sortable(self):
        """get_referral_count should have admin_order_field for column sorting."""
        self.assertEqual(
            self.admin.get_referral_count.admin_order_field, '_referral_count'
        )

    def test_no_extra_queries_for_referral_count(self):
        """
        After annotating, calling get_referral_count on materialized objects
        should not fire additional DB queries.
        """
        from apps.customer_portal.models import CustomerUser
        cu_user = User.objects.create_user(username='cu_user_ref_nq', password='x')
        cu = CustomerUser.objects.create(
            user=cu_user,
            customer=self.customer,
            is_primary_contact=True,
        )
        # Create 3 referral codes
        codes = []
        for i in range(3):
            code = ReferralCode.objects.create(customer_user=cu, code=f'CODE{i:03d}')
            codes.append(code)

        req = self._make_request()
        qs = self.admin.get_queryset(req).filter(id__in=[c.id for c in codes])
        codes_list = list(qs)  # materialize with annotation

        with CaptureQueriesContext(connection) as ctx:
            counts = [self.admin.get_referral_count(code) for code in codes_list]

        self.assertEqual(
            len(ctx.captured_queries), 0,
            f"Expected 0 extra queries after annotation, got {len(ctx.captured_queries)}"
        )
        for c in counts:
            self.assertIsInstance(c, int)
            self.assertGreaterEqual(c, 0)
