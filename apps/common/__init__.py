"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/common/__init__.py
==============================================================================

PURPOSE:
    Package initialisation for the common app. Contains shared utilities,
    base classes, and middleware used across all other apps.

APP CONTENTS:
    middleware.py  - TraceIDMiddleware for request correlation
    views.py       - health_check endpoint
    models.py      - Base model classes (TimestampMixin, etc.)

DEPENDENCIES:
    This app has no dependencies on other apps in the project.
    Other apps may depend on this one.

==============================================================================
"""

default_app_config = "apps.common.apps.CommonConfig"