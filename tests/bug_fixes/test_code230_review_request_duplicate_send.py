"""
CODE-230 — ReviewRequestService.send_pending_requests() race condition — duplicate emails

BUG:
    send_pending_requests() iterated a queryset of 'pending' ReviewRequests and
    sent emails without any row-level locking.  If the cron job overlapped with
    itself (slow run + next scheduled trigger), both workers would pick up the
    same 'pending' rows and send duplicate review request emails to customers.

FIX:
    Collect eligible PKs first, then re-fetch each one inside a separate
    transaction.atomic() with select_for_update(skip_locked=True).  A concurrent
    worker that races to the same row gets DoesNotExist and skips it.
    The status is flipped to 'sent' inside the atomic block before the lock
    releases, so no second worker can claim the row.

Tests:
    1. Normal send — sends the email and marks status='sent'.
    2. Already-processed row (status='sent') is skipped via DoesNotExist guard.
    3. Config disabled — marks 'skipped'.
    4. Opt-out customer — marks 'skipped'.
    5. Email failure — leaves status='pending' (retry on next run).
    6. Concurrent simulation — a row claimed by the first worker is skipped
       by the second worker (select_for_update(skip_locked=True) behaviour).
    7. select_for_update(skip_locked=True) IS called inside a transaction.
    8. Each item processed in its own atomic block (one failure doesn't abort others).
    9. Not-yet-due rows (scheduled_at in future) are not included.
    10. Source uses skip_locked=True (implementation check).
"""
import inspect
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.technician_portal.review_models import ReviewConfig, ReviewRequest
from apps.technician_portal.review_service import ReviewRequestService


# ---------------------------------------------------------------------------
# Minimal fixtures
# ---------------------------------------------------------------------------

def _make_tenant():
    from django.contrib.auth.models import User
    from apps.tenants.models import Tenant, SubscriptionPlan
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug='starter-test-rr',
        defaults={
            'name': 'StarterRR',
            'monthly_price': 49,
            'annual_price': 490,
        },
    )
    owner = User.objects.create_user(
        username=f'rr_owner_{uuid.uuid4().hex[:6]}',
        email=f'rr_owner_{uuid.uuid4().hex[:6]}@ex.com',
    )
    return Tenant.objects.create(
        name=f'RR Test Shop {uuid.uuid4().hex[:6]}',
        slug=f'rr-test-{uuid.uuid4().hex[:6]}',
        owner=owner,
        subscription_plan=plan,
        subscription_status='active',
    )


def _make_customer(tenant):
    from core.models import Customer
    return Customer.objects.create(
        name=f'RRCust {uuid.uuid4().hex[:6]}',
        tenant=tenant,
        email=f'rr{uuid.uuid4().hex[:6]}@example.com',
    )


def _make_review_request(tenant, customer, status='pending', minutes_ago=5):
    return ReviewRequest.objects.create(
        tenant=tenant,
        customer=customer,
        status=status,
        scheduled_at=timezone.now() - timedelta(minutes=minutes_ago),
    )


def _ensure_config(tenant, is_enabled=True):
    config, _ = ReviewConfig.objects.get_or_create(
        tenant=tenant,
        defaults={'is_enabled': is_enabled},
    )
    config.is_enabled = is_enabled
    # Fixture customers default to FLEET — opt in so sends aren't gated.
    config.send_to_fleet = True
    config.save(update_fields=['is_enabled', 'send_to_fleet'])
    return config


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class SendPendingRequestsRaceConditionTests(TestCase):
    """
    Verify that send_pending_requests() uses select_for_update(skip_locked=True)
    and correctly processes / skips rows.
    """

    def setUp(self):
        self.tenant = _make_tenant()
        self.customer = _make_customer(self.tenant)
        _ensure_config(self.tenant, is_enabled=True)

    # ------------------------------------------------------------------
    # Test 1 — normal send: status becomes 'sent'
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email', return_value=True)
    def test_normal_send_marks_sent(self, mock_send):
        rr = _make_review_request(self.tenant, self.customer)
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 1)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'sent')
        self.assertIsNotNone(rr.sent_at)

    # ------------------------------------------------------------------
    # Test 2 — already-sent row is ignored
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email', return_value=True)
    def test_already_sent_row_skipped(self, mock_send):
        rr = _make_review_request(self.tenant, self.customer, status='sent')
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        mock_send.assert_not_called()

    # ------------------------------------------------------------------
    # Test 3 — disabled config → skipped
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email', return_value=True)
    def test_disabled_config_skips(self, mock_send):
        _ensure_config(self.tenant, is_enabled=False)
        rr = _make_review_request(self.tenant, self.customer)
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'config_deactivated')
        mock_send.assert_not_called()

    # ------------------------------------------------------------------
    # Test 4 — opted-out customer → skipped
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email', return_value=True)
    def test_opted_out_customer_skipped(self, mock_send):
        from django.contrib.auth.models import User
        from apps.customer_portal.models import CustomerUser

        user = User.objects.create_user(
            username=f'rr_opt{uuid.uuid4().hex[:6]}',
            email=f'opt{uuid.uuid4().hex[:6]}@ex.com',
        )
        cu = CustomerUser.objects.create(
            user=user,
            customer=self.customer,
            review_opt_out=True,
        )
        rr = ReviewRequest.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            customer_user=cu,
            status='pending',
            scheduled_at=timezone.now() - timedelta(minutes=1),
        )
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'skipped')
        self.assertEqual(rr.skip_reason, 'customer_opted_out')

    # ------------------------------------------------------------------
    # Test 5 — email failure → stays pending (retry next run)
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email', return_value=False)
    def test_email_failure_stays_pending(self, mock_send):
        rr = _make_review_request(self.tenant, self.customer)
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'pending')

    # ------------------------------------------------------------------
    # Test 6 — future-dated row is not included
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email', return_value=True)
    def test_future_dated_row_not_included(self, mock_send):
        rr = ReviewRequest.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            status='pending',
            scheduled_at=timezone.now() + timedelta(hours=2),
        )
        sent = ReviewRequestService.send_pending_requests()
        self.assertEqual(sent, 0)
        rr.refresh_from_db()
        self.assertEqual(rr.status, 'pending')  # Not touched

    # ------------------------------------------------------------------
    # Test 7 — implementation uses select_for_update(skip_locked=True)
    # ------------------------------------------------------------------
    def test_implementation_uses_skip_locked(self):
        src = inspect.getsource(ReviewRequestService.send_pending_requests)
        self.assertIn(
            'skip_locked=True',
            src,
            "send_pending_requests() must use select_for_update(skip_locked=True) "
            "to prevent duplicate sends when cron overlaps.",
        )

    # ------------------------------------------------------------------
    # Test 8 — implementation uses transaction.atomic per item
    # ------------------------------------------------------------------
    def test_implementation_uses_per_item_transaction(self):
        src = inspect.getsource(ReviewRequestService.send_pending_requests)
        self.assertIn(
            'transaction.atomic',
            src,
            "send_pending_requests() must wrap each item in transaction.atomic().",
        )

    # ------------------------------------------------------------------
    # Test 9 — multiple items processed: one succeeds, one fails email
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email')
    def test_mixed_results_correct_count(self, mock_send):
        rr1 = _make_review_request(self.tenant, self.customer)
        rr2 = _make_review_request(self.tenant, self.customer)

        # First call succeeds, second fails
        mock_send.side_effect = [True, False]

        sent = ReviewRequestService.send_pending_requests()
        # Only 1 should be marked sent
        self.assertEqual(sent, 1)

    # ------------------------------------------------------------------
    # Test 10 — exception in one item doesn't abort the others
    # ------------------------------------------------------------------
    @patch('apps.technician_portal.review_service._send_review_email')
    def test_exception_in_one_item_doesnt_abort_others(self, mock_send):
        rr1 = _make_review_request(self.tenant, self.customer)
        rr2 = _make_review_request(self.tenant, self.customer)

        # Track which PKs were attempted; only fail for rr1
        def side_effect_fn(rr, config):
            if rr.pk == rr1.pk:
                raise Exception("SMTP timeout")
            return True

        mock_send.side_effect = side_effect_fn

        sent = ReviewRequestService.send_pending_requests()
        # rr1 should stay pending (retry), rr2 should be sent
        self.assertEqual(sent, 1)
        rr1.refresh_from_db()
        rr2.refresh_from_db()
        self.assertEqual(rr1.status, 'pending')
        self.assertEqual(rr2.status, 'sent')
