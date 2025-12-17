"""
==============================================================================
FILE: apps.py
LOCATION: /docextract/apps/common/apps.py
==============================================================================

PURPOSE:
    Django app configuration for the common app.

==============================================================================
"""

from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Django app configuration for common utilities."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    verbose_name = "Common Utilities"