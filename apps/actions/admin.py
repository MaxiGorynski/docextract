"""
==============================================================================
FILE: admin.py
LOCATION: /docextract/apps/actions/admin.py
==============================================================================

PURPOSE:
    Django admin configuration for Action model. Provides a read-only
    audit log viewer for all state changes in the system.

MODELS REGISTERED:
    - Action: Immutable audit records

USAGE:
    Access via Django admin at /admin/actions/action/

FEATURES:
    - Read-only audit log viewer
    - Filter by action type, status, actor
    - View pre/post state JSON
    - Trace ID search for request correlation
    - Rollback chain visualisation

NOTE:
    Actions are immutable. The admin interface is read-only by design
    to preserve audit integrity.

==============================================================================
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from apps.actions.models import Action, ActionType, ActionStatus


@admin.register(Action)
class ActionAdmin(admin.ModelAdmin):
    """
    Admin interface for Action model.

    Provides a read-only audit log viewer for all state changes.
    Actions are immutable and cannot be edited or deleted.
    """

    list_display = (
        "id_short",
        "action_type_badge",
        "status_badge",
        "target_display",
        "actor_display",
        "trace_id_short",
        "is_reversible_badge",
        "created_at",
    )

    list_filter = (
        "action_type",
        "status",
        "actor_type",
        "is_reversible",
        "created_at",
    )

    search_fields = (
        "trace_id",
        "actor_id",
        "actor_email",
        "target_id",
        "idempotency_key",
    )

    readonly_fields = (
        "id",
        "action_type",
        "status_badge_large",
        "actor_type",
        "actor_id",
        "actor_email",
        "target_type",
        "target_id",
        "target_link",
        "tenant_id",
        "trace_id",
        "idempotency_key",
        "pre_state_display",
        "post_state_display",
        "is_reversible",
        "reversed_by_link",
        "reverses_link",
        "metadata_display",
        "error_message",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "action_type",
                    "status_badge_large",
                ),
            },
        ),
        (
            "Actor",
            {
                "fields": (
                    "actor_type",
                    "actor_id",
                    "actor_email",
                ),
            },
        ),
        (
            "Target",
            {
                "fields": (
                    "target_type",
                    "target_id",
                    "target_link",
                    "tenant_id",
                ),
            },
        ),
        (
            "Tracing",
            {
                "fields": (
                    "trace_id",
                    "idempotency_key",
                ),
            },
        ),
        (
            "State Capture",
            {
                "fields": (
                    "pre_state_display",
                    "post_state_display",
                ),
            },
        ),
        (
            "Reversibility",
            {
                "fields": (
                    "is_reversible",
                    "reversed_by_link",
                    "reverses_link",
                ),
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "metadata_display",
                    "error_message",
                ),
                "classes": ("collapse",),
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

    list_per_page = 50
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        """Disable manual creation of actions."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable editing of actions (immutable)."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable deletion of actions (immutable audit log)."""
        return False

    @admin.display(description="ID")
    def id_short(self, obj):
        """Display shortened UUID."""
        return str(obj.id)[:8]

    @admin.display(description="Action Type")
    def action_type_badge(self, obj):
        """Display action type as a styled badge."""
        colours = {
            ActionType.COMMIT_EXTRACTION: "#198754",    # Green
            ActionType.ROLLBACK_EXTRACTION: "#fd7e14",  # Orange
            ActionType.REJECT_EXTRACTION: "#dc3545",    # Red
            ActionType.DOCUMENT_UPLOAD: "#0d6efd",      # Blue
            ActionType.DOCUMENT_DELETE: "#6c757d",      # Grey
            ActionType.UPDATE_FIELD: "#0dcaf0",         # Cyan
            ActionType.DELETE_FIELD: "#6c757d",         # Grey
        }
        colour = colours.get(obj.action_type, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 10px; font-weight: bold;">{}</span>',
            colour,
            obj.get_action_type_display(),
        )

    @admin.display(description="Status")
    def status_badge(self, obj):
        """Display status as a coloured badge."""
        colours = {
            ActionStatus.PENDING: "#fd7e14",     # Orange
            ActionStatus.COMPLETED: "#198754",   # Green
            ActionStatus.FAILED: "#dc3545",      # Red
            ActionStatus.ROLLED_BACK: "#6c757d", # Grey
        }
        colour = colours.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 10px; font-weight: bold;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Status")
    def status_badge_large(self, obj):
        """Display larger status badge for detail view."""
        colours = {
            ActionStatus.PENDING: "#fd7e14",
            ActionStatus.COMPLETED: "#198754",
            ActionStatus.FAILED: "#dc3545",
            ActionStatus.ROLLED_BACK: "#6c757d",
        }
        colour = colours.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 8px 20px; '
            'border-radius: 4px; font-size: 16px; font-weight: bold;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Target")
    def target_display(self, obj):
        """Display target type and shortened ID."""
        target_id = obj.target_id
        if len(target_id) > 8:
            target_id = target_id[:8]
        return f"{obj.target_type}:{target_id}"

    @admin.display(description="Target")
    def target_link(self, obj):
        """Attempt to link to the target object."""
        # Map target types to admin URLs
        url_map = {
            "ProposedExtraction": "extraction_proposedextraction_change",
            "Document": "documents_document_change",
            "ExtractedField": "extraction_extractedfield_change",
        }

        url_name = url_map.get(obj.target_type)
        if url_name:
            try:
                url = reverse(f"admin:{url_name}", args=[obj.target_id])
                return format_html(
                    '<a href="{}">{}: {}</a>',
                    url,
                    obj.target_type,
                    obj.target_id[:8],
                )
            except Exception:
                pass

        return f"{obj.target_type}: {obj.target_id}"

    @admin.display(description="Actor")
    def actor_display(self, obj):
        """Display actor type and ID."""
        if obj.actor_email:
            return f"{obj.actor_email}"
        return f"{obj.actor_type}:{obj.actor_id[:8]}"

    @admin.display(description="Trace ID")
    def trace_id_short(self, obj):
        """Display shortened trace ID."""
        trace = obj.trace_id
        if len(trace) > 12:
            return trace[:12] + "..."
        return trace

    @admin.display(description="Reversible")
    def is_reversible_badge(self, obj):
        """Display reversibility as icon."""
        if obj.is_reversible:
            if obj.reversed_by_id:
                return format_html(
                    '<span style="color: #6c757d;" title="Reversed">↩ Reversed</span>'
                )
            return format_html(
                '<span style="color: #198754;" title="Can be reversed">✓</span>'
            )
        return format_html(
            '<span style="color: #dc3545;" title="Cannot be reversed">✗</span>'
        )

    @admin.display(description="Pre-State")
    def pre_state_display(self, obj):
        """Display pre-state as formatted JSON."""
        import json
        formatted = json.dumps(obj.pre_state, indent=2, default=str)
        return format_html(
            '<pre style="background: #f8f9fa; padding: 10px; border-radius: 4px; '
            'max-height: 200px; overflow: auto; font-size: 12px;">{}</pre>',
            formatted,
        )

    @admin.display(description="Post-State")
    def post_state_display(self, obj):
        """Display post-state as formatted JSON."""
        import json
        formatted = json.dumps(obj.post_state, indent=2, default=str)
        return format_html(
            '<pre style="background: #f8f9fa; padding: 10px; border-radius: 4px; '
            'max-height: 200px; overflow: auto; font-size: 12px;">{}</pre>',
            formatted,
        )

    @admin.display(description="Metadata")
    def metadata_display(self, obj):
        """Display metadata as formatted JSON."""
        import json
        if not obj.metadata:
            return "—"
        formatted = json.dumps(obj.metadata, indent=2, default=str)
        return format_html(
            '<pre style="background: #f8f9fa; padding: 10px; border-radius: 4px; '
            'max-height: 150px; overflow: auto; font-size: 12px;">{}</pre>',
            formatted,
        )

    @admin.display(description="Reversed By")
    def reversed_by_link(self, obj):
        """Link to the action that reversed this one."""
        if not obj.reversed_by_id:
            return "—"
        url = reverse("admin:actions_action_change", args=[obj.reversed_by_id])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            str(obj.reversed_by_id)[:8],
        )

    @admin.display(description="Reverses")
    def reverses_link(self, obj):
        """Link to the action this one reverses."""
        if not obj.reverses_id:
            return "—"
        url = reverse("admin:actions_action_change", args=[obj.reverses_id])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            str(obj.reverses_id)[:8],
        )