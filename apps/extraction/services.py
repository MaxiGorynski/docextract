"""
==============================================================================
FILE: services.py
LOCATION: /docextract/apps/extraction/services.py
==============================================================================

PURPOSE:
    Service layer for extraction operations. Orchestrates the commit/reject
    workflow for proposed extractions, implementing the "commit" phase of
    the two-phase commit pattern.

CLASSES:
    - ExtractionService: Service for extraction lifecycle operations

USAGE:
    from apps.extraction.services import ExtractionService
    from apps.common.services import ServiceContext

    context = ServiceContext(
        tenant_id=tenant.id,
        actor_id=str(user.id),
        actor_type='user',
        trace_id=request.trace_id,
        feature_flags=request.feature_flags,
    )

    service = ExtractionService(context)

    # Commit an extraction
    result = service.commit_extraction(
        extraction_id=extraction.id,
        review_notes='Verified against original document',
    )

    # Reject an extraction
    result = service.reject_extraction(
        extraction_id=extraction.id,
        reason='Incorrect vendor identification',
        request_re_extraction=True,
    )

DESIGN PRINCIPLES:
    - Two-phase commit: Proposals are explicitly committed to become canonical
    - Auditable: All commits/rejects create Action records
    - Reversible: Committed extractions can be rolled back
    - Transaction-aware: Uses @transaction.atomic for data integrity

PERFORMANCE NOTES:
    - Commit creates ExtractedField records in bulk where possible
    - Field overrides validated before transaction starts
    - Selector used for efficient queries

TESTING:
    - Test commit creates correct ExtractedFields
    - Test reject updates status correctly
    - Test field overrides are applied
    - Test idempotency of commit

==============================================================================
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.common.services.base import BaseService, ServiceContext, ServiceResult
from apps.extraction.models import ProposalStatus, ProposedExtraction
from apps.extraction.selectors import ExtractionSelector

logger = logging.getLogger(__name__)


class ExtractionService(BaseService):
    """
    Service for extraction operations.

    Responsibilities:
    - Commit proposed extractions to canonical storage
    - Reject proposed extractions
    - Field override handling during commit
    - Extraction lifecycle management

    All operations are scoped to the tenant from ServiceContext.
    """

    def __init__(self, context: ServiceContext) -> None:
        """
        Initialise the extraction service.

        Args:
            context: ServiceContext with tenant, actor, and trace info
        """
        super().__init__(context)
        self.selector = ExtractionSelector(context.tenant_id)

    @transaction.atomic
    def commit_extraction(
        self,
        extraction_id: UUID,
        review_notes: str = "",
        field_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> ServiceResult[dict]:
        """
        Commit a proposed extraction to canonical storage.

        This is the "commit" phase of the two-phase pattern. Creates
        ExtractedField records from ProposedFields and logs an Action.

        Args:
            extraction_id: UUID of the ProposedExtraction to commit
            review_notes: Optional reviewer comments
            field_overrides: Dict of {field_id: {value, normalised_value}}
                           to override proposed values

        Returns:
            ServiceResult with commit details:
            - extraction_id: UUID of committed extraction
            - action_id: UUID of the commit Action
            - committed_fields: Count of fields committed

        Error codes:
            - not_found: Extraction does not exist
            - already_committed: Extraction was already committed
            - already_rejected: Cannot commit a rejected extraction
            - validation_failed: Invalid field override data
        """
        self.log_operation("commit_extraction", extraction_id=str(extraction_id))

        # Get extraction with fields
        extraction = self.selector.get_by_id_with_fields(extraction_id)
        if not extraction:
            return ServiceResult.fail(
                f"Extraction not found: {extraction_id}",
                error_code="not_found",
            )

        # Validate status
        if extraction.status == ProposalStatus.COMMITTED:
            return ServiceResult.fail(
                "Extraction has already been committed",
                error_code="already_committed",
            )

        if extraction.status == ProposalStatus.REJECTED:
            return ServiceResult.fail(
                "Cannot commit a rejected extraction",
                error_code="already_rejected",
            )

        if extraction.status == ProposalStatus.SUPERSEDED:
            return ServiceResult.fail(
                "Cannot commit a superseded extraction",
                error_code="invalid_status",
            )

        # Validate field overrides if provided
        if field_overrides:
            validation_result = self._validate_field_overrides(
                extraction, field_overrides
            )
            if not validation_result.success:
                return validation_result

        # Execute commit action
        from apps.extraction.actions import CommitExtractionAction

        action = CommitExtractionAction(
            extraction=extraction,
            actor_id=self.context.actor_id,
            actor_type=self.context.actor_type,
            trace_id=self.context.trace_id,
            review_notes=review_notes,
            field_overrides=field_overrides or {},
        )

        action_result = action.execute()

        self.logger.info(
            f"Extraction committed: {extraction_id}",
            extra={
                "extraction_id": str(extraction_id),
                "action_id": str(action_result.action_id),
                "trace_id": self.context.trace_id,
            },
        )

        return ServiceResult.ok(
            {
                "extraction_id": str(extraction_id),
                "action_id": str(action_result.action_id),
                "action_status": action_result.status,
                "committed_fields": extraction.fields.count(),
                "is_reversible": action_result.is_reversible,
            }
        )

    @transaction.atomic
    def reject_extraction(
        self,
        extraction_id: UUID,
        reason: str,
        request_re_extraction: bool = False,
    ) -> ServiceResult[dict]:
        """
        Reject a proposed extraction.

        Updates the extraction status to REJECTED and optionally
        triggers a new extraction.

        Args:
            extraction_id: UUID of the ProposedExtraction to reject
            reason: Reason for rejection (required)
            request_re_extraction: If True, trigger new extraction

        Returns:
            ServiceResult with rejection details:
            - extraction_id: UUID of rejected extraction
            - action_id: UUID of the reject Action
            - re_extraction_triggered: Whether re-extraction was requested
            - new_task_id: Celery task ID if re-extraction triggered

        Error codes:
            - not_found: Extraction does not exist
            - invalid_status: Extraction not in PENDING status
            - reason_required: Rejection reason is required
        """
        self.log_operation("reject_extraction", extraction_id=str(extraction_id))

        if not reason or not reason.strip():
            return ServiceResult.fail(
                "Rejection reason is required",
                error_code="reason_required",
            )

        # Get extraction
        extraction = self.selector.get_by_id(extraction_id)
        if not extraction:
            return ServiceResult.fail(
                f"Extraction not found: {extraction_id}",
                error_code="not_found",
            )

        # Validate status
        if extraction.status != ProposalStatus.PENDING:
            return ServiceResult.fail(
                f"Cannot reject extraction in status: {extraction.status}",
                error_code="invalid_status",
            )

        # Execute reject action
        from apps.extraction.actions import RejectExtractionAction

        action = RejectExtractionAction(
            extraction=extraction,
            actor_id=self.context.actor_id,
            actor_type=self.context.actor_type,
            trace_id=self.context.trace_id,
            reason=reason.strip(),
        )

        action_result = action.execute()

        self.logger.info(
            f"Extraction rejected: {extraction_id}",
            extra={
                "extraction_id": str(extraction_id),
                "action_id": str(action_result.action_id),
                "reason": reason,
                "trace_id": self.context.trace_id,
            },
        )

        # Optionally trigger re-extraction
        new_task_id = None
        if request_re_extraction:
            from apps.documents.services import DocumentService

            doc_service = DocumentService(self.context)
            re_extract_result = doc_service.trigger_extraction(
                extraction.document_id,
                force=True,
            )
            if re_extract_result.success:
                new_task_id = re_extract_result.data
            else:
                self.logger.warning(
                    f"Re-extraction trigger failed: {re_extract_result.error}",
                    extra={
                        "extraction_id": str(extraction_id),
                        "document_id": str(extraction.document_id),
                    },
                )

        return ServiceResult.ok(
            {
                "extraction_id": str(extraction_id),
                "action_id": str(action_result.action_id),
                "action_status": action_result.status,
                "re_extraction_triggered": request_re_extraction,
                "new_task_id": new_task_id,
            }
        )

    @transaction.atomic
    def rollback_extraction(
        self,
        extraction_id: UUID,
        reason: str = "",
    ) -> ServiceResult[dict]:
        """
        Rollback a committed extraction.

        Soft-deletes the ExtractedFields and reverts the extraction
        status to PENDING.

        Args:
            extraction_id: UUID of the committed extraction to rollback
            reason: Optional reason for rollback

        Returns:
            ServiceResult with rollback details:
            - extraction_id: UUID of rolled back extraction
            - rollback_action_id: UUID of the rollback Action
            - deactivated_fields: Count of fields deactivated

        Error codes:
            - not_found: Extraction does not exist
            - not_committed: Extraction is not in COMMITTED status
            - no_commit_action: Commit action not found
        """
        self.log_operation("rollback_extraction", extraction_id=str(extraction_id))

        # Get extraction
        extraction = self.selector.get_by_id(extraction_id)
        if not extraction:
            return ServiceResult.fail(
                f"Extraction not found: {extraction_id}",
                error_code="not_found",
            )

        # Validate status
        if extraction.status != ProposalStatus.COMMITTED:
            return ServiceResult.fail(
                f"Cannot rollback extraction in status: {extraction.status}. "
                "Only COMMITTED extractions can be rolled back.",
                error_code="not_committed",
            )

        # Get the original commit action
        if not extraction.committed_action_id:
            return ServiceResult.fail(
                "Commit action not found for this extraction",
                error_code="no_commit_action",
            )

        # Execute rollback via the action
        from apps.extraction.actions import CommitExtractionAction

        action = CommitExtractionAction(
            extraction=extraction,
            actor_id=self.context.actor_id,
            actor_type=self.context.actor_type,
            trace_id=self.context.trace_id,
        )

        rollback_result = action.rollback(
            action_id=extraction.committed_action_id,
            reason=reason,
        )

        # Count deactivated fields
        from apps.extraction.models import ExtractedField

        deactivated_count = ExtractedField.objects.filter(
            source_proposal=extraction,
            is_active=False,
        ).count()

        self.logger.info(
            f"Extraction rolled back: {extraction_id}",
            extra={
                "extraction_id": str(extraction_id),
                "rollback_action_id": str(rollback_result.action_id),
                "deactivated_fields": deactivated_count,
                "trace_id": self.context.trace_id,
            },
        )

        return ServiceResult.ok(
            {
                "extraction_id": str(extraction_id),
                "rollback_action_id": str(rollback_result.action_id),
                "rollback_status": rollback_result.status,
                "deactivated_fields": deactivated_count,
            }
        )

    def _validate_field_overrides(
        self,
        extraction: ProposedExtraction,
        overrides: dict[str, dict[str, Any]],
    ) -> ServiceResult[None]:
        """
        Validate field override data.

        Checks that all field IDs in overrides exist in the extraction.

        Args:
            extraction: The ProposedExtraction being committed
            overrides: Dict of field overrides to validate

        Returns:
            ServiceResult.ok(None) if valid, ServiceResult.fail() if not
        """
        field_ids = {str(f.id) for f in extraction.fields.all()}

        invalid_ids = []
        for field_id in overrides.keys():
            if field_id not in field_ids:
                invalid_ids.append(field_id)

        if invalid_ids:
            return ServiceResult.fail(
                f"Invalid field IDs in overrides: {', '.join(invalid_ids)}",
                error_code="validation_failed",
            )

        # Validate override structure
        for field_id, override_data in overrides.items():
            if not isinstance(override_data, dict):
                return ServiceResult.fail(
                    f"Override for field {field_id} must be a dictionary",
                    error_code="validation_failed",
                )

            allowed_keys = {"value", "normalised_value"}
            invalid_keys = set(override_data.keys()) - allowed_keys
            if invalid_keys:
                return ServiceResult.fail(
                    f"Invalid override keys for field {field_id}: {invalid_keys}",
                    error_code="validation_failed",
                )

        return ServiceResult.ok(None)