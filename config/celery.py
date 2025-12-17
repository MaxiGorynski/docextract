"""
==============================================================================
FILE: celery.py
LOCATION: /docextract/config/celery.py
==============================================================================

PURPOSE:
    Celery application configuration for async task processing. Creates the
    Celery app instance and configures it to use Django settings.

ARCHITECTURE:
    - Celery app is created here and imported in config/__init__.py
    - Tasks are auto-discovered from all INSTALLED_APPS
    - Configuration pulled from Django settings (CELERY_* namespace)

USAGE:
    Start worker:
        celery -A config worker -l info

    Start beat (scheduled tasks):
        celery -A config beat -l info

    In Docker:
        See docker-compose.yml celery service

HOW IT WORKS:
    1. Sets default Django settings module
    2. Creates Celery app named 'docextract'
    3. Loads config from Django settings (CELERY_* prefix)
    4. Auto-discovers tasks.py in all installed apps

TASK DISCOVERY:
    Celery automatically finds tasks in:
    - apps/documents/tasks.py
    - apps/extraction/tasks.py
    - apps/actions/tasks.py
    - Any other app with a tasks.py file

PERFORMANCE NOTES:
    - Worker concurrency controlled by -c flag (default: CPU count)
    - Prefetch multiplier set to 1 in base.py for fair distribution
    - TASK_ACKS_LATE=True ensures tasks aren't lost on worker crash

TESTING:
    For synchronous task testing, set:
        CELERY_TASK_ALWAYS_EAGER = True
        CELERY_TASK_EAGER_PROPAGATES = True

MONITORING:
    - Flower: celery -A config flower
    - Redis CLI: redis-cli llen celery (queue length)

==============================================================================
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("docextract")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing Celery connectivity."""
    print(f"Request: {self.request!r}")