#!/usr/bin/env python
"""
==============================================================================
FILE: manage.py
LOCATION: /docextract/manage.py (project root)
==============================================================================

PURPOSE:
    Django's command-line utility for administrative tasks. This is the
    entry point for all Django management commands during development.

COMMON COMMANDS:
    python manage.py runserver          - Start development server
    python manage.py migrate            - Apply database migrations
    python manage.py makemigrations     - Create new migrations
    python manage.py createsuperuser    - Create admin user
    python manage.py shell              - Django interactive shell
    python manage.py test               - Run tests
    python manage.py collectstatic      - Collect static files

CUSTOM COMMANDS:
    Apps can define custom commands in:
    apps/<appname>/management/commands/<commandname>.py

ENVIRONMENT:
    Defaults to config.settings.development
    Override with: DJANGO_SETTINGS_MODULE=config.settings.production

DOCKER USAGE:
    docker-compose exec web python manage.py <command>

PRODUCTION NOTE:
    In production, prefer gunicorn over runserver:
        gunicorn config.wsgi:application

DO NOT MODIFY:
    This is a standard Django file. Customization should go in settings
    or custom management commands.

==============================================================================
"""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()