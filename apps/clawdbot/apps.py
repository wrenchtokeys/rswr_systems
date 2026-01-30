from django.apps import AppConfig


class ClawdbotConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.clawdbot'
    verbose_name = 'Clawdbot'
    
    # Note: Business logic signals are in their domain apps (e.g., billing)
    # Clawdbot is an API/orchestration layer only
