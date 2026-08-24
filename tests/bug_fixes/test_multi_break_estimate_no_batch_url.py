"""
Regression: /app/services/ raised NoReverseMatch for a multi-break *estimate*.

Bug:
  A customer portal request of "there are several breaks, I don't know how
  many" creates ONE Repair with `is_multi_break_estimate=True` and no
  `repair_batch_id` (apps/customer_portal/views.py, request_repair).
  `Repair.is_part_of_batch` returned True for it anyway, so the services list
  grouped it under the batch key `str(None)` and the template reversed
  `customer_batch_detail` with `'None'`:

      Reverse for 'customer_batch_detail' with arguments '('None',)' not found

  The same conflation silently dropped the repair from the customer dashboard's
  awaiting-approval list (its batch summary came back empty).

Fix:
  `is_part_of_batch` requires an actual `repair_batch_id`; the estimate is a
  single row and renders as an ordinary repair. The two grouping loops in the
  customer portal also guard on the id before building a key.
"""

from decimal import Decimal
import uuid

from django.contrib.auth.models import User
from django.test import TestCase

from apps.billing.models import BillingConfig
from apps.customer_portal.models import CustomerUser
from apps.tenants.models import Tenant, TenantMembership
from apps.technician_portal.models import Repair, Technician
from core.models import Customer


class MultiBreakEstimateNotABatchTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner_mbe", password="test")
        self.tenant = Tenant.objects.create(
            name="Estimate Shop", slug="estimate-shop", owner=self.owner, plan="trial"
        )
        BillingConfig.objects.create(tenant=self.tenant)
        TenantMembership.objects.create(tenant=self.tenant, user=self.owner, role="owner")
        self.technician = Technician.objects.create(
            tenant=self.tenant, user=self.owner, is_active=True, can_repair=True
        )
        self.customer = Customer.objects.create(tenant=self.tenant, name="Fleet Co")

        self.portal_user = User.objects.create_user(username="cust_mbe", password="test")
        self.customer_user = CustomerUser.objects.create(
            user=self.portal_user, customer=self.customer
        )
        TenantMembership.objects.create(
            tenant=self.tenant, user=self.portal_user, role="viewer"
        )

        self.estimate = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number="U777",
            description="Windshield damage (Multiple breaks - count TBD)",
            queue_status="REQUESTED",
            is_multi_break_estimate=True,
            cost=Decimal("50.00"),
        )

    def test_estimate_without_batch_id_is_not_part_of_a_batch(self):
        self.assertIsNone(self.estimate.repair_batch_id)
        self.assertFalse(self.estimate.is_part_of_batch)

    def test_real_batch_member_is_still_part_of_a_batch(self):
        batch_id = uuid.uuid4()
        member = Repair.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.technician,
            unit_number="U888",
            queue_status="PENDING",
            repair_batch_id=batch_id,
            break_number=1,
            total_breaks_in_batch=3,
            cost=Decimal("50.00"),
        )
        self.assertTrue(member.is_part_of_batch)

    def test_services_page_renders_with_a_multi_break_estimate(self):
        self.client.force_login(self.portal_user)
        session = self.client.session
        session["tenant_id"] = self.tenant.id
        session.save()

        response = self.client.get("/app/services/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/app/batch/None/")
