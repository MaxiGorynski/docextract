"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/config/__init__.py
==============================================================================

PURPOSE:
    Config package initialisation. Imports the Celery app to ensure it's
    loaded when Django starts, enabling the @shared_task decorator and
    automatic task discovery.

WHY THIS MATTERS:
    Django needs to load the Celery app at startup so that:
    1. @shared_task decorator works in app tasks.py files
    2. Celery can auto-discover tasks from INSTALLED_APPS
    3. The app.autodiscover_tasks() call in celery.py functions

USAGE:
    This file is automatically loaded when Python imports the config package.
    No manual intervention needed.

CELERY INTEGRATION:
    The celery_app is exported in __all__ for explicit access:
        from config import celery_app

DO NOT MODIFY:
    Unless adding new package-level exports or initialisation logic.

==============================================================================
"""

from .celery import app as celery_app

__all__ = ("celery_app",)