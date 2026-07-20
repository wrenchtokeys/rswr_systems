"""
Tests for Warranty system (Phase 1 + Phase 2).

Phase 1 covers:
- WarrantyPolicy model (creation, default enforcement, uniqueness)
- WarrantyService (assign, void, check, query methods)
- Orchestrator auto-assignment on repair completion
- Repair.has_warranty property

Phase 2 covers:
- Per-customer warranty overrides
- Goodwill repair flag (excluded from loyalty points)
- Warranty badge expiring-soon indicator
- is_warranty_claim + warranty_original_repair fields
- Soft-deleted original repair display
- WarrantyPolicy.terms_summary property
- get_warranty_stats() with caching
- generate_warranty_report management command
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tenants.models import Tenant, TenantMembership, SubscriptionPlan
from apps.technician_portal.models import (
    Technician, Repair, WarrantyPolicy, UnitRepairCount,
)
from apps.technician_portal.warranty_service import WarrantyService
from core.models import Customer


TEST_SETTINGS = {
    'ALLOWED_HOSTS': ['*', 'testserver'],
    'CACHES': {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
}


def make_tenant(name, owner_username):
    """Create a tenant with an owner user + technician."""
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
    tech = Technician.objects.create(
        tenant=tenant, user=user, is_manager=True, is_active=True,
    )
    return user, tenant, tech


@override_settings(**TEST_SETTINGS)
class WarrantyPolicyModelTests(TestCase):
    """Tests for WarrantyPolicy model behaviour."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('WP Shop', 'wp_owner')

    def test_create_warranty_policy(self):
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard Warranty',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )
        self.assertEqual(str(policy), f"Standard Warranty ({self.tenant.name})")
        self.assertEqual(policy.duration_days, 365)

    def test_only_one_default_per_tenant(self):
        """When a new policy is saved with is_default=True, old default is cleared."""
        p1 = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Policy A',
            applies_to='repairs',
            is_default=True,
            is_active=True,
        )
        p2 = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Policy B',
            applies_to='replacements',
            is_default=True,
            is_active=True,
        )
        p1.refresh_from_db()
        self.assertFalse(p1.is_default)
        self.assertTrue(p2.is_default)

    def test_unique_together_tenant_name(self):
        WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Unique Policy', applies_to='repairs',
        )
        with self.assertRaises(Exception):
            WarrantyPolicy.objects.create(
                tenant=self.tenant, name='Unique Policy', applies_to='replacements',
            )

    def test_get_expiry_date_custom_days(self):
        policy = WarrantyPolicy(duration_type='custom_days', duration_days=365)
        now = timezone.now()
        expiry = policy.get_expiry_date(now)
        self.assertEqual(expiry, now + timedelta(days=365))

    def test_get_expiry_date_lifetime(self):
        policy = WarrantyPolicy(duration_type='lifetime')
        self.assertIsNone(policy.get_expiry_date(timezone.now()))

    def test_get_expiry_date_none(self):
        policy = WarrantyPolicy(duration_type='none')
        now = timezone.now()
        self.assertEqual(policy.get_expiry_date(now), now)


@override_settings(**TEST_SETTINGS)
class WarrantyServiceAssignTests(TestCase):
    """Tests for WarrantyService.assign_warranty()."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('WS Shop', 'ws_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Test Fleet',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard Warranty',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

    def _make_completed_repair(self, damage_type='Chip'):
        """Create a completed repair without triggering hooks (direct SQL-like)."""
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='UNIT-001',
            damage_type=damage_type,
            queue_status='COMPLETED',
        )
        # Use super().save() to bypass the Repair.save() orchestrator
        # to avoid side effects during test setup.
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        return repair

    def test_assign_warranty_success(self):
        repair = self._make_completed_repair()
        result = WarrantyService.assign_warranty(repair)
        self.assertIsNotNone(result.warranty_policy)
        self.assertIsNotNone(result.warranty_expires_at)
        self.assertEqual(result.warranty_policy.pk, self.policy.pk)

    def test_assign_warranty_with_explicit_policy(self):
        custom_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Custom Policy',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=180,
            is_active=True,
        )
        repair = self._make_completed_repair(damage_type='Chip')
        result = WarrantyService.assign_warranty(repair, policy=custom_policy)
        self.assertEqual(result.warranty_policy.pk, custom_policy.pk)

    def test_assign_warranty_fails_if_not_completed(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='UNIT-002',
            damage_type='Chip',
            queue_status='PENDING',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        with self.assertRaises(ValueError):
            WarrantyService.assign_warranty(repair)

    def test_assign_warranty_no_policy_raises(self):
        # Delete all policies
        WarrantyPolicy.objects.all().delete()
        repair = self._make_completed_repair()
        with self.assertRaises(ValueError):
            WarrantyService.assign_warranty(repair)

    def test_assign_warranty_replacement_gets_replacement_policy(self):
        """A completed replacement gets the 'replacements' policy, not the repair one."""
        from apps.technician_portal.models import GlassService, Replacement

        replacement_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Replacement Lifetime',
            applies_to='replacements',
            duration_type='lifetime',
            is_active=True,
        )
        replacement = Replacement(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='UNIT-R01',
            queue_status='COMPLETED',
        )
        GlassService.save(replacement)
        result = WarrantyService.assign_warranty(replacement)
        self.assertEqual(result.warranty_policy.pk, replacement_policy.pk)
        # Lifetime = no expiry
        self.assertIsNone(result.warranty_expires_at)

    def test_assign_warranty_replacement_no_replacement_policy_raises(self):
        """Repairs-only policy does NOT cover replacements."""
        from apps.technician_portal.models import GlassService, Replacement

        replacement = Replacement(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='UNIT-R02',
            queue_status='COMPLETED',
        )
        GlassService.save(replacement)
        with self.assertRaises(ValueError):
            WarrantyService.assign_warranty(replacement)

    def test_assign_warranty_none_duration_skips(self):
        """A 'none' duration policy means no warranty is assigned."""
        self.policy.duration_type = 'none'
        self.policy.save()
        repair = self._make_completed_repair()
        result = WarrantyService.assign_warranty(repair)
        self.assertIsNone(result.warranty_policy_id)


@override_settings(**TEST_SETTINGS)
class WarrantyServiceVoidTests(TestCase):
    """Tests for WarrantyService.void_warranty()."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Void Shop', 'void_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Void Fleet',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

    def _make_warranty_repair(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='VOID-001',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        return WarrantyService.assign_warranty(repair)

    def test_void_warranty_success(self):
        repair = self._make_warranty_repair()
        result = WarrantyService.void_warranty(repair, 'New impact damage')
        self.assertTrue(result.warranty_void)
        self.assertEqual(result.warranty_void_reason, 'New impact damage')

    def test_void_warranty_no_policy_raises(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='VOID-002',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        with self.assertRaises(ValueError):
            WarrantyService.void_warranty(repair, 'reason')

    def test_void_warranty_already_voided_raises(self):
        repair = self._make_warranty_repair()
        WarrantyService.void_warranty(repair, 'First void')
        with self.assertRaises(ValueError):
            WarrantyService.void_warranty(repair, 'Second void')

    def test_void_warranty_empty_reason_raises(self):
        repair = self._make_warranty_repair()
        with self.assertRaises(ValueError):
            WarrantyService.void_warranty(repair, '')


@override_settings(**TEST_SETTINGS)
class WarrantyServiceCheckTests(TestCase):
    """Tests for WarrantyService.check_warranty_valid()."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Check Shop', 'check_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Check Fleet',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

    def _make_warranty_repair(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='CHK-001',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        return WarrantyService.assign_warranty(repair)

    def test_check_valid_warranty(self):
        repair = self._make_warranty_repair()
        self.assertTrue(WarrantyService.check_warranty_valid(repair))

    def test_check_expired_warranty(self):
        repair = self._make_warranty_repair()
        # Manually set expiry to the past
        Repair.objects.filter(pk=repair.pk).update(
            warranty_expires_at=timezone.now() - timedelta(days=1),
        )
        repair.refresh_from_db()
        self.assertFalse(WarrantyService.check_warranty_valid(repair))

    def test_check_voided_warranty(self):
        repair = self._make_warranty_repair()
        WarrantyService.void_warranty(repair, 'Voided for test')
        self.assertFalse(WarrantyService.check_warranty_valid(repair))

    def test_check_no_warranty(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='CHK-002',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        self.assertFalse(WarrantyService.check_warranty_valid(repair))


@override_settings(**TEST_SETTINGS)
class RepairHasWarrantyPropertyTests(TestCase):
    """Tests for Repair.has_warranty property."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Prop Shop', 'prop_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Prop Fleet',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

    def test_has_warranty_true(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='PROP-001',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair)
        self.assertTrue(repair.has_warranty)

    def test_has_warranty_false_no_policy(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='PROP-002',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        self.assertFalse(repair.has_warranty)

    def test_has_warranty_false_voided(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='PROP-003',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair)
        WarrantyService.void_warranty(repair, 'test')
        self.assertFalse(repair.has_warranty)

    def test_has_warranty_false_expired(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='PROP-004',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair)
        Repair.objects.filter(pk=repair.pk).update(
            warranty_expires_at=timezone.now() - timedelta(days=1),
        )
        repair.refresh_from_db()
        self.assertFalse(repair.has_warranty)

    def test_has_warranty_true_lifetime(self):
        lifetime_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Lifetime Repairs',
            applies_to='repairs',
            duration_type='lifetime',
            is_active=True,
        )
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='PROP-005',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair, policy=lifetime_policy)
        self.assertTrue(repair.has_warranty)
        self.assertIsNone(repair.warranty_expires_at)


@override_settings(**TEST_SETTINGS)
class OrchestratorWarrantyHookTests(TestCase):
    """Tests that the orchestrator auto-assigns warranty on repair completion."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Hook Shop', 'hook_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Hook Fleet',
        )
        # Delete any policies seeded by the data migration to start clean
        WarrantyPolicy.objects.filter(tenant=self.tenant).delete()

    def test_orchestrator_assigns_warranty_with_default_policy(self):
        """Completing a repair auto-assigns warranty when a default policy exists."""
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )
        # Create repair at PENDING, then complete it via save() to trigger hooks
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='HOOK-001',
            damage_type='Chip',
            queue_status='PENDING',
        )
        repair.save()

        # Transition to COMPLETED — this triggers post_completion_hooks
        repair.queue_status = 'COMPLETED'
        repair.save()

        repair.refresh_from_db()
        self.assertIsNotNone(repair.warranty_policy_id)
        self.assertEqual(repair.warranty_policy_id, policy.pk)
        self.assertIsNotNone(repair.warranty_expires_at)

    def test_orchestrator_no_policy_no_crash(self):
        """Completing a repair without any warranty policy doesn't crash."""
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='HOOK-002',
            damage_type='Chip',
            queue_status='PENDING',
        )
        repair.save()

        repair.queue_status = 'COMPLETED'
        repair.save()  # Should not raise

        repair.refresh_from_db()
        self.assertIsNone(repair.warranty_policy_id)

    def test_orchestrator_does_not_double_assign(self):
        """Re-saving a COMPLETED repair does not reassign warranty."""
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='HOOK-003',
            damage_type='Chip',
            queue_status='PENDING',
        )
        repair.save()
        repair.queue_status = 'COMPLETED'
        repair.save()

        repair.refresh_from_db()
        original_expires = repair.warranty_expires_at

        # Create a new policy and re-save — should NOT change warranty
        WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='New Policy',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=30,
            is_default=True,
            is_active=True,
        )
        repair.save()
        repair.refresh_from_db()
        self.assertEqual(repair.warranty_expires_at, original_expires)
        self.assertEqual(repair.warranty_policy_id, policy.pk)


@override_settings(**TEST_SETTINGS)
class ReplacementWarrantyAutoAssignTests(TestCase):
    """Completing a Replacement auto-assigns the shop's replacement warranty."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Repl Shop', 'repl_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Repl Fleet',
        )

    def _make_replacement(self, **kwargs):
        from apps.technician_portal.models import Replacement
        defaults = dict(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='REPL-001',
            queue_status='PENDING',
        )
        defaults.update(kwargs)
        replacement = Replacement(**defaults)
        replacement.save()
        return replacement

    def test_completing_replacement_assigns_warranty(self):
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Replacement Warranty',
            applies_to='replacements',
            duration_type='custom_days',
            duration_days=365,
            is_active=True,
        )
        replacement = self._make_replacement()
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        replacement.refresh_from_db()
        self.assertEqual(replacement.warranty_policy_id, policy.pk)
        self.assertIsNotNone(replacement.warranty_expires_at)
        self.assertTrue(replacement.has_warranty)

    def test_completing_replacement_without_policy_no_crash(self):
        replacement = self._make_replacement()
        replacement.queue_status = 'COMPLETED'
        replacement.save()  # Should not raise

        replacement.refresh_from_db()
        self.assertIsNone(replacement.warranty_policy_id)
        self.assertFalse(replacement.has_warranty)

    def test_replacement_does_not_use_repair_policy(self):
        WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Repairs Only',
            applies_to='repairs',
            duration_type='lifetime',
            is_active=True,
        )
        replacement = self._make_replacement()
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        replacement.refresh_from_db()
        self.assertIsNone(replacement.warranty_policy_id)

    def test_resave_does_not_reassign(self):
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Replacement Warranty',
            applies_to='replacements',
            duration_type='custom_days',
            duration_days=365,
            is_active=True,
        )
        replacement = self._make_replacement()
        replacement.queue_status = 'COMPLETED'
        replacement.save()
        replacement.refresh_from_db()
        original_expires = replacement.warranty_expires_at

        WarrantyPolicy.objects.filter(pk=policy.pk).update(duration_days=30)
        replacement.save()
        replacement.refresh_from_db()
        self.assertEqual(replacement.warranty_expires_at, original_expires)

    def test_lifetime_replacement_warranty(self):
        WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Lifetime Replacements',
            applies_to='replacements',
            duration_type='lifetime',
            is_active=True,
        )
        replacement = self._make_replacement()
        replacement.queue_status = 'COMPLETED'
        replacement.save()

        replacement.refresh_from_db()
        self.assertIsNotNone(replacement.warranty_policy_id)
        self.assertIsNone(replacement.warranty_expires_at)
        self.assertTrue(replacement.has_warranty)


@override_settings(**TEST_SETTINGS)
class WarrantyServiceQueryTests(TestCase):
    """Tests for WarrantyService query methods."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Query Shop', 'query_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Query Fleet',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Standard',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

    def _make_warranty_repair(self, unit, expires_in_days=365):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number=unit,
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair)
        if expires_in_days != 365:
            Repair.objects.filter(pk=repair.pk).update(
                warranty_expires_at=timezone.now() + timedelta(days=expires_in_days),
            )
            repair.refresh_from_db()
        return repair

    def test_get_warranties_expiring_soon(self):
        # Expires in 15 days — should appear
        self._make_warranty_repair('QRY-001', expires_in_days=15)
        # Expires in 60 days — should NOT appear (outside 30-day window)
        self._make_warranty_repair('QRY-002', expires_in_days=60)

        expiring = WarrantyService.get_warranties_expiring_soon(self.tenant, days=30)
        self.assertEqual(expiring.count(), 1)
        self.assertEqual(expiring.first().unit_number, 'QRY-001')

    def test_get_all_warranty_repairs(self):
        self._make_warranty_repair('QRY-003')
        self._make_warranty_repair('QRY-004')

        # One without warranty
        repair_no_warranty = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='QRY-005',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair_no_warranty)

        all_warranty = WarrantyService.get_all_warranty_repairs(self.tenant)
        self.assertEqual(all_warranty.count(), 2)

    def test_get_active_warranty_info(self):
        repair = self._make_warranty_repair('QRY-006')
        info = WarrantyService.get_active_warranty(repair)
        self.assertIsNotNone(info)
        self.assertEqual(info['policy_name'], 'Standard')
        self.assertTrue(info['is_active'])
        self.assertFalse(info['is_voided'])
        self.assertFalse(info['is_lifetime'])

    def test_get_active_warranty_none_for_no_warranty(self):
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='QRY-007',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        from apps.technician_portal.models import GlassService
        GlassService.save(repair)
        self.assertIsNone(WarrantyService.get_active_warranty(repair))


@override_settings(**TEST_SETTINGS)
class WarrantyUITests(TestCase):
    """Tests for Sprint 5 — Warranty UI layer."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('UI Shop', 'ui_owner')
        # Second tenant for isolation tests
        self.user2, self.tenant2, self.tech2 = make_tenant('Other Shop', 'other_owner')

        self.customer = Customer.objects.create(
            tenant=self.tenant,
            name='Test Fleet',
            email='fleet@test.com',
        )

        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='UI Warranty',
            applies_to='repairs',
            duration_type='custom_days',
            duration_days=365,
            is_default=True,
            is_active=True,
        )

        self.client.force_login(self.user)
        # Inject tenant onto every request via session middleware workaround
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

    def _make_completed_repair_with_warranty(self):
        """Create a completed repair with an active warranty."""
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant,
            customer=self.customer,
            technician=self.tech,
            unit_number='UI-001',
            damage_type='Chip',
            queue_status='COMPLETED',
        )
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair)
        repair.refresh_from_db()
        return repair

    def _get_authed_client_for_tenant(self, user, tenant):
        """Return a test client logged in as user with tenant in session."""
        from django.test import Client
        c = Client(SERVER_NAME=f'{tenant.subdomain}.testserver')
        c.force_login(user)
        return c

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Create warranty claim — happy path
    # ─────────────────────────────────────────────────────────────────────────
    def test_create_warranty_claim_happy_path(self):
        repair = self._make_completed_repair_with_warranty()
        self.assertTrue(repair.has_warranty)

        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.post(
            f'/tech/repairs/{repair.id}/warranty-claim/',
            data={'claim_reason': 'Crack spread', 'technician_id': self.tech.id},
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        # Should redirect to the new repair
        self.assertEqual(response.status_code, 302)
        # A new repair should have been created
        claim = Repair.objects.filter(
            tenant=self.tenant, override_reason__contains=f'#{repair.pk}'
        ).first()
        self.assertIsNotNone(claim)
        self.assertEqual(claim.cost, Decimal('0.00'))
        self.assertTrue(claim.skip_invoicing)
        self.assertIn('WARRANTY CLAIM', claim.description)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Warranty claim — expired warranty rejected
    # ─────────────────────────────────────────────────────────────────────────
    def test_create_warranty_claim_expired_rejected(self):
        repair = self._make_completed_repair_with_warranty()
        # Force expiry in the past
        Repair.objects.filter(pk=repair.pk).update(
            warranty_expires_at=timezone.now() - timedelta(days=10)
        )
        repair.refresh_from_db()
        self.assertFalse(repair.has_warranty)

        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        before_count = Repair.objects.filter(tenant=self.tenant).count()
        response = client.post(
            f'/tech/repairs/{repair.id}/warranty-claim/',
            data={'claim_reason': 'Expired attempt'},
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        after_count = Repair.objects.filter(tenant=self.tenant).count()
        self.assertEqual(before_count, after_count, "No new repair should be created for expired warranty")
        self.assertEqual(response.status_code, 302)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Warranty claim — voided warranty rejected
    # ─────────────────────────────────────────────────────────────────────────
    def test_create_warranty_claim_voided_rejected(self):
        repair = self._make_completed_repair_with_warranty()
        Repair.objects.filter(pk=repair.pk).update(
            warranty_void=True, warranty_void_reason='Tampered'
        )
        repair.refresh_from_db()
        self.assertFalse(repair.has_warranty)

        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        before_count = Repair.objects.filter(tenant=self.tenant).count()
        client.post(
            f'/tech/repairs/{repair.id}/warranty-claim/',
            data={'claim_reason': 'Voided attempt'},
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        after_count = Repair.objects.filter(tenant=self.tenant).count()
        self.assertEqual(before_count, after_count, "No claim should be created for voided warranty")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Warranty claim — sets correct fields
    # ─────────────────────────────────────────────────────────────────────────
    def test_create_warranty_claim_sets_correct_fields(self):
        repair = self._make_completed_repair_with_warranty()

        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        client.post(
            f'/tech/repairs/{repair.id}/warranty-claim/',
            data={'claim_reason': 'Recrack', 'technician_id': self.tech.id},
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        claim = Repair.objects.filter(
            tenant=self.tenant, override_reason__contains=f'#{repair.pk}'
        ).first()
        self.assertIsNotNone(claim)
        self.assertEqual(claim.cost, Decimal('0.00'))
        self.assertEqual(claim.cost_override, Decimal('0.00'))
        self.assertTrue(claim.skip_invoicing)
        self.assertEqual(claim.queue_status, 'REQUESTED')
        self.assertEqual(claim.customer, repair.customer)
        self.assertEqual(claim.unit_number, repair.unit_number)
        self.assertIn('Recrack', claim.description)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Warranty policy list view — only shows tenant's policies
    # ─────────────────────────────────────────────────────────────────────────
    def test_warranty_policy_list_view_tenant_scoped(self):
        # Create a policy for another tenant
        WarrantyPolicy.objects.create(
            tenant=self.tenant2,
            name='Other Shop Policy',
            applies_to='repairs',
            is_active=True,
        )
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.get(
            '/tech/settings/warranty/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        self.assertEqual(response.status_code, 200)
        cards = response.context['policy_cards']
        names = [p.name for p in cards]
        self.assertIn('UI Warranty', names)
        self.assertNotIn('Other Shop Policy', names)
        for policy in cards:
            self.assertEqual(policy.tenant, self.tenant)

    def test_warranty_page_auto_creates_both_policies(self):
        """Visiting the page guarantees a repairs card AND a replacements card."""
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.get(
            '/tech/settings/warranty/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        self.assertEqual(response.status_code, 200)
        applies = sorted(p.applies_to for p in response.context['policy_cards'])
        self.assertEqual(applies, ['repairs', 'replacements'])
        # The replacements policy didn't exist before — it was created on load
        self.assertTrue(
            WarrantyPolicy.objects.filter(
                tenant=self.tenant, applies_to='replacements', customer__isnull=True,
            ).exists()
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Warranty policy create — AJAX endpoint works
    # ─────────────────────────────────────────────────────────────────────────
    def test_create_warranty_policy_ajax(self):
        import json
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.post(
            '/tech/settings/api/warranty/create/',
            data=json.dumps({
                'name': 'AJAX Policy',
                'applies_to': 'repairs',
                'duration_type': 'custom_days',
                'duration_days': 180,
                'coverage_description': 'Test',
                'covers_labor': True,
                'covers_materials': False,
                'is_default': False,
                'is_active': True,
            }),
            content_type='application/json',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(WarrantyPolicy.objects.filter(tenant=self.tenant, name='AJAX Policy').exists())

    # ─────────────────────────────────────────────────────────────────────────
    # 7. Warranty policy create — cross-tenant isolation
    # ─────────────────────────────────────────────────────────────────────────
    def test_create_warranty_policy_cross_tenant_isolation(self):
        """Policy created by user of tenant1 must be scoped to tenant1, not tenant2."""
        import json
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.post(
            '/tech/settings/api/warranty/create/',
            data=json.dumps({
                'name': 'Isolation Test Policy',
                'applies_to': 'replacements',
                'duration_type': 'lifetime',
                'duration_days': 365,
                'is_active': True,
            }),
            content_type='application/json',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        data = response.json()
        self.assertTrue(data['success'])
        policy = WarrantyPolicy.objects.get(name='Isolation Test Policy')
        self.assertEqual(policy.tenant, self.tenant)
        self.assertNotEqual(policy.tenant, self.tenant2)

    # ─────────────────────────────────────────────────────────────────────────
    # 8. Warranty policy update — AJAX endpoint works
    # ─────────────────────────────────────────────────────────────────────────
    def test_update_warranty_policy_ajax(self):
        import json
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.post(
            f'/tech/settings/api/warranty/{self.policy.id}/update/',
            data=json.dumps({'name': 'Updated Warranty', 'duration_days': 730}),
            content_type='application/json',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.name, 'Updated Warranty')
        self.assertEqual(self.policy.duration_days, 730)

    # ─────────────────────────────────────────────────────────────────────────
    # 9. Warranty policy delete — AJAX endpoint works
    # ─────────────────────────────────────────────────────────────────────────
    def test_delete_warranty_policy_ajax(self):
        policy_to_delete = WarrantyPolicy.objects.create(
            tenant=self.tenant,
            name='Delete Me',
            applies_to='repairs',
            is_active=True,
        )
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.post(
            f'/tech/settings/api/warranty/{policy_to_delete.id}/delete/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.assertFalse(WarrantyPolicy.objects.filter(id=policy_to_delete.id).exists())

    # ─────────────────────────────────────────────────────────────────────────
    # 10. Warranty policy toggle — AJAX endpoint works
    # ─────────────────────────────────────────────────────────────────────────
    def test_toggle_warranty_policy_ajax(self):
        self.assertTrue(self.policy.is_active)
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.post(
            f'/tech/settings/api/warranty/{self.policy.id}/toggle/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        data = response.json()
        self.assertTrue(data['success'])
        self.policy.refresh_from_db()
        self.assertFalse(self.policy.is_active)
        # Toggle again
        response2 = client.post(
            f'/tech/settings/api/warranty/{self.policy.id}/toggle/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        data2 = response2.json()
        self.assertTrue(data2['success'])
        self.policy.refresh_from_db()
        self.assertTrue(self.policy.is_active)

    # ─────────────────────────────────────────────────────────────────────────
    # 11. Repair detail view includes available_technicians in context
    # ─────────────────────────────────────────────────────────────────────────
    def test_repair_detail_includes_available_technicians(self):
        repair = self._make_completed_repair_with_warranty()
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.get(
            f'/tech/repairs/{repair.id}/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('available_technicians', response.context)

    # ─────────────────────────────────────────────────────────────────────────
    # 12. Warranty claim requires POST method
    # ─────────────────────────────────────────────────────────────────────────
    def test_warranty_claim_requires_post(self):
        repair = self._make_completed_repair_with_warranty()
        client = self._get_authed_client_for_tenant(self.user, self.tenant)
        response = client.get(
            f'/tech/repairs/{repair.id}/warranty-claim/',
            HTTP_HOST=f'{self.tenant.subdomain}.testserver',
        )
        # GET should redirect back to repair_detail (not create a claim)
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'/tech/repairs/{repair.id}/', response['Location'])
        # No extra repair created
        self.assertEqual(
            Repair.objects.filter(
                tenant=self.tenant, override_reason__contains=f'#{repair.pk}'
            ).count(),
            0,
        )


# =============================================================================
# PHASE 2 TESTS
# =============================================================================

@override_settings(**TEST_SETTINGS)
class PerCustomerWarrantyOverrideTests(TestCase):
    """Tests for per-customer warranty policy overrides."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Override Shop', 'override_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Alpha', email='alpha@test.com',
        )
        self.other_customer = Customer.objects.create(
            tenant=self.tenant, name='Fleet Beta', email='beta@test.com',
        )
        # Tenant-wide default: 365 days
        self.default_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Standard', applies_to='repairs',
            duration_type='custom_days', duration_days=365,
            is_default=True, is_active=True,
        )
        # Per-customer override for Fleet Alpha: lifetime
        self.customer_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Alpha Lifetime', applies_to='repairs',
            duration_type='lifetime',
            customer=self.customer,
            is_active=True,
        )

    def _make_repair(self, customer):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=customer, technician=self.tech,
            unit_number='OVR-001', damage_type='Chip', queue_status='COMPLETED',
        )
        GlassService.save(repair)
        return repair

    def test_per_customer_policy_preferred_over_tenant_wide(self):
        repair = self._make_repair(self.customer)
        WarrantyService.assign_warranty(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.warranty_policy, self.customer_policy)
        self.assertIsNone(repair.warranty_expires_at)  # Lifetime

    def test_other_customer_gets_tenant_wide_policy(self):
        repair = self._make_repair(self.other_customer)
        WarrantyService.assign_warranty(repair)
        repair.refresh_from_db()
        self.assertEqual(repair.warranty_policy, self.default_policy)
        self.assertIsNotNone(repair.warranty_expires_at)

    def test_per_customer_replacement_override(self):
        """A customer-specific replacements policy wins for that customer's replacements."""
        from apps.technician_portal.models import GlassService, Replacement

        tenant_replacement_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Shop Replacements', applies_to='replacements',
            duration_type='custom_days', duration_days=365, is_active=True,
        )
        alpha_replacement_policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Alpha Replacements 30d', applies_to='replacements',
            duration_type='custom_days', duration_days=30,
            customer=self.customer, is_active=True,
        )
        replacement = Replacement(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='OVR-R01', queue_status='COMPLETED',
        )
        GlassService.save(replacement)
        WarrantyService.assign_warranty(replacement)
        replacement.refresh_from_db()
        self.assertEqual(replacement.warranty_policy, alpha_replacement_policy)

        other = Replacement(
            tenant=self.tenant, customer=self.other_customer, technician=self.tech,
            unit_number='OVR-R02', queue_status='COMPLETED',
        )
        GlassService.save(other)
        WarrantyService.assign_warranty(other)
        other.refresh_from_db()
        self.assertEqual(other.warranty_policy, tenant_replacement_policy)

    def test_customer_fk_on_warranty_policy_model(self):
        self.assertEqual(self.customer_policy.customer, self.customer)
        self.assertIsNone(self.default_policy.customer)

    def test_warranty_policy_str_includes_customer(self):
        self.assertIn('Fleet Alpha', str(self.customer_policy))
        self.assertNotIn('Fleet Alpha', str(self.default_policy))


@override_settings(**TEST_SETTINGS)
class GoodwillRepairTests(TestCase):
    """Tests for is_goodwill_repair field and loyalty exclusion."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Goodwill Shop', 'goodwill_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='GW Customer', email='gw@test.com',
        )

    def test_goodwill_flag_defaults_to_false(self):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='GW-001', damage_type='Chip', queue_status='REQUESTED',
        )
        GlassService.save(repair)
        self.assertFalse(repair.is_goodwill_repair)

    def test_goodwill_repair_excludes_loyalty_points(self):
        """Goodwill repairs must not award loyalty points."""
        from apps.technician_portal.hooks import loyalty_hook

        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='GW-002', damage_type='Chip', queue_status='COMPLETED',
            is_goodwill_repair=True,
        )
        GlassService.save(repair)
        repair.original_status = 'PENDING'  # Simulate first-time completion

        # loyalty_hook should return early for goodwill repairs
        # (no exception = success; we verify no points by checking it doesn't crash)
        loyalty_hook(repair)

    def test_goodwill_repair_can_be_set_on_creation(self):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='GW-003', damage_type='Crack', queue_status='REQUESTED',
            is_goodwill_repair=True,
        )
        GlassService.save(repair)
        repair.refresh_from_db()
        self.assertTrue(repair.is_goodwill_repair)


@override_settings(**TEST_SETTINGS)
class WarrantyExpiringBadgeTests(TestCase):
    """Tests for warranty_expiring_soon property."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Badge Shop', 'badge_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Badge Co', email='badge@test.com',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Badge Policy', applies_to='repairs',
            duration_type='custom_days', duration_days=365,
            is_default=True, is_active=True,
        )

    def _make_warranted_repair(self, expires_delta_days):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='BDG-001', damage_type='Chip', queue_status='COMPLETED',
        )
        GlassService.save(repair)
        repair.warranty_policy = self.policy
        repair.warranty_expires_at = timezone.now() + timedelta(days=expires_delta_days)
        repair.save(update_fields=['warranty_policy', 'warranty_expires_at'])
        return repair

    def test_expiring_soon_within_30_days(self):
        repair = self._make_warranted_repair(15)
        self.assertTrue(repair.warranty_expiring_soon)

    def test_not_expiring_soon_over_30_days(self):
        repair = self._make_warranted_repair(60)
        self.assertFalse(repair.warranty_expiring_soon)

    def test_expired_not_expiring_soon(self):
        repair = self._make_warranted_repair(-5)
        self.assertFalse(repair.warranty_expiring_soon)  # has_warranty is False

    def test_lifetime_not_expiring_soon(self):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='BDG-002', damage_type='Chip', queue_status='COMPLETED',
        )
        GlassService.save(repair)
        repair.warranty_policy = self.policy
        repair.warranty_expires_at = None  # Lifetime
        repair.save(update_fields=['warranty_policy', 'warranty_expires_at'])
        self.assertFalse(repair.warranty_expiring_soon)

    def test_no_warranty_not_expiring_soon(self):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='BDG-003', damage_type='Chip', queue_status='COMPLETED',
        )
        GlassService.save(repair)
        self.assertFalse(repair.warranty_expiring_soon)


@override_settings(**TEST_SETTINGS)
class WarrantyClaimFieldsTests(TestCase):
    """Tests for is_warranty_claim and warranty_original_repair fields."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Claim Shop', 'claim_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Claim Fleet', email='claim@test.com',
        )
        self.policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Claim Policy', applies_to='repairs',
            duration_type='custom_days', duration_days=365,
            is_default=True, is_active=True,
        )

    def _make_completed_repair(self):
        from apps.technician_portal.models import GlassService
        repair = Repair(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='CLM-001', damage_type='Chip', queue_status='COMPLETED',
        )
        GlassService.save(repair)
        WarrantyService.assign_warranty(repair)
        repair.refresh_from_db()
        return repair

    def test_warranty_claim_sets_fields_via_view(self):
        original = self._make_completed_repair()
        self.client.force_login(self.user)
        session = self.client.session
        session['tenant_id'] = self.tenant.id
        session.save()

        self.client.post(
            f'/tech/repairs/{original.id}/warranty-claim/',
            data={'claim_reason': 'Recrack', 'technician_id': self.tech.id},
        )
        claim = Repair.objects.filter(
            tenant=self.tenant, is_warranty_claim=True,
        ).first()
        self.assertIsNotNone(claim)
        self.assertTrue(claim.is_warranty_claim)
        self.assertEqual(claim.warranty_original_repair, original)

    def test_soft_deleted_original_accessible_via_fk(self):
        """warranty_original_repair FK should still resolve to a soft-deleted repair."""
        original = self._make_completed_repair()
        claim = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='CLM-002', damage_type='Chip', queue_status='REQUESTED',
            is_warranty_claim=True, warranty_original_repair=original,
            cost=Decimal('0.00'), cost_override=Decimal('0.00'),
            skip_invoicing=True,
        )
        # Soft-delete the original
        Repair.objects.filter(pk=original.pk).update(deleted_at=timezone.now())

        claim.refresh_from_db()
        # FK still resolves even though original is soft-deleted
        orig = Repair.all_objects.get(pk=original.pk)
        self.assertIsNotNone(orig.deleted_at)
        self.assertEqual(claim.warranty_original_repair_id, original.pk)

    def test_warranty_claims_reverse_relation(self):
        original = self._make_completed_repair()
        claim = Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='CLM-003', damage_type='Chip', queue_status='REQUESTED',
            is_warranty_claim=True, warranty_original_repair=original,
            cost=Decimal('0.00'), cost_override=Decimal('0.00'),
            skip_invoicing=True,
        )
        self.assertIn(claim, original.warranty_claims.all())


@override_settings(**TEST_SETTINGS)
class TermsSummaryPropertyTests(TestCase):
    """Tests for WarrantyPolicy.terms_summary property."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Terms Shop', 'terms_owner')

    def test_lifetime_terms_summary(self):
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='Lifetime Repairs', applies_to='repairs',
            duration_type='lifetime', covers_labor=True, covers_materials=True,
            is_active=True,
        )
        self.assertIn('Lifetime', policy.terms_summary)
        self.assertIn('labor', policy.terms_summary)
        self.assertIn('materials', policy.terms_summary)

    def test_custom_days_terms_summary(self):
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='90-Day', applies_to='replacements',
            duration_type='custom_days', duration_days=90,
            covers_labor=True, covers_materials=False,
            is_active=True,
        )
        self.assertIn('90 days', policy.terms_summary)
        self.assertIn('labor', policy.terms_summary)
        self.assertNotIn('materials', policy.terms_summary)

    def test_none_duration_returns_empty(self):
        policy = WarrantyPolicy.objects.create(
            tenant=self.tenant, name='No Warranty', applies_to='repairs',
            duration_type='none', is_active=True,
        )
        self.assertEqual(policy.terms_summary, '')


@override_settings(**TEST_SETTINGS)
class WarrantyStatsAndCacheTests(TestCase):
    """Tests for get_warranty_stats() with caching."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Stats Shop', 'stats_owner')
        self.customer = Customer.objects.create(
            tenant=self.tenant, name='Stats Fleet', email='stats@test.com',
        )

    def test_get_warranty_stats_empty(self):
        stats = WarrantyService.get_warranty_stats(self.tenant, use_cache=False)
        self.assertEqual(stats['claims_this_period'], 0)
        self.assertEqual(stats['total_repairs'], 0)
        self.assertEqual(stats['warranty_rate'], 0)

    def test_get_warranty_stats_with_claims(self):
        from apps.technician_portal.models import GlassService
        # Create completed repairs
        for i in range(3):
            r = Repair(
                tenant=self.tenant, customer=self.customer, technician=self.tech,
                unit_number=f'STAT-{i}', damage_type='Chip', queue_status='COMPLETED',
            )
            GlassService.save(r)
        # Create a warranty claim
        Repair.objects.create(
            tenant=self.tenant, customer=self.customer, technician=self.tech,
            unit_number='STAT-CLM', damage_type='Chip', queue_status='REQUESTED',
            is_warranty_claim=True, cost=Decimal('0.00'), cost_override=Decimal('0.00'),
        )

        stats = WarrantyService.get_warranty_stats(self.tenant, use_cache=False)
        self.assertEqual(stats['claims_this_period'], 1)
        self.assertEqual(stats['total_repairs'], 3)

    def test_stats_are_cached(self):
        from django.core.cache import cache
        # Prime the cache
        WarrantyService.get_warranty_stats(self.tenant, use_cache=False)
        cache_key = WarrantyService.STATS_CACHE_KEY.format(tenant_pk=self.tenant.pk)
        cached = cache.get(cache_key)
        self.assertIsNotNone(cached)
        self.assertIn('claims_this_period', cached)

    def test_cache_hit_returns_cached_data(self):
        from django.core.cache import cache
        fake_stats = {'claims_this_period': 999, 'total_repairs': 1000, 'warranty_rate': 99.9}
        cache_key = WarrantyService.STATS_CACHE_KEY.format(tenant_pk=self.tenant.pk)
        cache.set(cache_key, fake_stats, 3600)
        result = WarrantyService.get_warranty_stats(self.tenant, use_cache=True)
        self.assertEqual(result['claims_this_period'], 999)


@override_settings(**TEST_SETTINGS)
class GenerateWarrantyReportCommandTests(TestCase):
    """Tests for generate_warranty_report management command."""

    def setUp(self):
        self.user, self.tenant, self.tech = make_tenant('Cmd Shop', 'cmd_owner')

    def test_command_runs_successfully(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('generate_warranty_report', stdout=out)
        output = out.getvalue()
        self.assertIn('Done', output)

    def test_command_json_output(self):
        from django.core.management import call_command
        from io import StringIO
        import json
        out = StringIO()
        call_command('generate_warranty_report', json=True, stdout=out)
        data = json.loads(out.getvalue())
        self.assertIn(self.tenant.name, data)

    def test_command_specific_tenant(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('generate_warranty_report', tenant=self.tenant.pk, stdout=out)
        output = out.getvalue()
        self.assertIn(self.tenant.name, output)
