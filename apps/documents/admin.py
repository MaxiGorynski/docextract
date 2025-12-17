"""
==============================================================================
FILE: admin.py
LOCATION: /docextract/apps/documents/admin.py
==============================================================================

PURPOSE:
    Django admin configuration for Document model. Provides a rich interface
    for document management with status badges, file preview, and extraction
    triggering capabilities.

MODELS REGISTERED:
    - Document: Uploaded documents with extraction status

USAGE:
    Access via Django admin at /admin/documents/document/

FEATURES:
    - List view with coloured status badges
    - File size display in human-readable format
    - Link to view proposed extractions
    - Search by filename and title
    - Filter by status, tenant, upload date
    - Custom action to trigger extraction

==============================================================================
"""

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html
from django.urls import reverse

from apps.documents.models import Document, DocumentStatus


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """
    Admin interface for Document model.

    Provides document management with visual status indicators,
    extraction controls, and related data access.
    """

    list_display = (
        "original_filename",
        "tenant",
        "status_badge",
        "file_type_short",
        "file_size_display",
        "extraction_count",
        "uploaded_by",
        "created_at",
    )

    list_filter = (
        "status",
        "tenant",
        "file_type",
        "created_at",
    )

    search_fields = (
        "original_filename",
        "title",
        "file_hash",
    )

    readonly_fields = (
        "id",
        "file_hash",
        "file_size_bytes",
        "status_badge_large",
        "extraction_link",
        "extraction_started_at",
        "extraction_completed_at",
        "extraction_duration",
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
                    "title",
                    "file",
                    "original_filename",
                ),
            },
        ),
        (
            "File Details",
            {
                "fields": (
                    "file_type",
                    "file_size_bytes",
                    "file_hash",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status_badge_large",
                    "status",
                    "status_message",
                ),
            },
        ),
        (
            "Extraction",
            {
                "fields": (
                    "extraction_link",
                    "extraction_started_at",
                    "extraction_completed_at",
                    "extraction_duration",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("metadata",),
                "classes": ("collapse",),
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "uploaded_by",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    list_per_page = 25
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    actions = ["trigger_extraction_action"]

    def get_queryset(self, request):
        """Annotate queryset with extraction count."""
        qs = super().get_queryset(request)
        return qs.annotate(
            _extraction_count=Count("proposed_extractions")
        ).select_related("tenant", "uploaded_by")

    @admin.display(description="Status")
    def status_badge(self, obj):
        """Display status as a coloured badge."""
        colours = {
            DocumentStatus.PENDING: "#6c757d",      # Grey
            DocumentStatus.PROCESSING: "#0d6efd",   # Blue
            DocumentStatus.EXTRACTED: "#198754",    # Green
            DocumentStatus.FAILED: "#dc3545",       # Red
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
            DocumentStatus.PENDING: "#6c757d",
            DocumentStatus.PROCESSING: "#0d6efd",
            DocumentStatus.EXTRACTED: "#198754",
            DocumentStatus.FAILED: "#dc3545",
        }
        colour = colours.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 6px 16px; '
            'border-radius: 4px; font-size: 14px; font-weight: bold;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Type")
    def file_type_short(self, obj):
        """Display shortened file type."""
        type_map = {
            "application/pdf": "PDF",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
        }
        return type_map.get(obj.file_type, obj.file_type[:10])

    @admin.display(description="Size")
    def file_size_display(self, obj):
        """Display file size in human-readable format."""
        size = obj.file_size_bytes
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @admin.display(description="Extractions")
    def extraction_count(self, obj):
        """Display count of proposed extractions with link."""
        count = getattr(obj, "_extraction_count", 0)
        if count == 0:
            return "—"

        url = reverse("admin:extraction_proposedextraction_changelist")
        return format_html(
            '<a href="{}?document__id__exact={}">{} extraction(s)</a>',
            url,
            obj.id,
            count,
        )

    @admin.display(description="View Extractions")
    def extraction_link(self, obj):
        """Link to related extractions in detail view."""
        url = reverse("admin:extraction_proposedextraction_changelist")
        return format_html(
            '<a href="{}?document__id__exact={}" class="button" '
            'style="padding: 5px 15px;">View Extractions →</a>',
            url,
            obj.id,
        )

    @admin.display(description="Processing Duration")
    def extraction_duration(self, obj):
        """Display extraction duration if available."""
        duration = obj.extraction_duration_ms
        if duration is None:
            return "—"
        if duration < 1000:
            return f"{duration}ms"
        return f"{duration / 1000:.2f}s"

    @admin.action(description="Trigger extraction for selected documents")
    def trigger_extraction_action(self, request, queryset):
        """Admin action to trigger extraction for selected documents."""
        from uuid import uuid4
        from apps.common.services import ServiceContext
        from apps.documents.services import DocumentService

        triggered = 0
        skipped = 0

        for document in queryset:
            # Create service context
            context = ServiceContext(
                tenant_id=document.tenant_id,
                actor_id=str(request.user.id),
                actor_type="user",
                trace_id=f"admin-{uuid4()}",
                feature_flags={"ai_extraction_enabled": True},
            )

            service = DocumentService(context)
            result = service.trigger_extraction(document.id, force=True)

            if result.success:
                triggered += 1
            else:
                skipped += 1

        self.message_user(
            request,
            f"Triggered extraction for {triggered} document(s). "
            f"Skipped {skipped} document(s).",
        )