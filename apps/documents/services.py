"""
==============================================================================
FILE: services.py
LOCATION: /docextract/apps/documents/services.py
==============================================================================

PURPOSE:
    Service layer for document operations. Orchestrates document upload,
    validation, and extraction triggering. Entry point for all document
    business logic.

CLASSES:
    - DocumentService: Service for document lifecycle operations

USAGE:
    from apps.documents.services import DocumentService
    from apps.common.services import ServiceContext

    context = ServiceContext(
        tenant_id=tenant.id,
        actor_id=str(user.id),
        actor_type='user',
        trace_id=request.trace_id,
        feature_flags=request.feature_flags,
    )

    service = DocumentService(context)

    # Upload document
    result = service.create_document(
        file=uploaded_file,
        original_filename='invoice.pdf',
        auto_extract=True,
    )

    if result.success:
        document = result.data
    else:
        handle_error(result.error_code, result.error)

DESIGN PRINCIPLES:
    - Stateless: All state from parameters or database
    - Transaction-aware: Uses @transaction.atomic for data integrity
    - Returns ServiceResult: Never raises for expected errors
    - Feature flag aware: Checks flags before triggering extraction

PERFORMANCE NOTES:
    - File hash computed in streaming fashion
    - Deduplication check uses indexed lookup
    - Celery task dispatched asynchronously

TESTING:
    - Use SimpleUploadedFile for test file uploads
    - Mock Celery task dispatch for unit tests
    - Test feature flag behavior

==============================================================================
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.common.services.base import BaseService, ServiceContext, ServiceResult
from apps.documents.models import Document, DocumentStatus
from apps.documents.selectors import DocumentSelector

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

logger = logging.getLogger(__name__)

# Supported file types for extraction
SUPPORTED_FILE_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

# Maximum file size (50MB)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


class DocumentService(BaseService):
    """
    Service for document operations.

    Responsibilities:
    - Document upload with validation
    - Triggering extraction workflows
    - Document lifecycle management

    All operations are scoped to the tenant from ServiceContext.
    """

    def __init__(self, context: ServiceContext) -> None:
        """
        Initialise the document service.

        Args:
            context: ServiceContext with tenant, actor, and trace info
        """
        super().__init__(context)
        self.selector = DocumentSelector(context.tenant_id)

    @transaction.atomic
    def create_document(
        self,
        file: UploadedFile,
        original_filename: str,
        title: str | None = None,
        metadata: dict | None = None,
        auto_extract: bool = False,
    ) -> ServiceResult[Document]:
        """
        Create a new document from an uploaded file.

        Validates the file type and size, calculates hash for deduplication,
        and optionally triggers extraction.

        Args:
            file: Uploaded file object (Django UploadedFile)
            original_filename: Original filename from client
            title: Optional document title (defaults to filename)
            metadata: Optional additional metadata dict
            auto_extract: If True, trigger extraction immediately

        Returns:
            ServiceResult containing created Document or error details

        Error codes:
            - invalid_file_type: File MIME type not supported
            - file_too_large: File exceeds maximum size
            - duplicate_file: Document with same hash already exists
        """
        self.log_operation("create_document", file_name=original_filename)

        # Validate file type
        file_type = self._detect_file_type(file)
        if file_type not in SUPPORTED_FILE_TYPES:
            self.log_error(
                "create_document",
                f"Unsupported file type: {file_type}",
                file_name=original_filename,
            )
            return ServiceResult.fail(
                f"Unsupported file type: {file_type}. "
                f"Supported types: PDF, DOCX",
                error_code="invalid_file_type",
            )

        # Validate file size
        if file.size > MAX_FILE_SIZE_BYTES:
            self.log_error(
                "create_document",
                f"File too large: {file.size} bytes",
                file_name=original_filename,
            )
            return ServiceResult.fail(
                f"File exceeds maximum size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB",
                error_code="file_too_large",
            )

        # Calculate hash for deduplication
        file_hash = self._calculate_hash(file)

        # Check for duplicates
        existing = self.selector.get_by_hash(file_hash)
        if existing:
            self.log_error(
                "create_document",
                f"Duplicate file: {existing.id}",
                file_name=original_filename,
                existing_id=str(existing.id),
            )
            return ServiceResult.fail(
                f"Document with identical content already exists: {existing.id}",
                error_code="duplicate_file",
            )

        # Determine uploaded_by
        uploaded_by_id = None
        if self.context.actor_type == "user":
            try:
                uploaded_by_id = int(self.context.actor_id)
            except (ValueError, TypeError):
                pass

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
            uploaded_by_id=uploaded_by_id,
            status=DocumentStatus.PENDING,
        )

        self.logger.info(
            f"Document created: {document.id}",
            extra={
                "document_id": str(document.id),
                "trace_id": self.context.trace_id,
                "file_name": original_filename,
                "file_type": file_type,
                "file_size": file.size,
            },
        )

        # Optionally trigger extraction
        if auto_extract and self.is_feature_enabled("ai_extraction_enabled"):
            extract_result = self.trigger_extraction(document.id)
            if not extract_result.success:
                self.logger.warning(
                    f"Auto-extraction trigger failed: {extract_result.error}",
                    extra={"document_id": str(document.id)},
                )

        return ServiceResult.ok(document)

    def trigger_extraction(
        self,
        document_id: UUID,
        force: bool = False,
        field_types: list[str] | None = None,
    ) -> ServiceResult[str]:
        """
        Trigger asynchronous extraction for a document.

        Dispatches a Celery task to process the document and create
        a ProposedExtraction.

        Args:
            document_id: UUID of the document to extract
            force: If True, re-extract even if extraction exists
            field_types: Optional list of specific field types to extract

        Returns:
            ServiceResult containing Celery task ID or error details

        Error codes:
            - feature_disabled: AI extraction feature is off
            - not_found: Document does not exist
            - extraction_in_progress: Document already being processed
            - extraction_exists: Extraction exists (use force=True)
        """
        self.log_operation("trigger_extraction", document_id=str(document_id))

        # Check feature flag
        if not self.is_feature_enabled("ai_extraction_enabled"):
            return ServiceResult.fail(
                "AI extraction is currently disabled",
                error_code="feature_disabled",
            )

        # Get document
        document = self.selector.get_by_id(document_id)
        if not document:
            return ServiceResult.fail(
                f"Document not found: {document_id}",
                error_code="not_found",
            )

        # Check if already processing
        if document.status == DocumentStatus.PROCESSING:
            return ServiceResult.fail(
                "Document extraction already in progress",
                error_code="extraction_in_progress",
            )

        # Check for existing extraction (unless force)
        if not force and document.status == DocumentStatus.EXTRACTED:
            existing = self.selector.get_latest_extraction(document_id)
            if existing and existing.status in ("pending", "committed"):
                return ServiceResult.fail(
                    "Extraction already exists. Use force=True to re-extract.",
                    error_code="extraction_exists",
                )

        # Generate idempotency key
        idempotency_key = f"extract-{document_id}-{self.context.trace_id}"

        # Update document status
        document.status = DocumentStatus.PROCESSING
        document.extraction_started_at = timezone.now()
        document.save(update_fields=["status", "extraction_started_at", "updated_at"])

        # Dispatch Celery task
        from apps.extraction.tasks import process_extraction_task

        task = process_extraction_task.apply_async(
            kwargs={
                "document_id": str(document_id),
                "tenant_id": str(self.context.tenant_id),
                "actor_id": self.context.actor_id,
                "trace_id": self.context.trace_id,
                "field_types": field_types,
                "idempotency_key": idempotency_key,
            },
            task_id=idempotency_key,
        )

        self.logger.info(
            f"Extraction task dispatched: {task.id}",
            extra={
                "document_id": str(document_id),
                "task_id": task.id,
                "trace_id": self.context.trace_id,
            },
        )

        return ServiceResult.ok(task.id)

    def update_document_status(
        self,
        document_id: UUID,
        status: DocumentStatus | str,
        status_message: str = "",
    ) -> ServiceResult[Document]:
        """
        Update the status of a document.

        Used by extraction tasks to update status after processing.

        Args:
            document_id: UUID of the document
            status: New status value
            status_message: Optional status message or error details

        Returns:
            ServiceResult containing updated Document or error
        """
        self.log_operation(
            "update_document_status",
            document_id=str(document_id),
            new_status=status,
        )

        document = self.selector.get_by_id(document_id)
        if not document:
            return ServiceResult.fail(
                f"Document not found: {document_id}",
                error_code="not_found",
            )

        document.status = status
        document.status_message = status_message

        if status == DocumentStatus.EXTRACTED:
            document.extraction_completed_at = timezone.now()

        document.save(
            update_fields=[
                "status",
                "status_message",
                "extraction_completed_at",
                "updated_at",
            ]
        )

        return ServiceResult.ok(document)

    def delete_document(self, document_id: UUID) -> ServiceResult[bool]:
        """
        Delete a document and its associated data.

        This is a hard delete. Consider soft delete for production use.

        Args:
            document_id: UUID of the document to delete

        Returns:
            ServiceResult containing True on success or error
        """
        self.log_operation("delete_document", document_id=str(document_id))

        document = self.selector.get_by_id(document_id)
        if not document:
            return ServiceResult.fail(
                f"Document not found: {document_id}",
                error_code="not_found",
            )

        # Cannot delete while processing
        if document.status == DocumentStatus.PROCESSING:
            return ServiceResult.fail(
                "Cannot delete document while extraction is in progress",
                error_code="extraction_in_progress",
            )

        # Delete file from storage
        if document.file:
            document.file.delete(save=False)

        # Delete document (cascades to extractions)
        document.delete()

        self.logger.info(
            f"Document deleted: {document_id}",
            extra={
                "document_id": str(document_id),
                "trace_id": self.context.trace_id,
            },
        )

        return ServiceResult.ok(True)

    def _detect_file_type(self, file: UploadedFile) -> str:
        """
        Detect MIME type from file content using magic bytes.

        Args:
            file: Uploaded file object

        Returns:
            MIME type string
        """
        try:
            import magic

            file.seek(0)
            mime = magic.from_buffer(file.read(2048), mime=True)
            file.seek(0)
            return mime
        except ImportError:
            # Fallback to content_type if python-magic not available
            self.logger.warning(
                "python-magic not installed, using content_type header"
            )
            return file.content_type or "application/octet-stream"

    def _calculate_hash(self, file: UploadedFile) -> str:
        """
        Calculate SHA-256 hash of file content.

        Streams the file in chunks to handle large files efficiently.

        Args:
            file: Uploaded file object

        Returns:
            Hex-encoded SHA-256 hash string
        """
        hasher = hashlib.sha256()
        file.seek(0)

        # Use chunks() for memory efficiency
        for chunk in file.chunks():
            hasher.update(chunk)

        file.seek(0)
        return hasher.hexdigest()