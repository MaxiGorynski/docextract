"""
==============================================================================
FILE: development.py
LOCATION: /docextract/config/settings/development.py
==============================================================================

PURPOSE:
    Development-specific Django settings. Enables DEBUG mode, uses local
    database, and relaxes security for easier local development.

INHERITS FROM:
    config.settings.base (all settings from base.py)

USAGE:
    export DJANGO_SETTINGS_MODULE=config.settings.development
    python manage.py runserver

    Or in docker-compose.yml:
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.development

ENVIRONMENT VARIABLES (all optional in dev):
    SECRET_KEY      - Django secret key (has insecure default for dev)
    POSTGRES_DB     - Database name (default: docextract)
    POSTGRES_USER   - Database user (default: docextract)
    POSTGRES_PASSWORD - Database password (default: docextract)
    POSTGRES_HOST   - Database host (default: localhost)
    REDIS_URL       - Redis connection URL (default: redis://localhost:6379/0)

SECURITY NOTES:
    - DEBUG=True exposes detailed error pages - NEVER use in production
    - CORS_ALLOW_ALL_ORIGINS=True - open CORS for local frontend dev
    - Default SECRET_KEY is insecure - only for development

TESTING:
    This settings file is suitable for local integration tests.
    For unit tests, consider overriding DATABASE to use SQLite.

==============================================================================
"""

import os
from .base import *  # noqa: F401, F403

DEBUG = True

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-dev-key-do-not-use-in-production-abc123xyz"
)

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
CORS_ALLOW_CREDENTIALS = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "docextract"),
        "USER": os.environ.get("POSTGRES_USER", "docextract"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "docextract"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# CORS - allow all in development
CORS_ALLOW_ALL_ORIGINS = True

# Cache - use Redis
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
    }
}

# Email - console backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Feature flags defaults
FEATURE_FLAGS = {
    "ai_extraction_enabled": True,
}