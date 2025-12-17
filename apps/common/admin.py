"""
==============================================================================
FILE: admin.py
LOCATION: /docextract/apps/common/admin.py
==============================================================================

PURPOSE:
    Django admin configuration for common app models. Provides admin
    interface for Tenant management with appropriate field display
    and filtering.

MODELS REGISTERED:
    - Tenant: Multi-tenancy organisation management

USAGE:
    Access via Django admin at /admin/common/tenant/

FEATURES:
    - List view with name, slug, active status, timestamps
    - Search by name and slug
    - Filter by active status
    - Inline JSON editor for settings

==============================================================================
"""

from django.contrib import admin

from apps.common.models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    """
    Admin interface for Tenant model.

    Provides management of multi-tenant organisations with
    configuration settings.
    """

    list_display = (
        "name",
        "slug",
        "is_active",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "slug",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            None,
            {
                "fields": ("id", "name", "slug", "is_active"),
            },
        ),
        (
            "Configuration",
            {
                "fields": ("settings",),
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

    prepopulated_fields = {"slug": ("name",)}

    ordering = ("name",)