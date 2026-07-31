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
    'django.contrib.messages.middleware.MessageMiddleware',
    'apps.tenants.middleware.TenantMiddleware',
    'apps.tenants.subscription_middleware.SubscriptionEnforcementMiddleware',
    'common.portal_middleware.PortalAccessMiddleware',
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
                'common.context_processors.customer_loyalty',
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
        # TokenAuthentication removed: nothing issues tokens anymore, but
        # tokens minted by the old unauthenticated API signup never expire —
        # disabling the auth class renders them inert.
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'common.throttles.ResilientAnonRateThrottle',
        'common.throttles.ResilientUserRateThrottle',
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
# STATICFILES_STORAGE is deprecated in Django 4.2+
# Use STORAGES dict in production.py instead

# =========================================
# FILE UPLOAD CONFIGURATION
# =========================================

DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# =========================================
# EMAIL CONFIGURATION (SMTP)
# =========================================
# Amazon SES over SMTP. Overridable via env so switching providers or
# regions is an `eb setenv`, not a code deploy.
#
# EMAIL_HOST_USER / EMAIL_HOST_PASSWORD are SES *SMTP credentials*, which
# are NOT the same as an AWS access key pair. Generate them under
# SES Console > SMTP settings > Create SMTP credentials.

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'email-smtp.us-east-1.amazonaws.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
# Cap SMTP connection time — without this a slow/unreachable provider
# hangs the web worker for the request that triggered the email.
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 10))

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'notifications@rssystems.io')
DEFAULT_FROM_NAME = os.environ.get('DEFAULT_FROM_NAME', 'RS Systems')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Canonical public origin for links in emails and webhooks. SITE_URL is the
# legacy alias some services read (review_service, invitation_service,
# notification templates) — keep both pointing at the same value.
BASE_URL = os.environ.get('BASE_URL', 'https://rssystems.io').rstrip('/')
SITE_URL = BASE_URL

# Don't count an invoice "view" within this window after sending — mail
# security gateways (Microsoft Defender Safe Links etc.) fetch every link
# in an email seconds after delivery while scanning it.
INVOICE_VIEW_GRACE_SECONDS = int(os.environ.get('INVOICE_VIEW_GRACE_SECONDS', 300))

# Site admins — receive new signup notifications and error reports
ADMINS = [
    ('Drake', os.environ.get('ADMIN_EMAIL', 'wdrakeduncan@gmail.com')),
]
MANAGERS = ADMINS

# =========================================
# SMS CONFIGURATION (AWS SNS)
# =========================================

AWS_SNS_REGION_NAME = os.environ.get('AWS_SNS_REGION', 'us-east-1')
SMS_ENABLED = os.environ.get('SMS_ENABLED', 'False').lower() == 'true'

# =========================================
# STRIPE CONFIGURATION
# =========================================

# STRIPE_MODE: set to 'test' or 'live' to switch between key sets
STRIPE_MODE = os.environ.get('STRIPE_MODE', 'live')

if STRIPE_MODE == 'test':
    STRIPE_PUBLISHABLE_KEY = os.environ.get('TEST_STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_SECRET_KEY = os.environ.get('TEST_STRIPE_SECRET_KEY', '')
else:
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')

STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')  # Billing/invoice webhooks
STRIPE_CONNECT_WEBHOOK_SECRET = os.environ.get('STRIPE_CONNECT_WEBHOOK_SECRET', '')  # Connect account webhooks
STRIPE_SUBSCRIPTION_WEBHOOK_SECRET = os.environ.get('STRIPE_SUBSCRIPTION_WEBHOOK_SECRET', '')  # SaaS subscription webhooks
STRIPE_TEST_MODE = STRIPE_MODE == 'test'

# =========================================
# INVOICE DEFAULTS
# =========================================

INVOICE_DEFAULT_DUE_DAYS = 30

# Celery removed — notifications are synchronous; batch billing runs via management commands.
