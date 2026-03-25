"""
Management command: reconcile_loyalty_balances

Nightly integrity check for the loyalty ledger.

For each customer who has PointTransaction records, this command:
  1. Sums all PointTransaction.amount values (the ground truth)
  2. Compares to Reward.points (the cached balance)
  3. If they diverge, logs an error and optionally repairs the cache

Run via cron: 0 3 * * * manage.py reconcile_loyalty_balances
              (3am daily — after expire_loyalty_points at midnight)

This is a REPORTING command by default. Pass --fix to update Reward.points
to match the ledger sum. The --fix flag must be approved by Drake before use
in production — it mutates balances without creating PointTransaction records.

Usage:
    python manage.py reconcile_loyalty_balances
    python manage.py reconcile_loyalty_balances --tenant-id 1
    python manage.py reconcile_loyalty_balances --fix
    python manage.py reconcile_loyalty_balances --json
"""

import json
import logging
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from apps.rewards_referrals.models import PointTransaction, Reward
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Reconcile Reward.points cached balances against the PointTransaction '
        'ledger. Reports discrepancies. Pass --fix to correct drift.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            type=int,
            default=None,
            help='Limit reconciliation to a specific tenant ID (default: all tenants)',
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            default=False,
            help=(
                'Correct Reward.points to match the ledger sum. '
                'WARNING: this mutates balances without creating PointTransaction '
                'records. Use only after manual review of discrepancies.'
            ),
        )
        parser.add_argument(
            '--json',
            action='store_true',
            default=False,
            help='Output results as JSON (useful for cron log parsing)',
        )

    def handle(self, *args, **options):
        tenant_id = options.get('tenant_id')
        fix_mode = options.get('fix', False)
        as_json = options.get('json', False)

        if not as_json:
            self.stdout.write(self.style.MIGRATE_HEADING(
                'reconcile_loyalty_balances — starting...'
            ))
            if fix_mode:
                self.stdout.write(self.style.WARNING(
                    '  --fix is active: Reward.points will be corrected where drift is found.'
                ))

        tenants_qs = Tenant.objects.all()
        if tenant_id is not None:
            tenants_qs = tenants_qs.filter(pk=tenant_id)

        results = []
        total_checked = 0
        total_ok = 0
        total_drifted = 0
        total_fixed = 0
        total_missing_reward = 0

        for tenant in tenants_qs:
            tenant_result = self._reconcile_tenant(tenant, fix_mode, as_json)
            results.append(tenant_result)
            total_checked += tenant_result['checked']
            total_ok += tenant_result['ok']
            total_drifted += tenant_result['drifted']
            total_fixed += tenant_result.get('fixed', 0)
            total_missing_reward += tenant_result.get('missing_reward_row', 0)

        summary = {
            'tenants_processed': len(results),
            'total_customers_checked': total_checked,
            'total_ok': total_ok,
            'total_drifted': total_drifted,
            'total_fixed': total_fixed,
            'total_missing_reward_row': total_missing_reward,
            'fix_mode': fix_mode,
            'details': results,
        }

        if as_json:
            self.stdout.write(json.dumps(summary, indent=2))
        else:
            self._print_summary(summary)

        # Exit with non-zero status if unresolved drift found (useful for cron alerting)
        unresolved = total_drifted - total_fixed
        if unresolved > 0:
            raise SystemExit(
                f'reconcile_loyalty_balances: {unresolved} unresolved discrepancies '
                f'(run with --fix to correct, or investigate manually)'
            )

    def _reconcile_tenant(self, tenant, fix_mode, as_json):
        """Reconcile all customers for a single tenant."""
        # Find all customer_users who have at least one PointTransaction for this tenant
        customer_user_ids = (
            PointTransaction.objects
            .filter(tenant=tenant)
            .values_list('customer_user_id', flat=True)
            .distinct()
        )

        checked = 0
        ok = 0
        drifted = 0
        fixed = 0
        missing_reward_row = 0
        discrepancies = []

        for cu_id in customer_user_ids:
            checked += 1

            # Sum the ledger (ground truth) — always tenant-scoped
            ledger_sum = (
                PointTransaction.objects
                .filter(tenant=tenant, customer_user_id=cu_id)
                .aggregate(total=Sum('amount'))
            )['total'] or 0

            # Get the cached Reward row — plain read here; the fix_mode path
            # re-fetches with select_for_update() inside its own atomic block.
            # select_for_update() outside a transaction raises TransactionManagementError.
            try:
                reward = Reward.objects.get(
                    customer_user_id=cu_id,
                )
            except Reward.DoesNotExist:
                missing_reward_row += 1
                logger.error(
                    'reconcile_loyalty: Reward row missing for customer_user_id=%s '
                    'tenant=%s (ledger_sum=%s)',
                    cu_id, tenant.slug, ledger_sum,
                )
                discrepancies.append({
                    'customer_user_id': cu_id,
                    'issue': 'missing_reward_row',
                    'ledger_sum': ledger_sum,
                    'cached_balance': None,
                })
                continue

            cached_balance = reward.points

            if ledger_sum == cached_balance:
                ok += 1
                continue

            # Discrepancy found
            drifted += 1
            drift = ledger_sum - cached_balance
            discrepancy = {
                'customer_user_id': cu_id,
                'tenant_slug': tenant.slug,
                'ledger_sum': ledger_sum,
                'cached_balance': cached_balance,
                'drift': drift,
            }
            discrepancies.append(discrepancy)

            logger.error(
                'reconcile_loyalty: DRIFT detected — customer_user_id=%s tenant=%s '
                'ledger_sum=%s cached=%s drift=%s%s',
                cu_id, tenant.slug, ledger_sum, cached_balance, drift,
                ' (FIXING)' if fix_mode else ' (run --fix to correct)',
            )

            if fix_mode:
                with transaction.atomic():
                    # Re-fetch with lock inside atomic block for the fix
                    reward_locked = Reward.objects.select_for_update().get(pk=reward.pk)
                    reward_locked.points = ledger_sum
                    reward_locked.save(update_fields=['points', 'updated_at'])
                fixed += 1
                discrepancy['fixed'] = True
                logger.info(
                    'reconcile_loyalty: FIXED customer_user_id=%s — set points=%s',
                    cu_id, ledger_sum,
                )

        return {
            'tenant_id': tenant.pk,
            'tenant_slug': tenant.slug,
            'tenant_name': tenant.name,
            'checked': checked,
            'ok': ok,
            'drifted': drifted,
            'fixed': fixed,
            'missing_reward_row': missing_reward_row,
            'discrepancies': discrepancies,
        }

    def _print_summary(self, summary):
        """Pretty-print reconciliation results to stdout."""
        self.stdout.write('')
        for tenant_result in summary['details']:
            name = tenant_result['tenant_name']
            checked = tenant_result['checked']
            ok = tenant_result['ok']
            drifted = tenant_result['drifted']
            fixed = tenant_result.get('fixed', 0)
            missing = tenant_result.get('missing_reward_row', 0)

            status = self.style.SUCCESS('✓ OK') if drifted == 0 else self.style.ERROR('✗ DRIFT')
            self.stdout.write(f'  {name}: {status}  checked={checked} ok={ok} drifted={drifted} fixed={fixed} missing_row={missing}')

            for d in tenant_result.get('discrepancies', []):
                if d.get('issue') == 'missing_reward_row':
                    self.stdout.write(self.style.WARNING(
                        f'    → customer_user={d["customer_user_id"]} MISSING Reward row (ledger={d["ledger_sum"]})'
                    ))
                else:
                    fix_note = ' [FIXED]' if d.get('fixed') else ' [UNRESOLVED — run --fix]'
                    self.stdout.write(self.style.ERROR(
                        f'    → customer_user={d["customer_user_id"]} '
                        f'ledger={d["ledger_sum"]} cached={d["cached_balance"]} '
                        f'drift={d["drift"]}{fix_note}'
                    ))

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('─' * 50))
        self.stdout.write(
            f'Tenants processed:  {summary["tenants_processed"]}\n'
            f'Customers checked:  {summary["total_customers_checked"]}\n'
            f'OK:                 {summary["total_ok"]}\n'
            f'Drifted:            {summary["total_drifted"]}\n'
            f'Fixed:              {summary["total_fixed"]}\n'
            f'Missing Reward row: {summary["total_missing_reward_row"]}\n'
        )

        unresolved = summary['total_drifted'] - summary['total_fixed']
        if unresolved == 0 and summary['total_drifted'] == 0:
            self.stdout.write(self.style.SUCCESS('All balances are consistent. ✓'))
        elif unresolved == 0:
            self.stdout.write(self.style.SUCCESS(f'All drift corrected ({summary["total_fixed"]} fixed). ✓'))
        else:
            self.stdout.write(self.style.ERROR(
                f'{unresolved} unresolved discrepancies. Run with --fix to correct.'
            ))
