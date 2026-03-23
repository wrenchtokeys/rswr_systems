"""
CODE-163 Regression Test: _assign_smart used 'repairs'/'replacements' instead of 'repair'/'replacement'
as the reverse relation name for Count annotations on Technician.

Root cause: Django's reverse accessor name for an FK with no explicit related_name is the
lowercase model name ('repair'), not the pluralised form ('repairs'). Using 'repairs' raises
FieldError at runtime.

Impact: Any tenant with assignment_strategy='auto' would fail when a customer submitted a
repair request. The Repair record was already committed to the DB before auto_assign_repair()
was called, so the exception was silently swallowed by the outer try/except in
handle_single_repair_request — leaving the repair unassigned and showing the user a false
"Error creating repair request" error message.

Fix: Changed Count('repairs', ...) → Count('repair', ...) and Count('replacements', ...) →
Count('replacement', ...) using a dynamic count_field variable scoped to service_type.
"""

from django.test import TestCase
from django.contrib.auth.models import User

from apps.technician_portal.models import Technician, Repair
from apps.technician_portal.models import Replacement
from apps.tenants.models import Tenant
from apps.tenants.services.assignment_service import (
    _assign_smart,
    _get_eligible_techs,
    auto_assign_repair,
)


def _make_tenant(slug, strategy='auto', owner=None):
    if owner is None:
        owner = User.objects.create_user(
            username=f'owner_{slug}',
            password='test1234',
        )
    return Tenant.objects.create(
        name=f'Test Shop {slug}',
        slug=slug,
        plan='trial',
        owner=owner,
        assignment_strategy=strategy,
    )


def _make_user(username):
    return User.objects.create_user(
        username=username,
        password='test1234',
        first_name='Tech',
        last_name=username.capitalize(),
    )


def _make_tech(user, tenant, can_repair=True, can_replace=True):
    return Technician.objects.create(
        user=user,
        tenant=tenant,
        can_repair=can_repair,
        can_replace=can_replace,
        is_active=True,
    )


class AssignSmartFieldErrorRegressionTest(TestCase):
    """
    Verify that _assign_smart does not raise FieldError when annotating
    Technician queryset with active repair/replacement counts.
    """

    def setUp(self):
        from apps.technician_portal.models import Customer
        self.tenant = _make_tenant('code163-smart', strategy='auto')
        self.user1 = _make_user('tech163a')
        self.user2 = _make_user('tech163b')
        self.tech1 = _make_tech(self.user1, self.tenant)
        self.tech2 = _make_tech(self.user2, self.tenant)
        self.customer = Customer.objects.create(
            name='Test Fleet 163',
            tenant=self.tenant,
        )

    def _make_repair(self, technician, status='IN_PROGRESS'):
        return Repair.objects.create(
            tenant=self.tenant,
            technician=technician,
            customer=self.customer,
            unit_number='UNIT-163',
            queue_status=status,
        )

    def test_assign_smart_does_not_raise_field_error(self):
        """_assign_smart must not raise FieldError for repair service_type."""
        repair = self._make_repair(self.tech1, status='REQUESTED')

        # Pre-load tech1 with 2 active repairs so _assign_smart should prefer tech2
        self._make_repair(self.tech1, status='IN_PROGRESS')
        self._make_repair(self.tech1, status='APPROVED')

        # This previously raised FieldError due to Count('repairs', ...)
        try:
            result = _assign_smart(repair, self.tenant, service_type='repair')
        except Exception as e:
            self.fail(f"_assign_smart raised {type(e).__name__}: {e}")

        # tech2 has 0 active repairs → should be preferred over tech1 (with 2)
        self.assertIsNotNone(result)
        self.assertEqual(result, self.tech2)

    def test_assign_smart_picks_lowest_workload_tech(self):
        """_assign_smart selects the technician with fewest active repairs."""
        # Give tech1 3 active repairs, tech2 has 0
        for _ in range(3):
            self._make_repair(self.tech1, status='IN_PROGRESS')

        repair = self._make_repair(self.tech1, status='REQUESTED')
        assigned = _assign_smart(repair, self.tenant, service_type='repair')
        self.assertEqual(assigned, self.tech2)

    def test_assign_smart_completed_repairs_excluded(self):
        """COMPLETED repairs should not count toward the workload."""
        # tech1 has 5 completed repairs but 0 active — should NOT be penalised
        for _ in range(5):
            self._make_repair(self.tech1, status='COMPLETED')

        # tech2 has 1 active repair
        self._make_repair(self.tech2, status='IN_PROGRESS')

        repair = self._make_repair(self.tech1, status='REQUESTED')
        assigned = _assign_smart(repair, self.tenant, service_type='repair')
        # tech1 (0 active) should beat tech2 (1 active) in workload ordering
        self.assertEqual(assigned, self.tech1)

    def test_assign_smart_replacement_service_type(self):
        """_assign_smart must not raise FieldError for replacement service_type."""
        from apps.technician_portal.models import Replacement
        repair_for_context = self._make_repair(self.tech1, status='REQUESTED')

        try:
            _assign_smart(repair_for_context, self.tenant, service_type='replacement')
        except Exception as e:
            self.fail(f"_assign_smart (replacement) raised {type(e).__name__}: {e}")

    def test_auto_assign_repair_strategy_auto_works(self):
        """auto_assign_repair with strategy='auto' must succeed end-to-end."""
        repair = self._make_repair(self.tech1, status='REQUESTED')

        try:
            result = auto_assign_repair(repair)
        except Exception as e:
            self.fail(f"auto_assign_repair raised {type(e).__name__}: {e}")

        # With only tech1 eligible and strategy=auto (smart), repair goes back to tech1
        # (lowest workload by default — they only have the REQUESTED repair itself)
        self.assertIsNotNone(result)

    def test_eligible_techs_annotated_correctly(self):
        """Eligible techs queryset annotation uses correct reverse accessor."""
        from django.db.models import Count, Q
        eligible = _get_eligible_techs(self.tenant, 'repair')

        # This is the exact annotation from the fixed _assign_smart
        active_statuses = ['PENDING', 'APPROVED', 'IN_PROGRESS', 'REQUESTED']
        count_field = 'repair'
        try:
            result = list(
                eligible.annotate(
                    active_repairs=Count(
                        count_field,
                        filter=Q(**{f'{count_field}__queue_status__in': active_statuses}),
                    )
                ).order_by('active_repairs', 'id')
            )
        except Exception as e:
            self.fail(f"Technician annotation raised {type(e).__name__}: {e}")

        self.assertTrue(len(result) >= 2)
        # All technicians in result should have the active_repairs attribute
        for tech in result:
            self.assertTrue(hasattr(tech, 'active_repairs'))
            self.assertGreaterEqual(tech.active_repairs, 0)
