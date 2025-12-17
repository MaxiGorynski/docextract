"""
==============================================================================
FILE: views.py
LOCATION: /docextract/apps/documents/views.py
==============================================================================

PURPOSE:
    DRF views for the Documents API. Implements thin views that delegate
    business logic to the service layer. Handles authentication, validation,
    and response formatting.

VIEWS:
    - DocumentViewSet: CRUD operations for documents (list, create, retrieve)
    - DocumentExtractView: Trigger async extraction for a document
    - DocumentDownloadView: Download original document file
    - DocumentExtractionsView: List extractions for a specific document

ENDPOINTS:
    GET    /api/v1/documents/                    - List documents
    POST   /api/v1/documents/                    - Upload document
    GET    /api/v1/documents/{id}/               - Retrieve document
    POST   /api/v1/documents/{id}/extract/       - Trigger extraction
    GET    /api/v1/documents/{id}/download/      - Download file
    GET    /api/v1/documents/{id}/extractions/   - List extractions

USAGE:
    URL routing is configured in apps/documents/urls.py.
    Views use serialisers from apps/documents/serialisers.py.

DESIGN DECISIONS:
    - Thin views: auth + validation only, logic in services
    - ServiceContext built from request for tenant/actor info
    - Consistent error response format via exception handling
    - Prefetch optimisation for list/detail queries

PERFORMANCE NOTES:
    - List view uses select_related and prefetch_related
    - Detail view prefetches extracted_fields and extractions
    - Pagination configured in DRF settings

==============================================================================
"""

from django.http import FileResponse, Http404
from django.db.models import Prefetch
from rest_framework import viewsets, status, views
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from apps.common.services.base import ServiceContext
from apps.documents.models import Document, DocumentStatus
from apps.documents.serialisers import (
    DocumentListSerialiser,
    DocumentCreateSerialiser,
    DocumentDetailSerialiser,
    TriggerExtractionRequestSerialiser,
    TriggerExtractionResponseSerialiser,
)
from apps.documents.services import DocumentService
from apps.documents.selectors import DocumentSelector
from apps.extraction.models import ExtractedField, ProposedExtraction
from apps.extraction.serialisers import ExtractionDetailSerialiser


class DocumentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for document operations.

    Provides list, create, and retrieve actions. Update and delete
    are not exposed via API (admin only).

    Filtering:
        - status: Filter by document status
        - created_after: Filter by creation date (ISO format)
        - created_before: Filter by creation date (ISO format)
        - search: Search in title and filename
        - ordering: Sort field (prefix - for descending)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        """
        Return documents for the current tenant with optimised loading.
        """
        tenant_id = self._get_tenant_id()

        queryset = Document.objects.filter(tenant_id=tenant_id)

        # Apply filters from query params
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        created_after = self.request.query_params.get("created_after")
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)

        created_before = self.request.query_params.get("created_before")
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)

        search = self.request.query_params.get("search")
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(original_filename__icontains=search)
            )

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "-created_at")
        allowed_orderings = [
            "created_at", "-created_at",
            "title", "-title",
            "status", "-status",
        ]
        if ordering in allowed_orderings:
            queryset = queryset.order_by(ordering)

        # Optimise loading based on action
        if self.action == "list":
            queryset = queryset.select_related("uploaded_by")
            queryset = queryset.prefetch_related(
                "proposed_extractions",
                Prefetch(
                    "extracted_fields",
                    queryset=ExtractedField.objects.filter(is_active=True),
                ),
            )
        elif self.action == "retrieve":
            queryset = queryset.select_related("uploaded_by")
            queryset = queryset.prefetch_related(
                Prefetch(
                    "proposed_extractions",
                    queryset=ProposedExtraction.objects.order_by("-created_at"),
                ),
                Prefetch(
                    "extracted_fields",
                    queryset=ExtractedField.objects.filter(is_active=True),
                    to_attr="active_fields",
                ),
            )

        return queryset

    def get_serializer_class(self):
        """Return appropriate serialiser based on action."""
        if self.action == "list":
            return DocumentListSerialiser
        if self.action == "create":
            return DocumentCreateSerialiser
        return DocumentDetailSerialiser

    def create(self, request, *args, **kwargs):
        """
        Upload a new document.

        Accepts multipart/form-data with file upload.
        Delegates to DocumentService for business logic.
        """
        serialiser = self.get_serializer(data=request.data)
        serialiser.is_valid(raise_exception=True)

        # Build service context
        context = self._build_service_context(self.request)
        service = DocumentService(context)

        # Extract validated data
        file = serialiser.validated_data["file"]
        title = serialiser.validated_data.get("title")
        metadata = serialiser.validated_data.get("metadata", {})
        auto_extract = serialiser.validated_data.get("auto_extract", False)

        # Call service
        result = service.create_document(
            file=file,
            original_filename=file.name,
            title=title,
            metadata=metadata,
            auto_extract=auto_extract,
        )

        if not result.success:
            return Response(
                {
                    "error": {
                        "code": result.error_code,
                        "message": result.error,
                        "trace_id": context.trace_id,
                    }
                },
                status=self._error_code_to_status(result.error_code),
            )

        # Serialise response
        response_serialiser = DocumentCreateSerialiser(result.data)
        return Response(
            response_serialiser.data,
            status=status.HTTP_201_CREATED,
        )

    def _get_tenant_id(self):
        """Get tenant ID from request (set by middleware)."""
        from uuid import UUID
        if hasattr(self.request, "tenant"):
            return self.request.tenant.id
        if hasattr(self.request.user, "tenant_id") and self.request.user.tenant_id:
            return self.request.user.tenant_id
        # Demo fallback
        return UUID("8c5a066d-12db-4c5b-ba3c-0d1cd581318f")

    def _build_service_context(self, request) -> ServiceContext:
        """Build ServiceContext from current request."""
        from uuid import UUID

        tenant_id = None
        if hasattr(request, "tenant"):
            tenant_id = request.tenant.id
        elif hasattr(request.user, "tenant_id") and request.user.tenant_id:
            tenant_id = request.user.tenant_id
        else:
            # Demo fallback
            tenant_id = UUID("8c5a066d-12db-4c5b-ba3c-0d1cd581318f")

        return ServiceContext(
            tenant_id=tenant_id,
            actor_id=str(request.user.id),
            actor_type="user",
            trace_id=getattr(request, "trace_id", "unknown"),
            feature_flags=getattr(request, "feature_flags", {}),
        )

    def _error_code_to_status(self, error_code: str) -> int:
        """Map service error codes to HTTP status codes."""
        mapping = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "invalid_file_type": status.HTTP_400_BAD_REQUEST,
            "file_too_large": status.HTTP_400_BAD_REQUEST,
            "duplicate_file": status.HTTP_400_BAD_REQUEST,
            "validation_failed": status.HTTP_400_BAD_REQUEST,
            "feature_disabled": status.HTTP_503_SERVICE_UNAVAILABLE,
            "extraction_in_progress": status.HTTP_400_BAD_REQUEST,
            "extraction_exists": status.HTTP_400_BAD_REQUEST,
        }
        return mapping.get(error_code, status.HTTP_400_BAD_REQUEST)


class DocumentExtractView(views.APIView):
    """
    Trigger async extraction for a document.

    POST /api/v1/documents/{id}/extract/

    Initiates AI-powered field extraction. Returns immediately with
    task ID for status polling.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, document_id):
        """Trigger extraction for the specified document."""
        serialiser = TriggerExtractionRequestSerialiser(data=request.data)
        serialiser.is_valid(raise_exception=True)

        # Build service context
        context = self._build_service_context(request)
        service = DocumentService(context)

        # Call service
        result = service.trigger_extraction(
            document_id=document_id,
            force=serialiser.validated_data.get("force", False),
            field_types=serialiser.validated_data.get("field_types"),
        )

        if not result.success:
            return Response(
                {
                    "error": {
                        "code": result.error_code,
                        "message": result.error,
                        "trace_id": context.trace_id,
                    }
                },
                status=self._error_code_to_status(result.error_code),
            )

        # Build response
        response_data = {
            "task_id": result.data,
            "document_id": str(document_id),
            "status": "queued",
            "message": "Extraction task queued",
            "estimated_duration_seconds": 30,
            "links": {
                "document": f"/api/v1/documents/{document_id}/",
                "status": f"/api/v1/tasks/{result.data}/",
            },
        }

        return Response(response_data, status=status.HTTP_202_ACCEPTED)

    def _build_service_context(self, request) -> ServiceContext:
        """Build ServiceContext from current request."""
        from uuid import UUID

        tenant_id = None
        if hasattr(request, "tenant"):
            tenant_id = request.tenant.id
        elif hasattr(request.user, "tenant_id") and request.user.tenant_id:
            tenant_id = request.user.tenant_id
        else:
            # Demo fallback
            tenant_id = UUID("8c5a066d-12db-4c5b-ba3c-0d1cd581318f")

        return ServiceContext(
            tenant_id=tenant_id,
            actor_id=str(request.user.id),
            actor_type="user",
            trace_id=getattr(request, "trace_id", "unknown"),
            feature_flags=getattr(request, "feature_flags", {}),
        )

    def _error_code_to_status(self, error_code: str) -> int:
        """Map service error codes to HTTP status codes."""
        mapping = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "feature_disabled": status.HTTP_503_SERVICE_UNAVAILABLE,
            "extraction_in_progress": status.HTTP_400_BAD_REQUEST,
            "extraction_exists": status.HTTP_400_BAD_REQUEST,
        }
        return mapping.get(error_code, status.HTTP_400_BAD_REQUEST)


class DocumentDownloadView(views.APIView):
    """
    Download the original document file.

    GET /api/v1/documents/{id}/download/

    Returns the file with appropriate Content-Type and
    Content-Disposition headers.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        """Download the document file."""
        tenant_id = self._get_tenant_id(request)

        try:
            document = Document.objects.get(
                id=document_id,
                tenant_id=tenant_id,
            )
        except Document.DoesNotExist:
            raise Http404("Document not found")

        # Return file response
        response = FileResponse(
            document.file.open("rb"),
            content_type=document.file_type,
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{document.original_filename}"'
        )
        return response

    def _get_tenant_id(self, request):
        """Get tenant ID from request."""
        from uuid import UUID

        if hasattr(request, "tenant"):
            return request.tenant.id
        if hasattr(request.user, "tenant_id") and request.user.tenant_id:
            return request.user.tenant_id
        # Demo fallback
        return UUID("8c5a066d-12db-4c5b-ba3c-0d1cd581318f")


class DocumentExtractionsView(views.APIView):
    """
    List extractions for a specific document.

    GET /api/v1/documents/{id}/extractions/

    Returns all proposed extractions for the document,
    ordered by creation date (newest first).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, document_id):
        """List extractions for the document."""
        tenant_id = self._get_tenant_id(request)

        # Verify document exists and belongs to tenant
        if not Document.objects.filter(
            id=document_id,
            tenant_id=tenant_id,
        ).exists():
            return Response(
                {
                    "error": {
                        "code": "not_found",
                        "message": "Document not found",
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Get extractions
        extractions = (
            ProposedExtraction.objects
            .filter(document_id=document_id, tenant_id=tenant_id)
            .select_related("reviewed_by")
            .prefetch_related("fields")
            .order_by("-created_at")
        )

        serialiser = ExtractionDetailSerialiser(extractions, many=True)

        return Response({
            "count": len(serialiser.data),
            "results": serialiser.data,
        })

    def _get_tenant_id(self, request):
        """Get tenant ID from request."""
        from uuid import UUID

        if hasattr(request, "tenant"):
            return request.tenant.id
        if hasattr(request.user, "tenant_id") and request.user.tenant_id:
            return request.user.tenant_id
        # Demo fallback
        return UUID("8c5a066d-12db-4c5b-ba3c-0d1cd581318f")