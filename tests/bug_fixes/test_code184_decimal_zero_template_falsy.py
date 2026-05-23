"""
Regression tests for CODE-184: Decimal('0.00') falsy in Django templates.

Bug: Three template locations used bare truthiness on Decimal fields:
  1. multi_break_repair_form.html: `{% if current_technician.approval_limit %}`
     — a manager with approval_limit=Decimal('0.00') (zero cap) saw no limit hint
  2. technician_portal/batch_detail.html: `{% if repair.cost_override %}`
     — a $0.00 price override showed no "Manager Price Override: Applied" badge
  3. customer_portal/batch_detail.html: same as above for customer view

Fix: Changed all three to `{% if ... is not None %}` (proper Django template syntax).

AGENTS.md gotcha: "Decimal('0.00') is falsy in Python — always use `is not None`
for optional Decimal fields that legitimately allow zero."
"""

import os
from decimal import Decimal

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.template import Template, Context

from apps.technician_portal.models import Technician, Repair
from apps.tenants.models import Tenant, TenantMembership
from tests.helpers import make_tenant

User = get_user_model()


class DecimalZeroFalsyTemplateTest(TestCase):
    """Test that Decimal('0.00') renders correctly in templates."""

    def test_approval_limit_zero_is_not_none_in_dtl(self):
        """{% if val is not None %} correctly treats Decimal('0.00') as not None."""
        t = Template('{% if val is not None %}SHOWN{% else %}HIDDEN{% endif %}')
        # Zero limit — should show (manager has a cap of $0)
        self.assertEqual(t.render(Context({'val': Decimal('0.00')})), 'SHOWN')

    def test_approval_limit_none_is_hidden_in_dtl(self):
        """{% if val is not None %} correctly treats None as None (unlimited — no hint)."""
        t = Template('{% if val is not None %}SHOWN{% else %}HIDDEN{% endif %}')
        # None limit — unlimited, no hint to show
        self.assertEqual(t.render(Context({'val': None})), 'HIDDEN')

    def test_approval_limit_positive_shows_in_dtl(self):
        """{% if val is not None %} works for positive Decimal too."""
        t = Template('{% if val is not None %}SHOWN{% else %}HIDDEN{% endif %}')
        self.assertEqual(t.render(Context({'val': Decimal('50.00')})), 'SHOWN')

    def test_cost_override_zero_is_not_none_in_dtl(self):
        """{% if repair.cost_override is not None %} treats $0.00 override as set."""
        t = Template('{% if cost_override is not None %}OVERRIDE_APPLIED{% else %}NO_OVERRIDE{% endif %}')
        # $0.00 override — should show badge (manager explicitly comped the repair)
        self.assertEqual(
            t.render(Context({'cost_override': Decimal('0.00')})),
            'OVERRIDE_APPLIED'
        )

    def test_cost_override_none_is_hidden_in_dtl(self):
        """{% if repair.cost_override is not None %} treats None as not overridden."""
        t = Template('{% if cost_override is not None %}OVERRIDE_APPLIED{% else %}NO_OVERRIDE{% endif %}')
        self.assertEqual(
            t.render(Context({'cost_override': None})),
            'NO_OVERRIDE'
        )

    def test_old_bare_truthiness_was_wrong_for_zero(self):
        """Demonstrate that the OLD bare {% if val %} was wrong for Decimal('0.00')."""
        old_template = Template('{% if val %}SHOWN{% else %}HIDDEN{% endif %}')
        # Old behavior: Decimal('0.00') is falsy → wrongly hidden
        self.assertEqual(
            old_template.render(Context({'val': Decimal('0.00')})),
            'HIDDEN',  # This was the bug — HIDDEN when it should be SHOWN
        )

    def test_model_within_approval_limit_zero_cap(self):
        """Technician.within_approval_limit() correctly enforces approval_limit=0."""
        _owner, tenant = make_tenant('Test Shop Zero', 'owner_zero')
        user = User.objects.create_user(
            username='mgr_zero', email='mgr@test.com', password='pass'
        )
        tech = Technician.objects.create(
            user=user,
            tenant=tenant,
            is_manager=True,
            can_override_pricing=True,
            approval_limit=Decimal('0.00'),
        )
        # approval_limit=0 means no amount is approved
        self.assertFalse(tech.can_approve_amount(Decimal('0.01')))
        self.assertTrue(tech.can_approve_amount(Decimal('0.00')))

    def test_model_within_approval_limit_none_means_unlimited(self):
        """Technician.within_approval_limit() returns True for any amount when limit is None."""
        _owner, tenant = make_tenant('Test Shop Unlimited', 'owner_unlimited')
        user = User.objects.create_user(
            username='mgr_unlimited', email='mgr2@test.com', password='pass'
        )
        tech = Technician.objects.create(
            user=user,
            tenant=tenant,
            is_manager=True,
            can_override_pricing=True,
            approval_limit=None,
        )
        self.assertTrue(tech.can_approve_amount(Decimal('999999.99')))

    def test_multi_break_form_template_file_uses_is_not_none(self):
        """Verify multi_break_repair_form.html uses `is not None` for approval_limit hint."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            '../../templates/technician_portal/multi_break_repair_form.html'
        )
        with open(template_path) as f:
            content = f.read()
        # Should NOT contain bare truthiness for approval_limit
        self.assertNotIn(
            '{% if current_technician and current_technician.approval_limit %}',
            content,
            "multi_break_repair_form.html still uses bare truthiness for approval_limit"
        )
        # Should contain the correct is not None pattern
        self.assertIn(
            'current_technician.approval_limit is not None',
            content,
        )

    def test_technician_batch_detail_template_uses_is_not_none(self):
        """Verify technician_portal/batch_detail.html uses `is not None` for cost_override badge."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            '../../templates/technician_portal/batch_detail.html'
        )
        with open(template_path) as f:
            content = f.read()
        # Should NOT contain bare truthiness for cost_override
        self.assertNotIn(
            '{% if repair.cost_override %}',
            content,
            "technician_portal/batch_detail.html still uses bare truthiness for cost_override"
        )
        self.assertIn('repair.cost_override is not None', content)

    def test_customer_batch_detail_template_uses_is_not_none(self):
        """Verify customer_portal/batch_detail.html uses `is not None` for cost_override badge."""
        template_path = os.path.join(
            os.path.dirname(__file__),
            '../../templates/customer_portal/batch_detail.html'
        )
        with open(template_path) as f:
            content = f.read()
        self.assertNotIn(
            '{% if repair.cost_override %}',
            content,
            "customer_portal/batch_detail.html still uses bare truthiness for cost_override"
        )
        self.assertIn('repair.cost_override is not None', content)
