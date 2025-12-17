"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/common/tasks/__init__.py
==============================================================================

PURPOSE:
    Package marker for common tasks module. Exports base task classes
    for Celery task implementation.

EXPORTS:
    - IdempotentTask: Base task with idempotency support

USAGE:
    from apps.common.tasks import IdempotentTask

==============================================================================
"""

from apps.common.tasks.base import IdempotentTask

__all__ = [
    "IdempotentTask",
]