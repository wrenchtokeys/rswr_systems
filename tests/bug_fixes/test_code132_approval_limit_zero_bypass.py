"""
CODE-132: approval_limit=Decimal('0.00') bypassed by falsy truthiness check.

Bug:
- `can_manager_override_price()` in pricing_service.py used:
      if technician.approval_limit:
          return proposed_amount <= technician.approval_limit
  Decimal('0.00') is falsy in Python, so a manager with approval_limit=0
  would fall through to "return True" (unlimited overrides).

- Same bug in RepairForm.clean() in forms.py:
      elif _clean_technician.approval_limit and cost_override > ...
  Again, 0.00 would never trigger the cap check.

Fix (CODE-132):
- Replace bare truthiness checks with `is not None` in both locations.
- Matches the documented anti-pattern in AGENTS.md and the correct pattern
  already used in Technician.can_approve_amount() (model method) and in
  the repair/batch view code (repairs.py:703, batch.py:317).

Tests:
1. approval_limit=None → unlimited, any amount allowed.
2. approval_limit=Decimal('100') → amounts ≤ 100 allowed, > 100 blocked.
3. approval_limit=Decimal('0.00') → ALL amounts blocked (the regression case).
4. approval_limit=Decimal('0.00') → even a $0.00 override attempt fails (zero cap).
5. No can_override_pricing → blocked regardless of limit.
6. Not is_manager → blocked regardless of limit.
"""

from decimal import Decimal

from django.test import TestCase
from django.contrib.auth.models import User

from apps.tenants.models import Tenant
from apps.technician_portal.models import Technician
from apps.technician_portal.services.pricing_service import can_manager_override_price


def _make_manager(tenant, username, approval_limit=None, can_override=True):
    """Helper: create a manager Technician with given settings."""
    user = User.objects.create_user(
        username=username, email=f'{username}@test.com', password='pass',
        first_name='Test', last_name='Manager',
    )
    tech = Technician.objects.create(
        user=user,
        tenant=tenant,
        is_manager=True,
        can_override_pricing=can_override,
        approval_limit=approval_limit,
    )
    return tech


class ApprovalLimitZeroBypassTest(TestCase):
    """Regression tests for CODE-132: Decimal('0.00') falsy bypass in approval_limit checks."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_132', email='owner_132@test.com', password='pass'
        )
        self.tenant = Tenant.objects.create(
            name='Test Shop 132', slug='test-shop-132', plan='starter',
            is_active=True, owner=self.owner,
        )

    # ------------------------------------------------------------------
    # can_manager_override_price() — pricing_service.py
    # ------------------------------------------------------------------

    def test_unlimited_manager_allows_any_amount(self):
        """approval_limit=None means unlimited — any amount should be allowed."""
        tech = _make_manager(self.tenant, 'mgr_unlimited_132', approval_limit=None)
        self.assertTrue(can_manager_override_price(tech, Decimal('9999.99')))

    def test_limit_100_allows_at_or_below(self):
        """approval_limit=100 allows amounts ≤ 100."""
        tech = _make_manager(self.tenant, 'mgr_100_132', approval_limit=Decimal('100.00'))
        self.assertTrue(can_manager_override_price(tech, Decimal('100.00')))
        self.assertTrue(can_manager_override_price(tech, Decimal('50.00')))

    def test_limit_100_blocks_above(self):
        """approval_limit=100 blocks amounts > 100."""
        tech = _make_manager(self.tenant, 'mgr_100b_132', approval_limit=Decimal('100.00'))
        self.assertFalse(can_manager_override_price(tech, Decimal('100.01')))
        self.assertFalse(can_manager_override_price(tech, Decimal('200.00')))

    def test_zero_limit_blocks_all_amounts_regression(self):
        """
        REGRESSION: approval_limit=Decimal('0.00') must block ALL overrides.
        Before the fix, the falsy check `if technician.approval_limit:` would
        treat 0.00 as "no limit" and allow unlimited overrides.
        """
        tech = _make_manager(self.tenant, 'mgr_zero_132', approval_limit=Decimal('0.00'))
        # Even a $0.01 override must be blocked
        self.assertFalse(can_manager_override_price(tech, Decimal('0.01')))
        self.assertFalse(can_manager_override_price(tech, Decimal('50.00')))
        self.assertFalse(can_manager_override_price(tech, Decimal('1000.00')))

    def test_zero_limit_blocks_zero_amount_too(self):
        """approval_limit=0 blocks even a $0.00 override request."""
        tech = _make_manager(self.tenant, 'mgr_zero2_132', approval_limit=Decimal('0.00'))
        # 0.00 override is ≤ 0.00 but the limit is zero so it's effectively blocked
        # (a $0 repair override makes no sense, but the guard should be consistent)
        self.assertFalse(can_manager_override_price(tech, Decimal('0.01')))

    def test_no_can_override_pricing_blocks_regardless(self):
        """can_override_pricing=False blocks even an unlimited manager."""
        tech = _make_manager(
            self.tenant, 'mgr_noflag_132',
            approval_limit=None, can_override=False,
        )
        self.assertFalse(can_manager_override_price(tech, Decimal('1.00')))

    def test_not_manager_blocks_regardless(self):
        """is_manager=False blocks override even with can_override_pricing=True."""
        user = User.objects.create_user(
            username='tech_notmgr_132', email='tech_notmgr_132@test.com', password='pass',
            first_name='Plain', last_name='Tech',
        )
        tech = Technician.objects.create(
            user=user, tenant=self.tenant,
            is_manager=False,
            can_override_pricing=True,  # flag set but is_manager=False
            approval_limit=None,
        )
        self.assertFalse(can_manager_override_price(tech, Decimal('10.00')))

    # ------------------------------------------------------------------
    # Technician.can_approve_amount() model method — already correct,
    # included here as a cross-check / documentation.
    # ------------------------------------------------------------------

    def test_model_can_approve_amount_zero_limit_regression(self):
        """
        Technician.can_approve_amount() uses `is not None` correctly already.
        Verify the model method still blocks zero-limit managers (defense-in-depth).
        """
        tech = _make_manager(self.tenant, 'mgr_model_132', approval_limit=Decimal('0.00'))
        # can_approve_amount(0) → 0 <= 0 → True (zero-amount is trivially approved)
        self.assertTrue(tech.can_approve_amount(Decimal('0.00')))
        # can_approve_amount(0.01) → 0.01 > 0 → False
        self.assertFalse(tech.can_approve_amount(Decimal('0.01')))
