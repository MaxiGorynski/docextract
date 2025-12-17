# Celery Tasks

**Async Task Specifications for DocExtract**

This document defines Celery task configurations, idempotency patterns, retry policies, and implementation details.

---

## Table of Contents

1. [Celery Configuration](#celery-configuration)
2. [Task Base Classes](#task-base-classes)
3. [Extraction Task](#extraction-task)
4. [Idempotency Patterns](#idempotency-patterns)
5. [Retry Policies](#retry-policies)
6. [Error Handling](#error-handling)
7. [Monitoring](#monitoring)
8. [Testing](#testing)

---

## Celery Configuration

### Settings

```python
# config/celery.py

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.production')

app = Celery('docextract')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


# config/settings/base.py

CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('REDIS_URL', default='redis://localhost:6379/0')

CELERY_TASK_SERIALISER = 'json'
CELERY_RESULT_SERIALISER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True

# Task execution settings
CELERY_TASK_ACKS_LATE = True  # Acknowledge after task completes
CELERY_TASK_REJECT_ON_WORKER_LOST = True  # Requeue if worker dies
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # One task at a time per worker

# Result expiration
CELERY_RESULT_EXPIRES = 60 * 60 * 24  # 24 hours

# Task time limits
CELERY_TASK_SOFT_TIME_LIMIT = 300  # 5 minutes soft limit
CELERY_TASK_TIME_LIMIT = 360  # 6 minutes hard limit

# Retry settings (defaults, overridden per-task)
CELERY_TASK_DEFAULT_RETRY_DELAY = 60  # 1 minute
CELERY_TASK_MAX_RETRIES = 3
```

### Queue Configuration

```python
# config/celery.py

from kombu import Queue

app.conf.task_queues = [
    Queue('default', routing_key='default'),
    Queue('extraction', routing_key='extraction.#'),
    Queue('high_priority', routing_key='high.#'),
]

app.conf.task_routes = {
    'apps.extraction.tasks.process_extraction_task': {
        'queue': 'extraction',
        'routing_key': 'extraction.process',
    },
    'apps.documents.tasks.*': {
        'queue': 'default',
        'routing_key': 'default',
    },
}
```

---

## Task Base Classes

### IdempotentTask

Base class for tasks that should be idempotent.

```python
# apps/common/tasks/base.py

import logging
from abc import abstractmethod
from celery import Task
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


class IdempotentTask(Task):
    """
    Base task class with idempotency support.
    
    Subclasses must implement:
    - run(): The task logic
    
    Features:
    - Idempotency key checking before execution
    - Automatic retry on transient failures
    - Structured logging with trace context
    - Transaction management
    """
    
    # Override in subclass
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
    
    def __call__(self, *args, **kwargs):
        """
        Wrapper that handles idempotency and logging.
        """
        idempotency_key = kwargs.get('idempotency_key')
        trace_id = kwargs.get('trace_id', 'unknown')
        
        self.log_extra = {
            'trace_id': trace_id,
            'task_id': self.request.id,
            'task_name': self.name,
            'idempotency_key': idempotency_key,
        }
        
        # Check idempotency
        if idempotency_key:
            cache_key = f"task_idempotency:{idempotency_key}"
            
            if cache.get(cache_key):
                logger.info(
                    f"Task skipped (idempotent): {idempotency_key}",
                    extra=self.log_extra
                )
                return {
                    'status': 'skipped',
                    'reason': 'idempotent_duplicate',
                    'idempotency_key': idempotency_key,
                }
            
            # Mark as in-progress (with short TTL in case of crash)
            cache.set(cache_key, 'in_progress', timeout=self.soft_time_limit)
        
        logger.info(
            f"Task started: {self.name}",
            extra=self.log_extra
        )
        
        try:
            result = super().__call__(*args, **kwargs)
            
            # Mark as completed
            if idempotency_key:
                cache.set(cache_key, 'completed', timeout=self.idempotency_ttl)
            
            logger.info(
                f"Task completed: {self.name}",
                extra={**self.log_extra, 'result_status': 'success'}
            )
            
            return result
            
        except self.autoretry_for as exc:
            logger.warning(
                f"Task failed (will retry): {self.name} - {exc}",
                extra={**self.log_extra, 'error': str(exc)},
                exc_info=True
            )
            
            # Clear idempotency on retry
            if idempotency_key:
                cache.delete(cache_key)
            
            raise
            
        except Exception as exc:
            logger.error(
                f"Task failed (no retry): {self.name} - {exc}",
                extra={**self.log_extra, 'error': str(exc)},
                exc_info=True
            )
            
            # Mark as failed
            if idempotency_key:
                cache.set(cache_key, 'failed', timeout=self.idempotency_ttl)
            
            raise
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried."""
        logger.info(
            f"Task retry: {self.name} (attempt {self.request.retries + 1}/{self.max_retries})",
            extra={
                'task_id': task_id,
                'retry_count': self.request.retries,
                'error': str(exc),
            }
        )
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails permanently."""
        logger.error(
            f"Task failed permanently: {self.name}",
            extra={
                'task_id': task_id,
                'error': str(exc),
                'traceback': str(einfo),
            }
        )


class TransactionalTask(IdempotentTask):
    """
    Task that wraps execution in a database transaction.
    
    If the task fails, database changes are rolled back.
    """
    
    abstract = True
    
    def __call__(self, *args, **kwargs):
        with transaction.atomic():
            return super().__call__(*args, **kwargs)
```

---

## Extraction Task

The main extraction task that processes documents.

```python
# apps/extraction/tasks.py

import time
import uuid
from celery import shared_task
from django.utils import timezone

from apps.common.tasks.base import IdempotentTask
from apps.documents.models import Document, DocumentStatus
from apps.extraction.models import (
    ProposedExtraction, ProposedField, ProposalStatus
)
from apps.extraction.agents import ExtractionAgent, AgentContext


@shared_task(
    bind=True,
    base=IdempotentTask,
    name='apps.extraction.tasks.process_extraction_task',
    max_retries=3,
    soft_time_limit=300,
    time_limit=360,
)
def process_extraction_task(
    self,
    document_id: str,
    tenant_id: str,
    actor_id: str,
    trace_id: str,
    field_types: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """
    Process document extraction asynchronously.
    
    This task:
    1. Loads the document
    2. Runs the ExtractionAgent
    3. Creates ProposedExtraction with ProposedFields
    4. Updates document status
    
    Args:
        document_id: UUID of document to process
        tenant_id: UUID of tenant
        actor_id: ID of actor who triggered extraction
        trace_id: Request trace ID for correlation
        field_types: Optional list of specific fields to extract
        idempotency_key: Key for idempotency checking
        
    Returns:
        Dict with extraction results
        
    Raises:
        Document.DoesNotExist: If document not found
        ExtractionError: If extraction fails
    """
    start_time = time.time()
    run_id = uuid.uuid4()
    
    logger = self.get_logger()
    logger.info(
        f"Starting extraction for document {document_id}",
        extra={
            'document_id': document_id,
            'tenant_id': tenant_id,
            'trace_id': trace_id,
            'run_id': str(run_id),
        }
    )
    
    # Load document
    try:
        document = Document.objects.get(
            id=document_id,
            tenant_id=tenant_id,
        )
    except Document.DoesNotExist:
        logger.error(f"Document not found: {document_id}")
        raise
    
    # Create agent context
    context = AgentContext(
        tenant_id=uuid.UUID(tenant_id),
        document_id=uuid.UUID(document_id),
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
        document.status = DocumentStatus.FAILED
        document.status_message = f"Extraction failed: {str(exc)}"
        document.save(update_fields=['status', 'status_message', 'updated_at'])
        raise
    
    if not result.success:
        document.status = DocumentStatus.FAILED
        document.status_message = result.error or "Unknown extraction error"
        document.save(update_fields=['status', 'status_message', 'updated_at'])
        
        return {
            'status': 'failed',
            'document_id': document_id,
            'error': result.error,
            'run_id': str(run_id),
        }
    
    # Calculate processing duration
    duration_ms = int((time.time() - start_time) * 1000)
    
    # Create ProposedExtraction
    proposal = ProposedExtraction.objects.create(
        tenant_id=tenant_id,
        document=document,
        status=ProposalStatus.PENDING,
        agent_run_id=run_id,
        model_version=result.model_version,
        prompt_hash=result.prompt_hash,
        overall_confidence=result.overall_confidence,
        token_usage=result.token_usage or {},
        processing_duration_ms=duration_ms,
    )
    
    # Create ProposedFields
    for field_data in result.fields:
        ProposedField.objects.create(
            extraction=proposal,
            field_type=field_data['field_type'],
            field_name=field_data['field_name'],
            value=field_data['value'],
            normalized_value=field_data.get('normalized_value'),
            source_text=field_data['source_text'],
            source_page=field_data.get('source_page'),
            source_location=field_data.get('source_location'),
            confidence=field_data['confidence'],
            confidence_reason=field_data.get('confidence_reason', ''),
            validation_status='valid',
        )
    
    # Update document status
    document.status = DocumentStatus.EXTRACTED
    document.extraction_completed_at = timezone.now()
    document.save(update_fields=[
        'status', 'extraction_completed_at', 'updated_at'
    ])
    
    logger.info(
        f"Extraction completed for document {document_id}",
        extra={
            'document_id': document_id,
            'proposal_id': str(proposal.id),
            'field_count': len(result.fields),
            'duration_ms': duration_ms,
            'overall_confidence': result.overall_confidence,
        }
    )
    
    return {
        'status': 'success',
        'document_id': document_id,
        'proposal_id': str(proposal.id),
        'field_count': len(result.fields),
        'overall_confidence': result.overall_confidence,
        'duration_ms': duration_ms,
        'run_id': str(run_id),
    }
```

---

## Idempotency Patterns

### Why Idempotency?

Celery tasks can be executed multiple times due to:
- Worker crashes mid-execution
- Network timeouts causing retry
- Explicit retry on failure
- Duplicate task dispatch

Idempotency ensures the same task produces the same result regardless of execution count.

### Implementation Strategies

#### 1. Idempotency Key in Cache

```python
def check_idempotency(key: str) -> bool:
    """Check if task already processed."""
    return cache.get(f"task:{key}") is not None

def mark_idempotency(key: str, result: dict, ttl: int = 86400):
    """Mark task as processed."""
    cache.set(f"task:{key}", result, timeout=ttl)
```

#### 2. Database-Level Idempotency

For critical operations, use database constraints:

```python
class ProposedExtraction(models.Model):
    # Add unique constraint on agent_run_id
    agent_run_id = models.UUIDField(unique=True)
```

Then handle `IntegrityError`:

```python
from django.db import IntegrityError

try:
    proposal = ProposedExtraction.objects.create(
        agent_run_id=run_id,
        ...
    )
except IntegrityError:
    # Already exists, fetch existing
    proposal = ProposedExtraction.objects.get(agent_run_id=run_id)
    return {'status': 'duplicate', 'proposal_id': str(proposal.id)}
```

#### 3. Task ID as Idempotency Key

Use Celery's task ID for idempotency:

```python
# When dispatching
task = process_extraction_task.apply_async(
    kwargs={...},
    task_id=f"extract-{document_id}-{uuid.uuid4()}",
)

# In task, check if already processed
existing = TaskResult.objects.filter(task_id=self.request.id).first()
if existing:
    return existing.result
```

---

## Retry Policies

### Exponential Backoff

```python
@shared_task(
    bind=True,
    autoretry_for=(TransientError,),
    retry_backoff=True,        # Enable exponential backoff
    retry_backoff_max=600,     # Max 10 minutes between retries
    retry_jitter=True,         # Add randomness to prevent thundering herd
    max_retries=5,
)
def my_task(self):
    # Retry delays: ~1s, ~2s, ~4s, ~8s, ~16s (with jitter)
    pass
```

### Custom Retry Logic

```python
@shared_task(bind=True, max_retries=3)
def extraction_task(self, document_id: str):
    try:
        result = call_external_api()
    except RateLimitError as exc:
        # Retry after rate limit window
        retry_after = exc.retry_after or 60
        raise self.retry(exc=exc, countdown=retry_after)
    except TransientError as exc:
        # Exponential backoff
        raise self.retry(
            exc=exc,
            countdown=2 ** self.request.retries * 10,  # 10s, 20s, 40s
        )
    except PermanentError:
        # Don't retry
        raise
```

### Error Classification

```python
# apps/common/exceptions.py

class ExtractionError(Exception):
    """Base extraction error."""
    pass

class TransientExtractionError(ExtractionError):
    """Temporary error, retry may succeed."""
    pass

class PermanentExtractionError(ExtractionError):
    """Permanent error, retry will not help."""
    pass

class RateLimitError(TransientExtractionError):
    """API rate limit hit."""
    def __init__(self, retry_after: int = None):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")
```

---

## Error Handling

### Task Failure Flow

```
Task Execution
     │
     ├─► Success → Return result
     │
     ├─► TransientError → Retry (if retries remaining)
     │                        │
     │                        ├─► Success → Return result
     │                        │
     │                        └─► Max retries → Mark as failed
     │
     └─► PermanentError → Mark as failed immediately
```

### Failure Callbacks

```python
@shared_task(bind=True)
def process_extraction_task(self, document_id: str, **kwargs):
    pass

@shared_task
def handle_extraction_failure(request, exc, traceback, document_id: str, **kwargs):
    """Called when extraction task fails permanently."""
    logger.error(
        f"Extraction failed permanently for {document_id}",
        extra={
            'document_id': document_id,
            'error': str(exc),
            'task_id': request.id,
        }
    )
    
    # Update document status
    Document.objects.filter(id=document_id).update(
        status=DocumentStatus.FAILED,
        status_message=f"Extraction failed: {str(exc)}",
    )
    
    # Optionally notify via webhook/email
    notify_extraction_failure(document_id, str(exc))

# Register callback
process_extraction_task.link_error(handle_extraction_failure.s())
```

### Dead Letter Queue Pattern

```python
@shared_task(bind=True, max_retries=3)
def process_extraction_task(self, document_id: str, **kwargs):
    try:
        return do_extraction(document_id)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # Send to dead letter queue
            send_to_dlq.delay(
                task_name=self.name,
                task_id=self.request.id,
                args=[document_id],
                kwargs=kwargs,
                error=str(exc),
            )
        raise

@shared_task
def send_to_dlq(task_name: str, task_id: str, args: list, kwargs: dict, error: str):
    """Store failed task for manual review."""
    FailedTask.objects.create(
        task_name=task_name,
        task_id=task_id,
        args=args,
        kwargs=kwargs,
        error=error,
    )
```

---

## Monitoring

### Task Metrics

Key metrics to track:

| Metric | Type | Description |
|--------|------|-------------|
| `celery_task_started_total` | Counter | Tasks started |
| `celery_task_succeeded_total` | Counter | Tasks completed successfully |
| `celery_task_failed_total` | Counter | Tasks failed permanently |
| `celery_task_retried_total` | Counter | Tasks retried |
| `celery_task_duration_seconds` | Histogram | Task execution time |
| `celery_queue_length` | Gauge | Tasks waiting in queue |

### Logging

Structured log format:

```json
{
    "timestamp": "2024-01-15T10:30:00Z",
    "level": "INFO",
    "message": "Task completed",
    "task_name": "apps.extraction.tasks.process_extraction_task",
    "task_id": "abc-123",
    "trace_id": "req-xyz",
    "document_id": "doc-456",
    "duration_ms": 4523,
    "status": "success"
}
```

### Health Check

```python
# apps/common/tasks/health.py

from celery import shared_task

@shared_task
def health_check():
    """Simple task to verify Celery is working."""
    return {'status': 'ok', 'timestamp': timezone.now().isoformat()}

# Usage: Check worker is responsive
result = health_check.apply_async()
result.get(timeout=10)  # Raises if worker unresponsive
```

---

## Testing

### Unit Testing Tasks

```python
# apps/extraction/tests/test_tasks.py

import pytest
from unittest.mock import Mock, patch
from apps.extraction.tasks import process_extraction_task

@pytest.fixture
def mock_agent():
    with patch('apps.extraction.tasks.ExtractionAgent') as mock:
        agent_instance = Mock()
        agent_instance.run.return_value = Mock(
            success=True,
            fields=[
                {
                    'field_type': 'parties',
                    'field_name': 'Contract Parties',
                    'value': 'Acme Corp and Beta LLC',
                    'source_text': 'Agreement between...',
                    'confidence': 0.95,
                }
            ],
            overall_confidence=0.95,
            model_version='gpt-4',
            prompt_hash='abc123',
            token_usage={'input': 100, 'output': 50},
        )
        mock.return_value = agent_instance
        yield mock

@pytest.mark.django_db
class TestExtractionTask:
    def test_successful_extraction(
        self, document, mock_agent
    ):
        result = process_extraction_task(
            document_id=str(document.id),
            tenant_id=str(document.tenant_id),
            actor_id='1',
            trace_id='test-trace',
        )
        
        assert result['status'] == 'success'
        assert result['field_count'] == 1
        
        # Verify proposal created
        document.refresh_from_db()
        assert document.status == 'extracted'
        assert document.proposed_extractions.count() == 1
    
    def test_idempotency(self, document, mock_agent):
        kwargs = {
            'document_id': str(document.id),
            'tenant_id': str(document.tenant_id),
            'actor_id': '1',
            'trace_id': 'test-trace',
            'idempotency_key': 'test-key-123',
        }
        
        result1 = process_extraction_task(**kwargs)
        result2 = process_extraction_task(**kwargs)
        
        # Second call should be skipped
        assert result1['status'] == 'success'
        assert result2['status'] == 'skipped'
        
        # Only one proposal created
        assert document.proposed_extractions.count() == 1
    
    def test_failure_updates_document_status(
        self, document, mock_agent
    ):
        mock_agent.return_value.run.side_effect = Exception("API error")
        
        with pytest.raises(Exception):
            process_extraction_task(
                document_id=str(document.id),
                tenant_id=str(document.tenant_id),
                actor_id='1',
                trace_id='test-trace',
            )
        
        document.refresh_from_db()
        assert document.status == 'failed'
        assert 'API error' in document.status_message
```

### Integration Testing with Celery

```python
# apps/extraction/tests/test_tasks_integration.py

import pytest
from celery.contrib.testing.worker import start_worker
from config.celery import app

@pytest.fixture(scope='session')
def celery_worker():
    """Start a Celery worker for integration tests."""
    with start_worker(app, perform_ping_check=False) as worker:
        yield worker

@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
class TestExtractionTaskIntegration:
    def test_async_extraction(self, document, celery_worker):
        task = process_extraction_task.apply_async(
            kwargs={
                'document_id': str(document.id),
                'tenant_id': str(document.tenant_id),
                'actor_id': '1',
                'trace_id': 'test-trace',
            }
        )
        
        result = task.get(timeout=30)
        
        assert result['status'] == 'success'
        document.refresh_from_db()
        assert document.status == 'extracted'
```

### Testing Retry Behavior

```python
@pytest.mark.django_db
class TestExtractionTaskRetry:
    def test_retries_on_transient_error(self, document, mock_agent):
        # Fail twice, succeed on third try
        mock_agent.return_value.run.side_effect = [
            TransientExtractionError("API timeout"),
            TransientExtractionError("API timeout"),
            Mock(success=True, fields=[], overall_confidence=0.5, ...),
        ]
        
        # Use eager mode to test retry logic
        with patch.object(
            process_extraction_task, 'retry',
            side_effect=process_extraction_task.retry
        ) as mock_retry:
            result = process_extraction_task.apply(
                kwargs={
                    'document_id': str(document.id),
                    'tenant_id': str(document.tenant_id),
                    'actor_id': '1',
                    'trace_id': 'test-trace',
                }
            ).get()
        
        assert mock_retry.call_count == 2
        assert result['status'] == 'success'
```