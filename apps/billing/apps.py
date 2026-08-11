from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.billing'
    verbose_name = 'Billing'

    def ready(self):
        """Import signals when app is ready."""
        import apps.billing.signals  # noqa: F401

        # Pin the Stripe API version once, before any call can be made.
        # Otherwise the payload shape depends on whichever SDK the last
        # build resolved -- see stripe_compat for the fields Basil moved.
        from apps.billing.services.stripe_compat import configure_stripe
        configure_stripe()
