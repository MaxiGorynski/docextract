"""
==============================================================================
FILE: admin.py
LOCATION: /docextract/apps/extraction/admin.py
==============================================================================

PURPOSE:
    Django admin configuration for extraction models. This is the primary
    review interface for the two-phase commit workflow, allowing users to
    view proposed extractions, review individual fields, and commit or
    reject proposals.

MODELS REGISTERED:
    - ProposedExtraction: AI-generated extraction proposals
    - ProposedField: Individual extracted fields (inline)
    - ExtractedField: Committed canonical fields

USAGE:
    Access via Django admin at /admin/extraction/

FEATURES:
    - ProposedExtraction list with status badges and confidence scores
    - Inline ProposedField display with confidence indicators
    - Commit and Reject admin actions
    - Link to source document
    - ExtractedField read-only viewer

==============================================================================
"""

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone

from apps.extraction.models import (
    ProposedExtraction,
    ProposedField,
    ExtractedField,
    ProposalStatus,
)


class ProposedFieldInline(admin.TabularInline):
    """
    Inline display of ProposedFields within ProposedExtraction.

    Shows all extracted fields with their values, confidence scores,
    and source information for review.
    """

    model = ProposedField
    extra = 0
    can_delete = False

    fields = (
        "field_type",
        "field_name",
        "value",
        "confidence_display",
        "source_page",
        "validation_status",
    )

    readonly_fields = (
        "field_type",
        "field_name",
        "value",
        "confidence_display",
        "source_page",
        "validation_status",
    )

    ordering = ("field_type",)

    def has_add_permission(self, request, obj=None):
        """Disable adding fields manually."""
        return False

    @admin.display(description="Confidence")
    def confidence_display(self, obj):
        """Display confidence as a coloured percentage."""
        confidence = obj.confidence
        if confidence >= 0.9:
            colour = "#198754"  # Green
        elif confidence >= 0.7:
            colour = "#fd7e14"  # Orange
        else:
            colour = "#dc3545"  # Red

        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.0%}</span>',
            colour,
            confidence,
        )


@admin.register(ProposedExtraction)
class ProposedExtractionAdmin(admin.ModelAdmin):
    """
    Admin interface for ProposedExtraction model.

    This is the primary review interface for the two-phase commit
    workflow. Users can view proposals, review fields, and commit
    or reject extractions.
    """

    list_display = (
        "id_short",
        "document_link",
        "tenant",
        "status_badge",
        "confidence_badge",
        "field_count",
        "model_version",
        "created_at",
    )

    list_filter = (
        "status",
        "tenant",
        "model_version",
        "created_at",
    )

    search_fields = (
        "document__original_filename",
        "document__title",
        "agent_run_id",
    )

    readonly_fields = (
        "id",
        "document_link_detail",
        "status_badge_large",
        "confidence_badge_large",
        "agent_run_id",
        "model_version",
        "prompt_hash",
        "token_usage",
        "processing_duration_display",
        "reviewed_by",
        "reviewed_at",
        "committed_action_link",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "tenant",
                    "document_link_detail",
                    "status_badge_large",
                ),
            },
        ),
        (
            "Quality Metrics",
            {
                "fields": (
                    "confidence_badge_large",
                    "processing_duration_display",
                ),
            },
        ),
        (
            "AI Execution",
            {
                "fields": (
                    "agent_run_id",
                    "model_version",
                    "prompt_hash",
                    "token_usage",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Review",
            {
                "fields": (
                    "review_notes",
                    "reviewed_by",
                    "reviewed_at",
                    "committed_action_link",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [ProposedFieldInline]

    list_per_page = 25
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    actions = [
        "commit_extraction_action",
        "reject_extraction_action",
    ]

    def get_queryset(self, request):
        """Annotate queryset with field count."""
        qs = super().get_queryset(request)
        return qs.annotate(
            _field_count=Count("fields")
        ).select_related("tenant", "document", "reviewed_by", "committed_action")

    @admin.display(description="ID")
    def id_short(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8]

    @admin.display(description="Document")
    def document_link(self, obj):
        """Display document name with link."""
        url = reverse("admin:documents_document_change", args=[obj.document_id])
        filename = obj.document.original_filename
        if len(filename) > 30:
            filename = filename[:27] + "..."
        return format_html('<a href="{}">{}</a>', url, filename)

    @admin.display(description="Document")
    def document_link_detail(self, obj):
        """Display document link for detail view."""
        url = reverse("admin:documents_document_change", args=[obj.document_id])
        return format_html(
            '<a href="{}" class="button" style="padding: 5px 15px;">'
            '{} →</a>',
            url,
            obj.document.original_filename,
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        """Display status as a coloured badge."""
        colours = {
            ProposalStatus.PENDING: "#fd7e14",     # Orange
            ProposalStatus.APPROVED: "#0d6efd",    # Blue
            ProposalStatus.COMMITTED: "#198754",   # Green
            ProposalStatus.REJECTED: "#dc3545",    # Red
            ProposalStatus.SUPERSEDED: "#6c757d",  # Grey
        }
        colour = colours.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Status")
    def status_badge_large(self, obj):
        """Display larger status badge for detail view."""
        colours = {
            ProposalStatus.PENDING: "#fd7e14",
            ProposalStatus.APPROVED: "#0d6efd",
            ProposalStatus.COMMITTED: "#198754",
            ProposalStatus.REJECTED: "#dc3545",
            ProposalStatus.SUPERSEDED: "#6c757d",
        }
        colour = colours.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 8px 20px; '
            'border-radius: 4px; font-size: 16px; font-weight: bold;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Confidence")
    def confidence_badge(self, obj):
        """Display confidence as a coloured percentage."""
        confidence = obj.overall_confidence
        if confidence >= 0.9:
            colour = "#198754"  # Green
        elif confidence >= 0.7:
            colour = "#fd7e14"  # Orange
        else:
            colour = "#dc3545"  # Red

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}%</span>',
            colour,
            int(confidence * 100),
        )

    @admin.display(description="Overall Confidence")
    def confidence_badge_large(self, obj):
        """Display larger confidence badge for detail view."""
        confidence = obj.overall_confidence
        if confidence >= 0.9:
            colour = "#198754"
            label = "High"
        elif confidence >= 0.7:
            colour = "#fd7e14"
            label = "Medium"
        else:
            colour = "#dc3545"
            label = "Low"

        return format_html(
            '<span style="background-color: {}; color: white; padding: 6px 16px; '
            'border-radius: 4px; font-size: 14px; font-weight: bold;">'
            '{:.0%} ({})</span>',
            colour,
            confidence,
            label,
        )

    @admin.display(description="Fields")
    def field_count(self, obj):
        """Display count of proposed fields."""
        count = getattr(obj, "_field_count", 0)
        return count

    @admin.display(description="Processing Time")
    def processing_duration_display(self, obj):
        """Display processing duration in human-readable format."""
        ms = obj.processing_duration_ms
        if ms < 1000:
            return f"{ms}ms"
        return f"{ms / 1000:.2f}s"

    @admin.display(description="Committed Action")
    def committed_action_link(self, obj):
        """Display link to committed action if exists."""
        if not obj.committed_action_id:
            return "—"
        url = reverse("admin:actions_action_change", args=[obj.committed_action_id])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            str(obj.committed_action_id)[:8],
        )

    @admin.action(description="Commit selected extractions")
    def commit_extraction_action(self, request, queryset):
        """Admin action to commit selected extractions."""
        from uuid import uuid4
        from apps.common.services import ServiceContext
        from apps.extraction.services import ExtractionService

        committed = 0
        skipped = 0
        errors = []

        for extraction in queryset:
            if extraction.status != ProposalStatus.PENDING:
                skipped += 1
                continue

            context = ServiceContext(
                tenant_id=extraction.tenant_id,
                actor_id=str(request.user.id),
                actor_type="user",
                trace_id=f"admin-{uuid4()}",
                feature_flags={},
            )

            service = ExtractionService(context)
            result = service.commit_extraction(
                extraction_id=extraction.id,
                review_notes=f"Committed via admin by {request.user.username}",
            )

            if result.success:
                committed += 1
            else:
                errors.append(f"{extraction.id}: {result.error}")

        message = f"Committed {committed} extraction(s). Skipped {skipped}."
        if errors:
            message += f" Errors: {'; '.join(errors[:3])}"

        self.message_user(request, message)

    @admin.action(description="Reject selected extractions")
    def reject_extraction_action(self, request, queryset):
        """Admin action to reject selected extractions."""
        from uuid import uuid4
        from apps.common.services import ServiceContext
        from apps.extraction.services import ExtractionService

        rejected = 0
        skipped = 0

        for extraction in queryset:
            if extraction.status != ProposalStatus.PENDING:
                skipped += 1
                continue

            context = ServiceContext(
                tenant_id=extraction.tenant_id,
                actor_id=str(request.user.id),
                actor_type="user",
                trace_id=f"admin-{uuid4()}",
                feature_flags={},
            )

            service = ExtractionService(context)
            result = service.reject_extraction(
                extraction_id=extraction.id,
                reason=f"Rejected via admin by {request.user.username}",
            )

            if result.success:
                rejected += 1

        self.message_user(
            request,
            f"Rejected {rejected} extraction(s). Skipped {skipped}.",
        )


@admin.register(ExtractedField)
class ExtractedFieldAdmin(admin.ModelAdmin):
    """
    Admin interface for ExtractedField model.

    Read-only view of committed extraction fields. These are the
    canonical extracted values.
    """

    list_display = (
        "id_short",
        "document_link",
        "field_type",
        "field_name",
        "value_short",
        "confidence_display",
        "is_active_badge",
        "committed_at",
    )

    list_filter = (
        "is_active",
        "field_type",
        "tenant",
        "committed_at",
    )

    search_fields = (
        "document__original_filename",
        "field_name",
        "value",
    )

    readonly_fields = (
        "id",
        "tenant",
        "document",
        "source_proposal",
        "source_proposed_field",
        "field_type",
        "field_name",
        "value",
        "normalised_value",
        "source_text",
        "source_page",
        "source_location",
        "confidence",
        "committed_by",
        "committed_at",
        "committed_action",
        "is_active",
        "deactivated_at",
        "deactivated_by_action",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "tenant",
                    "document",
                    "is_active",
                ),
            },
        ),
        (
            "Field Data",
            {
                "fields": (
                    "field_type",
                    "field_name",
                    "value",
                    "normalised_value",
                    "confidence",
                ),
            },
        ),
        (
            "Provenance",
            {
                "fields": (
                    "source_text",
                    "source_page",
                    "source_location",
                    "source_proposal",
                    "source_proposed_field",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Commit Details",
            {
                "fields": (
                    "committed_by",
                    "committed_at",
                    "committed_action",
                ),
            },
        ),
        (
            "Deactivation",
            {
                "fields": (
                    "deactivated_at",
                    "deactivated_by_action",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    list_per_page = 25
    ordering = ("-committed_at",)

    def has_add_permission(self, request):
        """Disable manual creation of extracted fields."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable editing of extracted fields."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deletion of extracted fields."""
        return False

    @admin.display(description="ID")
    def id_short(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8]

    @admin.display(description="Document")
    def document_link(self, obj):
        """Display document name with link."""
        url = reverse("admin:documents_document_change", args=[obj.document_id])
        filename = obj.document.original_filename
        if len(filename) > 25:
            filename = filename[:22] + "..."
        return format_html('<a href="{}">{}</a>', url, filename)

    @admin.display(description="Value")
    def value_short(self, obj):
        """Display shortened value."""
        value = obj.value
        if len(value) > 40:
            return value[:37] + "..."
        return value

    @admin.display(description="Confidence")
    def confidence_display(self, obj):
        """Display confidence as a coloured percentage."""
        confidence = obj.confidence
        if confidence >= 0.9:
            colour = "#198754"
        elif confidence >= 0.7:
            colour = "#fd7e14"
        else:
            colour = "#dc3545"

        return format_html(
            '<span style="color: {}; font-weight: bold;">{}%</span>',
            colour,
            int(confidence * 100),
        )

    @admin.display(description="Active")
    def is_active_badge(self, obj):
        """Display active status as a badge."""
        if obj.is_active:
            return format_html(
                '<span style="color: #198754; font-weight: bold;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: #dc3545; font-weight: bold;">✗ Inactive</span>'
        )