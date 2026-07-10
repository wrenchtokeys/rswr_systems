"""
Production settings for rs_systems project.

Imports everything from base.py and adds production-specific overrides.
Used by wsgi.py, Procfile, and .ebextensions for AWS Elastic Beanstalk.
"""

import os
import logging
import dj_database_url
from .base import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

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
    'rssystems.io',
    'www.rssystems.io',
])

# EB hostname (e.g., "myapp.us-east-1.elasticbeanstalk.com")
EB_HOSTNAME = os.environ.get('EB_HOSTNAME')
if EB_HOSTNAME:
    ALLOWED_HOSTS.append(EB_HOSTNAME)

# Internal AWS hostname for health checks behind load balancer
AWS_INTERNAL_HOSTNAME = os.environ.get('AWS_INTERNAL_HOSTNAME')
if AWS_INTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(AWS_INTERNAL_HOSTNAME)

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
            "BACKEND": "rs_systems.storage.ForgivingManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "rs_systems.storage.ForgivingManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# =========================================
# SECURITY - Hardened for production
# =========================================

USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

_USE_HTTPS = os.environ.get('USE_HTTPS', 'true').lower() != 'false'
SECURE_SSL_REDIRECT = _USE_HTTPS
SESSION_COOKIE_SECURE = _USE_HTTPS
CSRF_COOKIE_SECURE = _USE_HTTPS

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
    'https://rssystems.io',
    'https://www.rssystems.io',
]

# =========================================
# CACHING
# =========================================
# Use Redis if available (set REDIS_URL or REDIS_CACHE_URL in EB env vars).
# Falls back to database-backed cache — survives gunicorn restarts and works
# across multiple workers (unlike LocMemCache which is per-process).
# django-ratelimit, DRF throttling, and template caching all depend on this.

# Database-backed cache — no external dependencies, works across multiple
# gunicorn workers, survives process restarts. The django_cache table is
# created by the postdeploy hook (createcachetable).
#
# To upgrade to Redis later: install redis package, add REDIS_URL env var,
# and swap the backend. See docs/SCALING.md for details.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'django_cache',
        'TIMEOUT': 300,
        'OPTIONS': {
            'MAX_ENTRIES': 5000,
        },
    }
}

# =========================================
# EMAIL (Production overrides)
# =========================================

EMAIL_USE_SSL = False  # Use TLS on port 587, not SSL

# SES caps this account at 14 messages/second. Nothing reads this setting
# today; it is here so a future sender honours that ceiling.
EMAIL_RATE_LIMIT = int(os.environ.get('EMAIL_RATE_LIMIT', 14))

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

# Local business timezone (C7). With USE_TZ=True, storage stays UTC; this
# only controls what "today" means for DateFields, invoice dates, due-date
# arithmetic, aging buckets, and the overdue cron. It was 'UTC', which gave
# a Central-time shop invoices dated tomorrow for any work saved after 7pm
# (and off-by-one due dates / aging from then on). Matches development's
# default; override with the TIME_ZONE env var if a deployment ever serves
# a different region.
TIME_ZONE = os.environ.get('TIME_ZONE', 'America/Chicago')

# Celery removed — notifications are synchronous; batch billing runs via management commands.

# =========================================
# LOGGING
# =========================================
# In production, log WARNING+ for Django internals and INFO for our apps.
# All output goes to stdout where EB/CloudWatch can capture it.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
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
            'level': 'WARNING',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security.DisallowedHost': {
            'handlers': ['console'],
            'level': 'CRITICAL',  # Suppress noisy scanner traffic
            'propagate': False,
        },
        'core': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'common': {
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

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
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
