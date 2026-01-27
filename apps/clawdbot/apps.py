from django.apps import AppConfig


class ClawdbotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clawdbot'
    verbose_name = 'Clawdbot'

    def ready(self):
        """Import signals when app is ready."""
        import apps.clawdbot.signals  # noqa: F401
