"""
Stripe Connect Service

Handles Connected Account onboarding, status tracking, and payment routing
for multi-tenant invoice payments.

Architecture:
- Platform account (Drake's) receives SaaS subscriptions
- Connected accounts (each shop) receive their customer invoice payments
- Platform takes an optional fee on each invoice payment

Uses Stripe Express accounts — Stripe handles KYC/compliance, shop owners
get a simplified onboarding experience.

Author: Amelia (Clawdbot AI)
"""

import logging
import stripe
from decimal import Decimal
from django.conf import settings

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
        self.api_key = settings.STRIPE_SECRET_KEY
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
                tenant.save(update_fields=['stripe_connect_account_id'])
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

            tenant.stripe_connect_charges_enabled = account.charges_enabled
            tenant.stripe_connect_payouts_enabled = account.payouts_enabled
            tenant.stripe_connect_onboarding_complete = account.details_submitted
            tenant.save(update_fields=[
                'stripe_connect_charges_enabled',
                'stripe_connect_payouts_enabled',
                'stripe_connect_onboarding_complete',
            ])

            logger.info(
                f"Synced Connect status for {tenant.slug}: "
                f"charges={account.charges_enabled}, "
                f"payouts={account.payouts_enabled}, "
                f"onboarding={'complete' if account.details_submitted else 'incomplete'}"
            )

            return {
                'charges_enabled': account.charges_enabled,
                'payouts_enabled': account.payouts_enabled,
                'details_submitted': account.details_submitted,
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

    # ------------------------------------------------------------------
    # Payment Routing
    # ------------------------------------------------------------------

    def calculate_platform_fee(self, amount, tenant):
        """
        Calculate the platform fee for an invoice payment.

        Args:
            amount: Payment amount in dollars (Decimal)
            tenant: Tenant model instance

        Returns:
            int: Fee amount in cents for Stripe
        """
        fee_percent = tenant.platform_fee_percent or Decimal('0')
        if fee_percent <= 0:
            return 0
        fee = amount * fee_percent / 100
        return int(fee * 100)  # Convert to cents

    def create_connected_checkout_session(
        self, invoice, success_url=None, cancel_url=None
    ):
        """
        Create a Checkout Session that routes payment to the shop's
        connected account, with an optional platform fee.

        This replaces the standard create_checkout_session when the
        tenant has a connected Stripe account.

        Args:
            invoice: Invoice model instance
            success_url: Redirect URL on success
            cancel_url: Redirect URL on cancel

        Returns:
            dict: {success, checkout_url, session_id}
        """
        tenant = invoice.tenant
        if not tenant or not tenant.can_accept_payments:
            return {
                'success': False,
                'error': 'Shop has not completed Stripe setup',
            }

        try:
            base_url = getattr(settings, 'BASE_URL', 'https://rssystems.io')
            amount_cents = int(invoice.amount_due * 100)
            fee_cents = self.calculate_platform_fee(invoice.amount_due, tenant)

            session_params = {
                'payment_method_types': ['card'],
                'line_items': [{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': amount_cents,
                        'product_data': {
                            'name': f'Invoice {invoice.invoice_number}',
                            'description': (
                                f'{invoice.line_items.count()} windshield repair(s) '
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
                },
                'payment_intent_data': {
                    'transfer_data': {
                        'destination': tenant.stripe_connect_account_id,
                    },
                },
            }

            # Add platform fee if configured
            if fee_cents > 0:
                session_params['payment_intent_data']['application_fee_amount'] = fee_cents

            session = stripe.checkout.Session.create(**session_params)

            logger.info(
                f"Connected checkout session for {invoice.invoice_number}: "
                f"${invoice.amount_due} → {tenant.stripe_connect_account_id} "
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

    def create_connected_payment_link(self, invoice):
        """
        Create a Stripe Payment Link that routes to the shop's connected account.

        Unlike checkout sessions, payment links are reusable and can be
        emailed or shared. However, Payment Links don't support
        transfer_data directly — so we use on_behalf_of + application_fee.

        For connected payments, we prefer checkout sessions (called from
        the customer portal "Pay" button) over payment links.

        Returns:
            dict: {success, payment_link, amount_due}
        """
        tenant = invoice.tenant
        if not tenant or not tenant.can_accept_payments:
            # Fall back to platform payment link (all funds to Drake)
            return None  # Caller should use standard payment link

        try:
            amount_cents = int(invoice.amount_due * 100)
            fee_cents = self.calculate_platform_fee(invoice.amount_due, tenant)

            # Create a one-time price
            price = stripe.Price.create(
                unit_amount=amount_cents,
                currency='usd',
                product_data={
                    'name': f'Invoice {invoice.invoice_number} - {invoice.customer.name}',
                },
            )

            link_params = {
                'line_items': [{'price': price.id, 'quantity': 1}],
                'metadata': {
                    'rs_invoice_id': str(invoice.id),
                    'rs_invoice_number': invoice.invoice_number,
                    'rs_tenant_id': str(tenant.id),
                },
                'after_completion': {
                    'type': 'redirect',
                    'redirect': {
                        'url': f'{getattr(settings, "BASE_URL", "https://rssystems.io")}/payment-complete',
                    },
                },
                'transfer_data': {
                    'destination': tenant.stripe_connect_account_id,
                },
            }

            if fee_cents > 0:
                link_params['application_fee_amount'] = fee_cents

            payment_link = stripe.PaymentLink.create(**link_params)

            logger.info(
                f"Connected payment link for {invoice.invoice_number}: "
                f"{payment_link.url}"
            )

            return {
                'success': True,
                'payment_link': payment_link.url,
                'amount_due': float(invoice.amount_due),
            }

        except stripe.error.StripeError as e:
            logger.error(
                f"Failed to create connected payment link for "
                f"{invoice.invoice_number}: {e}"
            )
            return None  # Fall back to standard payment link


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
        f"charges={status.get('charges_enabled')}, "
        f"payouts={status.get('payouts_enabled')}"
    )

    return {
        'success': True,
        'handled': True,
        'tenant': tenant.slug,
        'charges_enabled': status.get('charges_enabled'),
        'payouts_enabled': status.get('payouts_enabled'),
    }
