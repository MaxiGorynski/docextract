"""
==============================================================================
FILE: tasks.py
LOCATION: /docextract/apps/extraction/tasks.py
==============================================================================

PURPOSE:
    Defines Celery tasks for asynchronous document extraction. The main task
    process_extraction_task orchestrates the ExtractionAgent to analyse
    documents and create proposed extractions.

TASKS:
    - process_extraction_task: Main extraction task with idempotency

USAGE:
    from apps.extraction.tasks import process_extraction_task

    # Dispatch task
    task = process_extraction_task.apply_async(
        kwargs={
            'document_id': str(document.id),
            'tenant_id': str(tenant.id),
            'actor_id': str(user.id),
            'trace_id': request.trace_id,
            'idempotency_key': f'extract-{document.id}-{trace_id}',
        },
        task_id=idempotency_key,
    )

    # Check result
    result = task.get(timeout=300)

TASK FLOW:
    1. Validate document exists and belongs to tenant
    2. Create AgentContext with execution parameters
    3. Run ExtractionAgent (creates ProposedExtraction + ProposedFields)
    4. Update document status based on result
    5. Return structured result dict

IDEMPOTENCY:
    - Uses cache-based idempotency via IdempotentTask base class
    - idempotency_key should be unique per extraction attempt
    - Duplicate calls return immediately without re-processing

RETRY POLICY:
    - Max 3 retries with exponential backoff
    - Transient errors (API timeouts) trigger retry
    - Permanent errors (invalid document) fail immediately

PERFORMANCE NOTES:
    - Soft time limit: 5 minutes
    - Hard time limit: 6 minutes
    - Agent execution is the primary time consumer

TESTING:
    - Use CELERY_TASK_ALWAYS_EAGER=True for synchronous testing
    - Mock ExtractionAgent for unit tests
    - Test idempotency with duplicate task dispatch

==============================================================================
"""

from __future__ import annotations

import logging
import time
import uuid as uuid_module
from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.common.tasks.base import IdempotentTask
from apps.documents.models import Document, DocumentStatus
from apps.extraction.agents import AgentContext, ExtractionAgent

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Base exception for extraction errors."""

    pass


class TransientExtractionError(ExtractionError):
    """Temporary error that may succeed on retry."""

    pass


class PermanentExtractionError(ExtractionError):
    """Permanent error that will not succeed on retry."""

    pass


@shared_task(
    bind=True,
    base=IdempotentTask,
    name="apps.extraction.tasks.process_extraction_task",
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
    autoretry_for=(TransientExtractionError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def process_extraction_task(
    self,
    document_id: str,
    tenant_id: str,
    actor_id: str,
    trace_id: str,
    field_types: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """
    Process document extraction asynchronously.

    Orchestrates the ExtractionAgent to analyse a document and create
    a ProposedExtraction with ProposedFields for human review.

    Args:
        document_id: UUID string of document to process
        tenant_id: UUID string of tenant (for data isolation)
        actor_id: ID of actor who triggered extraction
        trace_id: Request correlation ID for distributed tracing
        field_types: Optional list of specific field types to extract
        idempotency_key: Key for idempotency checking (prevents duplicates)

    Returns:
        Dict containing:
        - status: 'success', 'failed', or 'skipped'
        - document_id: The processed document ID
        - proposal_id: UUID of created ProposedExtraction (on success)
        - field_count: Number of fields extracted (on success)
        - overall_confidence: Aggregate confidence score (on success)
        - duration_ms: Processing time in milliseconds
        - run_id: UUID of the agent execution run
        - error: Error message (on failure)

    Raises:
        PermanentExtractionError: Document not found or invalid
        TransientExtractionError: Temporary failure (will retry)
    """
    start_time = time.time()
    run_id = uuid_module.uuid4()

    log_context = {
        "document_id": document_id,
        "tenant_id": tenant_id,
        "trace_id": trace_id,
        "run_id": str(run_id),
        "task_id": self.request.id,
    }

    logger.info(
        f"Starting extraction for document {document_id}",
        extra=log_context,
    )

    # Load and validate document
    try:
        document = Document.objects.get(
            id=document_id,
            tenant_id=tenant_id,
        )
    except Document.DoesNotExist:
        logger.error(
            f"Document not found: {document_id}",
            extra=log_context,
        )
        raise PermanentExtractionError(f"Document not found: {document_id}")

    # Verify document is in correct state
    if document.status not in (DocumentStatus.PROCESSING, DocumentStatus.PENDING):
        logger.warning(
            f"Document in unexpected status: {document.status}",
            extra={**log_context, "document_status": document.status},
        )
        # Allow processing anyway - may be a retry

    # Create agent context
    context = AgentContext(
        tenant_id=uuid_module.UUID(tenant_id),
        document_id=uuid_module.UUID(document_id),
        trace_id=trace_id,
        run_id=run_id,
        field_types=field_types,
    )

    # Run extraction agent
    agent = ExtractionAgent(context)

    try:
        result = agent.run()
    except Exception as exc:
        # Update document status to failed
        _update_document_failed(document, str(exc))

        logger.error(
            f"Agent execution failed: {exc}",
            extra={**log_context, "error": str(exc)},
            exc_info=True,
        )

        # Determine if retryable
        if _is_transient_error(exc):
            raise TransientExtractionError(str(exc)) from exc
        raise PermanentExtractionError(str(exc)) from exc

    # Handle agent failure
    if not result.success:
        _update_document_failed(document, result.error or "Unknown extraction error")

        logger.error(
            f"Extraction failed: {result.error}",
            extra={**log_context, "error": result.error},
        )

        return {
            "status": "failed",
            "document_id": document_id,
            "error": result.error,
            "run_id": str(run_id),
            "duration_ms": _calculate_duration_ms(start_time),
        }

    # Agent succeeded - proposal already created by agent
    proposal = result.proposal

    # Update document status to extracted
    document.status = DocumentStatus.EXTRACTED
    document.extraction_completed_at = timezone.now()
    document.status_message = ""
    document.save(
        update_fields=[
            "status",
            "extraction_completed_at",
            "status_message",
            "updated_at",
        ]
    )

    duration_ms = _calculate_duration_ms(start_time)

    logger.info(
        f"Extraction completed for document {document_id}",
        extra={
            **log_context,
            "proposal_id": str(proposal.id),
            "field_count": proposal.fields.count(),
            "overall_confidence": result.proposal.overall_confidence,
            "duration_ms": duration_ms,
        },
    )

    return {
        "status": "success",
        "document_id": document_id,
        "proposal_id": str(proposal.id),
        "field_count": proposal.fields.count(),
        "overall_confidence": proposal.overall_confidence,
        "duration_ms": duration_ms,
        "run_id": str(run_id),
        "token_usage": result.token_usage,
    }


def _update_document_failed(document: Document, error_message: str) -> None:
    """
    Update document status to failed with error message.

    Args:
        document: Document instance to update
        error_message: Error message to store
    """
    document.status = DocumentStatus.FAILED
    document.status_message = error_message[:1000]  # Truncate long errors
    document.save(update_fields=["status", "status_message", "updated_at"])


def _calculate_duration_ms(start_time: float) -> int:
    """
    Calculate duration in milliseconds from start time.

    Args:
        start_time: Start timestamp from time.time()

    Returns:
        Duration in milliseconds
    """
    return int((time.time() - start_time) * 1000)


def _is_transient_error(exc: Exception) -> bool:
    """
    Determine if an exception is transient (worth retrying).

    Args:
        exc: The exception to check

    Returns:
        True if the error is likely transient
    """
    transient_indicators = [
        "timeout",
        "connection",
        "temporary",
        "rate limit",
        "503",
        "502",
        "504",
        "retry",
    ]

    error_str = str(exc).lower()
    return any(indicator in error_str for indicator in transient_indicators)