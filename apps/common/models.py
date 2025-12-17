"""
==============================================================================
FILE: models.py
LOCATION: /docextract/apps/common/models.py
==============================================================================

PURPOSE:
    Defines base model classes and mixins used across all Django apps, plus
    the core Tenant model for multi-tenancy isolation.

MODELS:
    - TimestampMixin: Adds created_at and updated_at fields to any model
    - TenantMixin: Adds tenant foreign key with scoped queries
    - Tenant: Organisational tenant for multi-tenancy isolation

USAGE:
    from apps.common.models import TimestampMixin, TenantMixin, Tenant

    class MyModel(TenantMixin, TimestampMixin, models.Model):
        # Your fields here
        pass

DESIGN DECISIONS:
    - UUID primary keys for distributed system compatibility
    - Abstract mixins to avoid multiple inheritance issues
    - Tenant settings stored as JSONB for flexible configuration
    - All tenant-scoped queries should filter by tenant_id

PERFORMANCE NOTES:
    - Tenant.slug is indexed for URL-based lookups
    - TimestampMixin uses auto_now/auto_now_add for efficiency
    - Consider select_related('tenant') when accessing tenant data

TESTING:
    - Use factory_boy to create test tenants
    - Test tenant isolation by creating data across multiple tenants

==============================================================================
"""

import uuid

from django.db import models


class TimestampMixin(models.Model):
    """
    Abstract mixin that adds created_at and updated_at timestamp fields.

    These fields are automatically managed by Django:
    - created_at: Set once when the record is first created
    - updated_at: Updated every time the record is saved
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when the record was created",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp when the record was last modified",
    )

    class Meta:
        abstract = True


class TenantMixin(models.Model):
    """
    Abstract mixin that adds tenant foreign key for multi-tenancy.

    All domain models should inherit from this mixin to ensure proper
    tenant isolation. Queries should always filter by tenant_id to
    prevent data leakage between organisations.

    The related_name uses %(class)s to generate unique reverse relations
    for each model that uses this mixin.
    """

    tenant = models.ForeignKey(
        "common.Tenant",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
        help_text="The tenant/organisation that owns this record",
    )

    class Meta:
        abstract = True


class Tenant(TimestampMixin, models.Model):
    """
    Organisational tenant for multi-tenancy isolation.

    All domain data is scoped to a tenant. Queries should always
    filter by tenant_id to prevent data leakage between organisations.

    Attributes:
        id: UUID primary key for distributed system compatibility
        name: Human-readable display name for the organisation
        slug: URL-safe identifier used in API paths and lookups
        is_active: Controls whether tenant users can access the system
        settings: JSONB field for tenant-specific configuration overrides
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        max_length=255,
        help_text="Display name for the tenant/organisation",
    )

    slug = models.SlugField(
        max_length=63,
        unique=True,
        help_text="URL-safe identifier, used in API paths",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Inactive tenants cannot access the system",
    )

    settings = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tenant-specific configuration overrides",
    )

    class Meta:
        db_table = "tenants"
        indexes = [
            models.Index(fields=["slug"], name="ix_tenants_slug"),
            models.Index(fields=["is_active"], name="ix_tenants_is_active"),
        ]
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"

    def __str__(self) -> str:
        return self.name