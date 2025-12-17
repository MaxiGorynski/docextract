# Service Layer

**Services, Selectors, and Actions — Interface Contracts for DocExtract**

This document defines the domain layer components: their responsibilities, interfaces, and implementation patterns.

---

## Table of Contents

1. [Layer Overview](#layer-overview)
2. [Services](#services)
3. [Selectors](#selectors)
4. [Actions](#actions)
5. [Agents](#agents)
6. [Functions](#functions)
7. [Error Handling](#error-handling)
8. [Testing Patterns](#testing-patterns)

---

## Layer Overview

The domain layer implements "thin web layer, rich domain layer" architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Views (Thin)                             │
│  • Auth + validation + response formatting                       │
│  • NO business logic                                            │
└─────────────────────────────┬───────────────────────────────────┘
                              │ calls
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Domain Layer (Rich)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │  Services   │  │  Selectors  │  │   Actions   │             │
│  │ (orchestrate│  │ (read/query)│  │ (audit +    │             │
│  │  operations)│  │             │  │  mutate)    │             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                │                │                     │
│         │    ┌───────────┴────────────────┘                    │
│         │    │                                                  │
│         ▼    ▼                                                  │
│  ┌─────────────────────────────────────────┐                   │
│  │  Agents (AI orchestration)              │                   │
│  │  Functions (AI tools)                   │                   │
│  └─────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer (Models)                         │
└─────────────────────────────────────────────────────────────────┘
```

### Responsibilities

| Component | Responsibility | Side Effects |
|-----------|---------------|--------------|
| **Service** | Orchestrate operations, enforce business rules, manage transactions | May call Actions |
| **Selector** | Query data, build complex filters, return DTOs | None (read-only) |
| **Action** | Auditable state transitions with pre/post capture | Yes (logged) |
| **Agent** | Orchestrate AI workflows, compose Functions | Produces proposals only |
| **Function** | Discrete AI capability (extraction, validation) | None (deterministic) |

---

## Services

Services are the primary entry point for business operations. They orchestrate Selectors, Actions, and Agents.

### Design Principles

1. **Stateless** — All state from parameters or database
2. **Transaction-aware** — Use `@transaction.atomic` where needed
3. **Composable** — Services may call other Services
4. **Testable** — Dependencies injectable, no side effects in constructors

### Base Service Pattern

```python
# apps/common/services/base.py

from dataclasses import dataclass
from typing import TypeVar, Generic
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class ServiceResult(Generic[T]):
    """Standard service return wrapper."""
    success: bool
    data: T | None = None
    error: str | None = None
    error_code: str | None = None
    
    @classmethod
    def ok(cls, data: T) -> 'ServiceResult[T]':
        return cls(success=True, data=data)
    
    @classmethod
    def fail(cls, error: str, error_code: str = 'error') -> 'ServiceResult[T]':
        return cls(success=False, error=error, error_code=error_code)


class BaseService:
    """Base class for services with common utilities."""
    
    def __init__(self, context: 'ServiceContext'):
        self.context = context
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def log_operation(self, operation: str, **kwargs):
        """Structured logging with context."""
        self.logger.info(
            f"{operation}",
            extra={
                'trace_id': self.context.trace_id,
                'actor_id': self.context.actor_id,
                'tenant_id': str(self.context.tenant_id),
                **kwargs,
            }
        )


@dataclass
class ServiceContext:
    """Context passed to all service operations."""
    tenant_id: UUID
    actor_id: str
    actor_type: str  # 'user', 'system', 'celery_task'
    trace_id: str
    feature_flags: dict[str, bool]
```

---

### DocumentService

Handles document lifecycle operations.

```python
# apps/documents/services.py

from django.db import transaction
from apps.common.services.base import BaseService, ServiceResult, ServiceContext
from apps.documents.models import Document, DocumentStatus
from apps.documents.selectors import DocumentSelector
from apps.actions.actions import DocumentUploadAction
from apps.extraction.tasks import process_extraction_task


class DocumentService(BaseService):
    """
    Service for document operations.
    
    Responsibilities:
    - Document upload with validation
    - Triggering extraction workflows
    - Document lifecycle management
    """
    
    def __init__(self, context: ServiceContext):
        super().__init__(context)
        self.selector = DocumentSelector(context.tenant_id)
    
    @transaction.atomic
    def create_document(
        self,
        file,
        original_filename: str,
        title: str | None = None,
        metadata: dict | None = None,
        auto_extract: bool = False,
    ) -> ServiceResult[Document]:
        """
        Create a new document from uploaded file.
        
        Args:
            file: Uploaded file object
            original_filename: Original filename from client
            title: Optional title (defaults to filename)
            metadata: Optional additional metadata
            auto_extract: Trigger extraction immediately
            
        Returns:
            ServiceResult containing created Document or error
            
        Raises:
            None - all errors returned via ServiceResult
        """
        self.log_operation('create_document', filename=original_filename)
        
        # Validate file type
        file_type = self._detect_file_type(file)
        if file_type not in ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            return ServiceResult.fail(
                f"Unsupported file type: {file_type}",
                error_code='invalid_file_type'
            )
        
        # Validate file size
        if file.size > 50 * 1024 * 1024:  # 50MB
            return ServiceResult.fail(
                "File exceeds maximum size of 50MB",
                error_code='file_too_large'
            )
        
        # Calculate hash for deduplication
        file_hash = self._calculate_hash(file)
        
        # Check for duplicates
        existing = self.selector.get_by_hash(file_hash)
        if existing:
            return ServiceResult.fail(
                f"Document with same content already exists: {existing.id}",
                error_code='duplicate_file'
            )
        
        # Create document
        document = Document.objects.create(
            tenant_id=self.context.tenant_id,
            file=file,
            original_filename=original_filename,
            file_type=file_type,
            file_size_bytes=file.size,
            file_hash=file_hash,
            title=title or original_filename,
            metadata=metadata or {},
            uploaded_by_id=self.context.actor_id if self.context.actor_type == 'user' else None,
            status=DocumentStatus.PENDING,
        )
        
        # Log action
        DocumentUploadAction(
            document=document,
            actor_id=self.context.actor_id,
            actor_type=self.context.actor_type,
            trace_id=self.context.trace_id,
        ).execute()
        
        # Optionally trigger extraction
        if auto_extract and self.context.feature_flags.get('ai_extraction_enabled'):
            self.trigger_extraction(document.id)
        
        return ServiceResult.ok(document)
    
    def trigger_extraction(
        self,
        document_id: UUID,
        force: bool = False,
        field_types: list[str] | None = None,
    ) -> ServiceResult[str]:
        """
        Trigger async extraction for a document.
        
        Args:
            document_id: Document to extract
            force: Re-extract even if extraction exists
            field_types: Specific fields to extract (None = all)
            
        Returns:
            ServiceResult containing Celery task ID
        """
        self.log_operation('trigger_extraction', document_id=str(document_id))
        
        # Check feature flag
        if not self.context.feature_flags.get('ai_extraction_enabled'):
            return ServiceResult.fail(
                "AI extraction is currently disabled",
                error_code='feature_disabled'
            )
        
        # Get document
        document = self.selector.get_by_id(document_id)
        if not document:
            return ServiceResult.fail(
                f"Document not found: {document_id}",
                error_code='not_found'
            )
        
        # Check if already processing
        if document.status == DocumentStatus.PROCESSING:
            return ServiceResult.fail(
                "Document extraction already in progress",
                error_code='extraction_in_progress'
            )
        
        # Check for existing extraction (unless force)
        if not force and document.status == DocumentStatus.EXTRACTED:
            existing = self.selector.get_latest_extraction(document_id)
            if existing and existing.status in ['pending', 'committed']:
                return ServiceResult.fail(
                    "Extraction already exists. Use force=true to re-extract.",
                    error_code='extraction_exists'
                )
        
        # Generate idempotency key
        idempotency_key = f"extract-{document_id}-{self.context.trace_id}"
        
        # Update document status
        document.status = DocumentStatus.PROCESSING
        document.extraction_started_at = timezone.now()
        document.save(update_fields=['status', 'extraction_started_at', 'updated_at'])
        
        # Dispatch Celery task
        task = process_extraction_task.apply_async(
            kwargs={
                'document_id': str(document_id),
                'tenant_id': str(self.context.tenant_id),
                'actor_id': self.context.actor_id,
                'trace_id': self.context.trace_id,
                'field_types': field_types,
                'idempotency_key': idempotency_key,
            },
            task_id=idempotency_key,
        )
        
        return ServiceResult.ok(task.id)
    
    def _detect_file_type(self, file) -> str:
        """Detect MIME type from file content."""
        import magic
        file.seek(0)
        mime = magic.from_buffer(file.read(2048), mime=True)
        file.seek(0)
        return mime
    
    def _calculate_hash(self, file) -> str:
        """Calculate SHA-256 hash of file."""
        import hashlib
        hasher = hashlib.sha256()
        file.seek(0)
        for chunk in file.chunks():
            hasher.update(chunk)
        file.seek(0)
        return hasher.hexdigest()
```

---

### ExtractionService

Handles extraction lifecycle and commit/reject operations.

```python
# apps/extraction/services.py

from django.db import transaction
from apps.common.services.base import BaseService, ServiceResult, ServiceContext
from apps.extraction.models import ProposedExtraction, ProposalStatus
from apps.extraction.selectors import ExtractionSelector
from apps.extraction.actions import CommitExtractionAction, RejectExtractionAction


class ExtractionService(BaseService):
    """
    Service for extraction operations.
    
    Responsibilities:
    - Commit/reject proposed extractions
    - Field override handling
    - Extraction lifecycle management
    """
    
    def __init__(self, context: ServiceContext):
        super().__init__(context)
        self.selector = ExtractionSelector(context.tenant_id)
    
    @transaction.atomic
    def commit_extraction(
        self,
        extraction_id: UUID,
        review_notes: str = '',
        field_overrides: dict | None = None,
    ) -> ServiceResult[dict]:
        """
        Commit a proposed extraction to canonical storage.
        
        This is the "commit" phase of the two-phase pattern.
        Creates ExtractedField records and logs an Action.
        
        Args:
            extraction_id: ProposedExtraction to commit
            review_notes: Optional reviewer comments
            field_overrides: Dict of {field_id: {value, normalized_value}}
            
        Returns:
            ServiceResult with action details
        """
        self.log_operation('commit_extraction', extraction_id=str(extraction_id))
        
        # Get extraction
        extraction = self.selector.get_by_id(extraction_id)
        if not extraction:
            return ServiceResult.fail(
                f"Extraction not found: {extraction_id}",
                error_code='not_found'
            )
        
        # Validate status
        if extraction.status == ProposalStatus.COMMITTED:
            return ServiceResult.fail(
                "Extraction already committed",
                error_code='already_committed'
            )
        
        if extraction.status == ProposalStatus.REJECTED:
            return ServiceResult.fail(
                "Cannot commit rejected extraction",
                error_code='already_rejected'
            )
        
        # Validate field overrides
        if field_overrides:
            validation_result = self._validate_field_overrides(
                extraction, field_overrides
            )
            if not validation_result.success:
                return validation_result
        
        # Execute commit action
        action = CommitExtractionAction(
            extraction=extraction,
            actor_id=self.context.actor_id,
            actor_type=self.context.actor_type,
            trace_id=self.context.trace_id,
            review_notes=review_notes,
            field_overrides=field_overrides,
        )
        
        result = action.execute()
        
        return ServiceResult.ok({
            'extraction_id': extraction_id,
            'action': result,
            'committed_fields': len(extraction.fields.all()),
        })
    
    @transaction.atomic
    def reject_extraction(
        self,
        extraction_id: UUID,
        reason: str,
        request_re_extraction: bool = False,
    ) -> ServiceResult[dict]:
        """
        Reject a proposed extraction.
        
        Args:
            extraction_id: ProposedExtraction to reject
            reason: Rejection reason
            request_re_extraction: Trigger new extraction
            
        Returns:
            ServiceResult with action details
        """
        self.log_operation('reject_extraction', extraction_id=str(extraction_id))
        
        extraction = self.selector.get_by_id(extraction_id)
        if not extraction:
            return ServiceResult.fail(
                f"Extraction not found: {extraction_id}",
                error_code='not_found'
            )
        
        if extraction.status != ProposalStatus.PENDING:
            return ServiceResult.fail(
                f"Cannot reject extraction in status: {extraction.status}",
                error_code='invalid_status'
            )
        
        # Execute reject action
        action = RejectExtractionAction(
            extraction=extraction,
            actor_id=self.context.actor_id,
            actor_type=self.context.actor_type,
            trace_id=self.context.trace_id,
            reason=reason,
        )
        
        result = action.execute()
        
        # Optionally trigger re-extraction
        new_task_id = None
        if request_re_extraction:
            from apps.documents.services import DocumentService
            doc_service = DocumentService(self.context)
            re_extract_result = doc_service.trigger_extraction(
                extraction.document_id,
                force=True
            )
            if re_extract_result.success:
                new_task_id = re_extract_result.data
        
        return ServiceResult.ok({
            'extraction_id': extraction_id,
            'action': result,
            're_extraction_triggered': request_re_extraction,
            'new_task_id': new_task_id,
        })
    
    def _validate_field_overrides(
        self,
        extraction: ProposedExtraction,
        overrides: dict
    ) -> ServiceResult:
        """Validate field override data."""
        field_ids = set(str(f.id) for f in extraction.fields.all())
        
        for field_id in overrides.keys():
            if field_id not in field_ids:
                return ServiceResult.fail(
                    f"Invalid field ID in overrides: {field_id}",
                    error_code='validation_failed'
                )
        
        return ServiceResult.ok(None)
```

---

## Selectors

Selectors encapsulate read operations. They return data without side effects.

### Design Principles

1. **Read-only** — Never mutate state
2. **Tenant-scoped** — Always filter by tenant
3. **Composable** — Methods can be chained logically
4. **Cacheable** — Results can be cached (selectors don't mutate)

### DocumentSelector

```python
# apps/documents/selectors.py

from django.db.models import QuerySet, Count, Q, Prefetch
from apps.documents.models import Document, DocumentStatus
from apps.extraction.models import ExtractedField


class DocumentSelector:
    """
    Selector for document queries.
    
    All queries are automatically scoped to tenant.
    """
    
    def __init__(self, tenant_id: UUID):
        self.tenant_id = tenant_id
    
    def _base_queryset(self) -> QuerySet[Document]:
        """Base queryset with tenant filter."""
        return Document.objects.filter(tenant_id=self.tenant_id)
    
    def get_by_id(self, document_id: UUID) -> Document | None:
        """Get document by ID within tenant."""
        return self._base_queryset().filter(id=document_id).first()
    
    def get_by_hash(self, file_hash: str) -> Document | None:
        """Get document by file hash (for deduplication)."""
        return self._base_queryset().filter(file_hash=file_hash).first()
    
    def list_documents(
        self,
        status: DocumentStatus | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        search: str | None = None,
        ordering: str = '-created_at',
    ) -> QuerySet[Document]:
        """
        List documents with filtering.
        
        Args:
            status: Filter by status
            created_after: Filter by creation date
            created_before: Filter by creation date
            search: Search in title and filename
            ordering: Sort field (prefix - for descending)
            
        Returns:
            QuerySet of documents
        """
        qs = self._base_queryset()
        
        if status:
            qs = qs.filter(status=status)
        
        if created_after:
            qs = qs.filter(created_at__gte=created_after)
        
        if created_before:
            qs = qs.filter(created_at__lte=created_before)
        
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(original_filename__icontains=search)
            )
        
        return qs.order_by(ordering)
    
    def get_with_fields(self, document_id: UUID) -> Document | None:
        """Get document with prefetched active extracted fields."""
        return (
            self._base_queryset()
            .filter(id=document_id)
            .prefetch_related(
                Prefetch(
                    'extracted_fields',
                    queryset=ExtractedField.objects.filter(is_active=True),
                    to_attr='active_fields'
                )
            )
            .first()
        )
    
    def get_latest_extraction(self, document_id: UUID):
        """Get most recent extraction for document."""
        from apps.extraction.models import ProposedExtraction
        return (
            ProposedExtraction.objects
            .filter(document_id=document_id, tenant_id=self.tenant_id)
            .order_by('-created_at')
            .first()
        )
    
    def get_documents_pending_extraction(self) -> QuerySet[Document]:
        """Get documents awaiting extraction."""
        return self._base_queryset().filter(status=DocumentStatus.PENDING)
    
    def count_by_status(self) -> dict[str, int]:
        """Count documents by status."""
        return dict(
            self._base_queryset()
            .values('status')
            .annotate(count=Count('id'))
            .values_list('status', 'count')
        )
```

---

## Actions

Actions are auditable state transitions. Every mutation to domain state goes through an Action.

### Design Principles

1. **Capture pre-state** — Before any mutation
2. **Atomic execution** — All-or-nothing within transaction
3. **Capture post-state** — After mutation completes
4. **Immutable log** — Action records never updated
5. **Reversible** — Implement `rollback()` for reversible actions

### Base Action Pattern

```python
# apps/actions/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from django.db import transaction
from apps.actions.models import Action, ActionType, ActionStatus


@dataclass
class ActionResult:
    """Result of action execution."""
    action_id: UUID
    action_type: str
    status: str
    is_reversible: bool


class BaseAction(ABC):
    """
    Base class for auditable actions.
    
    Subclasses must implement:
    - action_type: ActionType enum value
    - _capture_pre_state(): Capture state before mutation
    - _execute(): Perform the mutation
    - _capture_post_state(): Capture state after mutation
    - _rollback() (optional): Reverse the action
    """
    
    action_type: ActionType = None
    is_reversible: bool = True
    
    def __init__(
        self,
        actor_id: str,
        actor_type: str,
        trace_id: str,
        **kwargs
    ):
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.trace_id = trace_id
        self.kwargs = kwargs
        
        self._pre_state = None
        self._post_state = None
        self._action_record = None
    
    @abstractmethod
    def _get_target(self) -> tuple[str, str]:
        """Return (target_type, target_id) for the action."""
        pass
    
    @abstractmethod
    def _capture_pre_state(self) -> dict:
        """Capture state before mutation."""
        pass
    
    @abstractmethod
    def _execute(self) -> None:
        """Perform the mutation."""
        pass
    
    @abstractmethod
    def _capture_post_state(self) -> dict:
        """Capture state after mutation."""
        pass
    
    def _get_idempotency_key(self) -> str | None:
        """Optional idempotency key for deduplication."""
        return None
    
    @transaction.atomic
    def execute(self) -> ActionResult:
        """
        Execute the action with full audit logging.
        
        Returns:
            ActionResult with action details
        """
        # Check idempotency
        idempotency_key = self._get_idempotency_key()
        if idempotency_key:
            existing = Action.objects.filter(
                idempotency_key=idempotency_key
            ).first()
            if existing:
                return ActionResult(
                    action_id=existing.id,
                    action_type=existing.action_type,
                    status=existing.status,
                    is_reversible=existing.is_reversible,
                )
        
        # Capture pre-state
        self._pre_state = self._capture_pre_state()
        
        # Execute mutation
        try:
            self._execute()
            status = ActionStatus.COMPLETED
            error_message = ''
        except Exception as e:
            status = ActionStatus.FAILED
            error_message = str(e)
            raise
        
        # Capture post-state
        self._post_state = self._capture_post_state()
        
        # Get target info
        target_type, target_id = self._get_target()
        
        # Create action record
        self._action_record = Action.objects.create(
            action_type=self.action_type,
            status=status,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            target_type=target_type,
            target_id=target_id,
            tenant_id=self._get_tenant_id(),
            trace_id=self.trace_id,
            idempotency_key=idempotency_key,
            pre_state=self._pre_state,
            post_state=self._post_state,
            is_reversible=self.is_reversible,
            error_message=error_message,
            metadata=self._get_metadata(),
        )
        
        return ActionResult(
            action_id=self._action_record.id,
            action_type=self._action_record.action_type,
            status=self._action_record.status,
            is_reversible=self._action_record.is_reversible,
        )
    
    @abstractmethod
    def _get_tenant_id(self) -> UUID:
        """Return tenant ID for the action."""
        pass
    
    def _get_metadata(self) -> dict:
        """Optional metadata to include in action record."""
        return {}


class ReversibleAction(BaseAction):
    """Base for actions that can be rolled back."""
    
    is_reversible = True
    
    @abstractmethod
    def _rollback(self, action: Action) -> None:
        """Reverse the action using captured pre_state."""
        pass
    
    @transaction.atomic
    def rollback(self, action_id: UUID, reason: str = '') -> ActionResult:
        """
        Rollback a previously executed action.
        
        Args:
            action_id: ID of action to rollback
            reason: Reason for rollback
            
        Returns:
            ActionResult for the rollback action
        """
        original_action = Action.objects.get(id=action_id)
        
        if not original_action.is_reversible:
            raise ValueError("Action is not reversible")
        
        if original_action.reversed_by_id:
            raise ValueError("Action already reversed")
        
        # Capture current state as pre-state for rollback
        pre_state = self._capture_post_state()  # Current state
        
        # Execute rollback
        self._rollback(original_action)
        
        # Post-state should match original pre-state
        post_state = self._capture_pre_state()
        
        # Create rollback action record
        target_type, target_id = self._get_target()
        
        rollback_action = Action.objects.create(
            action_type=f"rollback_{self.action_type}",
            status=ActionStatus.COMPLETED,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            target_type=target_type,
            target_id=target_id,
            tenant_id=self._get_tenant_id(),
            trace_id=self.trace_id,
            pre_state=pre_state,
            post_state=post_state,
            is_reversible=False,
            reverses_id=action_id,
            metadata={'reason': reason},
        )
        
        # Mark original as reversed
        original_action.reversed_by = rollback_action
        original_action.save(update_fields=['reversed_by'])
        
        return ActionResult(
            action_id=rollback_action.id,
            action_type=rollback_action.action_type,
            status=rollback_action.status,
            is_reversible=rollback_action.is_reversible,
        )
```

### CommitExtractionAction

```python
# apps/extraction/actions.py

from apps.actions.base import ReversibleAction
from apps.actions.models import ActionType
from apps.extraction.models import (
    ProposedExtraction, ProposalStatus, ExtractedField
)


class CommitExtractionAction(ReversibleAction):
    """
    Commits a proposed extraction to canonical storage.
    
    Pre-state: ProposedExtraction in PENDING status
    Post-state: ProposedExtraction COMMITTED, ExtractedFields created
    
    Rollback: Soft-delete ExtractedFields, revert proposal to PENDING
    """
    
    action_type = ActionType.COMMIT_EXTRACTION
    
    def __init__(
        self,
        extraction: ProposedExtraction,
        actor_id: str,
        actor_type: str,
        trace_id: str,
        review_notes: str = '',
        field_overrides: dict | None = None,
    ):
        super().__init__(actor_id, actor_type, trace_id)
        self.extraction = extraction
        self.review_notes = review_notes
        self.field_overrides = field_overrides or {}
        self._created_field_ids = []
    
    def _get_target(self) -> tuple[str, str]:
        return ('ProposedExtraction', str(self.extraction.id))
    
    def _get_tenant_id(self) -> UUID:
        return self.extraction.tenant_id
    
    def _get_idempotency_key(self) -> str:
        return f"commit-{self.extraction.id}"
    
    def _capture_pre_state(self) -> dict:
        return {
            'proposal_status': self.extraction.status,
            'existing_field_ids': list(
                ExtractedField.objects
                .filter(document=self.extraction.document, is_active=True)
                .values_list('id', flat=True)
            ),
        }
    
    def _execute(self) -> None:
        from django.utils import timezone
        
        # Create ExtractedField for each ProposedField
        for proposed_field in self.extraction.fields.all():
            # Apply overrides if present
            override = self.field_overrides.get(str(proposed_field.id), {})
            value = override.get('value', proposed_field.value)
            normalized = override.get(
                'normalized_value',
                proposed_field.normalized_value
            )
            
            extracted = ExtractedField.objects.create(
                tenant_id=self.extraction.tenant_id,
                document=self.extraction.document,
                source_proposal=self.extraction,
                source_proposed_field=proposed_field,
                field_type=proposed_field.field_type,
                field_name=proposed_field.field_name,
                value=value,
                normalized_value=normalized,
                source_text=proposed_field.source_text,
                source_page=proposed_field.source_page,
                source_location=proposed_field.source_location,
                confidence=proposed_field.confidence,
                committed_by_id=self.actor_id if self.actor_type == 'user' else None,
                committed_action=self._action_record,
                is_active=True,
            )
            self._created_field_ids.append(extracted.id)
        
        # Update proposal status
        self.extraction.status = ProposalStatus.COMMITTED
        self.extraction.reviewed_by_id = self.actor_id if self.actor_type == 'user' else None
        self.extraction.reviewed_at = timezone.now()
        self.extraction.review_notes = self.review_notes
        self.extraction.save()
        
        # Update document status
        self.extraction.document.status = DocumentStatus.EXTRACTED
        self.extraction.document.extraction_completed_at = timezone.now()
        self.extraction.document.save()
    
    def _capture_post_state(self) -> dict:
        return {
            'proposal_status': self.extraction.status,
            'created_field_ids': [str(id) for id in self._created_field_ids],
        }
    
    def _rollback(self, action: Action) -> None:
        from django.utils import timezone
        
        # Soft-delete created fields
        field_ids = action.post_state.get('created_field_ids', [])
        ExtractedField.objects.filter(id__in=field_ids).update(
            is_active=False,
            deactivated_at=timezone.now(),
            deactivated_by_action=self._action_record,
        )
        
        # Revert proposal status
        self.extraction.status = ProposalStatus.PENDING
        self.extraction.reviewed_by = None
        self.extraction.reviewed_at = None
        self.extraction.committed_action = None
        self.extraction.save()
        
        # Revert document status if no other committed extractions
        has_other_committed = (
            ProposedExtraction.objects
            .filter(
                document=self.extraction.document,
                status=ProposalStatus.COMMITTED
            )
            .exclude(id=self.extraction.id)
            .exists()
        )
        
        if not has_other_committed:
            self.extraction.document.status = DocumentStatus.PENDING
            self.extraction.document.save()
    
    def _get_metadata(self) -> dict:
        return {
            'agent_run_id': str(self.extraction.agent_run_id),
            'field_count': len(self._created_field_ids),
            'had_overrides': bool(self.field_overrides),
        }
```

---

## Agents

Agents orchestrate AI workflows. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full Agent/Function/Action pattern.

### ExtractionAgent Interface

```python
# apps/extraction/agents.py

@dataclass
class AgentContext:
    """Context for agent execution."""
    tenant_id: UUID
    document_id: UUID
    trace_id: str
    run_id: UUID
    field_types: list[str] | None = None


@dataclass  
class AgentResult:
    """Result of agent execution."""
    success: bool
    proposal: ProposedExtraction | None = None
    error: str | None = None
    token_usage: dict | None = None
    duration_ms: int = 0


class ExtractionAgent:
    """
    Orchestrates document field extraction.
    
    The agent:
    1. Extracts text from document
    2. Calls LLM to identify fields based on document type
    3. Validates extracted fields
    4. Creates ProposedExtraction (no commits)
    """
    
    def __init__(self, context: AgentContext):
        self.context = context
        self.functions = {
            'text_extraction': TextExtractionFunction(),
            'field_extraction': FieldExtractionFunction(),
            'validation': FieldValidationFunction(),
        }
    
    def run(self) -> AgentResult:
        """Execute extraction workflow."""
        # Implementation in CELERY_TASKS.md
        pass
```

---

## Error Handling

### Service Errors

Services return errors via `ServiceResult.fail()`:

```python
if not document:
    return ServiceResult.fail(
        "Document not found",
        error_code='not_found'
    )
```

### Action Errors

Actions raise exceptions which are caught and logged:

```python
try:
    action.execute()
except ValidationError as e:
    # Logged in action record with status=FAILED
    raise
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `not_found` | 404 | Resource doesn't exist |
| `validation_failed` | 400 | Input validation error |
| `invalid_status` | 400 | Invalid state transition |
| `already_committed` | 400 | Duplicate commit attempt |
| `feature_disabled` | 503 | Feature flag is off |
| `extraction_in_progress` | 400 | Concurrent extraction |

---

## Testing Patterns

### Service Tests

```python
# apps/documents/tests/test_services.py

import pytest
from apps.documents.services import DocumentService
from apps.common.services.base import ServiceContext

@pytest.fixture
def service_context(tenant):
    return ServiceContext(
        tenant_id=tenant.id,
        actor_id='1',
        actor_type='user',
        trace_id='test-trace',
        feature_flags={'ai_extraction_enabled': True},
    )

@pytest.fixture
def document_service(service_context):
    return DocumentService(service_context)

class TestDocumentService:
    def test_create_document_success(self, document_service, pdf_file):
        result = document_service.create_document(
            file=pdf_file,
            original_filename='test.pdf',
        )
        
        assert result.success
        assert result.data.original_filename == 'test.pdf'
        assert result.data.status == 'pending'
    
    def test_create_document_invalid_type(self, document_service, txt_file):
        result = document_service.create_document(
            file=txt_file,
            original_filename='test.txt',
        )
        
        assert not result.success
        assert result.error_code == 'invalid_file_type'
```

### Action Tests

```python
# apps/extraction/tests/test_actions.py

@pytest.mark.django_db
class TestCommitExtractionAction:
    def test_commit_creates_extracted_fields(
        self, proposed_extraction, user
    ):
        action = CommitExtractionAction(
            extraction=proposed_extraction,
            actor_id=str(user.id),
            actor_type='user',
            trace_id='test-trace',
        )
        
        result = action.execute()
        
        assert result.status == 'completed'
        assert ExtractedField.objects.filter(
            source_proposal=proposed_extraction
        ).count() == proposed_extraction.fields.count()
    
    def test_commit_is_idempotent(self, proposed_extraction, user):
        action = CommitExtractionAction(
            extraction=proposed_extraction,
            actor_id=str(user.id),
            actor_type='user',
            trace_id='test-trace',
        )
        
        result1 = action.execute()
        result2 = action.execute()
        
        # Same action ID returned
        assert result1.action_id == result2.action_id
    
    def test_rollback_deactivates_fields(
        self, committed_extraction, user
    ):
        # Get the commit action
        commit_action = committed_extraction.committed_action
        
        # Rollback
        action = CommitExtractionAction(
            extraction=committed_extraction,
            actor_id=str(user.id),
            actor_type='user',
            trace_id='test-trace',
        )
        
        result = action.rollback(commit_action.id, reason='Test rollback')
        
        assert result.status == 'completed'
        assert not ExtractedField.objects.filter(
            source_proposal=committed_extraction,
            is_active=True
        ).exists()
```