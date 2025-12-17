"""
==============================================================================
FILE: production.py
LOCATION: /docextract/config/settings/production.py
==============================================================================

PURPOSE:
    Production-specific Django settings. Enforces security best practices,
    requires explicit environment variables, and disables debug features.

INHERITS FROM:
    config.settings.base (all settings from base.py)

USAGE:
    export DJANGO_SETTINGS_MODULE=config.settings.production
    gunicorn config.wsgi:application

    Or in docker-compose.yml:
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.production

REQUIRED ENVIRONMENT VARIABLES:
    SECRET_KEY          - Django secret key (generate with get_random_secret_key())
    POSTGRES_PASSWORD   - Database password
    ALLOWED_HOSTS       - Comma-separated list of allowed hostnames

OPTIONAL ENVIRONMENT VARIABLES:
    POSTGRES_DB              - Database name (default: docextract)
    POSTGRES_USER            - Database user (default: docextract)
    POSTGRES_HOST            - Database host (default: db)
    REDIS_URL                - Redis URL (default: redis://redis:6379/0)
    CSRF_TRUSTED_ORIGINS     - Comma-separated origins for CSRF
    CORS_ALLOWED_ORIGINS     - Comma-separated origins for CORS
    SECURE_SSL_REDIRECT      - Enable HTTPS redirect (default: false)
    SESSION_COOKIE_SECURE    - Secure session cookies (default: false)
    CSRF_COOKIE_SECURE       - Secure CSRF cookies (default: false)
    SECURE_HSTS_SECONDS      - HSTS max-age in seconds (default: 0, disabled)
    AI_EXTRACTION_ENABLED    - Feature flag (default: true)

SSL/HTTPS CONFIGURATION:
    After obtaining SSL certificates, enable HTTPS settings by adding
    these to your .env file:

        SECURE_SSL_REDIRECT=true
        SESSION_COOKIE_SECURE=true
        CSRF_COOKIE_SECURE=true
        SECURE_HSTS_SECONDS=31536000

SECURITY FEATURES:
    - DEBUG=False (hardcoded, cannot be overridden)
    - XSS and content-type sniffing protection
    - X-Frame-Options DENY (clickjacking protection)
    - HTTPS settings configurable via environment

PERFORMANCE NOTES:
    - CONN_MAX_AGE=60 for database connection pooling
    - connect_timeout=10 to fail fast on DB issues

DEPLOYMENT CHECKLIST:
    [ ] SECRET_KEY set to unique, random value
    [ ] ALLOWED_HOSTS contains only valid hostnames
    [ ] Database credentials are secure
    [ ] SSL certificates obtained and configured
    [ ] HTTPS environment variables enabled
    [ ] Sentry DSN configured for error tracking

==============================================================================
"""

import os
from .base import *  # noqa: F401, F403


def get_bool_env(name: str, default: bool = False) -> bool:
    """
    Get boolean value from environment variable.

    Accepts: 'true', '1', 'yes', 'on' (case-insensitive) as True
    Everything else (including empty string) is False
    """
    value = os.environ.get(name, "").lower().strip()
    if default:
        # Default is True, so only explicit false values should return False
        return value not in ("false", "0", "no", "off")
    else:
        # Default is False, so only explicit true values should return True
        return value in ("true", "1", "yes", "on")


# =============================================================================
# Core Settings
# =============================================================================

# SECURITY: Debug is ALWAYS False in production
DEBUG = False

# Secret key - REQUIRED, no default
SECRET_KEY = os.environ["SECRET_KEY"]

# Allowed hosts - REQUIRED
# Parse comma-separated list, strip whitespace, filter empty strings
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "").split(",")
    if host.strip()
]

# =============================================================================
# Database Configuration
# =============================================================================

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "docextract"),
        "USER": os.environ.get("POSTGRES_USER", "docextract"),
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        # Connection pooling - reuse connections for 60 seconds
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            # Fail fast if database is unreachable
            "connect_timeout": 10,
        },
    }
}

# =============================================================================
# Cache Configuration
# =============================================================================

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    }
}

# =============================================================================
# Security Settings - Always Enabled
# =============================================================================

# Prevent XSS attacks
SECURE_BROWSER_XSS_FILTER = True

# Prevent MIME type sniffing
SECURE_CONTENT_TYPE_NOSNIFF = True

# Prevent clickjacking
X_FRAME_OPTIONS = "DENY"

# =============================================================================
# HTTPS/SSL Settings - Configurable via Environment
# =============================================================================
# These should be enabled AFTER SSL certificates are configured.
# Set the corresponding environment variables to 'true' to enable.

# Redirect all HTTP requests to HTTPS
SECURE_SSL_REDIRECT = get_bool_env("SECURE_SSL_REDIRECT", default=False)

# Only send session cookie over HTTPS
SESSION_COOKIE_SECURE = get_bool_env("SESSION_COOKIE_SECURE", default=False)

# Only send CSRF cookie over HTTPS
CSRF_COOKIE_SECURE = get_bool_env("CSRF_COOKIE_SECURE", default=False)

# HTTP Strict Transport Security (HSTS)
# Set to 31536000 (1 year) after confirming HTTPS works correctly
# Setting to 0 disables HSTS
SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))

# Include subdomains in HSTS (only if SECURE_HSTS_SECONDS > 0)
if SECURE_HSTS_SECONDS > 0:
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Proxy SSL header - Trust X-Forwarded-Proto from Nginx
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# =============================================================================
# CSRF Configuration
# =============================================================================

# Trusted origins for CSRF (required for cross-origin requests)
# Parse comma-separated list
_csrf_origins = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in _csrf_origins.split(",")
    if origin.strip()
]

# =============================================================================
# CORS Configuration
# =============================================================================

# Allowed origins for CORS (if frontend is on different domain)
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _cors_origins.split(",")
    if origin.strip()
]

# Allow credentials (cookies) in CORS requests
CORS_ALLOW_CREDENTIALS = True

# =============================================================================
# Feature Flags
# =============================================================================

FEATURE_FLAGS = {
    "ai_extraction_enabled": get_bool_env("AI_EXTRACTION_ENABLED", default=True),
}

# =============================================================================
# Logging Configuration
# =============================================================================
# Override base logging for production - more structured, less verbose

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "json": {
            "format": '{"level": "%(levelname)s", "time": "%(asctime)s", "module": "%(module)s", "message": "%(message)s"}',
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# =============================================================================
# Optional: Sentry Error Tracking
# =============================================================================
# Uncomment and configure if using Sentry

# SENTRY_DSN = os.environ.get("SENTRY_DSN")
# if SENTRY_DSN:
#     import sentry_sdk
#     from sentry_sdk.integrations.django import DjangoIntegration
#     from sentry_sdk.integrations.celery import CeleryIntegration
#
#     sentry_sdk.init(
#         dsn=SENTRY_DSN,
#         integrations=[
#             DjangoIntegration(),
#             CeleryIntegration(),
#         ],
#         traces_sample_rate=0.1,
#         send_default_pii=False,
#     )