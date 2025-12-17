"""
==============================================================================
FILE: models.py
LOCATION: /docextract/apps/documents/models.py
==============================================================================

PURPOSE:
    Defines the Document model for uploaded documents pending or completed
    field extraction. Documents are the core entity around which the
    extraction workflow operates.

MODELS:
    - DocumentStatus: Enumeration of document processing states
    - Document: An uploaded document for field extraction

USAGE:
    from apps.documents.models import Document, DocumentStatus

    document = Document.objects.create(
        tenant=tenant,
        file=uploaded_file,
        original_filename='invoice.pdf',
        file_type='application/pdf',
        file_size_bytes=1024000,
        file_hash=computed_sha256,
        uploaded_by=request.user,
    )

LIFECYCLE:
    Documents progress through statuses:
    PENDING → PROCESSING → EXTRACTED (success path)
    PENDING → PROCESSING → FAILED (error path)

DESIGN DECISIONS:
    - UUID primary keys for distributed system compatibility
    - SHA-256 hash stored for deduplication and integrity checking
    - File storage path includes date partitioning for scalability
    - Soft reference to User (SET_NULL) to preserve history if user deleted
    - Extraction timestamps for performance monitoring

PERFORMANCE NOTES:
    - Index on (tenant, status) for filtered listing queries
    - Index on file_hash for deduplication lookups
    - Consider select_related('tenant', 'uploaded_by') for detail views
    - File storage backend configurable via Django settings

TESTING:
    - Use SimpleUploadedFile for test file uploads
    - Test status transitions and validation
    - Verify file_hash computation accuracy

==============================================================================
"""

import uuid

from django.db import models

from apps.common.models import TenantMixin, TimestampMixin


class DocumentStatus(models.TextChoices):
    """
    Enumeration of document processing states.

    Status transitions:
    - PENDING: Document uploaded, awaiting extraction
    - PROCESSING: Extraction in progress (Celery task running)
    - EXTRACTED: Extraction completed successfully
    - FAILED: Extraction failed (see status_message for details)
    """

    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    EXTRACTED = "extracted", "Extracted"
    FAILED = "failed", "Failed"


class Document(TenantMixin, TimestampMixin, models.Model):
    """
    An uploaded document for field extraction.

    Documents progress through statuses as they are processed:
    PENDING → PROCESSING → EXTRACTED (or FAILED)

    File storage is handled via Django's FileField with a configurable
    storage backend. Files are organised by date for scalability.

    Attributes:
        id: UUID primary key
        tenant: Foreign key to the owning tenant
        file: The uploaded document file (PDF, DOCX, etc.)
        original_filename: Filename as provided by the uploader
        file_type: MIME type or extension (pdf, docx, etc.)
        file_size_bytes: File size for validation and display
        file_hash: SHA-256 hash for deduplication and integrity
        status: Current processing status
        status_message: Human-readable status details or error message
        title: Document title (extracted or user-provided)
        metadata: Additional document metadata as JSONB
        uploaded_by: Reference to the user who uploaded the document
        extraction_started_at: Timestamp when processing began
        extraction_completed_at: Timestamp when processing finished
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # File storage
    file = models.FileField(
        upload_to="documents/%Y/%m/%d/",
        help_text="The uploaded document file",
    )

    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename from upload",
    )

    file_type = models.CharField(
        max_length=50,
        help_text="MIME type or extension (e.g., pdf, docx)",
    )

    file_size_bytes = models.PositiveIntegerField(
        help_text="File size in bytes",
    )

    file_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hash for deduplication and integrity",
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING,
        db_index=True,
        help_text="Current processing status",
    )

    status_message = models.TextField(
        blank=True,
        help_text="Human-readable status details (e.g., error message)",
    )

    # Metadata
    title = models.CharField(
        max_length=500,
        blank=True,
        help_text="Document title (extracted or user-provided)",
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional document metadata",
    )

    # Ownership
    uploaded_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
        help_text="User who uploaded the document",
    )

    # Processing tracking
    extraction_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when extraction processing began",
    )

    extraction_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when extraction processing completed",
    )

    class Meta:
        db_table = "documents"
        indexes = [
            models.Index(
                fields=["tenant", "status"],
                name="ix_documents_tenant_status",
            ),
            models.Index(
                fields=["tenant", "created_at"],
                name="ix_documents_tenant_created",
            ),
            models.Index(
                fields=["file_hash"],
                name="ix_documents_file_hash",
            ),
            models.Index(
                fields=["uploaded_by"],
                name="ix_documents_uploaded_by",
            ),
        ]
        ordering = ["-created_at"]
        verbose_name = "Document"
        verbose_name_plural = "Documents"

    def __str__(self) -> str:
        return f"{self.original_filename} ({self.status})"

    @property
    def is_processing(self) -> bool:
        """Check if document is currently being processed."""
        return self.status == DocumentStatus.PROCESSING

    @property
    def is_extractable(self) -> bool:
        """Check if document can have extraction triggered."""
        return self.status in (DocumentStatus.PENDING, DocumentStatus.FAILED)

    @property
    def extraction_duration_ms(self) -> int | None:
        """
        Calculate extraction duration in milliseconds.

        Returns None if extraction has not completed.
        """
        if not self.extraction_started_at or not self.extraction_completed_at:
            return None
        delta = self.extraction_completed_at - self.extraction_started_at
        return int(delta.total_seconds() * 1000)