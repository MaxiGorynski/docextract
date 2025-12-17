"""
==============================================================================
FILE: selectors.py
LOCATION: /docextract/apps/documents/selectors.py
==============================================================================

PURPOSE:
    Encapsulates read operations for documents. Selectors provide a clean
    interface for querying data without side effects, always scoped to
    a specific tenant for data isolation.

CLASSES:
    - DocumentSelector: Query interface for Document model

USAGE:
    from apps.documents.selectors import DocumentSelector

    selector = DocumentSelector(tenant_id=request.tenant.id)

    # Get single document
    document = selector.get_by_id(document_id)

    # List with filters
    documents = selector.list_documents(
        status=DocumentStatus.PENDING,
        search='invoice',
        ordering='-created_at',
    )

DESIGN PRINCIPLES:
    - Read-only: Selectors never mutate state
    - Tenant-scoped: All queries filter by tenant automatically
    - Composable: Methods return QuerySets for further filtering
    - Cacheable: Results can be cached (no side effects)

PERFORMANCE NOTES:
    - Base queryset includes tenant filter for index usage
    - Use get_with_fields() to prefetch related data
    - Consider pagination for list_documents() results

TESTING:
    - Create test data across multiple tenants
    - Verify tenant isolation (no cross-tenant leakage)
    - Test filter combinations

==============================================================================
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.documents.models import Document, DocumentStatus

if TYPE_CHECKING:
    from apps.extraction.models import ProposedExtraction


class DocumentSelector:
    """
    Selector for document queries.

    All queries are automatically scoped to the tenant provided
    at initialisation. This ensures data isolation between tenants.

    Attributes:
        tenant_id: UUID of the tenant to scope queries to
    """

    def __init__(self, tenant_id: UUID) -> None:
        """
        Initialise the selector with tenant scope.

        Args:
            tenant_id: UUID of the tenant to scope all queries to
        """
        self.tenant_id = tenant_id

    def _base_queryset(self) -> QuerySet[Document]:
        """
        Return base queryset with tenant filter applied.

        All queries should build on this to ensure tenant isolation.

        Returns:
            QuerySet filtered by tenant_id
        """
        return Document.objects.filter(tenant_id=self.tenant_id)

    def get_by_id(self, document_id: UUID) -> Document | None:
        """
        Get a document by ID within the tenant.

        Args:
            document_id: UUID of the document to retrieve

        Returns:
            Document instance or None if not found
        """
        return self._base_queryset().filter(id=document_id).first()

    def get_by_hash(self, file_hash: str) -> Document | None:
        """
        Get a document by file hash (for deduplication).

        Args:
            file_hash: SHA-256 hash of the file content

        Returns:
            Document instance or None if not found
        """
        return self._base_queryset().filter(file_hash=file_hash).first()

    def list_documents(
        self,
        status: DocumentStatus | str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        search: str | None = None,
        uploaded_by_id: int | None = None,
        ordering: str = "-created_at",
    ) -> QuerySet[Document]:
        """
        List documents with optional filtering.

        Args:
            status: Filter by document status
            created_after: Filter documents created after this datetime
            created_before: Filter documents created before this datetime
            search: Search in title and original filename
            uploaded_by_id: Filter by uploader user ID
            ordering: Sort field (prefix with - for descending)

        Returns:
            QuerySet of documents matching filters
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
                Q(title__icontains=search) | Q(original_filename__icontains=search)
            )

        if uploaded_by_id:
            qs = qs.filter(uploaded_by_id=uploaded_by_id)

        return qs.order_by(ordering)

    def get_with_fields(self, document_id: UUID) -> Document | None:
        """
        Get document with prefetched active extracted fields.

        Use this when you need to access extracted fields to avoid
        N+1 queries.

        Args:
            document_id: UUID of the document to retrieve

        Returns:
            Document instance with active_fields attribute, or None
        """
        from apps.extraction.models import ExtractedField

        return (
            self._base_queryset()
            .filter(id=document_id)
            .prefetch_related(
                Prefetch(
                    "extracted_fields",
                    queryset=ExtractedField.objects.filter(is_active=True).order_by(
                        "field_type"
                    ),
                    to_attr="active_fields",
                )
            )
            .first()
        )

    def get_with_extractions(self, document_id: UUID) -> Document | None:
        """
        Get document with prefetched proposed extractions.

        Use this when you need to access extraction proposals.

        Args:
            document_id: UUID of the document to retrieve

        Returns:
            Document instance with prefetched extractions, or None
        """
        from apps.extraction.models import ProposedExtraction

        return (
            self._base_queryset()
            .filter(id=document_id)
            .prefetch_related(
                Prefetch(
                    "proposed_extractions",
                    queryset=ProposedExtraction.objects.order_by("-created_at"),
                )
            )
            .first()
        )

    def get_latest_extraction(self, document_id: UUID) -> ProposedExtraction | None:
        """
        Get the most recent extraction proposal for a document.

        Args:
            document_id: UUID of the document

        Returns:
            Most recent ProposedExtraction or None
        """
        from apps.extraction.models import ProposedExtraction

        return (
            ProposedExtraction.objects.filter(
                document_id=document_id, tenant_id=self.tenant_id
            )
            .order_by("-created_at")
            .first()
        )

    def get_documents_pending_extraction(self) -> QuerySet[Document]:
        """
        Get documents awaiting extraction processing.

        Returns:
            QuerySet of documents with PENDING status
        """
        return self._base_queryset().filter(status=DocumentStatus.PENDING)

    def get_documents_processing(self) -> QuerySet[Document]:
        """
        Get documents currently being processed.

        Returns:
            QuerySet of documents with PROCESSING status
        """
        return self._base_queryset().filter(status=DocumentStatus.PROCESSING)

    def count_by_status(self) -> dict[str, int]:
        """
        Count documents grouped by status.

        Returns:
            Dict mapping status to count, e.g. {'pending': 5, 'extracted': 10}
        """
        counts = (
            self._base_queryset()
            .values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
        return dict(counts)

    def exists_with_hash(self, file_hash: str) -> bool:
        """
        Check if a document with the given hash exists.

        More efficient than get_by_hash() when you only need
        to check existence.

        Args:
            file_hash: SHA-256 hash to check

        Returns:
            True if document exists, False otherwise
        """
        return self._base_queryset().filter(file_hash=file_hash).exists()

    def get_recent(self, limit: int = 10) -> QuerySet[Document]:
        """
        Get the most recently created documents.

        Args:
            limit: Maximum number of documents to return

        Returns:
            QuerySet of most recent documents
        """
        return self._base_queryset().order_by("-created_at")[:limit]