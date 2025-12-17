"""
==============================================================================
FILE: models.py
LOCATION: /docextract/apps/features/models.py
==============================================================================

PURPOSE:
    Defines the FeatureFlag model for progressive rollout, kill switches,
    and tenant-specific feature toggling.

MODELS:
    - FeatureFlag: Database-backed feature flag with rollout controls

USAGE:
    from apps.features.models import FeatureFlag

    # Check if flag is enabled globally
    flag = FeatureFlag.objects.get(key='ai_extraction_enabled')
    if flag.is_enabled_for_tenant(tenant_id):
        # Feature is enabled
        pass

MVP NOTE:
    For the initial MVP, feature flags are managed via Django settings
    (see apps.features.middleware.FeatureFlagMiddleware). This database
    model enables future migration to database-backed flags without
    code changes.

DESIGN DECISIONS:
    - UUID primary keys for consistency with other models
    - Tenant overrides via JSONB arrays for flexibility
    - Rollout percentage for gradual feature releases
    - Expiry date for temporary flags and experiments

PERFORMANCE NOTES:
    - Flags are typically cached in middleware per-request
    - Index on 'key' for fast lookups
    - Consider Redis caching for high-traffic deployments

TESTING:
    - Test rollout_percentage with deterministic seeds
    - Test tenant override logic (enabled > disabled > percentage)

==============================================================================
"""

import uuid

from django.core.validators import MaxValueValidator
from django.db import models

from apps.common.models import TimestampMixin


class FeatureFlag(TimestampMixin, models.Model):
    """
    Feature flag for progressive rollout and kill switches.

    Flags support multiple evaluation strategies:
    1. Global is_enabled toggle (master switch)
    2. Tenant-specific overrides (enabled_tenants, disabled_tenants)
    3. Percentage-based rollout (rollout_percentage)

    Evaluation order:
    1. If tenant_id in disabled_tenants → False
    2. If tenant_id in enabled_tenants → True
    3. If is_enabled is False → False
    4. Apply rollout_percentage based on tenant_id hash

    Attributes:
        key: Unique identifier for the flag (e.g., 'ai_extraction_enabled')
        description: Human-readable explanation of what the flag controls
        is_enabled: Master switch - if False, flag is disabled for everyone
        rollout_percentage: Percentage of tenants who see this enabled (0-100)
        enabled_tenants: List of tenant UUIDs where flag is always enabled
        disabled_tenants: List of tenant UUIDs where flag is always disabled
        owner: Team or person responsible for this flag
        expires_at: Optional auto-disable timestamp for temporary flags
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    key = models.CharField(
        max_length=100,
        unique=True,
        help_text="Flag identifier (e.g., 'ai_extraction_enabled')",
    )

    description = models.TextField(
        blank=True,
        help_text="What this flag controls",
    )

    # Global state
    is_enabled = models.BooleanField(
        default=False,
        help_text="Master switch - if False, flag is disabled for everyone",
    )

    # Rollout configuration
    rollout_percentage = models.PositiveIntegerField(
        default=100,
        validators=[MaxValueValidator(100)],
        help_text="Percentage of tenants who see this enabled (0-100)",
    )

    # Tenant overrides
    enabled_tenants = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tenant UUIDs where flag is always enabled",
    )

    disabled_tenants = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tenant UUIDs where flag is always disabled",
    )

    # Metadata
    owner = models.CharField(
        max_length=100,
        blank=True,
        help_text="Team or person responsible for this flag",
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Auto-disable after this time",
    )

    class Meta:
        db_table = "feature_flags"
        indexes = [
            models.Index(fields=["key"], name="ix_feature_flags_key"),
            models.Index(fields=["is_enabled"], name="ix_feature_flags_enabled"),
        ]
        verbose_name = "Feature Flag"
        verbose_name_plural = "Feature Flags"

    def __str__(self) -> str:
        status = "enabled" if self.is_enabled else "disabled"
        return f"{self.key} ({status})"

    def is_enabled_for_tenant(self, tenant_id: str) -> bool:
        """
        Evaluate whether this flag is enabled for a specific tenant.

        Evaluation order:
        1. Check disabled_tenants (explicit deny)
        2. Check enabled_tenants (explicit allow)
        3. Check is_enabled master switch
        4. Apply rollout_percentage

        Args:
            tenant_id: UUID string of the tenant to check

        Returns:
            True if the flag is enabled for this tenant, False otherwise
        """
        from django.utils import timezone

        # Check expiry first
        if self.expires_at and timezone.now() > self.expires_at:
            return False

        tenant_id_str = str(tenant_id)

        # Explicit deny takes precedence
        if tenant_id_str in [str(t) for t in self.disabled_tenants]:
            return False

        # Explicit allow
        if tenant_id_str in [str(t) for t in self.enabled_tenants]:
            return True

        # Master switch
        if not self.is_enabled:
            return False

        # Percentage rollout (deterministic based on tenant_id)
        if self.rollout_percentage >= 100:
            return True

        if self.rollout_percentage <= 0:
            return False

        # Use hash of tenant_id for deterministic percentage check
        hash_value = hash(tenant_id_str) % 100
        return hash_value < self.rollout_percentage