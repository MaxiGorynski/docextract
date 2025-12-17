"""
==============================================================================
FILE: admin.py
LOCATION: /docextract/apps/features/admin.py
==============================================================================

PURPOSE:
    Django admin configuration for FeatureFlag model. Provides management
    interface for feature flags with rollout controls and tenant overrides.

MODELS REGISTERED:
    - FeatureFlag: Feature toggle configuration

USAGE:
    Access via Django admin at /admin/features/featureflag/

FEATURES:
    - List view with enabled status and rollout percentage
    - Tenant override management
    - Expiry date tracking
    - Search by key and description

==============================================================================
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from apps.features.models import FeatureFlag


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    """
    Admin interface for FeatureFlag model.

    Provides feature flag management with rollout controls,
    tenant overrides, and expiry tracking.
    """

    list_display = (
        "key",
        "is_enabled_badge",
        "rollout_display",
        "tenant_overrides_summary",
        "owner",
        "expiry_status",
        "updated_at",
    )

    list_filter = (
        "is_enabled",
        "owner",
        "created_at",
    )

    search_fields = (
        "key",
        "description",
        "owner",
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
                "fields": (
                    "id",
                    "key",
                    "description",
                    "is_enabled",
                ),
            },
        ),
        (
            "Rollout Configuration",
            {
                "fields": (
                    "rollout_percentage",
                ),
            },
        ),
        (
            "Tenant Overrides",
            {
                "fields": (
                    "enabled_tenants",
                    "disabled_tenants",
                ),
                "description": (
                    "Enter tenant UUIDs as a JSON array. "
                    "Example: [\"uuid-1\", \"uuid-2\"]"
                ),
            },
        ),
        (
            "Management",
            {
                "fields": (
                    "owner",
                    "expires_at",
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

    ordering = ("key",)
    list_per_page = 25

    @admin.display(description="Enabled")
    def is_enabled_badge(self, obj):
        """Display enabled status as a badge."""
        if obj.is_enabled:
            return format_html(
                '<span style="background-color: #198754; color: white; '
                'padding: 3px 10px; border-radius: 3px; font-weight: bold;">'
                'ON</span>'
            )
        return format_html(
            '<span style="background-color: #dc3545; color: white; '
            'padding: 3px 10px; border-radius: 3px; font-weight: bold;">'
            'OFF</span>'
        )

    @admin.display(description="Rollout")
    def rollout_display(self, obj):
        """Display rollout percentage with visual indicator."""
        percentage = obj.rollout_percentage

        # Colour based on percentage
        if percentage >= 100:
            colour = "#198754"  # Green - full rollout
        elif percentage >= 50:
            colour = "#0d6efd"  # Blue - majority
        elif percentage > 0:
            colour = "#fd7e14"  # Orange - partial
        else:
            colour = "#dc3545"  # Red - disabled

        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.0f}%</span>',
            colour,
            percentage,
        )

    @admin.display(description="Tenant Overrides")
    def tenant_overrides_summary(self, obj):
        """Display summary of tenant overrides."""
        enabled_count = len(obj.enabled_tenants) if obj.enabled_tenants else 0
        disabled_count = len(obj.disabled_tenants) if obj.disabled_tenants else 0

        if enabled_count == 0 and disabled_count == 0:
            return "—"

        parts = []
        if enabled_count > 0:
            parts.append(format_html(
                '<span style="color: #198754;">+{}</span>',
                enabled_count,
            ))
        if disabled_count > 0:
            parts.append(format_html(
                '<span style="color: #dc3545;">-{}</span>',
                disabled_count,
            ))

        return format_html(" / ".join(str(p) for p in parts))

    @admin.display(description="Expiry")
    def expiry_status(self, obj):
        """Display expiry status with visual indicator."""
        if not obj.expires_at:
            return "—"

        now = timezone.now()
        if obj.expires_at < now:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;" '
                'title="{}">EXPIRED</span>',
                obj.expires_at.strftime("%Y-%m-%d %H:%M"),
            )

        # Calculate days until expiry
        delta = obj.expires_at - now
        days = delta.days

        if days <= 7:
            colour = "#fd7e14"  # Orange - expiring soon
        else:
            colour = "#6c757d"  # Grey - OK

        return format_html(
            '<span style="color: {};" title="{}">{} days</span>',
            colour,
            obj.expires_at.strftime("%Y-%m-%d %H:%M"),
            days,
        )