"""
==============================================================================
FILE: prompt_views.py
LOCATION: /docextract/apps/extraction/prompt_views.py
==============================================================================

PURPOSE:
    API views for managing prompt templates. Allows users to view the
    current prompts used for extraction and edit them.

VIEWS:
    - PromptTemplateViewSet: CRUD for prompt templates
    - ActivePromptView: Get the currently active prompt
    - PromptPlaceholdersView: List available template placeholders
    - PromptDefaultsView: Get default prompts for each document type
    - CreateDefaultPromptView: Create template from defaults

ENDPOINTS:
    GET    /api/v1/prompts/              - List all templates
    POST   /api/v1/prompts/              - Create new template
    GET    /api/v1/prompts/{id}/         - Get template detail
    PUT    /api/v1/prompts/{id}/         - Update template
    DELETE /api/v1/prompts/{id}/         - Delete template
    GET    /api/v1/prompts/active/       - Get active prompt (with defaults)
    POST   /api/v1/prompts/{id}/activate/ - Activate a template
    POST   /api/v1/prompts/{id}/deactivate/ - Deactivate a template
    POST   /api/v1/prompts/{id}/duplicate/ - Duplicate a template
    GET    /api/v1/prompts/placeholders/ - List available placeholders
    GET    /api/v1/prompts/defaults/     - Get default prompts by doc type
    POST   /api/v1/prompts/create-default/ - Create template from defaults

==============================================================================
"""

from uuid import UUID

from django.db import transaction
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from apps.extraction.prompt_models import PromptTemplate
from apps.extraction.prompt_serialisers import (
    PromptTemplateListSerialiser,
    PromptTemplateDetailSerialiser,
    PromptTemplateCreateSerialiser,
    PromptTemplateUpdateSerialiser,
    ActivePromptSerialiser,
    PromptPlaceholdersSerialiser,
)

# Import defaults from agents.py (single source of truth)
from apps.extraction.agents import (
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_USER_PROMPT,
    ExtractionAgent,
)


# Demo tenant UUID (same as elsewhere in the project)
DEMO_TENANT_ID = UUID("8c5a066d-12db-4c5b-ba3c-0d1cd581318f")


def get_tenant_id(request) -> UUID:
    """Extract tenant ID from request, with demo fallback."""
    if hasattr(request, "tenant") and request.tenant:
        return request.tenant.id
    return DEMO_TENANT_ID


class PromptTemplateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing prompt templates.

    Provides full CRUD operations for prompt templates with tenant isolation.
    """

    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        """Filter templates by tenant."""
        tenant_id = get_tenant_id(self.request)
        return PromptTemplate.objects.filter(
            tenant_id=tenant_id
        ).select_related("created_by", "updated_by")

    def get_serializer_class(self):
        """Return appropriate serialiser for action."""
        if self.action == "list":
            return PromptTemplateListSerialiser
        elif self.action == "create":
            return PromptTemplateCreateSerialiser
        elif self.action in ("update", "partial_update"):
            return PromptTemplateUpdateSerialiser
        return PromptTemplateDetailSerialiser

    def perform_create(self, serializer):
        """Set tenant and created_by on creation."""
        tenant_id = get_tenant_id(self.request)
        serializer.save(
            tenant_id=tenant_id,
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def perform_update(self, serializer):
        """Set updated_by on update."""
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def activate(self, request, id=None):
        """
        Activate a prompt template.

        This will deactivate any other active template for the same
        document type.
        """
        template = self.get_object()
        template.is_active = True
        template.updated_by = request.user
        template.save()

        return Response({
            "status": "activated",
            "id": str(template.id),
            "name": template.name,
            "document_type": template.document_type,
        })

    @action(detail=True, methods=["post"])
    def deactivate(self, request, id=None):
        """Deactivate a prompt template."""
        template = self.get_object()
        template.is_active = False
        template.updated_by = request.user
        template.save()

        return Response({
            "status": "deactivated",
            "id": str(template.id),
            "name": template.name,
        })

    @action(detail=True, methods=["post"])
    def duplicate(self, request, id=None):
        """
        Create a copy of a prompt template.

        Useful for creating variations based on an existing template.
        """
        original = self.get_object()

        with transaction.atomic():
            new_template = PromptTemplate.objects.create(
                tenant_id=original.tenant_id,
                name=f"{original.name} (copy)",
                description=f"Copied from: {original.name}",
                document_type=original.document_type,
                system_prompt=original.system_prompt,
                user_prompt_template=original.user_prompt_template,
                is_active=False,  # Don't activate the copy
                created_by=request.user,
                updated_by=request.user,
            )

        serialiser = PromptTemplateDetailSerialiser(new_template)
        return Response(serialiser.data, status=status.HTTP_201_CREATED)


class ActivePromptView(APIView):
    """
    Get the currently active prompt template.

    Returns the active template from the database, or the hardcoded
    defaults if no template is active. This is what the extraction
    agent will use.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, document_type: str = None):
        """
        Get active prompt for a document type.

        Query params:
            document_type: Optional, filter by doc type (hr, invoice, etc.)
        """
        tenant_id = get_tenant_id(request)
        doc_type = document_type or request.query_params.get("document_type")

        # Try to get active template from DB
        template = PromptTemplate.get_active_template(tenant_id, doc_type)

        if template:
            data = {
                "id": str(template.id),
                "name": template.name,
                "document_type": template.document_type,
                "system_prompt": template.system_prompt,
                "user_prompt_template": template.user_prompt_template,
                "is_default": False,
                "updated_at": template.updated_at,
                "updated_by": {
                    "id": template.updated_by.id,
                    "email": template.updated_by.email,
                    "username": template.updated_by.username,
                } if template.updated_by else None,
            }
        else:
            # Return hardcoded defaults
            data = {
                "id": None,
                "name": "Default Template",
                "document_type": None,
                "system_prompt": DEFAULT_SYSTEM_PROMPT,
                "user_prompt_template": DEFAULT_USER_PROMPT,
                "is_default": True,
                "updated_at": None,
                "updated_by": None,
            }

        serialiser = ActivePromptSerialiser(data)
        return Response(serialiser.data)


class PromptPlaceholdersView(APIView):
    """
    List available placeholders for prompt templates.

    Helps users understand what variables they can use in their
    custom prompts.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return list of available placeholders."""
        placeholders = [
            {
                "name": "doc_type",
                "description": "Detected document type (hr, invoice, contract, insurance, generic)",
                "example": "invoice",
                "used_in": ["system_prompt", "user_prompt"],
            },
            {
                "name": "filename",
                "description": "Original filename of the uploaded document",
                "example": "Invoice_2024_001.pdf",
                "used_in": ["user_prompt"],
            },
            {
                "name": "text_content",
                "description": "Extracted text content from the document (truncated to 50,000 chars)",
                "example": "[Page 1]\\nINVOICE\\nInvoice Number: INV-2024-001...",
                "used_in": ["user_prompt"],
            },
            {
                "name": "field_examples",
                "description": "Document-type-specific field extraction guidance. Automatically populated based on doc_type.",
                "example": "For invoices, extract ALL of these (where present):\\n- Vendor/seller name...",
                "used_in": ["system_prompt"],
            },
            {
                "name": "additional_notes",
                "description": "Extra instructions from template description field. Use for custom guidance.",
                "example": "Always extract the PO number even if confidence is low.",
                "used_in": ["system_prompt"],
            },
        ]

        serialiser = PromptPlaceholdersSerialiser({"placeholders": placeholders})
        return Response(serialiser.data)


class PromptDefaultsView(APIView):
    """
    Get default prompts and field examples for each document type.

    Useful for understanding what the extraction agent uses by default
    and for building custom templates.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Return default prompts and field examples.

        Query params:
            document_type: Optional, get examples for specific type only
        """
        doc_type = request.query_params.get("document_type")

        # Get field examples from agent
        field_examples = ExtractionAgent.FIELD_EXAMPLES

        if doc_type:
            # Return specific document type only
            examples = field_examples.get(doc_type, field_examples.get("generic"))
            return Response({
                "document_type": doc_type,
                "system_prompt": DEFAULT_SYSTEM_PROMPT,
                "user_prompt_template": DEFAULT_USER_PROMPT,
                "field_examples": examples,
                "available_document_types": list(field_examples.keys()),
            })

        # Return all defaults
        return Response({
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "user_prompt_template": DEFAULT_USER_PROMPT,
            "field_examples_by_type": field_examples,
            "available_document_types": list(field_examples.keys()),
            "notes": (
                "The {field_examples} placeholder in system_prompt is automatically "
                "populated based on detected document type. You can override this by "
                "removing the placeholder and writing your own instructions."
            ),
        })


class CreateDefaultPromptView(APIView):
    """
    Create a prompt template from the current defaults.

    This is a convenience endpoint that creates a new template
    populated with the hardcoded default prompts, allowing users
    to customise from a known-working baseline.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Create a template from defaults.

        Request body:
            name: Template name (optional, defaults to "Custom Template")
            document_type: Document type scope (optional, null = all types)
            include_field_examples: If true, bake in field examples for the doc type
        """
        tenant_id = get_tenant_id(request)
        doc_type = request.data.get("document_type")
        name = request.data.get("name", "Custom Template")
        include_examples = request.data.get("include_field_examples", False)

        # Build system prompt
        system_prompt = DEFAULT_SYSTEM_PROMPT

        # Optionally bake in field examples for the document type
        if include_examples and doc_type:
            field_examples = ExtractionAgent.FIELD_EXAMPLES.get(
                doc_type, ExtractionAgent.FIELD_EXAMPLES.get("generic")
            )
            system_prompt = system_prompt.replace("{field_examples}", field_examples)

        template = PromptTemplate.objects.create(
            tenant_id=tenant_id,
            name=name,
            description=f"Created from default template{' for ' + doc_type if doc_type else ''}",
            document_type=doc_type,
            system_prompt=system_prompt,
            user_prompt_template=DEFAULT_USER_PROMPT,
            is_active=False,
            created_by=request.user,
            updated_by=request.user,
        )

        serialiser = PromptTemplateDetailSerialiser(template)
        return Response(serialiser.data, status=status.HTTP_201_CREATED)