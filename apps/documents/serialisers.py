"""
==============================================================================
FILE: serialisers.py
LOCATION: /docextract/apps/documents/serialisers.py
==============================================================================

PURPOSE:
    DRF serialisers for the Documents API. Handles serialisation of Document
    models for list, create, retrieve, and extraction trigger endpoints.

SERIALISERS:
    - UserBriefSerialiser: Minimal user representation for nested display
    - DocumentListSerialiser: Compact representation for list views
    - DocumentCreateSerialiser: Handles file upload with validation
    - DocumentDetailSerialiser: Full representation with related data
    - TriggerExtractionRequestSerialiser: Request body for extraction trigger
    - TriggerExtractionResponseSerialiser: Response for async task dispatch
    - LatestExtractionSerialiser: Nested extraction summary
    - ExtractedFieldBriefSerialiser: Minimal field representation

USAGE:
    from apps.documents.serialisers import (
        DocumentListSerialiser,
        DocumentCreateSerialiser,
        DocumentDetailSerialiser,
    )

    # In viewset
    def get_serialiser_class(self):
        if self.action == 'list':
            return DocumentListSerialiser
        if self.action == 'create':
            return DocumentCreateSerialiser
        return DocumentDetailSerialiser

DESIGN DECISIONS:
    - Separate serialisers for list/detail to optimise payload size
    - Links field provides HATEOAS-style navigation
    - Nested serialisers for uploaded_by, latest_extraction
    - Read-only computed fields (extraction_count, active_field_count)
    - File validation in serialiser, business logic in service

PERFORMANCE NOTES:
    - DocumentDetailSerialiser requires prefetch_related for efficiency
    - List serialiser omits heavy fields (extracted_fields, links)
    - Consider select_related('uploaded_by') for list queries

==============================================================================
"""

from rest_framework import serializers

from apps.documents.models import Document, DocumentStatus


class UserBriefSerialiser(serializers.Serializer):
    """
    Minimal user representation for nested display.

    Used in uploaded_by, reviewed_by, and similar fields where
    only basic user identification is needed.
    """

    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)


class ExtractedFieldBriefSerialiser(serializers.Serializer):
    """
    Minimal extracted field representation for document detail view.

    Shows only the essential field data without full provenance.
    """

    id = serializers.UUIDField(read_only=True)
    field_type = serializers.CharField(read_only=True)
    field_name = serializers.CharField(read_only=True)
    value = serializers.CharField(read_only=True)
    confidence = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)


class LatestExtractionSerialiser(serializers.Serializer):
    """
    Summary of the most recent extraction for a document.

    Provides quick access to extraction status without full detail.
    """

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    overall_confidence = serializers.FloatField(read_only=True)
    field_count = serializers.IntegerField(read_only=True)


class DocumentListSerialiser(serializers.ModelSerializer):
    """
    Compact document representation for list views.

    Optimised for listing many documents with essential metadata.
    Includes computed counts for extraction status overview.
    """

    uploaded_by = UserBriefSerialiser(read_only=True)
    extraction_count = serializers.SerializerMethodField()
    active_field_count = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "original_filename",
            "file_type",
            "file_size_bytes",
            "status",
            "status_message",
            "title",
            "uploaded_by",
            "extraction_count",
            "active_field_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_extraction_count(self, obj: Document) -> int:
        """Return count of proposed extractions for this document."""
        # Use prefetched data if available, otherwise query
        if hasattr(obj, "_prefetched_objects_cache") and \
           "proposed_extractions" in obj._prefetched_objects_cache:
            return len(obj.proposed_extractions.all())
        return obj.proposed_extractions.count()

    def get_active_field_count(self, obj: Document) -> int:
        """Return count of active extracted fields for this document."""
        # Use prefetched data if available, otherwise query
        if hasattr(obj, "_prefetched_objects_cache") and \
           "extracted_fields" in obj._prefetched_objects_cache:
            return sum(1 for f in obj.extracted_fields.all() if f.is_active)
        return obj.extracted_fields.filter(is_active=True).count()


class DocumentCreateSerialiser(serializers.ModelSerializer):
    """
    Handles document upload with file validation.

    Accepts multipart/form-data with file upload. Validates file type
    and size. Business logic (hash computation, deduplication) handled
    by DocumentService.

    Request fields:
        file: Required. The document file (PDF, DOCX).
        title: Optional. Defaults to original filename.
        metadata: Optional. Additional metadata as JSON object.
        auto_extract: Optional. Trigger extraction immediately.

    Response includes links for subsequent operations.
    """

    file = serializers.FileField(write_only=True)
    auto_extract = serializers.BooleanField(default=False, write_only=True)

    # Response-only fields
    uploaded_by = UserBriefSerialiser(read_only=True)
    links = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            # Write fields
            "file",
            "title",
            "metadata",
            "auto_extract",
            # Read fields (response)
            "id",
            "original_filename",
            "file_type",
            "file_size_bytes",
            "file_hash",
            "status",
            "status_message",
            "uploaded_by",
            "created_at",
            "updated_at",
            "links",
        ]
        read_only_fields = [
            "id",
            "original_filename",
            "file_type",
            "file_size_bytes",
            "file_hash",
            "status",
            "status_message",
            "uploaded_by",
            "created_at",
            "updated_at",
        ]

    def validate_file(self, value):
        """
        Validate uploaded file type and size.

        Detailed validation (MIME type detection, hash computation)
        is performed in DocumentService.
        """
        # Basic extension check (service does thorough MIME detection)
        allowed_extensions = [".pdf", ".docx"]
        filename = value.name.lower()

        if not any(filename.endswith(ext) for ext in allowed_extensions):
            raise serializers.ValidationError(
                f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
            )

        # Size limit (50MB)
        max_size = 50 * 1024 * 1024
        if value.size > max_size:
            raise serializers.ValidationError(
                "File exceeds maximum size of 50MB."
            )

        return value

    def get_links(self, obj: Document) -> dict:
        """Generate HATEOAS-style links for the document."""
        base = f"/api/v1/documents/{obj.id}"
        return {
            "self": f"{base}/",
            "extract": f"{base}/extract/",
            "extractions": f"{base}/extractions/",
        }


class DocumentDetailSerialiser(serializers.ModelSerializer):
    """
    Full document representation with related data.

    Includes latest extraction summary, all active extracted fields,
    and navigation links. Used for retrieve endpoint.

    Requires prefetch_related for efficient loading:
        - proposed_extractions (for latest_extraction)
        - extracted_fields (filtered to is_active=True)
    """

    uploaded_by = UserBriefSerialiser(read_only=True)
    latest_extraction = serializers.SerializerMethodField()
    extracted_fields = serializers.SerializerMethodField()
    links = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "original_filename",
            "file_type",
            "file_size_bytes",
            "file_hash",
            "status",
            "status_message",
            "title",
            "metadata",
            "uploaded_by",
            "extraction_started_at",
            "extraction_completed_at",
            "created_at",
            "updated_at",
            "latest_extraction",
            "extracted_fields",
            "links",
        ]
        read_only_fields = fields

    def get_latest_extraction(self, obj: Document) -> dict | None:
        """
        Return summary of the most recent extraction.

        Uses prefetched data if available for efficiency.
        """
        # Check for prefetched extractions
        extractions = None
        if hasattr(obj, "_prefetched_objects_cache") and \
           "proposed_extractions" in obj._prefetched_objects_cache:
            extractions = list(obj.proposed_extractions.all())
        else:
            extractions = list(
                obj.proposed_extractions.order_by("-created_at")[:1]
            )

        if not extractions:
            return None

        # Get most recent (already ordered by -created_at)
        latest = extractions[0] if extractions else None
        if not latest:
            return None

        return LatestExtractionSerialiser(latest).data

    def get_extracted_fields(self, obj: Document) -> list[dict]:
        """
        Return all active extracted fields for this document.

        Uses prefetched data if available (should be filtered to is_active=True).
        """
        # Check for prefetched active fields
        if hasattr(obj, "active_fields"):
            fields = obj.active_fields
        elif hasattr(obj, "_prefetched_objects_cache") and \
             "extracted_fields" in obj._prefetched_objects_cache:
            fields = [f for f in obj.extracted_fields.all() if f.is_active]
        else:
            fields = obj.extracted_fields.filter(is_active=True)

        return ExtractedFieldBriefSerialiser(fields, many=True).data

    def get_links(self, obj: Document) -> dict:
        """Generate HATEOAS-style links for the document."""
        base = f"/api/v1/documents/{obj.id}"
        return {
            "self": f"{base}/",
            "download": f"{base}/download/",
            "extract": f"{base}/extract/",
            "extractions": f"{base}/extractions/",
        }


class TriggerExtractionRequestSerialiser(serializers.Serializer):
    """
    Request body for triggering document extraction.

    Used by POST /api/v1/documents/{id}/extract/ endpoint.
    """

    force = serializers.BooleanField(
        default=False,
        help_text="Re-extract even if extraction exists",
    )
    field_types = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_null=True,
        help_text="Specific fields to extract (default: all)",
    )


class TriggerExtractionResponseSerialiser(serializers.Serializer):
    """
    Response for async extraction task dispatch.

    Returned by POST /api/v1/documents/{id}/extract/ endpoint.
    """

    task_id = serializers.CharField(read_only=True)
    document_id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    estimated_duration_seconds = serializers.IntegerField(read_only=True)
    links = serializers.DictField(read_only=True)