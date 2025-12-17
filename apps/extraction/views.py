"""
==============================================================================
FILE: views.py
LOCATION: /docextract/apps/extraction/views.py
==============================================================================

PURPOSE:
    DRF views for the Extractions API. Implements thin views that delegate
    business logic to the service layer. Handles the two-phase commit
    workflow: retrieve proposals, commit or reject.

VIEWS:
    - ExtractionViewSet: Retrieve extraction details (read-only)
    - ExtractionCommitView: Commit a proposed extraction
    - ExtractionRejectView: Reject a proposed extraction

ENDPOINTS:
    GET    /api/v1/extractions/{id}/          - Retrieve extraction
    POST   /api/v1/extractions/{id}/commit/   - Commit extraction
    POST   /api/v1/extractions/{id}/reject/   - Reject extraction

USAGE:
    URL routing is configured in apps/extraction/urls.py.
    Views use serialisers from apps/extraction/serialisers.py.

DESIGN DECISIONS:
    - Thin views: auth + validation only, logic in services
    - Commit/reject as separate views for clarity
    - ServiceContext built from request for tenant/actor info
    - Consistent error response format

PERFORMANCE NOTES:
    - Detail view prefetches fields for single query
    - Commit/reject are transactional in service layer

==============================================================================
"""

from rest_framework import viewsets, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.common.services.base import ServiceContext
from apps.extraction.models import ProposedExtraction
from apps.extraction.serialisers import (
    ExtractionDetailSerialiser,
    CommitRequestSerialiser,
    CommitResponseSerialiser,
    RejectRequestSerialiser,
    RejectResponseSerialiser,
)
from apps.extraction.services import ExtractionService
from apps.actions.models import Action


class ExtractionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for extraction retrieval.

    Provides retrieve action only. Extractions are created by the
    AI agent via Celery tasks, not via API.

    List functionality is provided by DocumentExtractionsView
    to maintain document-centric navigation.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ExtractionDetailSerialiser
    lookup_field = "id"

    def get_queryset(self):
        """
        Return extractions for the current tenant with optimised loading.
        """
        tenant_id = self._get_tenant_id()

        return (
            ProposedExtraction.objects
            .filter(tenant_id=tenant_id)
            .select_related("document", "reviewed_by", "committed_action")
            .prefetch_related("fields")
        )

    def _get_tenant_id(self):
        """Get tenant ID from request."""
        if hasattr(self.request, "tenant"):
            return self.request.tenant.id
        return getattr(self.request.user, "tenant_id", None)


class ExtractionCommitView(views.APIView):
    """
    Commit a proposed extraction.

    POST /api/v1/extractions/{id}/commit/

    Commits the proposed extraction to canonical storage via an
    auditable Action. Creates ExtractedField records from the
    ProposedField records.

    Allows optional field value overrides for corrections before commit.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, extraction_id):
        """Commit the specified extraction."""
        serialiser = CommitRequestSerialiser(data=request.data)
        serialiser.is_valid(raise_exception=True)

        # Build service context
        context = self._build_service_context(request)
        service = ExtractionService(context)

        # Call service
        result = service.commit_extraction(
            extraction_id=extraction_id,
            review_notes=serialiser.validated_data.get("review_notes", ""),
            field_overrides=serialiser.validated_data.get("field_overrides"),
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
        action_data = result.data.get("action")
        action_obj = None
        if action_data and hasattr(action_data, "action_id"):
            try:
                action_obj = Action.objects.get(id=action_data.action_id)
            except Action.DoesNotExist:
                pass

        response_data = {
            "extraction_id": str(extraction_id),
            "action": {
                "id": str(action_data.action_id) if action_data else None,
                "action_type": action_data.action_type if action_data else None,
                "status": action_data.status if action_data else None,
                "is_reversible": action_data.is_reversible if action_data else None,
                "created_at": action_obj.created_at.isoformat() if action_obj else None,
            },
            "committed_fields": result.data.get("committed_fields", 0),
            "message": "Extraction committed successfully",
            "links": {
                "extraction": f"/api/v1/extractions/{extraction_id}/",
                "action": f"/api/v1/actions/{action_data.action_id}/" if action_data else None,
                "document": None,  # Would need to fetch extraction to get document_id
            },
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _build_service_context(self, request) -> ServiceContext:
        """Build ServiceContext from current request."""
        tenant_id = None
        if hasattr(request, "tenant"):
            tenant_id = request.tenant.id
        else:
            tenant_id = getattr(request.user, "tenant_id", None)

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
            "already_committed": status.HTTP_400_BAD_REQUEST,
            "already_rejected": status.HTTP_400_BAD_REQUEST,
            "validation_failed": status.HTTP_400_BAD_REQUEST,
            "invalid_status": status.HTTP_400_BAD_REQUEST,
            "concurrent_modification": status.HTTP_409_CONFLICT,
        }
        return mapping.get(error_code, status.HTTP_400_BAD_REQUEST)


class ExtractionRejectView(views.APIView):
    """
    Reject a proposed extraction.

    POST /api/v1/extractions/{id}/reject/

    Rejects the proposed extraction with a reason. Optionally
    triggers a new extraction attempt.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, extraction_id):
        """Reject the specified extraction."""
        serialiser = RejectRequestSerialiser(data=request.data)
        serialiser.is_valid(raise_exception=True)

        # Build service context
        context = self._build_service_context(request)
        service = ExtractionService(context)

        # Call service
        result = service.reject_extraction(
            extraction_id=extraction_id,
            reason=serialiser.validated_data["reason"],
            request_re_extraction=serialiser.validated_data.get(
                "request_re_extraction", False
            ),
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
        action_data = result.data.get("action")

        response_data = {
            "extraction_id": str(extraction_id),
            "status": "rejected",
            "action": {
                "id": str(action_data.action_id) if action_data else None,
                "action_type": action_data.action_type if action_data else None,
                "status": action_data.status if action_data else None,
            },
            "re_extraction_triggered": result.data.get("re_extraction_triggered", False),
            "new_task_id": result.data.get("new_task_id"),
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _build_service_context(self, request) -> ServiceContext:
        """Build ServiceContext from current request."""
        tenant_id = None
        if hasattr(request, "tenant"):
            tenant_id = request.tenant.id
        else:
            tenant_id = getattr(request.user, "tenant_id", None)

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
            "invalid_status": status.HTTP_400_BAD_REQUEST,
            "already_committed": status.HTTP_400_BAD_REQUEST,
            "already_rejected": status.HTTP_400_BAD_REQUEST,
        }
        return mapping.get(error_code, status.HTTP_400_BAD_REQUEST)