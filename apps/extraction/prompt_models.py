"""
==============================================================================
FILE: prompt_models.py
LOCATION: /docextract/apps/extraction/prompt_models.py
==============================================================================

PURPOSE:
    Defines the PromptTemplate model for storing and versioning extraction
    prompts. Allows users to view and edit the prompts sent to OpenAI.

MODELS:
    - PromptTemplate: Stores system and user prompt templates

USAGE:
    from apps.extraction.prompt_models import PromptTemplate

    # Get the active prompt template
    template = PromptTemplate.objects.filter(is_active=True).first()

    # Use in extraction
    system_prompt = template.system_prompt
    user_prompt = template.user_prompt_template.format(doc_type=doc_type, ...)

INTEGRATION:
    Add to apps/extraction/models.py:
        from .prompt_models import PromptTemplate

    Then run:
        python manage.py makemigrations extraction
        python manage.py migrate

==============================================================================
"""

import uuid

from django.db import models
from django.contrib.auth import get_user_model

from apps.common.models import TenantMixin, TimestampMixin


User = get_user_model()


class PromptTemplate(TenantMixin, TimestampMixin, models.Model):
    """
    Stores extraction prompt templates that can be edited by users.

    Only one template should be active at a time (per tenant). The system
    loads the active template when running extractions, falling back to
    hardcoded defaults if none exists.

    Attributes:
        name: Human-readable identifier for this template version
        description: Notes about this template version
        document_type: Document type this applies to (null = all types)
        system_prompt: The system message sent to OpenAI
        user_prompt_template: The user message template with placeholders
        is_active: Whether this is the currently active template
        created_by: User who created this template
        updated_by: User who last modified this template
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        max_length=100,
        help_text="Human-readable name for this template version",
    )

    description = models.TextField(
        blank=True,
        help_text="Notes about this template or changes made",
    )

    document_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Document type this applies to (null = default for all)",
    )

    system_prompt = models.TextField(
        help_text="System message sent to the AI model",
    )

    user_prompt_template = models.TextField(
        help_text="User message template. Use {placeholders} for dynamic content",
    )

    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this is the active template for its document type",
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_prompt_templates",
        help_text="User who created this template",
    )

    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_prompt_templates",
        help_text="User who last modified this template",
    )

    class Meta:
        db_table = "prompt_templates"
        indexes = [
            models.Index(
                fields=["tenant", "is_active"],
                name="ix_prompts_tenant_active",
            ),
            models.Index(
                fields=["document_type", "is_active"],
                name="ix_prompts_doctype_active",
            ),
        ]
        ordering = ["-updated_at"]
        verbose_name = "Prompt Template"
        verbose_name_plural = "Prompt Templates"

    def __str__(self) -> str:
        doc_type = self.document_type or "all"
        active = " (active)" if self.is_active else ""
        return f"{self.name} [{doc_type}]{active}"

    def save(self, *args, **kwargs):
        """Ensure only one active template per document type per tenant."""
        if self.is_active:
            # Deactivate other templates for same doc type and tenant
            PromptTemplate.objects.filter(
                tenant_id=self.tenant_id,
                document_type=self.document_type,
                is_active=True,
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active_template(cls, tenant_id, document_type: str = None):
        """
        Get the active prompt template for a document type.

        Falls back to the default (document_type=None) if no specific
        template exists for the given document type.

        Args:
            tenant_id: UUID of the tenant
            document_type: Optional document type (hr, invoice, etc.)

        Returns:
            PromptTemplate instance or None
        """
        # First try document-type-specific template
        if document_type:
            template = cls.objects.filter(
                tenant_id=tenant_id,
                document_type=document_type,
                is_active=True,
            ).first()
            if template:
                return template

        # Fall back to default template (document_type=None)
        return cls.objects.filter(
            tenant_id=tenant_id,
            document_type__isnull=True,
            is_active=True,
        ).first()