"""
Development settings for rs_systems project.

Imports everything from base.py and adds dev-specific overrides.
Used by manage.py and local development.
"""

import os
import dj_database_url
from dotenv import load_dotenv
from .base import *  # noqa: F401,F403

# Load environment variables from .env file in project root
load_dotenv(os.path.join(BASE_DIR, '.env'))

# =========================================
# CORE
# =========================================

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only-key-not-for-production')

DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

# Credential encryption (common.encryption): derive a stable dev key from
# SECRET_KEY when the env var is unset, so dev and the test suite need no
# setup. Production has no fallback — see base.py.
if not FIELD_ENCRYPTION_KEY:  # noqa: F405
    import base64 as _b64
    import hashlib as _hashlib
    FIELD_ENCRYPTION_KEY = _b64.urlsafe_b64encode(
        _hashlib.sha256(('field-encryption:' + SECRET_KEY).encode()).digest()
    ).decode()

# =========================================
# CORS
# =========================================

CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', 'http://localhost:8000').split(',')
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:8000').split(',')
CORS_ALLOW_CREDENTIALS = os.environ.get('CORS_ALLOW_CREDENTIALS', 'True').lower() == 'true'

# =========================================
# DATABASE
# =========================================

USE_AWS_DB = os.environ.get('USE_AWS_DB', 'False').lower() == 'true'

if USE_AWS_DB:
    db_url = os.environ.get('AWS_DATABASE_URL')
else:
    db_url = os.environ.get('LOCAL_DATABASE_URL')

if not db_url:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    DATABASES = {
        'default': dj_database_url.config(default=db_url, conn_max_age=600),
    }
    DATABASES['default'].setdefault('TEST', {})

# =========================================
# MEDIA FILES
# =========================================

USE_S3 = os.environ.get('USE_S3', 'False').lower() == 'true'

if USE_S3:
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_S3_VERIFY = True
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    MEDIA_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com/'
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    os.makedirs(os.path.join(MEDIA_ROOT, 'repair_photos', 'before'), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_ROOT, 'repair_photos', 'after'), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_ROOT, 'repair_photos', 'crops'), exist_ok=True)

# =========================================
# SECURITY
# =========================================

USE_HTTPS = os.environ.get('USE_HTTPS', 'False').lower() == 'true'
IS_CLOUD_DEPLOYMENT = any(host.endswith(('.railway.app', '.herokuapp.com', '.vercel.app')) for host in ALLOWED_HOSTS)

if IS_CLOUD_DEPLOYMENT or USE_HTTPS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = not IS_CLOUD_DEPLOYMENT  # Cloud providers handle SSL termination
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
else:
    SECURE_PROXY_SSL_HEADER = None
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

# =========================================
# CACHING
# =========================================

REDIS_CACHE_URL = os.environ.get('REDIS_CACHE_URL', 'redis://localhost:6379/1')


def _redis_available():
    """Check if Redis is reachable (called once at startup)."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(('localhost', 6379))
        s.close()
        return True
    except (socket.error, OSError):
        return False


if _redis_available():
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_CACHE_URL,
            'KEY_PREFIX': 'rs_systems',
            'TIMEOUT': 300,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'KEY_PREFIX': 'rs_systems',
            'TIMEOUT': 300,
        }
    }

TIME_ZONE = os.environ.get('TIME_ZONE', 'America/Chicago')

# =========================================
# EMAIL (Dev overrides)
# =========================================

# Use console email backend in dev to avoid SSL issues
# Set USE_REAL_EMAIL=True to actually send emails
USE_REAL_EMAIL = os.environ.get('USE_REAL_EMAIL', 'False').lower() == 'true'

if not USE_REAL_EMAIL or not os.environ.get('EMAIL_HOST_PASSWORD'):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    # Emails will be printed to console instead of sent

# =========================================
# LOGGING
# =========================================

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.getenv('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
    },
}
