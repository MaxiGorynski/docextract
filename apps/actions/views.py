"""
==============================================================================
FILE: views.py
LOCATION: /docextract/apps/actions/views.py
==============================================================================

PURPOSE:
    DRF views for the Actions API. Provides read-only access to the
    audit log with rollback capability for reversible actions.

VIEWS:
    - ActionViewSet: List and retrieve actions (read-only)
    - ActionRollbackView: Rollback a reversible action

ENDPOINTS:
    GET    /api/v1/actions/              - List actions
    GET    /api/v1/actions/{id}/         - Retrieve action
    POST   /api/v1/actions/{id}/rollback/ - Rollback action

USAGE:
    URL routing is configured in apps/actions/urls.py.
    Views use serialisers from apps/actions/serialisers.py.

DESIGN DECISIONS:
    - Actions are read-only (immutable audit log)
    - Rollback creates new action, doesn't modify existing
    - Comprehensive filtering for audit trail analysis
    - Tenant-scoped queries for data isolation

PERFORMANCE NOTES:
    - List view supports extensive filtering
    - Consider pagination for high-volume logs
    - Index on trace_id for correlation queries

==============================================================================
"""

from rest_framework import viewsets, status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.common.services.base import ServiceContext
from apps.actions.models import Action, ActionType, ActionStatus
from apps.actions.serialisers import (
    ActionListSerialiser,
    ActionDetailSerialiser,
    RollbackRequestSerialiser,
    RollbackResponseSerialiser,
)
from apps.extraction.services import ExtractionService


class ActionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for action audit log.

    Provides list and retrieve actions only. Actions are created
    by the service layer, never directly via API.

    Filtering:
        - action_type: Filter by action type
        - target_type: Filter by target model
        - target_id: Filter by target ID
        - actor_id: Filter by actor
        - trace_id: Filter by trace ID
        - created_after: Filter by creation date
        - created_before: Filter by creation date
    """

    permission_classes = [IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        """
        Return actions for the current tenant with filtering.
        """
        tenant_id = self._get_tenant_id()

        queryset = Action.objects.filter(tenant_id=tenant_id)

        # Apply filters from query params
        action_type = self.request.query_params.get("action_type")
        if action_type:
            queryset = queryset.filter(action_type=action_type)

        target_type = self.request.query_params.get("target_type")
        if target_type:
            queryset = queryset.filter(target_type=target_type)

        target_id = self.request.query_params.get("target_id")
        if target_id:
            queryset = queryset.filter(target_id=target_id)

        actor_id = self.request.query_params.get("actor_id")
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)

        trace_id = self.request.query_params.get("trace_id")
        if trace_id:
            queryset = queryset.filter(trace_id=trace_id)

        created_after = self.request.query_params.get("created_after")
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)

        created_before = self.request.query_params.get("created_before")
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)

        # Default ordering: newest first
        return queryset.order_by("-created_at")

    def get_serializer_class(self):
        """Return appropriate serialiser based on action."""
        if self.action == "list":
            return ActionListSerialiser
        return ActionDetailSerialiser

    def _get_tenant_id(self):
        """Get tenant ID from request."""
        if hasattr(self.request, "tenant"):
            return self.request.tenant.id
        return getattr(self.request.user, "tenant_id", None)


class ActionRollbackView(views.APIView):
    """
    Rollback a reversible action.

    POST /api/v1/actions/{id}/rollback/

    Creates a new rollback action that reverses the effects of
    the original action. Only works for actions marked as reversible
    that have not already been reversed.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, action_id):
        """Rollback the specified action."""
        serialiser = RollbackRequestSerialiser(data=request.data)
        serialiser.is_valid(raise_exception=True)

        # Get tenant ID
        tenant_id = self._get_tenant_id(request)

        # Fetch the action to rollback
        try:
            action = Action.objects.get(id=action_id, tenant_id=tenant_id)
        except Action.DoesNotExist:
            return Response(
                {
                    "error": {
                        "code": "not_found",
                        "message": "Action not found",
                    }
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Validate action is reversible
        if not action.is_reversible:
            return Response(
                {
                    "error": {
                        "code": "not_reversible",
                        "message": "This action cannot be rolled back",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if already reversed
        if action.reversed_by_id:
            return Response(
                {
                    "error": {
                        "code": "already_reversed",
                        "message": "This action has already been rolled back",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build service context
        context = self._build_service_context(request)

        # Determine rollback strategy based on action type
        reason = serialiser.validated_data.get("reason", "")

        try:
            rollback_result = self._execute_rollback(action, context, reason)
        except ValueError as e:
            return Response(
                {
                    "error": {
                        "code": "rollback_failed",
                        "message": str(e),
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Build response
        response_data = {
            "original_action_id": str(action_id),
            "rollback_action": {
                "id": str(rollback_result["action_id"]),
                "action_type": rollback_result["action_type"],
                "status": "completed",
                "reverses": str(action_id),
            },
            "restored_state": rollback_result.get("restored_state", {}),
            "message": "Action rolled back successfully",
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def _execute_rollback(
        self,
        action: Action,
        context: ServiceContext,
        reason: str,
    ) -> dict:
        """
        Execute rollback based on action type.

        Dispatches to appropriate service for rollback execution.
        """
        if action.action_type == ActionType.COMMIT_EXTRACTION:
            return self._rollback_commit_extraction(action, context, reason)
        elif action.action_type == ActionType.REJECT_EXTRACTION:
            raise ValueError("Rejection actions cannot be rolled back")
        else:
            raise ValueError(f"Rollback not supported for action type: {action.action_type}")

    def _rollback_commit_extraction(
        self,
        action: Action,
        context: ServiceContext,
        reason: str,
    ) -> dict:
        """
        Rollback a commit extraction action.

        Deactivates created ExtractedFields and reverts proposal status.
        """
        from apps.extraction.models import ProposedExtraction, ExtractedField
        from apps.extraction.actions import CommitExtractionAction
        from django.utils import timezone

        # Get the extraction from target
        extraction_id = action.target_id
        try:
            extraction = ProposedExtraction.objects.get(id=extraction_id)
        except ProposedExtraction.DoesNotExist:
            raise ValueError(f"Extraction not found: {extraction_id}")

        # Get field IDs from post_state
        field_ids = action.post_state.get("created_field_ids", [])

        # Deactivate the fields
        deactivated_count = ExtractedField.objects.filter(
            id__in=field_ids
        ).update(
            is_active=False,
            deactivated_at=timezone.now(),
        )

        # Revert extraction status
        from apps.extraction.models import ProposalStatus
        extraction.status = ProposalStatus.PENDING
        extraction.reviewed_by = None
        extraction.reviewed_at = None
        extraction.committed_action = None
        extraction.save()

        # Revert document status if needed
        from apps.documents.models import Document, DocumentStatus
        has_other_committed = (
            ProposedExtraction.objects
            .filter(
                document=extraction.document,
                status=ProposalStatus.COMMITTED
            )
            .exclude(id=extraction.id)
            .exists()
        )

        if not has_other_committed:
            extraction.document.status = DocumentStatus.PENDING
            extraction.document.save()

        # Create rollback action record
        rollback_action = Action.objects.create(
            action_type=ActionType.ROLLBACK_EXTRACTION,
            status=ActionStatus.COMPLETED,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            target_type="ProposedExtraction",
            target_id=str(extraction_id),
            tenant_id=context.tenant_id,
            trace_id=context.trace_id,
            pre_state=action.post_state,
            post_state={
                "proposal_status": "pending",
                "deactivated_field_ids": field_ids,
            },
            is_reversible=False,
            reverses=action,
            metadata={"reason": reason},
        )

        # Mark original as reversed
        action.reversed_by = rollback_action
        # Use update to bypass immutability check
        Action.objects.filter(id=action.id).update(reversed_by=rollback_action)

        return {
            "action_id": rollback_action.id,
            "action_type": ActionType.ROLLBACK_EXTRACTION,
            "restored_state": {
                "proposal_status": "pending",
                "deactivated_field_count": deactivated_count,
            },
        }

    def _get_tenant_id(self, request):
        """Get tenant ID from request."""
        if hasattr(request, "tenant"):
            return request.tenant.id
        return getattr(request.user, "tenant_id", None)

    def _build_service_context(self, request) -> ServiceContext:
        """Build ServiceContext from current request."""
        return ServiceContext(
            tenant_id=self._get_tenant_id(request),
            actor_id=str(request.user.id),
            actor_type="user",
            trace_id=getattr(request, "trace_id", "unknown"),
            feature_flags=getattr(request, "feature_flags", {}),
        )