"""
Celery configuration for RS Systems notification system.

This module initializes the Celery app and configures:
- Task autodiscovery from all installed Django apps
- Periodic task scheduling (Beat)
- Task routing and queues
"""

import logging
import os
from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)

# Set Django settings module
# Production sets this via Procfile / .ebextensions; default to development for local use
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rs_systems.settings.development')

# Create Celery app
app = Celery('rs_systems')

# Track Celery availability for graceful degradation
CELERY_AVAILABLE = False

# Load configuration from Django settings with CELERY_ prefix
# Example: CELERY_BROKER_URL in settings.py becomes broker_url in Celery
try:
    app.config_from_object('django.conf:settings', namespace='CELERY')
    # Auto-discover tasks in all installed apps
    # Looks for tasks.py in each app directory
    app.autodiscover_tasks()
    CELERY_AVAILABLE = True
    logger.info("✅ Celery initialized successfully")
except Exception as e:
    logger.warning(f"⚠️  Celery initialization failed: {e}")
    logger.warning("Notifications disabled. App will continue without async tasks.")
    # Fallback to in-memory broker to prevent crashes
    app.conf.update(
        broker_url='memory://',
        result_backend='cache+memory://',
        task_always_eager=True
    )


# Periodic task schedule (Celery Beat)
# These tasks will be created in Phase 4
app.conf.beat_schedule = {
    # Retry failed notification deliveries every 5 minutes
    # Uses exponential backoff logic from NotificationDeliveryLog
    'retry-failed-notifications': {
        'task': 'core.tasks.retry_failed_notifications',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },

    # Send daily digest emails at 9 AM local time
    # For users who prefer batched notifications
    'send-daily-digests': {
        'task': 'core.tasks.send_daily_digests',
        'schedule': crontab(hour=9, minute=0),  # 9:00 AM daily
    },

    # Cleanup old notification delivery logs weekly
    # Keeps database size manageable
    'cleanup-old-logs': {
        'task': 'core.tasks.cleanup_old_delivery_logs',
        'schedule': crontab(hour=2, minute=0, day_of_week=0),  # 2 AM Sunday
    },
    
    # === BILLING AUTOMATION (Phase 6) ===
    
    # Process overdue invoices daily at 8 AM
    # Updates SENT → OVERDUE status and sends reminder emails
    'process-overdue-invoices': {
        'task': 'billing.process_overdue_invoices',
        'schedule': crontab(hour=8, minute=0),  # 8:00 AM daily
    },
    
    # Process batch invoices daily at 6 AM
    # Only creates invoices on configured days (checks internally)
    'process-batch-invoices': {
        'task': 'billing.process_batch_invoices',
        'schedule': crontab(hour=6, minute=0),  # 6:00 AM daily
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """
    Debug task for testing Celery configuration.

    Usage:
        from rs_systems.celery import debug_task
        debug_task.delay()

    This task will print request details to the Celery worker log.
    """
    print(f'Request: {self.request!r}')
    return 'Debug task executed successfully'
