"""
Platform fee resolution — the mechanism, shipped OFF.

The plumbing was always correct: invoice payments are DIRECT charges on the
shop's connected account with an `application_fee_amount`, which Stripe moves
into the platform's own balance. What was broken was the *rate*, in two ways:

1. `PlatformConfig.default_fee_percent` defaults to 0.00, and
2. migration 0011 added `Tenant.platform_fee_percent` as `default=0` NOT NULL
   while 0012 made it nullable **without backfilling** -- so every pre-0012
   tenant carried an explicit 0.00 that silently beat any global rate.

Net effect: `fee_cents > 0` was never true, `application_fee_amount` was never
attached, and zero PlatformFeeRecord rows exist. Not one cent was ever
collected. The trap is documented in docs/deployment/STRIPE_ARCHITECTURE.md
and had already bitten once.

These tests lock down the repaired semantics, the platform-owner exemption
(so Drake's own shop can never be charged), the master switch, and the clamp
that keeps a fixed fee from making a small invoice unpayable.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from apps.billing.models import PlatformConfig, PlatformFeeRecord
from apps.tenants.models import Tenant
from apps.tenants.services.connect_service import ConnectService


def make_tenant(slug='fee-shop', **kwargs):
    owner = User.objects.create_user(
        username=f'{slug}-owner', email=f'{slug}@test.com', password='pw123!',
    )
    return Tenant.objects.create(
        name='Fee Shop', slug=slug, owner=owner, **kwargs,
    )


class FeeResolutionTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.default_fee_percent = Decimal('2.00')
        config.default_fee_fixed_cents = 25
        config.save()

    def test_global_default_applies_when_tenant_is_null(self):
        """NULL means 'use the global default'. This is the case that was
        broken for every pre-0012 tenant."""
        self.tenant.platform_fee_percent = None
        self.tenant.platform_fee_fixed_cents = None
        percent, fixed, source = self.tenant.effective_platform_fee
        self.assertEqual((percent, fixed, source), (Decimal('2.00'), 25, 'global'))

    def test_explicit_zero_means_zero_rated(self):
        """After the 0026 backfill, a literal 0.00 means what it says."""
        self.tenant.platform_fee_percent = Decimal('0.00')
        percent, fixed, source = self.tenant.effective_platform_fee
        self.assertEqual((percent, fixed, source), (Decimal('0.00'), 0, 'tenant'))

    def test_tenant_pair_resolves_as_a_unit(self):
        """A tenant percent must not be mixed with the global fixed amount."""
        self.tenant.platform_fee_percent = Decimal('1.00')
        self.tenant.platform_fee_fixed_cents = None
        percent, fixed, source = self.tenant.effective_platform_fee
        self.assertEqual((percent, fixed, source), (Decimal('1.00'), 0, 'tenant'))

    def test_fixed_only_override_still_counts_as_an_override(self):
        self.tenant.platform_fee_percent = None
        self.tenant.platform_fee_fixed_cents = 50
        percent, fixed, source = self.tenant.effective_platform_fee
        self.assertEqual((percent, fixed, source), (Decimal('0'), 50, 'tenant'))

    def test_master_switch_off_beats_everything(self):
        config = PlatformConfig.get_solo()
        config.fee_enabled = False
        config.save()
        self.tenant.platform_fee_percent = Decimal('5.00')
        percent, fixed, source = self.tenant.effective_platform_fee
        self.assertEqual((percent, fixed, source), (Decimal('0'), 0, 'disabled'))

    def test_platform_owner_is_never_charged(self):
        """Protects Drake's own shop -- which is also the tenant most likely
        to be sitting on a legacy 0.00."""
        self.tenant.is_platform_owner = True
        self.tenant.platform_fee_percent = None
        percent, fixed, source = self.tenant.effective_platform_fee
        self.assertEqual((percent, fixed, source), (Decimal('0'), 0, 'platform_owner'))

    def test_platform_owner_exemption_beats_an_explicit_override(self):
        self.tenant.is_platform_owner = True
        self.tenant.platform_fee_percent = Decimal('9.00')
        _percent, _fixed, source = self.tenant.effective_platform_fee
        self.assertEqual(source, 'platform_owner')


class ShipsOffByDefaultTests(TestCase):
    """The deploy must not start charging anyone."""

    def test_a_fresh_config_has_fees_disabled(self):
        PlatformConfig.objects.all().delete()
        config = PlatformConfig.get_solo()
        self.assertFalse(config.fee_enabled)
        self.assertEqual(config.default_fee_percent, Decimal('0.00'))
        self.assertEqual(config.default_fee_fixed_cents, 0)

    def test_no_fee_is_charged_out_of_the_box(self):
        tenant = make_tenant('fresh-shop')
        PlatformConfig.objects.all().delete()
        fee_cents, percent, fixed = ConnectService().calculate_platform_fee(
            Decimal('100.00'), tenant,
        )
        self.assertEqual((fee_cents, percent, fixed), (0, Decimal('0'), 0))


class FeeMathTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()
        self.svc = ConnectService()
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.save()

    def _set(self, percent=None, fixed=0):
        config = PlatformConfig.get_solo()
        config.default_fee_percent = Decimal(str(percent or 0))
        config.default_fee_fixed_cents = fixed
        config.save()
        self.tenant.platform_fee_percent = None
        self.tenant.platform_fee_fixed_cents = None

    def test_percent_plus_fixed(self):
        self._set(percent='2.9', fixed=30)
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('100.00'), self.tenant)
        self.assertEqual(fee, 320)  # 290 + 30

    def test_percent_only(self):
        self._set(percent='2.5')
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('100.00'), self.tenant)
        self.assertEqual(fee, 250)

    def test_fixed_only(self):
        self._set(fixed=25)
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('100.00'), self.tenant)
        self.assertEqual(fee, 25)

    def test_truncates_to_whole_cents(self):
        self._set(percent='2.5')
        # $1.25 * 2.5% = 3.125c -> 3
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('1.25'), self.tenant)
        self.assertEqual(fee, 3)

    def test_clamped_so_a_small_invoice_stays_payable(self):
        """Stripe rejects an application fee larger than the charge.

        Unclamped, a $0.25 invoice with a $0.30 fixed fee makes the whole
        Checkout Session creation throw -- the customer cannot pay at all,
        which is far worse than collecting a smaller fee.
        """
        self._set(fixed=30)
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('0.25'), self.tenant)
        self.assertLessEqual(fee, 25)
        self.assertGreaterEqual(fee, 0)

    def test_clamp_leaves_a_minimum_net(self):
        self._set(percent='99')
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('10.00'), self.tenant)
        self.assertEqual(fee, 1000 - ConnectService.MIN_NET_CENTS)

    def test_never_negative(self):
        self._set(fixed=500)
        fee, _p, _f = self.svc.calculate_platform_fee(Decimal('0.10'), self.tenant)
        self.assertGreaterEqual(fee, 0)


class FeeLabelTests(TestCase):
    """Shops are told the fee before they onboard, not after KYC."""

    def setUp(self):
        self.tenant = make_tenant()
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.save()

    def test_no_fee_label(self):
        config = PlatformConfig.get_solo()
        config.fee_enabled = False
        config.save()
        self.assertEqual(self.tenant.platform_fee_label, 'No platform fee')

    def test_percent_and_fixed_label(self):
        self.tenant.platform_fee_percent = Decimal('2.50')
        self.tenant.platform_fee_fixed_cents = 30
        self.assertEqual(
            self.tenant.platform_fee_label, '2.5% + $0.30 per transaction',
        )

    def test_percent_only_label(self):
        self.tenant.platform_fee_percent = Decimal('2.00')
        self.tenant.platform_fee_fixed_cents = 0
        self.assertIn('2%', self.tenant.platform_fee_label)


class DeadCodeIsGoneTests(TestCase):
    """Three implementations of one calculation is how they drift.

    The deleted module-level create_direct_charge_session wrote metadata key
    'rs_fee_cents' while the reader expected 'rs_fee_percent' -- exactly the
    mismatch that caused CODE-069.
    """

    def test_module_level_duplicates_are_removed(self):
        from apps.tenants.services import connect_service

        for name in ('calculate_platform_fee', 'create_direct_charge_session'):
            self.assertFalse(
                hasattr(connect_service, name),
                f"connect_service.{name} is a duplicate implementation and "
                f"must not be reintroduced",
            )

    def test_record_platform_fee_method_is_removed(self):
        self.assertFalse(hasattr(ConnectService, 'record_platform_fee'))


class FeeRecordConstraintTests(TestCase):
    """One fee per payment, enforced by the database.

    Both the webhook and the 15-minute reconcile sweep can record the same
    PaymentIntent; an `.exists()` check does not hold under a race.
    """

    def test_duplicate_payment_intent_is_rejected(self):
        from django.db import IntegrityError, transaction
        from apps.billing.models import Invoice
        from core.models import Customer

        tenant = make_tenant('dupe-shop')
        customer = Customer.objects.create(name='Acme', tenant=tenant)
        invoice = Invoice.objects.create(
            tenant=tenant, customer=customer, invoice_number='INV-DUP-1',
            subtotal=Decimal('100'), total=Decimal('100'),
        )
        common = dict(
            tenant=tenant, invoice=invoice, payment_intent_id='pi_dupe',
            gross_amount=Decimal('100'), fee_amount=Decimal('2'),
            fee_percent=Decimal('2.00'), stripe_account_id='acct_x',
        )
        PlatformFeeRecord.objects.create(**common)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PlatformFeeRecord.objects.create(**common)


class MigrationBackfillTests(TestCase):
    """The 0.00 -> NULL repair, asserted as behaviour.

    Running the historical migration in a test is awkward; what matters is
    the semantics it restores: a NULL tenant follows the global default.
    """

    def test_null_tenant_follows_the_global_default(self):
        tenant = make_tenant('backfilled-shop')
        tenant.platform_fee_percent = None
        tenant.platform_fee_fixed_cents = None
        config = PlatformConfig.get_solo()
        config.fee_enabled = True
        config.default_fee_percent = Decimal('3.00')
        config.save()

        _percent, _fixed, source = tenant.effective_platform_fee
        self.assertEqual(
            source, 'global',
            "a cleared tenant must pick up the global rate -- this is the "
            "whole point of migration 0026",
        )

    def test_the_migration_file_exists_and_is_reversible(self):
        from importlib import import_module

        mod = import_module(
            'apps.tenants.migrations.0026_backfill_platform_fee_percent_null'
        )
        forward, reverse = mod.Migration.operations[0].code, \
            mod.Migration.operations[0].reverse_code
        self.assertTrue(callable(forward))
        self.assertTrue(
            callable(reverse),
            "the data migration must not be a one-way door",
        )
