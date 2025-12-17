"""
==============================================================================
FILE: wsgi.py
LOCATION: /docextract/config/wsgi.py
==============================================================================

PURPOSE:
    WSGI (Web Server Gateway Interface) configuration. This is the entry
    point for WSGI-compatible web servers (Gunicorn, uWSGI) to serve Django.

USAGE:
    Gunicorn:
        gunicorn config.wsgi:application --bind 0.0.0.0:8000

    uWSGI:
        uwsgi --module config.wsgi:application

    The 'application' variable is the WSGI callable that servers look for.

PRODUCTION DEPLOYMENT:
    In production, this file is used by Gunicorn (see Dockerfile):
        CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

ENVIRONMENT:
    Defaults to development settings. In production, set:
        DJANGO_SETTINGS_MODULE=config.settings.production

PERFORMANCE NOTES:
    - Gunicorn workers: (2 x CPU cores) + 1 is a good starting point
    - For CPU-bound: use sync workers
    - For I/O-bound: consider gevent or uvicorn (ASGI)

DO NOT MODIFY:
    This file rarely needs changes. Configuration should go in settings.

==============================================================================
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

application = get_wsgi_application()