import os
from pathlib import Path
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is required for AWS deployment")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

# Configure allowed hosts via environment variable - NO hardcoded IPs for robust deployment
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',') if os.environ.get('ALLOWED_HOSTS') else []

# Add production domains - domains only, never IPs for robust scaling
ALLOWED_HOSTS.extend([
    'rockstarwindshield.repair',
    'www.rockstarwindshield.repair',
    '.elasticbeanstalk.com',  # For Elastic Beanstalk domains
    '.amazonaws.com',         # For AWS domains
])

# For development/local testing only
if DEBUG:
    ALLOWED_HOSTS.extend(['localhost', '127.0.0.1'])

# Application definition
INSTALLED_APPS = [
    'rest_framework',
    'rest_framework.authtoken',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.technician_portal',
    'apps.customer_portal',
    'apps.rewards_referrals',
    'apps.security',
    'core',
    'drf_spectacular',
    'storages',  # For django-storages
]

MIDDLEWARE = [
    'common.health_check_middleware.HealthCheckMiddleware',  # Must be first to bypass host validation
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Whitenoise for static files
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'rs_systems.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'templates',
            BASE_DIR / 'rs_systems' / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'rs_systems.wsgi.application'

# Database - MUST use RDS PostgreSQL in production
# DATABASE_URL must be configured as an environment variable
import dj_database_url

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is REQUIRED for AWS deployment. Configure RDS PostgreSQL.")

DATABASES = {
    'default': dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Ensure we're not using SQLite
if 'sqlite' in DATABASE_URL.lower():
    raise ValueError("SQLite is not allowed in production! Use RDS PostgreSQL for data persistence.")

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files configuration
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Use whitenoise for static files
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security settings for deploying behind AWS Load Balancer/proxy - ROBUST configuration
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Health checks are handled by middleware, no wildcard needed

SECURE_SSL_REDIRECT = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
SESSION_COOKIE_SECURE = os.environ.get('USE_HTTPS', 'false').lower() == 'true'
CSRF_COOKIE_SECURE = os.environ.get('USE_HTTPS', 'false').lower() == 'true'

# Additional security headers for production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000  # 1 year
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

# CSRF trusted origins for production domain
CSRF_TRUSTED_ORIGINS = [
    'https://rockstarwindshield.repair',
    'https://www.rockstarwindshield.repair',
]

# HSTS settings
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# File upload size limits - Allow up to 10MB for image uploads
# This provides headroom beyond the 5MB validation in the application
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# DRF Spectacular settings
SPECTACULAR_SETTINGS = {
    'TITLE': 'RS Systems API',
    'DESCRIPTION': 'API for RS Systems application',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Media files configuration - S3 for production, local for development
# NOTE: Static files always use WhiteNoise/nginx, only media files use S3
USE_S3 = os.environ.get('USE_S3', 'False').lower() == 'true'

if USE_S3:
    # AWS S3 settings for MEDIA files only (photos)
    # Static files (CSS/JS) continue to use WhiteNoise
    AWS_S3_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_S3_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_DEFAULT_ACL = None  # Don't use ACLs, use bucket policy instead
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

    # S3 media settings - Django 4.2+ STORAGES format
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
    # Local media files settings for development
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# =========================================
# EMAIL CONFIGURATION (SendGrid)
# =========================================

# Production: SendGrid SMTP Backend
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# SendGrid SMTP Settings
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False  # Use TLS on port 587, not SSL

# SendGrid Credentials (API key as password, 'apikey' as username)
EMAIL_HOST_USER = 'apikey'
EMAIL_HOST_PASSWORD = os.environ.get('SENDGRID_API_KEY')

# Sender information
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'notifications@rockstarwindshield.repair')
DEFAULT_FROM_NAME = os.environ.get('DEFAULT_FROM_NAME', 'RS Systems')
SERVER_EMAIL = DEFAULT_FROM_EMAIL  # For error emails

# Email rate limiting (SendGrid allows higher rates than SES)
EMAIL_RATE_LIMIT = int(os.environ.get('EMAIL_RATE_LIMIT', 100))  # Emails per second

# =========================================
# SMS CONFIGURATION (AWS SNS)
# =========================================

# AWS SNS Configuration for SMS
AWS_SNS_REGION_NAME = os.environ.get('AWS_SNS_REGION', 'us-east-1')
# AWS credentials shared with S3 (already defined above if USE_S3=true)
# If not using S3, need to define AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
if not USE_S3:
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')

# SMS Settings
SMS_ENABLED = os.environ.get('SMS_ENABLED', 'True').lower() == 'true'
SMS_DEFAULT_SENDER_ID = os.environ.get('SMS_SENDER_ID', 'RS Systems')  # Not used in US
SMS_MAX_PRICE_USD = float(os.environ.get('SMS_MAX_PRICE_USD', '0.50'))  # Max price per SMS

# SMS rate limiting
SMS_RATE_LIMIT = int(os.environ.get('SMS_RATE_LIMIT', 10))  # SMS per second

# =========================================
# CELERY CONFIGURATION (Production)
# =========================================

# Celery broker and result backend (AWS ElastiCache Redis)
CELERY_BROKER_URL = os.environ.get(
    'CELERY_BROKER_URL',
    os.environ.get('REDIS_URL', 'redis://localhost:6379/0')  # Fallback for local testing
)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)

# Celery serialization settings
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Timezone configuration (match Django timezone)
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True

# Task routing (send notification tasks to specific queue)
CELERY_TASK_ROUTES = {
    'apps.core.tasks.send_notification_email': {'queue': 'notifications'},
    'apps.core.tasks.send_notification_sms': {'queue': 'notifications'},
    'apps.core.tasks.retry_failed_notifications': {'queue': 'notifications'},
    'apps.core.tasks.send_daily_digests': {'queue': 'notifications'},
    'apps.core.tasks.cleanup_old_delivery_logs': {'queue': 'maintenance'},
}

# Task time limits (prevent hanging tasks)
CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 minutes soft limit

# Retry configuration
CELERY_TASK_ACKS_LATE = True  # Tasks acknowledged after completion (safer)
CELERY_TASK_REJECT_ON_WORKER_LOST = True  # Requeue if worker crashes

# Worker concurrency (number of worker processes)
CELERY_WORKER_CONCURRENCY = int(os.environ.get('CELERY_CONCURRENCY', 8))
CELERY_WORKER_MAX_TASKS_PER_CHILD = 1000  # Restart workers after 1000 tasks (prevents memory leaks)

# Production: Never use eager mode
CELERY_TASK_ALWAYS_EAGER = False

# Rate limiting for external APIs (SES/SNS)
CELERY_ANNOTATIONS = {
    'apps.core.tasks.send_notification_email': {
        'rate_limit': '14/s',  # Match SES limit (14 emails/second)
    },
    'apps.core.tasks.send_notification_sms': {
        'rate_limit': '10/s',  # Conservative SMS rate limit
    },
}

# Monitoring
CELERY_SEND_TASK_ERROR_EMAILS = True
CELERY_SEND_TASK_SENT_EVENT = True

# =========================================
# CACHING CONFIGURATION (AWS ElastiCache Redis)
# =========================================

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get(
            'REDIS_CACHE_URL',
            os.environ.get('REDIS_URL', 'redis://localhost:6379/1')
        ),
        'KEY_PREFIX': 'rs_systems_prod',
        'TIMEOUT': 300,  # 5 minutes default timeout
    }
}

# Logging configuration - outputs errors with full tracebacks to stdout
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
        'apps.core.tasks': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# =========================================
# SENTRY ERROR TRACKING (Production Only)
# =========================================

# Sentry configuration for production error tracking and performance monitoring
# Only initialize Sentry in production (DEBUG=False)
if not DEBUG:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        # Sentry DSN from environment variable
        dsn=os.environ.get('SENTRY_DSN'),

        # Integrations for Django, Celery, and Redis monitoring
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            RedisIntegration(),
        ],

        # Performance monitoring (10% sampling to reduce overhead)
        traces_sample_rate=0.1,

        # Error sampling (capture 100% of errors)
        sample_rate=1.0,

        # Environment and release tracking
        environment=os.environ.get('ENVIRONMENT', 'production'),
        release=os.environ.get('APP_VERSION', 'unknown'),

        # Send default PII (Personally Identifiable Information)
        send_default_pii=False,  # Set to True if you want user context

        # Tag all events with component information
        before_send=lambda event, hint: event,
    )

# =========================================
# CLOUDWATCH METRICS (Production Only)
# =========================================

# Enable CloudWatch metrics publishing for notification system monitoring
AWS_CLOUDWATCH_ENABLED = os.environ.get('AWS_CLOUDWATCH_ENABLED', 'False').lower() == 'true'
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1') 