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
    # intcomma for money figures — "$3,700.00" not "$3700.00". A four-figure
    # revenue number without a thousands separator reads as unfinished.
    'django.contrib.humanize',
    'apps.technician_portal',
    'apps.customer_portal',
    'apps.rewards_referrals',
    'apps.security',
    'apps.clawdbot',
    'apps.support',
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
# PHOTO CROP SUGGESTIONS (tap-to-crop P3)
# =========================================

# Pre-place the "tap the break" marker using the local suggester in
# apps/technician_portal/services/photo_suggest.py. Defaults ON because it
# runs entirely on this server — no API key, no per-photo cost, and no photo
# ever leaves our infrastructure (that was the explicit decision; a hosted
# vision model was rejected). Set to 'false' to fall back to the plain
# empty modal, which is the pre-P3 behaviour and always usable.
PHOTO_SUGGEST_ENABLED = (
    os.environ.get('PHOTO_SUGGEST_ENABLED', 'True').lower() == 'true'
)

# =========================================
# SMS CONFIGURATION (AWS End User Messaging)
# =========================================

AWS_SNS_REGION_NAME = os.environ.get('AWS_SNS_REGION', 'us-east-1')  # legacy name, kept for old callers
AWS_SMS_REGION_NAME = os.environ.get('AWS_SMS_REGION', os.environ.get('AWS_SNS_REGION', 'us-east-1'))
SMS_ENABLED = os.environ.get('SMS_ENABLED', 'False').lower() == 'true'

# Master switch for all SMS features: the registered toll-free number (E.164)
# or pool ARN that texts are sent from. Empty = SMS disabled everywhere,
# regardless of SMS_ENABLED. Set via EB env once the number is verified.
SMS_ORIGINATION_IDENTITY = os.environ.get('SMS_ORIGINATION_IDENTITY', '')

# Optional End User Messaging configuration set (delivery-event tracking)
SMS_CONFIGURATION_SET = os.environ.get('SMS_CONFIGURATION_SET', '')

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

# Pin the API version that outbound calls request. Without this the version
# is whatever the installed SDK happens to default to, so a routine
# `pip install` silently changes payload shapes in production: the
# `stripe>=8.0.0,<16` range had already drifted prod to 15.4.0
# (2026-07-29.dahlia) while a dev machine sat on 14.3.0 (2026-01-28.clover).
#
# This value matches what production was already sending, so pinning it
# changes no behaviour today — it just stops the next rebuild from moving it.
# Override with `eb setenv STRIPE_API_VERSION=...` to roll forward
# deliberately, and read apps/billing/services/stripe_compat.py first: the
# accessors there tolerate both the pre-Basil and Basil+ shapes, but code
# that reads Stripe fields directly does not.
#
# NOTE: this governs outbound calls only. Inbound webhook payload shape is
# set by the version pinned on each endpoint in the Stripe Dashboard, which
# is configured separately and need not match.
STRIPE_API_VERSION = os.environ.get('STRIPE_API_VERSION', '2026-07-29.dahlia')

# =========================================
# CREDENTIAL ENCRYPTION AT REST
# =========================================

# Fernet key for common.encryption — encrypts third-party credentials tenants
# hand us (Mygrant passwords/API keys). Deliberately NOT SECRET_KEY: rotating
# Django's signing key must never brick stored credentials. No production
# fallback; development.py derives a dev key so local dev and tests just work.
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')

# Where platform-level billing alerts go: Stripe disputes, and the daily
# digest of webhook events that failed to process. These concern the
# platform's own money and Stripe account risk, not any shop's, so they must
# NOT be routed through the tenant notification path.
PLATFORM_ALERT_EMAIL = os.environ.get(
    'PLATFORM_ALERT_EMAIL', ''
) or os.environ.get('DEFAULT_FROM_EMAIL', 'notifications@rssystems.io')

# =========================================
# SUBSCRIPTION LIFECYCLE
# =========================================

# Days of full access a past_due tenant keeps before the shop goes
# read-only. past_due used to be warn-only forever, so a shop whose card
# died kept full write access indefinitely, for free.
#
# 14 is chosen against Stripe's retry window (~3 weeks of smart retries):
# restricting at day 0 punishes an innocently expired card, and there is
# still roughly a week of automatic retries left after the restriction
# lands. /owner/billing/ stays exempt so the fix is always reachable.
PAST_DUE_GRACE_DAYS = int(os.environ.get('PAST_DUE_GRACE_DAYS', '14'))

# Read-only days an expired TRIAL gets. Previously zero -- grace_period_end
# was only ever set by the subscription.deleted webhook, so a shop that
# never subscribed hit a hard wall the moment the trial clock ran out.
# Shorter than the 30 days a paid lapse gets: they never paid us.
TRIAL_GRACE_DAYS = int(os.environ.get('TRIAL_GRACE_DAYS', '14'))

# =========================================
# INVOICE DEFAULTS
# =========================================

INVOICE_DEFAULT_DUE_DAYS = 30

# Celery removed — notifications are synchronous; batch billing runs via management commands.
