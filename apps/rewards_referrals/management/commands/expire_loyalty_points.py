"""
Management command: expire_loyalty_points

Daily expiration of loyalty points that have passed their expires_at date.

For each un-expired PointTransaction with expires_at in the past:
  1. Marks it expired=True
  2. Creates a corresponding negative PointTransaction ('expiration' type)
  3. Updates the Reward cached balance

Run via cron: 0 0 * * * manage.py expire_loyalty_points
              (midnight daily — before reconcile_loyalty_balances at 3am)

Note: expiry_warning emails (sent X days before expiry) are NOT handled here.
      They are the responsibility of a future notification management command.

Usage:
    python manage.py expire_loyalty_points
    python manage.py expire_loyalty_points --tenant-id 1
    python manage.py expire_loyalty_points --dry-run
    python manage.py expire_loyalty_points --json
"""

import json
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone

from apps.rewards_referrals.models import LoyaltyConfig, PointTransaction, Reward
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)

# Process in batches to avoid locking too many rows at once
BATCH_SIZE = 100


class Command(BaseCommand):
    help = (
        'Expire loyalty points whose expires_at has passed. '
        'Creates negative PointTransaction records and updates cached balances.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            type=int,
            default=None,
            help='Limit expiration to a specific tenant ID (default: all tenants)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help='Show what would be expired without making any changes',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            default=False,
            help='Output results as JSON',
        )

    def handle(self, *args, **options):
        tenant_id = options.get('tenant_id')
        dry_run = options.get('dry_run', False)
        as_json = options.get('json', False)
        now = timezone.now()

        if not as_json:
            self.stdout.write(self.style.MIGRATE_HEADING(
                'expire_loyalty_points — starting...'
            ))
            if dry_run:
                self.stdout.write(self.style.WARNING('  --dry-run active: no changes will be made.'))

        tenants_qs = Tenant.objects.all()
        if tenant_id is not None:
            tenants_qs = tenants_qs.filter(pk=tenant_id)

        results = []
        total_expired = 0
        total_points_removed = 0

        for tenant in tenants_qs:
            tenant_result = self._expire_tenant(tenant, now, dry_run)
            results.append(tenant_result)
            total_expired += tenant_result['transactions_expired']
            total_points_removed += tenant_result['points_removed']

        summary = {
            'run_at': now.isoformat(),
            'dry_run': dry_run,
            'tenants_processed': len(results),
            'total_transactions_expired': total_expired,
            'total_points_removed': total_points_removed,
            'details': results,
        }

        if as_json:
            self.stdout.write(json.dumps(summary, indent=2))
        else:
            self._print_summary(summary)

        logger.info(
            'expire_loyalty_points complete: %s transactions expired, %s points removed '
            '(dry_run=%s)',
            total_expired, total_points_removed, dry_run,
        )

    def _expire_tenant(self, tenant, now, dry_run):
        """Expire all due PointTransactions for a single tenant."""
        # Find all un-expired positive transactions whose expires_at has passed
        # Only positive amounts can expire — redemptions and adjustments don't expire
        expirable = (
            PointTransaction.objects
            .filter(
                tenant=tenant,
                expired=False,
                expires_at__lte=now,
                expires_at__isnull=False,
                amount__gt=0,
            )
            .select_related('customer_user')
            .order_by('customer_user_id', 'expires_at')
        )

        transactions_expired = 0
        points_removed = 0
        expired_details = []

        # Group by customer_user to batch balance updates
        current_cu_id = None
        pending_expiry_amount = 0
        pending_transaction_pks = []

        def _flush_pending(cu_id, amount_to_expire, txn_pks):
            """Atomically expire a batch of transactions for one customer."""
            nonlocal transactions_expired, points_removed

            if not txn_pks:
                return

            if dry_run:
                transactions_expired += len(txn_pks)
                points_removed += amount_to_expire
                return

            with transaction.atomic():
                # Lock Reward row
                try:
                    reward = Reward.objects.select_for_update().get(
                        customer_user_id=cu_id,
                    )
                except Reward.DoesNotExist:
                    logger.error(
                        'expire_loyalty: Reward row missing for customer_user_id=%s — skipping',
                        cu_id,
                    )
                    return

                # Mark all these transactions as expired
                PointTransaction.objects.filter(pk__in=txn_pks).update(expired=True)

                # Create a single negative expiration transaction
                # balance_after is recalculated from current cached balance minus the expiry
                new_balance = reward.points - amount_to_expire
                # Clamp to 0 — never go negative via expiration
                if new_balance < 0:
                    actual_amount = -reward.points
                    new_balance = 0
                    logger.warning(
                        'expire_loyalty: expiry would take balance negative for '
                        'customer_user_id=%s (balance=%s, expiring=%s) — clamping to 0',
                        cu_id, reward.points, amount_to_expire,
                    )
                else:
                    actual_amount = -amount_to_expire

                if actual_amount != 0:
                    PointTransaction.objects.create(
                        tenant=reward.tenant,
                        customer_user_id=cu_id,
                        amount=actual_amount,
                        balance_after=new_balance,
                        transaction_type='expiration',
                        description=f'Points expired ({len(txn_pks)} transaction(s))',
                    )
                    reward.points = new_balance
                    reward.save(update_fields=['points', 'updated_at'])

                transactions_expired += len(txn_pks)
                points_removed += abs(actual_amount)

        for pt in expirable.iterator(chunk_size=BATCH_SIZE):
            cu_id = pt.customer_user_id

            if current_cu_id is not None and cu_id != current_cu_id:
                _flush_pending(current_cu_id, pending_expiry_amount, pending_transaction_pks)
                pending_expiry_amount = 0
                pending_transaction_pks = []

            current_cu_id = cu_id
            pending_expiry_amount += pt.amount
            pending_transaction_pks.append(pt.pk)
            expired_details.append({
                'transaction_id': pt.pk,
                'customer_user_id': cu_id,
                'amount': pt.amount,
                'expires_at': pt.expires_at.isoformat() if pt.expires_at else None,
            })

        # Flush last group
        if pending_transaction_pks:
            _flush_pending(current_cu_id, pending_expiry_amount, pending_transaction_pks)

        return {
            'tenant_id': tenant.pk,
            'tenant_slug': tenant.slug,
            'tenant_name': tenant.name,
            'transactions_expired': transactions_expired,
            'points_removed': points_removed,
        }

    def _print_summary(self, summary):
        """Pretty-print expiration results."""
        self.stdout.write('')
        for tenant_result in summary['details']:
            expired = tenant_result['transactions_expired']
            points = tenant_result['points_removed']
            name = tenant_result['tenant_name']
            if expired > 0:
                self.stdout.write(
                    f'  {name}: {self.style.WARNING(str(expired))} transaction(s) expired, '
                    f'{self.style.WARNING(str(points))} points removed'
                )
            else:
                self.stdout.write(f'  {name}: nothing to expire')

        dry_note = ' [DRY RUN — no changes made]' if summary['dry_run'] else ''
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('─' * 50))
        self.stdout.write(
            f'Tenants processed:        {summary["tenants_processed"]}\n'
            f'Transactions expired:     {summary["total_transactions_expired"]}\n'
            f'Total points removed:     {summary["total_points_removed"]}{dry_note}\n'
        )
        if summary['total_transactions_expired'] == 0:
            self.stdout.write(self.style.SUCCESS('Nothing to expire. ✓'))
        elif summary['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'Dry run complete — {summary["total_transactions_expired"]} transactions would be expired.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Expired {summary["total_transactions_expired"]} transactions '
                f'({summary["total_points_removed"]} points). ✓'
            ))
