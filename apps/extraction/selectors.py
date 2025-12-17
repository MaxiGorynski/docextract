"""
==============================================================================
FILE: selectors.py
LOCATION: /docextract/apps/extraction/selectors.py
==============================================================================

PURPOSE:
    Encapsulates read operations for extractions. Provides a clean interface
    for querying ProposedExtraction, ProposedField, and ExtractedField models
    without side effects, always scoped to a specific tenant.

CLASSES:
    - ExtractionSelector: Query interface for extraction models

USAGE:
    from apps.extraction.selectors import ExtractionSelector

    selector = ExtractionSelector(tenant_id=request.tenant.id)

    # Get extraction with fields
    extraction = selector.get_by_id_with_fields(extraction_id)

    # List pending extractions
    pending = selector.list_pending()

    # Get committed fields for document
    fields = selector.get_committed_fields(document_id)

DESIGN PRINCIPLES:
    - Read-only: Selectors never mutate state
    - Tenant-scoped: All queries filter by tenant automatically
    - Composable: Methods return QuerySets for further filtering
    - Cacheable: Results can be cached (no side effects)

PERFORMANCE NOTES:
    - Use get_by_id_with_fields() to prefetch related fields
    - Committed fields query uses is_active index
    - Consider pagination for list methods

TESTING:
    - Create test data across multiple tenants
    - Verify tenant isolation
    - Test prefetch effectiveness with assertNumQueries

==============================================================================
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.extraction.models import (
    ExtractedField,
    FieldType,
    ProposalStatus,
    ProposedExtraction,
    ProposedField,
)


class ExtractionSelector:
    """
    Selector for extraction queries.

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

    def _base_queryset(self) -> QuerySet[ProposedExtraction]:
        """
        Return base queryset with tenant filter applied.

        Returns:
            QuerySet filtered by tenant_id
        """
        return ProposedExtraction.objects.filter(tenant_id=self.tenant_id)

    def get_by_id(self, extraction_id: UUID) -> ProposedExtraction | None:
        """
        Get an extraction by ID within the tenant.

        Args:
            extraction_id: UUID of the extraction to retrieve

        Returns:
            ProposedExtraction instance or None if not found
        """
        return self._base_queryset().filter(id=extraction_id).first()

    def get_by_id_with_fields(self, extraction_id: UUID) -> ProposedExtraction | None:
        """
        Get extraction with prefetched proposed fields.

        Use this when you need to access fields to avoid N+1 queries.

        Args:
            extraction_id: UUID of the extraction to retrieve

        Returns:
            ProposedExtraction with prefetched fields, or None
        """
        return (
            self._base_queryset()
            .filter(id=extraction_id)
            .prefetch_related(
                Prefetch(
                    "fields",
                    queryset=ProposedField.objects.order_by("field_type"),
                )
            )
            .select_related("document")
            .first()
        )

    def list_extractions(
        self,
        document_id: UUID | None = None,
        status: ProposalStatus | str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        min_confidence: float | None = None,
        ordering: str = "-created_at",
    ) -> QuerySet[ProposedExtraction]:
        """
        List extractions with optional filtering.

        Args:
            document_id: Filter by document
            status: Filter by proposal status
            created_after: Filter extractions created after this datetime
            created_before: Filter extractions created before this datetime
            min_confidence: Filter by minimum overall confidence
            ordering: Sort field (prefix with - for descending)

        Returns:
            QuerySet of extractions matching filters
        """
        qs = self._base_queryset()

        if document_id:
            qs = qs.filter(document_id=document_id)

        if status:
            qs = qs.filter(status=status)

        if created_after:
            qs = qs.filter(created_at__gte=created_after)

        if created_before:
            qs = qs.filter(created_at__lte=created_before)

        if min_confidence is not None:
            qs = qs.filter(overall_confidence__gte=min_confidence)

        return qs.order_by(ordering)

    def list_pending(self) -> QuerySet[ProposedExtraction]:
        """
        Get all extractions pending review.

        Returns:
            QuerySet of extractions with PENDING status
        """
        return self._base_queryset().filter(status=ProposalStatus.PENDING)

    def list_pending_for_document(
        self, document_id: UUID
    ) -> QuerySet[ProposedExtraction]:
        """
        Get pending extractions for a specific document.

        Args:
            document_id: UUID of the document

        Returns:
            QuerySet of pending extractions for the document
        """
        return self._base_queryset().filter(
            document_id=document_id, status=ProposalStatus.PENDING
        )

    def get_latest_for_document(self, document_id: UUID) -> ProposedExtraction | None:
        """
        Get the most recent extraction for a document.

        Args:
            document_id: UUID of the document

        Returns:
            Most recent ProposedExtraction or None
        """
        return (
            self._base_queryset()
            .filter(document_id=document_id)
            .order_by("-created_at")
            .first()
        )

    def get_committed_fields(
        self,
        document_id: UUID,
        field_type: FieldType | str | None = None,
    ) -> QuerySet[ExtractedField]:
        """
        Get active (committed) extracted fields for a document.

        Args:
            document_id: UUID of the document
            field_type: Optional filter by field type

        Returns:
            QuerySet of active ExtractedField instances
        """
        qs = ExtractedField.objects.filter(
            tenant_id=self.tenant_id,
            document_id=document_id,
            is_active=True,
        )

        if field_type:
            qs = qs.filter(field_type=field_type)

        return qs.order_by("field_type")

    def get_all_committed_fields(
        self,
        document_id: UUID,
        include_inactive: bool = False,
    ) -> QuerySet[ExtractedField]:
        """
        Get all extracted fields for a document.

        Args:
            document_id: UUID of the document
            include_inactive: Include soft-deleted (rolled back) fields

        Returns:
            QuerySet of ExtractedField instances
        """
        qs = ExtractedField.objects.filter(
            tenant_id=self.tenant_id,
            document_id=document_id,
        )

        if not include_inactive:
            qs = qs.filter(is_active=True)

        return qs.order_by("-committed_at")

    def count_by_status(self) -> dict[str, int]:
        """
        Count extractions grouped by status.

        Returns:
            Dict mapping status to count
        """
        counts = (
            self._base_queryset()
            .values("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
        return dict(counts)

    def count_pending_by_document(self) -> dict[UUID, int]:
        """
        Count pending extractions grouped by document.

        Returns:
            Dict mapping document_id to pending count
        """
        counts = (
            self._base_queryset()
            .filter(status=ProposalStatus.PENDING)
            .values("document_id")
            .annotate(count=Count("id"))
            .values_list("document_id", "count")
        )
        return dict(counts)

    def get_by_agent_run_id(self, agent_run_id: UUID) -> ProposedExtraction | None:
        """
        Get extraction by agent run ID.

        Useful for tracing agent executions.

        Args:
            agent_run_id: UUID of the agent run

        Returns:
            ProposedExtraction instance or None
        """
        return self._base_queryset().filter(agent_run_id=agent_run_id).first()

    def has_pending_extraction(self, document_id: UUID) -> bool:
        """
        Check if document has any pending extraction.

        Args:
            document_id: UUID of the document

        Returns:
            True if pending extraction exists
        """
        return (
            self._base_queryset()
            .filter(document_id=document_id, status=ProposalStatus.PENDING)
            .exists()
        )

    def has_committed_extraction(self, document_id: UUID) -> bool:
        """
        Check if document has any committed extraction.

        Args:
            document_id: UUID of the document

        Returns:
            True if committed extraction exists
        """
        return (
            self._base_queryset()
            .filter(document_id=document_id, status=ProposalStatus.COMMITTED)
            .exists()
        )

    def get_field_by_id(self, field_id: UUID) -> ProposedField | None:
        """
        Get a proposed field by ID.

        Verifies tenant ownership through the extraction relationship.

        Args:
            field_id: UUID of the proposed field

        Returns:
            ProposedField instance or None
        """
        return (
            ProposedField.objects.filter(id=field_id)
            .select_related("extraction")
            .filter(extraction__tenant_id=self.tenant_id)
            .first()
        )

    def get_low_confidence_fields(
        self,
        extraction_id: UUID,
        threshold: float = 0.7,
    ) -> QuerySet[ProposedField]:
        """
        Get proposed fields below confidence threshold.

        Useful for highlighting fields that need human attention.

        Args:
            extraction_id: UUID of the extraction
            threshold: Confidence threshold (default 0.7)

        Returns:
            QuerySet of low-confidence fields
        """
        return ProposedField.objects.filter(
            extraction_id=extraction_id,
            extraction__tenant_id=self.tenant_id,
            confidence__lt=threshold,
        ).order_by("confidence")