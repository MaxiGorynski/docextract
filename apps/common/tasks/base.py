"""
==============================================================================
FILE: base.py
LOCATION: /docextract/apps/common/tasks/base.py
==============================================================================

PURPOSE:
    Defines base Celery task classes with idempotency support, structured
    logging, and automatic retry handling.

CLASSES:
    - IdempotentTask: Base task with idempotency checking via cache

USAGE:
    from celery import shared_task
    from apps.common.tasks.base import IdempotentTask

    @shared_task(bind=True, base=IdempotentTask)
    def my_task(self, document_id: str, idempotency_key: str = None):
        # Task logic here
        pass

FEATURES:
    - Idempotency key checking before execution (cache-based)
    - Automatic retry on transient failures with exponential backoff
    - Structured logging with trace context
    - Configurable time limits

DESIGN PRINCIPLES:
    - Tasks should be idempotent: same input produces same result
    - Transient failures trigger retry; permanent failures fail fast
    - All execution is logged for debugging and monitoring

PERFORMANCE NOTES:
    - Idempotency check uses Redis cache (fast O(1) lookup)
    - Short TTL during execution prevents stuck tasks
    - Final TTL of 24 hours prevents duplicate processing

TESTING:
    - Test idempotency by calling task twice with same key
    - Test retry by simulating transient failures
    - Use CELERY_TASK_ALWAYS_EAGER=True for synchronous testing

==============================================================================
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Task
from django.core.cache import cache

logger = logging.getLogger(__name__)


class IdempotentTask(Task):
    """
    Base task class with idempotency support.

    Provides:
    - Idempotency key checking before execution
    - Automatic retry on transient failures
    - Structured logging with trace context
    - Configurable time limits

    Subclasses inherit these features automatically when used
    as the base class for @shared_task.

    Idempotency Flow:
    1. Check cache for idempotency_key
    2. If found → skip execution, return cached status
    3. If not found → mark as 'in_progress' with short TTL
    4. Execute task
    5. On success → mark as 'completed' with long TTL
    6. On retry → clear cache to allow re-execution
    7. On permanent failure → mark as 'failed'

    Attributes:
        autoretry_for: Tuple of exception types to retry
        retry_backoff: Enable exponential backoff
        retry_backoff_max: Maximum backoff delay in seconds
        retry_jitter: Add randomness to prevent thundering herd
        max_retries: Maximum retry attempts
        soft_time_limit: Soft time limit (raises SoftTimeLimitExceeded)
        time_limit: Hard time limit (kills worker)
        idempotency_ttl: How long to remember completed tasks
    """

    # Mark as abstract so Celery doesn't register this directly
    abstract = True

    # Retry configuration
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600  # 10 minutes max backoff
    retry_jitter = True
    max_retries = 3

    # Time limits
    soft_time_limit = 300  # 5 minutes
    time_limit = 360  # 6 minutes

    # Idempotency
    idempotency_ttl = 60 * 60 * 24  # 24 hours

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Wrapper that handles idempotency and logging.

        Intercepts task execution to:
        1. Check idempotency before running
        2. Log task start/completion/failure
        3. Update idempotency cache based on outcome
        """
        idempotency_key = kwargs.get("idempotency_key")
        trace_id = kwargs.get("trace_id", "unknown")

        # Build logging context
        self.log_extra = {
            "trace_id": trace_id,
            "task_id": self.request.id,
            "task_name": self.name,
            "idempotency_key": idempotency_key,
        }

        # Check idempotency
        if idempotency_key:
            cache_key = f"task_idempotency:{idempotency_key}"
            cached_status = cache.get(cache_key)

            if cached_status:
                logger.info(
                    f"Task skipped (idempotent): {idempotency_key} "
                    f"[status={cached_status}]",
                    extra=self.log_extra,
                )
                return {
                    "status": "skipped",
                    "reason": "idempotent_duplicate",
                    "idempotency_key": idempotency_key,
                    "previous_status": cached_status,
                }

            # Mark as in-progress with short TTL (in case of crash)
            cache.set(cache_key, "in_progress", timeout=self.soft_time_limit)

        logger.info(
            f"Task started: {self.name}",
            extra=self.log_extra,
        )

        try:
            # Execute the actual task
            result = super().__call__(*args, **kwargs)

            # Mark as completed
            if idempotency_key:
                cache.set(cache_key, "completed", timeout=self.idempotency_ttl)

            logger.info(
                f"Task completed: {self.name}",
                extra={**self.log_extra, "result_status": "success"},
            )

            return result

        except self.autoretry_for as exc:
            # Will be retried
            logger.warning(
                f"Task failed (will retry): {self.name} - {exc}",
                extra={**self.log_extra, "error": str(exc)},
                exc_info=True,
            )

            # Clear idempotency to allow retry
            if idempotency_key:
                cache.delete(cache_key)

            raise

        except Exception as exc:
            # Permanent failure (not in autoretry_for or max retries exceeded)
            logger.error(
                f"Task failed (no retry): {self.name} - {exc}",
                extra={**self.log_extra, "error": str(exc)},
                exc_info=True,
            )

            # Mark as failed
            if idempotency_key:
                cache.set(cache_key, "failed", timeout=self.idempotency_ttl)

            raise

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        """
        Called when task is retried.

        Logs retry attempt with context for debugging.
        """
        logger.info(
            f"Task retry: {self.name} "
            f"(attempt {self.request.retries + 1}/{self.max_retries})",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "retry_count": self.request.retries,
                "max_retries": self.max_retries,
                "error": str(exc),
                "trace_id": kwargs.get("trace_id", "unknown"),
            },
        )

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        """
        Called when task fails permanently.

        Logs failure with full context and traceback.
        """
        logger.error(
            f"Task failed permanently: {self.name}",
            extra={
                "task_id": task_id,
                "task_name": self.name,
                "error": str(exc),
                "traceback": str(einfo),
                "trace_id": kwargs.get("trace_id", "unknown"),
                "args": args,
            },
        )

    def on_success(
        self,
        retval: Any,
        task_id: str,
        args: tuple,
        kwargs: dict,
    ) -> None:
        """
        Called when task completes successfully.

        Can be overridden for post-success hooks.
        """
        pass