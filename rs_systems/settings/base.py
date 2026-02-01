"""
Base Django settings for rs_systems project.

Shared configuration used by both development and production.
Environment-specific settings are in development.py and production.py.
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
# settings/ is one level deeper than the old settings.py, so go up 3 levels.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# =========================================
# APPLICATION DEFINITION
# =========================================

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
    'apps.clawdbot',
    'apps.billing',
    'apps.tenants',
    'apps.saas',
    'core',
    'drf_spectacular',
    'storages',
    'django_cleanup.apps.CleanupConfig',  # Must be last - automatically deletes files when models are deleted
]

MIDDLEWARE = [
    'common.health_check_middleware.HealthCheckMiddleware',  # Must be first to bypass host validation
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.tenants.middleware.TenantMiddleware',
    'common.portal_middleware.PortalAccessMiddleware',
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
                'common.context_processors.portal_access',
            ],
        },
    },
]

WSGI_APPLICATION = 'rs_systems.wsgi.application'

# =========================================
# AUTHENTICATION CONFIGURATION
# =========================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

# =========================================
# REST FRAMEWORK CONFIGURATION
# =========================================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/minute',
        'user': '60/minute',
        'signup': '5/hour',
    },
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'RSWR Systems API',
    'DESCRIPTION': 'API documentation for RSWR Systems',
    'VERSION': '1.0.0',
}

# =========================================
# INTERNATIONALIZATION
# =========================================

LANGUAGE_CODE = 'en-us'
USE_I18N = True
USE_TZ = True

# =========================================
# DEFAULT FIELDS
# =========================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =========================================
# STATIC FILES CONFIGURATION
# =========================================

STATIC_URL = os.environ.get('STATIC_URL', '/static/')
STATIC_ROOT = os.environ.get('STATIC_ROOT', os.path.join(BASE_DIR, 'staticfiles'))
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# =========================================
# FILE UPLOAD CONFIGURATION
# =========================================

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# =========================================
# EMAIL CONFIGURATION (SendGrid)
# =========================================

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.sendgrid.net'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'apikey'
EMAIL_HOST_PASSWORD = os.environ.get('SENDGRID_API_KEY')

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'notifications@rockstarwindshield.repair')
DEFAULT_FROM_NAME = os.environ.get('DEFAULT_FROM_NAME', 'RS Systems')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# =========================================
# SMS CONFIGURATION (AWS SNS)
# =========================================

AWS_SNS_REGION_NAME = os.environ.get('AWS_SNS_REGION', 'us-east-1')
SMS_ENABLED = os.environ.get('SMS_ENABLED', 'False').lower() == 'true'

# =========================================
# STRIPE CONFIGURATION
# =========================================

STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_TEST_MODE = STRIPE_SECRET_KEY.startswith('sk_test_') if STRIPE_SECRET_KEY else True

# =========================================
# INVOICE DEFAULTS
# =========================================

INVOICE_DEFAULT_DUE_DAYS = 30
INVOICE_FROM_EMAIL = os.environ.get('INVOICE_FROM_EMAIL', 'billing@rockstarwindshield.repair')

# =========================================
# CELERY CONFIGURATION (Shared)
# =========================================

CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

CELERY_ENABLE_UTC = True

CELERY_TASK_ROUTES = {
    'core.tasks.send_notification_email': {'queue': 'notifications'},
    'core.tasks.send_notification_sms': {'queue': 'notifications'},
    'core.tasks.retry_failed_notifications': {'queue': 'notifications'},
    'core.tasks.send_daily_digests': {'queue': 'notifications'},
    'core.tasks.cleanup_old_delivery_logs': {'queue': 'maintenance'},
}

CELERY_TASK_TIME_LIMIT = 300  # 5 minutes hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 minutes soft limit

CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
