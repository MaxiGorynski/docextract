"""
==============================================================================
FILE: serialisers.py
LOCATION: /docextract/apps/extraction/serialisers.py
==============================================================================

PURPOSE:
    DRF serialisers for the Extractions API. Handles serialisation of
    ProposedExtraction, ProposedField, and related commit/reject operations.

SERIALISERS:
    - ProposedFieldSerialiser: Full field representation with provenance
    - ExtractionListSerialiser: Compact representation for list views
    - ExtractionDetailSerialiser: Full representation with nested fields
    - DocumentBriefSerialiser: Minimal document info for nested display
    - CommitRequestSerialiser: Request body for extraction commit
    - CommitResponseSerialiser: Response after successful commit
    - RejectRequestSerialiser: Request body for extraction rejection
    - RejectResponseSerialiser: Response after successful rejection
    - ActionBriefSerialiser: Minimal action info for nested display

USAGE:
    from apps.extraction.serialisers import (
        ExtractionListSerialiser,
        ExtractionDetailSerialiser,
        CommitRequestSerialiser,
    )

    # In viewset
    def get_serialiser_class(self):
        if self.action == 'list':
            return ExtractionListSerialiser
        return ExtractionDetailSerialiser

DESIGN DECISIONS:
    - Separate list/detail serialisers for payload optimisation
    - ProposedFieldSerialiser includes full provenance for review
    - Commit response includes action details for audit trail
    - Links provide HATEOAS navigation to related resources

PERFORMANCE NOTES:
    - ExtractionDetailSerialiser requires prefetch_related('fields')
    - List queries should use select_related('document', 'reviewed_by')

==============================================================================
"""

from rest_framework import serializers

from apps.extraction.models import (
    ProposedExtraction,
    ProposedField,
    ProposalStatus,
)


class DocumentBriefSerialiser(serializers.Serializer):
    """
    Minimal document representation for nested display.

    Used in extraction detail view to show source document info.
    """

    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(read_only=True)


class UserBriefSerialiser(serializers.Serializer):
    """
    Minimal user representation for nested display.

    Used in reviewed_by and similar fields.
    """

    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)


class ActionBriefSerialiser(serializers.Serializer):
    """
    Minimal action representation for nested display.

    Used in commit/reject responses to show action audit info.
    """

    id = serializers.UUIDField(read_only=True)
    action_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    is_reversible = serializers.BooleanField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class ProposedFieldSerialiser(serializers.ModelSerializer):
    """
    Full proposed field representation with provenance.

    Includes all information needed for human review:
    - Extracted value and normalised form
    - Source text and location for verification
    - Confidence score and reasoning
    - Validation status
    """

    class Meta:
        model = ProposedField
        fields = [
            "id",
            "field_type",
            "field_name",
            "value",
            "normalised_value",
            "source_text",
            "source_page",
            "source_location",
            "confidence",
            "confidence_reason",
            "validation_status",
            "validation_errors",
        ]
        read_only_fields = fields


class ExtractionListSerialiser(serializers.ModelSerializer):
    """
    Compact extraction representation for list views.

    Shows essential metadata without nested fields.
    Suitable for listing extractions for a document.
    """

    document_id = serializers.UUIDField(source="document.id", read_only=True)
    reviewed_by = UserBriefSerialiser(read_only=True)
    field_count = serializers.SerializerMethodField()

    class Meta:
        model = ProposedExtraction
        fields = [
            "id",
            "document_id",
            "status",
            "overall_confidence",
            "model_version",
            "processing_duration_ms",
            "field_count",
            "reviewed_by",
            "reviewed_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_field_count(self, obj: ProposedExtraction) -> int:
        """Return count of proposed fields in this extraction."""
        if hasattr(obj, "_prefetched_objects_cache") and \
           "fields" in obj._prefetched_objects_cache:
            return len(obj.fields.all())
        return obj.fields.count()


class ExtractionDetailSerialiser(serializers.ModelSerializer):
    """
    Full extraction representation with nested fields.

    Includes all information needed for review and commit decision:
    - Document reference
    - All proposed fields with provenance
    - AI model and execution metadata
    - Review status and notes
    - Navigation links
    """

    document = DocumentBriefSerialiser(read_only=True)
    fields = ProposedFieldSerialiser(many=True, read_only=True)
    reviewed_by = UserBriefSerialiser(read_only=True)
    committed_action = ActionBriefSerialiser(read_only=True)
    links = serializers.SerializerMethodField()

    class Meta:
        model = ProposedExtraction
        fields = [
            "id",
            "document",
            "status",
            "overall_confidence",
            "model_version",
            "agent_run_id",
            "processing_duration_ms",
            "token_usage",
            "fields",
            "review_notes",
            "reviewed_by",
            "reviewed_at",
            "committed_action",
            "created_at",
            "links",
        ]
        read_only_fields = fields

    def get_links(self, obj: ProposedExtraction) -> dict:
        """Generate HATEOAS-style links for the extraction."""
        base = f"/api/v1/extractions/{obj.id}"
        links = {
            "self": f"{base}/",
            "document": f"/api/v1/documents/{obj.document_id}/",
        }

        # Only include action links if in appropriate status
        if obj.status == ProposalStatus.PENDING:
            links["commit"] = f"{base}/commit/"
            links["reject"] = f"{base}/reject/"

        return links


class FieldOverrideSerialiser(serializers.Serializer):
    """
    Serialiser for field override values in commit request.

    Allows reviewer to correct values before committing.
    """

    value = serializers.CharField(required=False)
    normalised_value = serializers.JSONField(required=False)


class CommitRequestSerialiser(serializers.Serializer):
    """
    Request body for committing a proposed extraction.

    Allows optional review notes and field value corrections.

    Fields:
        review_notes: Optional reviewer comments.
        field_overrides: Dict mapping field IDs to corrected values.
    """

    review_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Reviewer comments",
    )
    field_overrides = serializers.DictField(
        child=FieldOverrideSerialiser(),
        required=False,
        allow_null=True,
        help_text="Corrections to proposed values: {field_id: {value, normalised_value}}",
    )

    def validate_field_overrides(self, value):
        """Validate field override structure."""
        if value is None:
            return {}

        # Ensure all keys are valid UUIDs
        import uuid
        for field_id in value.keys():
            try:
                uuid.UUID(str(field_id))
            except ValueError:
                raise serializers.ValidationError(
                    f"Invalid field ID format: {field_id}"
                )

        return value


class CommitResponseSerialiser(serializers.Serializer):
    """
    Response after successful extraction commit.

    Includes action audit details and navigation links.
    """

    extraction_id = serializers.UUIDField(read_only=True)
    action = ActionBriefSerialiser(read_only=True)
    committed_fields = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    links = serializers.DictField(read_only=True)


class RejectRequestSerialiser(serializers.Serializer):
    """
    Request body for rejecting a proposed extraction.

    Fields:
        reason: Required explanation for rejection.
        request_re_extraction: Whether to trigger a new extraction.
    """

    reason = serializers.CharField(
        required=True,
        help_text="Rejection reason",
    )
    request_re_extraction = serializers.BooleanField(
        default=False,
        help_text="Trigger new extraction after rejection",
    )

    def validate_reason(self, value):
        """Ensure reason is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "Rejection reason is required."
            )
        return value.strip()


class RejectResponseSerialiser(serializers.Serializer):
    """
    Response after successful extraction rejection.

    Includes action audit details and optional re-extraction task info.
    """

    extraction_id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    action = ActionBriefSerialiser(read_only=True)
    re_extraction_triggered = serializers.BooleanField(read_only=True)
    new_task_id = serializers.CharField(read_only=True, allow_null=True)