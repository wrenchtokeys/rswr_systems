"""
Stripe Connect Service

Handles Connected Account onboarding, status tracking, and payment routing
for multi-tenant invoice payments.

Architecture:
- Platform account (Drake's) receives SaaS subscriptions
- Connected accounts (each shop) receive their customer invoice payments
- Platform takes an optional fee (application_fee_amount) via direct charges
- Direct charges: payment hits shop's connected account, Stripe fees paid by shop

Uses Stripe Express accounts — Stripe handles KYC/compliance, shop owners
get a simplified onboarding experience.

Author: Amelia (Clawdbot AI)
"""

import logging
import stripe
from decimal import Decimal
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class ConnectError(Exception):
    """Raised when a Stripe Connect operation fails."""
    pass


class ConnectService:
    """
    Manages Stripe Connect operations for tenant payment routing.

    Usage:
        svc = ConnectService()
        url = svc.create_connect_account(tenant, return_url, refresh_url)
        svc.sync_account_status(tenant)
    """

    def __init__(self):
        self.api_key = getattr(settings, 'STRIPE_SECRET_KEY', None)
        if self.api_key:
            stripe.api_key = self.api_key

    def is_enabled(self):
        """Check if Stripe is configured."""
        return bool(self.api_key)

    # ------------------------------------------------------------------
    # Account Creation & Onboarding
    # ------------------------------------------------------------------

    def create_connect_account(self, tenant, return_url, refresh_url):
        """
        Create a Stripe Express Connected Account and return the onboarding URL.

        If the tenant already has a connect account, creates a new onboarding
        link (for completing incomplete onboarding).

        Args:
            tenant: Tenant model instance
            return_url: URL to redirect to after onboarding completes
            refresh_url: URL to redirect to if the link expires

        Returns:
            str: Stripe onboarding URL

        Raises:
            ConnectError on failure
        """
        if not self.is_enabled():
            raise ConnectError("Stripe is not configured")

        try:
            # Create account if doesn't exist yet
            if not tenant.stripe_connect_account_id:
                account = stripe.Account.create(
                    type='express',
                    country='US',
                    email=tenant.business_email or None,
                    business_type='company',
                    company={
                        'name': tenant.name,
                    },
                    capabilities={
                        'card_payments': {'requested': True},
                        'transfers': {'requested': True},
                    },
                    metadata={
                        'rs_tenant_id': str(tenant.id),
                        'rs_tenant_slug': tenant.slug,
                    },
                )
                tenant.stripe_connect_account_id = account.id
                tenant.stripe_onboarding_status = 'pending'
                tenant.save(update_fields=[
                    'stripe_connect_account_id',
                    'stripe_onboarding_status',
                ])
                logger.info(
                    f"Created Stripe Connect account {account.id} "
                    f"for tenant {tenant.slug}"
                )

            # Create onboarding link
            link = stripe.AccountLink.create(
                account=tenant.stripe_connect_account_id,
                refresh_url=refresh_url,
                return_url=return_url,
                type='account_onboarding',
            )

            logger.info(
                f"Created onboarding link for tenant {tenant.slug} "
                f"(account {tenant.stripe_connect_account_id})"
            )
            return link.url

        except stripe.error.StripeError as e:
            logger.error(f"Stripe Connect error for {tenant.slug}: {e}")
            raise ConnectError(str(e))

    def create_login_link(self, tenant):
        """
        Create a Stripe Express Dashboard login link for the shop owner.

        Returns:
            str: URL to the Stripe Express Dashboard

        Raises:
            ConnectError if account doesn't exist or Stripe fails
        """
        if not tenant.stripe_connect_account_id:
            raise ConnectError("No Stripe Connect account found")

        try:
            link = stripe.Account.create_login_link(
                tenant.stripe_connect_account_id,
            )
            return link.url
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create login link for {tenant.slug}: {e}")
            raise ConnectError(str(e))

    # ------------------------------------------------------------------
    # Account Status Sync
    # ------------------------------------------------------------------

    def sync_account_status(self, tenant):
        """
        Fetch the latest account status from Stripe and update the tenant.

        Call this after onboarding return, on account.updated webhook,
        or periodically to keep status fresh.

        Returns:
            dict with account status fields
        """
        if not tenant.stripe_connect_account_id:
            return {'error': 'No connect account'}

        try:
            account = stripe.Account.retrieve(tenant.stripe_connect_account_id)

            # Determine onboarding status from Stripe account state
            old_status = tenant.stripe_onboarding_status
            new_status = self._derive_onboarding_status(account)

            tenant.stripe_connect_charges_enabled = account.charges_enabled
            tenant.stripe_connect_payouts_enabled = account.payouts_enabled
            tenant.stripe_connect_onboarding_complete = account.details_submitted
            tenant.stripe_onboarding_status = new_status

            update_fields = [
                'stripe_connect_charges_enabled',
                'stripe_connect_payouts_enabled',
                'stripe_connect_onboarding_complete',
                'stripe_onboarding_status',
            ]

            # Record first activation timestamp
            if new_status == 'active' and old_status != 'active' and not tenant.stripe_connected_at:
                tenant.stripe_connected_at = timezone.now()
                update_fields.append('stripe_connected_at')

            tenant.save(update_fields=update_fields)

            logger.info(
                f"Synced Connect status for {tenant.slug}: "
                f"status={new_status}, charges={account.charges_enabled}, "
                f"payouts={account.payouts_enabled}"
            )

            return {
                'charges_enabled': account.charges_enabled,
                'payouts_enabled': account.payouts_enabled,
                'details_submitted': account.details_submitted,
                'onboarding_status': new_status,
                'requirements': {
                    'currently_due': account.requirements.currently_due if account.requirements else [],
                    'eventually_due': account.requirements.eventually_due if account.requirements else [],
                    'past_due': account.requirements.past_due if account.requirements else [],
                    'disabled_reason': account.requirements.disabled_reason if account.requirements else None,
                },
            }

        except stripe.error.StripeError as e:
            logger.error(f"Failed to sync Connect status for {tenant.slug}: {e}")
            raise ConnectError(str(e))

    @staticmethod
    def _derive_onboarding_status(account):
        """Derive our onboarding_status from Stripe account fields."""
        if account.charges_enabled and account.details_submitted:
            # Check for restrictions
            reqs = account.requirements
            if reqs and reqs.disabled_reason:
                return 'restricted'
            return 'active'
        elif account.details_submitted:
            return 'in_review'
        else:
            return 'pending'

    # ------------------------------------------------------------------
    # Payment Routing (Direct Charges)
    # ------------------------------------------------------------------

    def calculate_platform_fee(self, amount, tenant):
        """
        Calculate the platform fee for an invoice payment.

        Priority:
        1. Tenant-specific override (tenant.platform_fee_percent)
        2. Global default (PlatformConfig.default_fee_percent)
        3. Fallback: 0 (no fee)

        Args:
            amount: Payment amount in dollars (Decimal)
            tenant: Tenant model instance

        Returns:
            tuple: (fee_cents: int, fee_percent: Decimal)
        """
        fee_percent = tenant.platform_fee_percent
        if fee_percent is None:
            from apps.billing.models import PlatformConfig
            config = PlatformConfig.get()
            fee_percent = config.default_fee_percent
        if fee_percent is None or fee_percent <= 0:
            return 0, Decimal('0')
        fee = amount * fee_percent / 100
        return max(int(fee * 100), 0), fee_percent  # cents, percent

    def create_connected_checkout_session(
        self, invoice, success_url=None, cancel_url=None
    ):
        """
        Create a Checkout Session using DIRECT CHARGES on the shop's
        connected account, with an optional platform fee.

        Direct charges: the payment is created directly on the connected
        account (stripe_account param). The platform collects a fee via
        application_fee_amount. Stripe processing fees are paid by the shop.

        HARD BLOCK: Raises ConnectError if tenant has no active Connect account.

        Args:
            invoice: Invoice model instance
            success_url: Redirect URL on success
            cancel_url: Redirect URL on cancel

        Returns:
            dict: {success, checkout_url, session_id}

        Raises:
            ConnectError if tenant cannot accept payments
        """
        tenant = invoice.tenant
        if not tenant or not tenant.can_accept_payments:
            raise ConnectError(
                f"Shop '{tenant.name if tenant else 'unknown'}' has not completed "
                f"Stripe Connect setup. Online payments are not available."
            )

        try:
            base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
            amount_cents = int(invoice.amount_due * 100)
            fee_cents, fee_percent = self.calculate_platform_fee(
                invoice.amount_due, tenant
            )

            session_params = {
                'payment_method_types': ['card'],
                'line_items': [{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': amount_cents,
                        'product_data': {
                            'name': f'Invoice {invoice.invoice_number}',
                            'description': (
                                f'{invoice.line_items.count()} service(s) '
                                f'for {invoice.customer.name}'
                            ),
                        },
                    },
                    'quantity': 1,
                }],
                'mode': 'payment',
                'success_url': success_url or f'{base_url}/payment-complete?session={{CHECKOUT_SESSION_ID}}',
                'cancel_url': cancel_url or f'{base_url}/payment-cancelled',
                'metadata': {
                    'rs_invoice_id': str(invoice.id),
                    'rs_invoice_number': invoice.invoice_number,
                    'rs_tenant_id': str(tenant.id),
                    'rs_fee_percent': str(fee_percent),
                },
                # Metadata must ALSO live on the PaymentIntent — Stripe does
                # not copy session metadata onto it, and the webhook's
                # payment_intent.succeeded handler resolves the invoice (and
                # writes PlatformFeeRecord) from PaymentIntent metadata.
                'payment_intent_data': {
                    'metadata': {
                        'rs_invoice_id': str(invoice.id),
                        'rs_invoice_number': invoice.invoice_number,
                        'rs_tenant_id': str(tenant.id),
                        'rs_fee_percent': str(fee_percent),
                    },
                },
                # Direct charge: session created ON the connected account
                'stripe_account': tenant.stripe_connect_account_id,
            }

            # Add platform fee if configured (only with direct charges)
            if fee_cents > 0:
                session_params['payment_intent_data']['application_fee_amount'] = fee_cents

            session = stripe.checkout.Session.create(**session_params)

            logger.info(
                f"Direct charge checkout for {invoice.invoice_number}: "
                f"${invoice.amount_due} on {tenant.stripe_connect_account_id} "
                f"(fee: ${fee_cents/100:.2f})"
            )

            return {
                'success': True,
                'checkout_url': session.url,
                'session_id': session.id,
            }

        except stripe.error.StripeError as e:
            logger.error(
                f"Failed to create connected checkout for "
                f"{invoice.invoice_number}: {e}"
            )
            return {'success': False, 'error': str(e)}

    def record_platform_fee(self, invoice, payment_intent_id, gross_amount,
                            fee_cents, fee_percent):
        """
        Record a PlatformFeeRecord after a successful connected charge.

        Args:
            invoice: Invoice model instance
            payment_intent_id: Stripe PaymentIntent ID
            gross_amount: Total payment in dollars (Decimal)
            fee_cents: Platform fee in cents
            fee_percent: Fee rate at time of charge
        """
        if fee_cents <= 0:
            return None

        from apps.billing.models import PlatformFeeRecord
        tenant = invoice.tenant
        try:
            record = PlatformFeeRecord.objects.create(
                tenant=tenant,
                invoice=invoice,
                payment_intent_id=payment_intent_id,
                gross_amount=gross_amount,
                fee_amount=Decimal(str(fee_cents)) / 100,
                fee_percent=fee_percent,
                stripe_account_id=tenant.stripe_connect_account_id,
            )
            logger.info(
                f"Recorded platform fee: ${record.fee_amount} on "
                f"{invoice.invoice_number}"
            )
            return record
        except Exception as e:
            logger.error(f"Failed to record platform fee: {e}")
            return None


# ------------------------------------------------------------------
# Webhook Handler
# ------------------------------------------------------------------

def handle_account_updated(event_data):
    """
    Handle account.updated webhook — sync onboarding status.

    Called when a connected account's status changes (e.g., after
    completing onboarding, when verification is needed, etc.)
    """
    from apps.tenants.models import Tenant

    account_id = event_data.get('id')
    if not account_id:
        return {'success': False, 'error': 'No account ID'}

    try:
        tenant = Tenant.objects.get(stripe_connect_account_id=account_id)
    except Tenant.DoesNotExist:
        logger.warning(f"account.updated for unknown account {account_id}")
        return {'success': True, 'handled': False}

    svc = ConnectService()
    status = svc.sync_account_status(tenant)

    logger.info(
        f"account.updated for {tenant.slug}: "
        f"status={status.get('onboarding_status')}, "
        f"charges={status.get('charges_enabled')}, "
        f"payouts={status.get('payouts_enabled')}"
    )

    return {
        'success': True,
        'handled': True,
        'tenant': tenant.slug,
        'onboarding_status': status.get('onboarding_status'),
        'charges_enabled': status.get('charges_enabled'),
        'payouts_enabled': status.get('payouts_enabled'),
    }


# ------------------------------------------------------------------
# Module-level convenience functions (spec-required names)
# ------------------------------------------------------------------

def create_connect_account(tenant):
    """
    Create (or resume) a Stripe Express account for the tenant.

    This is a module-level wrapper used by views.
    Returns the Stripe account object.

    Raises ConnectError on failure.
    """
    if not getattr(settings, 'STRIPE_SECRET_KEY', None):
        raise ConnectError("Stripe is not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        if not tenant.stripe_connect_account_id:
            account = stripe.Account.create(
                type='express',
                country='US',
                email=getattr(tenant, 'business_email', None) or None,
                capabilities={
                    'card_payments': {'requested': True},
                    'transfers': {'requested': True},
                },
                metadata={
                    'rs_tenant_id': str(tenant.id),
                    'rs_tenant_slug': tenant.slug,
                },
            )
            tenant.stripe_connect_account_id = account.id
            tenant.stripe_onboarding_status = 'pending'
            tenant.save(update_fields=[
                'stripe_connect_account_id',
                'stripe_onboarding_status',
            ])
            logger.info(f"Created Connect account {account.id} for {tenant.slug}")
            return account
        else:
            return stripe.Account.retrieve(tenant.stripe_connect_account_id)
    except stripe.error.StripeError as e:
        logger.error(f"create_connect_account error for {tenant.slug}: {e}")
        raise ConnectError(str(e))


def create_account_link(tenant, return_url, refresh_url):
    """
    Create a Stripe AccountLink for (re)starting onboarding.

    Returns the AccountLink URL string.
    """
    if not getattr(settings, 'STRIPE_SECRET_KEY', None):
        raise ConnectError("Stripe is not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY

    if not tenant.stripe_connect_account_id:
        raise ConnectError("No Stripe Connect account on this tenant — call create_connect_account first")

    try:
        link = stripe.AccountLink.create(
            account=tenant.stripe_connect_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type='account_onboarding',
        )
        return link.url
    except stripe.error.StripeError as e:
        logger.error(f"create_account_link error for {tenant.slug}: {e}")
        raise ConnectError(str(e))


def handle_account_updated_webhook(account_data):
    """
    Handle account.updated webhook — update tenant stripe fields.

    Updates stripe_onboarding_status, stripe_connect_charges_enabled,
    stripe_connect_payouts_enabled, stripe_connect_onboarding_complete.

    Args:
        account_data: Stripe Account object (dict-like) from webhook event

    Returns:
        dict with success, handled, tenant, and status fields
    """
    from apps.tenants.models import Tenant

    # Support both dict and Stripe object
    if hasattr(account_data, 'get'):
        account_id = account_data.get('id')
        charges_enabled = account_data.get('charges_enabled', False)
        payouts_enabled = account_data.get('payouts_enabled', False)
        details_submitted = account_data.get('details_submitted', False)
        requirements = account_data.get('requirements') or {}
        if hasattr(requirements, 'get'):
            disabled_reason = requirements.get('disabled_reason')
        else:
            disabled_reason = getattr(requirements, 'disabled_reason', None)
    else:
        account_id = getattr(account_data, 'id', None)
        charges_enabled = getattr(account_data, 'charges_enabled', False)
        payouts_enabled = getattr(account_data, 'payouts_enabled', False)
        details_submitted = getattr(account_data, 'details_submitted', False)
        requirements = getattr(account_data, 'requirements', None)
        disabled_reason = getattr(requirements, 'disabled_reason', None) if requirements else None

    if not account_id:
        return {'success': False, 'error': 'No account ID in event data'}

    try:
        tenant = Tenant.objects.get(stripe_connect_account_id=account_id)
    except Tenant.DoesNotExist:
        logger.warning(f"account.updated for unknown account {account_id}")
        return {'success': True, 'handled': False}

    # Derive status
    if charges_enabled and details_submitted:
        new_status = 'restricted' if disabled_reason else 'active'
    elif details_submitted:
        new_status = 'in_review'
    else:
        new_status = 'pending'

    old_status = tenant.stripe_onboarding_status

    tenant.stripe_connect_charges_enabled = charges_enabled
    tenant.stripe_connect_payouts_enabled = payouts_enabled
    tenant.stripe_connect_onboarding_complete = details_submitted
    tenant.stripe_onboarding_status = new_status

    update_fields = [
        'stripe_connect_charges_enabled',
        'stripe_connect_payouts_enabled',
        'stripe_connect_onboarding_complete',
        'stripe_onboarding_status',
    ]

    if new_status == 'active' and old_status != 'active' and not tenant.stripe_connected_at:
        tenant.stripe_connected_at = timezone.now()
        update_fields.append('stripe_connected_at')

    tenant.save(update_fields=update_fields)

    logger.info(
        f"handle_account_updated_webhook for {tenant.slug}: "
        f"status={new_status}, charges={charges_enabled}, payouts={payouts_enabled}"
    )

    return {
        'success': True,
        'handled': True,
        'tenant': tenant.slug,
        'onboarding_status': new_status,
        'charges_enabled': charges_enabled,
        'payouts_enabled': payouts_enabled,
    }


def calculate_platform_fee(amount_cents, tenant):
    """
    Calculate platform fee in cents.

    Priority:
    1. Tenant-specific override (tenant.platform_fee_percent)
    2. Global default (PlatformConfig.get_solo().default_fee_percent)
    3. Fallback: 0

    Args:
        amount_cents: Payment amount in CENTS (int)
        tenant: Tenant model instance

    Returns:
        int: Platform fee in cents (never negative)
    """
    from apps.billing.models import PlatformConfig

    fee_percent = getattr(tenant, 'platform_fee_percent', None)
    if fee_percent is None:
        config = PlatformConfig.get_solo()
        fee_percent = config.default_fee_percent

    if not fee_percent or fee_percent <= 0:
        return 0

    fee = int(amount_cents * Decimal(str(fee_percent)) / 100)
    return max(fee, 0)


def create_direct_charge_session(invoice, success_url, cancel_url):
    """
    Create a Stripe Checkout Session via direct charge on the tenant's connected account.

    HARD BLOCK: Raises ConnectError if tenant has no active Connect account
    (stripe_onboarding_status != 'active' OR not stripe_connect_charges_enabled).

    Args:
        invoice: Invoice model instance
        success_url: Redirect URL on success
        cancel_url: Redirect URL on cancel

    Returns:
        Stripe checkout.Session object

    Raises:
        ConnectError if tenant cannot accept payments
    """
    tenant = invoice.tenant
    if not tenant:
        raise ConnectError("Invoice has no tenant")

    # Validate Connect status BEFORE checking Stripe config (fail fast with clear error)
    if tenant.stripe_onboarding_status != 'active':
        raise ConnectError(
            f"Tenant '{tenant.name}' Stripe Connect is not active "
            f"(status: {tenant.stripe_onboarding_status}). "
            f"Complete onboarding before accepting online payments."
        )

    if not tenant.stripe_connect_charges_enabled:
        raise ConnectError(
            f"Tenant '{tenant.name}' cannot accept charges. "
            f"Stripe Connect charges are not enabled."
        )

    if not getattr(settings, 'STRIPE_SECRET_KEY', None):
        raise ConnectError("Stripe is not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY

    amount_cents = int(invoice.amount_due * 100)
    fee_cents = calculate_platform_fee(amount_cents, tenant)

    session_params = {
        'payment_method_types': ['card'],
        'line_items': [{
            'price_data': {
                'currency': 'usd',
                'unit_amount': amount_cents,
                'product_data': {
                    'name': f'Invoice {invoice.invoice_number}',
                },
            },
            'quantity': 1,
        }],
        'mode': 'payment',
        'success_url': success_url,
        'cancel_url': cancel_url,
        'metadata': {
            'rs_invoice_id': str(invoice.id),
            'rs_invoice_number': invoice.invoice_number,
            'rs_tenant_id': str(tenant.id),
            'rs_fee_cents': str(fee_cents),
        },
        # Metadata must ALSO live on the PaymentIntent — Stripe does not
        # copy session metadata onto it, and the webhook resolves the
        # invoice (and writes PlatformFeeRecord) from PaymentIntent metadata.
        'payment_intent_data': {
            'metadata': {
                'rs_invoice_id': str(invoice.id),
                'rs_invoice_number': invoice.invoice_number,
                'rs_tenant_id': str(tenant.id),
                'rs_fee_cents': str(fee_cents),
            },
        },
        # Direct charge on connected account
        'stripe_account': tenant.stripe_connect_account_id,
    }

    if fee_cents > 0:
        session_params['payment_intent_data']['application_fee_amount'] = fee_cents

    try:
        session = stripe.checkout.Session.create(**session_params)
        logger.info(
            f"Direct charge session for {invoice.invoice_number}: "
            f"${invoice.amount_due} on {tenant.stripe_connect_account_id} "
            f"(fee: {fee_cents}¢)"
        )
        return session
    except stripe.error.StripeError as e:
        logger.error(f"create_direct_charge_session error: {e}")
        raise ConnectError(str(e))
