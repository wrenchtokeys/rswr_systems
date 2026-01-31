"""
Production settings for rs_systems project.

Imports everything from base.py and adds production-specific overrides.
Used by wsgi.py, Procfile, and .ebextensions for AWS Elastic Beanstalk.
"""

import os
import dj_database_url
from .base import *  # noqa: F401,F403

# =========================================
# CORE
# =========================================

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required for production deployment")

DEBUG = False

# Production domains
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',') if os.environ.get('ALLOWED_HOSTS') else []
ALLOWED_HOSTS.extend([
    'rockstarwindshield.repair',
    'www.rockstarwindshield.repair',
    '.elasticbeanstalk.com',
    '.amazonaws.com',
])

if DEBUG:
    ALLOWED_HOSTS.extend(['localhost', '127.0.0.1'])

# =========================================
# DATABASE - PostgreSQL required
# =========================================

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is REQUIRED for production. Configure RDS PostgreSQL.")

if 'sqlite' in DATABASE_URL.lower():
    raise ValueError("SQLite is not allowed in production! Use RDS PostgreSQL for data persistence.")

DATABASES = {
    'default': dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# =========================================
# MEDIA FILES - S3
# =========================================

USE_S3 = os.environ.get('USE_S3', 'False').lower() == 'true'

if USE_S3:
    AWS_S3_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_S3_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_DEFAULT_ACL = None
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

    # Django 4.2+ STORAGES format
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": AWS_S3_ACCESS_KEY_ID,
                "secret_key": AWS_S3_SECRET_ACCESS_KEY,
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "region_name": AWS_S3_REGION_NAME,
                "default_acl": None,
                "location": "media",
                "object_parameters": {"CacheControl": "max-age=86400"},
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# =========================================
# SECURITY - Hardened for production
# =========================================

USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

SECURE_SSL_REDIRECT = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
SESSION_COOKIE_SECURE = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
CSRF_COOKIE_SECURE = os.environ.get('USE_HTTPS', 'false').lower() == 'true'

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Session security
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 86400  # 24 hours

# CSRF security
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_FAILURE_VIEW = 'django.views.csrf.csrf_failure'
CSRF_TRUSTED_ORIGINS = [
    'https://rockstarwindshield.repair',
    'https://www.rockstarwindshield.repair',
]

# =========================================
# CACHING - Redis only
# =========================================

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get(
            'REDIS_CACHE_URL',
            os.environ.get('REDIS_URL', 'redis://localhost:6379/1')
        ),
        'KEY_PREFIX': 'rs_systems_prod',
        'TIMEOUT': 300,
    }
}

# =========================================
# EMAIL (Production overrides)
# =========================================

EMAIL_USE_SSL = False  # Use TLS on port 587, not SSL
EMAIL_RATE_LIMIT = int(os.environ.get('EMAIL_RATE_LIMIT', 100))

# =========================================
# SMS (Production overrides)
# =========================================

SMS_ENABLED = os.environ.get('SMS_ENABLED', 'True').lower() == 'true'
SMS_DEFAULT_SENDER_ID = os.environ.get('SMS_SENDER_ID', 'RS Systems')
SMS_MAX_PRICE_USD = float(os.environ.get('SMS_MAX_PRICE_USD', '0.50'))
SMS_RATE_LIMIT = int(os.environ.get('SMS_RATE_LIMIT', 10))

# AWS credentials (if not already set via S3)
if not USE_S3:
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

# =========================================
# CELERY (Production overrides)
# =========================================

TIME_ZONE = 'UTC'
CELERY_TIMEZONE = TIME_ZONE

CELERY_BROKER_URL = os.environ.get(
    'CELERY_BROKER_URL',
    os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)

CELERY_WORKER_CONCURRENCY = int(os.environ.get('CELERY_CONCURRENCY', 8))
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000

CELERY_TASK_ALWAYS_EAGER = False

CELERY_ANNOTATIONS = {
    'core.tasks.send_notification_email': {
        'rate_limit': '14/s',
    },
    'core.tasks.send_notification_sms': {
        'rate_limit': '10/s',
    },
}

CELERY_SEND_TASK_ERROR_EMAILS = True
CELERY_SEND_TASK_SENT_EVENT = True

# =========================================
# LOGGING
# =========================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'core.tasks': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# =========================================
# SENTRY ERROR TRACKING
# =========================================

SENTRY_DSN = os.environ.get('SENTRY_DSN')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],
        traces_sample_rate=0.1,
        sample_rate=1.0,
        environment=os.environ.get('ENVIRONMENT', 'production'),
        release=os.environ.get('APP_VERSION', 'unknown'),
        send_default_pii=False,
        before_send=lambda event, hint: event,
    )

# =========================================
# CLOUDWATCH METRICS
# =========================================

AWS_CLOUDWATCH_ENABLED = os.environ.get('AWS_CLOUDWATCH_ENABLED', 'False').lower() == 'true'
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
