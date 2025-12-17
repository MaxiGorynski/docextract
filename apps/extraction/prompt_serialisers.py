"""
==============================================================================
FILE: prompt_serialisers.py
LOCATION: /docextract/apps/extraction/prompt_serialisers.py
==============================================================================

PURPOSE:
    DRF serialisers for the PromptTemplate API. Provides endpoints for
    viewing and editing extraction prompts.

SERIALISERS:
    - PromptTemplateListSerialiser: Compact list view
    - PromptTemplateDetailSerialiser: Full detail with prompts
    - PromptTemplateCreateSerialiser: Creating new templates
    - PromptTemplateUpdateSerialiser: Updating existing templates
    - ActivePromptSerialiser: Current active prompt (read-only)

USAGE:
    Used by prompt_views.py for the /api/v1/prompts/ endpoints.

==============================================================================
"""

from rest_framework import serializers

from apps.extraction.prompt_models import PromptTemplate


class UserBriefSerialiser(serializers.Serializer):
    """Minimal user representation for nested display."""

    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    username = serializers.CharField(read_only=True)


class PromptTemplateListSerialiser(serializers.ModelSerializer):
    """Compact serialiser for listing prompt templates."""

    created_by = UserBriefSerialiser(read_only=True)
    updated_by = UserBriefSerialiser(read_only=True)

    class Meta:
        model = PromptTemplate
        fields = [
            "id",
            "name",
            "description",
            "document_type",
            "is_active",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PromptTemplateDetailSerialiser(serializers.ModelSerializer):
    """Full serialiser including prompt content."""

    created_by = UserBriefSerialiser(read_only=True)
    updated_by = UserBriefSerialiser(read_only=True)
    system_prompt_preview = serializers.SerializerMethodField()
    user_prompt_preview = serializers.SerializerMethodField()

    class Meta:
        model = PromptTemplate
        fields = [
            "id",
            "name",
            "description",
            "document_type",
            "system_prompt",
            "system_prompt_preview",
            "user_prompt_template",
            "user_prompt_preview",
            "is_active",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
            "system_prompt_preview",
            "user_prompt_preview",
        ]

    def get_system_prompt_preview(self, obj) -> str:
        """Return first 200 chars of system prompt."""
        if len(obj.system_prompt) > 200:
            return obj.system_prompt[:200] + "..."
        return obj.system_prompt

    def get_user_prompt_preview(self, obj) -> str:
        """Return first 200 chars of user prompt template."""
        if len(obj.user_prompt_template) > 200:
            return obj.user_prompt_template[:200] + "..."
        return obj.user_prompt_template


class PromptTemplateCreateSerialiser(serializers.ModelSerializer):
    """Serialiser for creating new prompt templates."""

    class Meta:
        model = PromptTemplate
        fields = [
            "name",
            "description",
            "document_type",
            "system_prompt",
            "user_prompt_template",
            "is_active",
        ]

    def validate_system_prompt(self, value):
        """Ensure system prompt is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("System prompt cannot be empty")
        return value.strip()

    def validate_user_prompt_template(self, value):
        """Ensure user prompt template is not empty."""
        if not value or not value.strip():
            raise serializers.ValidationError("User prompt template cannot be empty")
        return value.strip()


class PromptTemplateUpdateSerialiser(serializers.ModelSerializer):
    """Serialiser for updating existing prompt templates."""

    class Meta:
        model = PromptTemplate
        fields = [
            "name",
            "description",
            "document_type",
            "system_prompt",
            "user_prompt_template",
            "is_active",
        ]

    def validate_system_prompt(self, value):
        """Ensure system prompt is not empty."""
        if value is not None and not value.strip():
            raise serializers.ValidationError("System prompt cannot be empty")
        return value.strip() if value else value

    def validate_user_prompt_template(self, value):
        """Ensure user prompt template is not empty."""
        if value is not None and not value.strip():
            raise serializers.ValidationError("User prompt template cannot be empty")
        return value.strip() if value else value


class ActivePromptSerialiser(serializers.Serializer):
    """
    Read-only serialiser for the currently active prompt.

    Used by the frontend to display the prompt that will be used
    for extractions.
    """

    id = serializers.UUIDField(read_only=True, allow_null=True)
    name = serializers.CharField(read_only=True, allow_null=True)
    document_type = serializers.CharField(read_only=True, allow_null=True)
    system_prompt = serializers.CharField(read_only=True)
    user_prompt_template = serializers.CharField(read_only=True)
    is_default = serializers.BooleanField(
        read_only=True,
        help_text="True if using hardcoded default (no DB template)",
    )
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    updated_by = UserBriefSerialiser(read_only=True, allow_null=True)


class PromptPlaceholdersSerialiser(serializers.Serializer):
    """Documents available placeholders for user prompt template."""

    placeholders = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
    )