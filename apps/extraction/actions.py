"""
==============================================================================
FILE: actions.py
LOCATION: /docextract/apps/extraction/actions.py
==============================================================================

PURPOSE:
    Defines auditable actions for extraction state changes. These actions
    implement the two-phase commit pattern, creating immutable audit records
    for every state transition.

CLASSES:
    - CommitExtractionAction: Commits proposal to canonical storage
    - RejectExtractionAction: Rejects a proposal

USAGE:
    from apps.extraction.actions import CommitExtractionAction

    action = CommitExtractionAction(
        extraction=proposed_extraction,
        actor_id=str(user.id),
        actor_type='user',
        trace_id=request.trace_id,
        review_notes='Verified against source document',
    )

    result = action.execute()
    # result.action_id contains the Action record UUID

    # To rollback:
    rollback_result = action.rollback(result.action_id, reason='Incorrect data')

DESIGN PRINCIPLES:
    - Immutable audit trail: Action records never modified
    - Pre/post state capture: Full snapshot for debugging
    - Idempotent: Same action produces same result
    - Reversible: CommitExtractionAction supports rollback

PERFORMANCE NOTES:
    - ExtractedFields created in loop (consider bulk_create for large sets)
    - Pre-state capture queries existing fields
    - Post-state captures created field IDs

TESTING:
    - Test commit creates correct ExtractedFields
    - Test idempotency with duplicate executions
    - Test rollback deactivates fields correctly
    - Test pre/post state accuracy

==============================================================================
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.actions.base import BaseAction, ReversibleAction
from apps.actions.models import Action, ActionType
from apps.documents.models import DocumentStatus
from apps.extraction.models import (
    ExtractedField,
    ProposalStatus,
    ProposedExtraction,
)

logger = logging.getLogger(__name__)


class CommitExtractionAction(ReversibleAction):
    """
    Commits a proposed extraction to canonical storage.

    This action:
    1. Creates ExtractedField records from ProposedFields
    2. Updates ProposedExtraction status to COMMITTED
    3. Updates Document status to EXTRACTED
    4. Creates an immutable Action record

    Pre-state: ProposedExtraction in PENDING/APPROVED status
    Post-state: ProposedExtraction COMMITTED, ExtractedFields created

    Rollback: Soft-deletes ExtractedFields, reverts proposal to PENDING
    """

    action_type = ActionType.COMMIT_EXTRACTION

    def __init__(
        self,
        extraction: ProposedExtraction,
        actor_id: str,
        actor_type: str,
        trace_id: str,
        review_notes: str = "",
        field_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """
        Initialise the commit action.

        Args:
            extraction: The ProposedExtraction to commit
            actor_id: ID of the actor performing the commit
            actor_type: Type of actor ('user', 'system', 'celery_task')
            trace_id: Request correlation ID
            review_notes: Optional reviewer comments
            field_overrides: Dict of {field_id: {value, normalised_value}}
        """
        super().__init__(actor_id, actor_type, trace_id)
        self.extraction = extraction
        self.review_notes = review_notes
        self.field_overrides = field_overrides or {}
        self._created_field_ids: list[UUID] = []

    def _get_target(self) -> tuple[str, str]:
        """Return target type and ID for the action record."""
        return ("ProposedExtraction", str(self.extraction.id))

    def _get_tenant_id(self) -> UUID:
        """Return tenant ID for the action record."""
        return self.extraction.tenant_id

    def _get_idempotency_key(self) -> str:
        """Return idempotency key to prevent duplicate commits."""
        return f"commit-{self.extraction.id}"

    def _capture_pre_state(self) -> dict:
        """
        Capture state before mutation.

        Records the proposal status and any existing active fields
        for the document.
        """
        existing_field_ids = list(
            ExtractedField.objects.filter(
                document=self.extraction.document,
                is_active=True,
            ).values_list("id", flat=True)
        )

        return {
            "proposal_status": self.extraction.status,
            "proposal_reviewed_by": self.extraction.reviewed_by_id,
            "proposal_reviewed_at": (
                self.extraction.reviewed_at.isoformat()
                if self.extraction.reviewed_at
                else None
            ),
            "document_status": self.extraction.document.status,
            "existing_field_ids": [str(fid) for fid in existing_field_ids],
        }

    def _execute(self) -> None:
        """
        Perform the commit mutation.

        Creates ExtractedField records from each ProposedField,
        applying any field overrides provided.
        """
        now = timezone.now()

        # Determine committed_by user ID
        committed_by_id = None
        if self.actor_type == "user":
            try:
                committed_by_id = int(self.actor_id)
            except (ValueError, TypeError):
                pass

        # Create ExtractedField for each ProposedField
        for proposed_field in self.extraction.fields.all():
            # Apply overrides if present
            override = self.field_overrides.get(str(proposed_field.id), {})
            value = override.get("value", proposed_field.value)
            normalised_value = override.get(
                "normalised_value", proposed_field.normalised_value
            )

            extracted = ExtractedField.objects.create(
                tenant_id=self.extraction.tenant_id,
                document=self.extraction.document,
                source_proposal=self.extraction,
                source_proposed_field=proposed_field,
                field_type=proposed_field.field_type,
                field_name=proposed_field.field_name,
                value=value,
                normalised_value=normalised_value,
                source_text=proposed_field.source_text,
                source_page=proposed_field.source_page,
                source_location=proposed_field.source_location,
                confidence=proposed_field.confidence,
                committed_by_id=committed_by_id,
                committed_action=self._action_record,
                is_active=True,
            )
            self._created_field_ids.append(extracted.id)

        # Update proposal status
        self.extraction.status = ProposalStatus.COMMITTED
        self.extraction.reviewed_by_id = committed_by_id
        self.extraction.reviewed_at = now
        self.extraction.review_notes = self.review_notes
        self.extraction.committed_action = self._action_record
        self.extraction.save(
            update_fields=[
                "status",
                "reviewed_by_id",
                "reviewed_at",
                "review_notes",
                "committed_action",
                "updated_at",
            ]
        )

        # Update document status
        self.extraction.document.status = DocumentStatus.EXTRACTED
        self.extraction.document.extraction_completed_at = now
        self.extraction.document.save(
            update_fields=[
                "status",
                "extraction_completed_at",
                "updated_at",
            ]
        )

    def _capture_post_state(self) -> dict:
        """
        Capture state after mutation.

        Records the updated proposal status and IDs of created fields.
        """
        return {
            "proposal_status": self.extraction.status,
            "proposal_reviewed_by": self.extraction.reviewed_by_id,
            "proposal_reviewed_at": (
                self.extraction.reviewed_at.isoformat()
                if self.extraction.reviewed_at
                else None
            ),
            "document_status": self.extraction.document.status,
            "created_field_ids": [str(fid) for fid in self._created_field_ids],
            "field_count": len(self._created_field_ids),
        }

    def _rollback(self, original_action: Action) -> None:
        """
        Reverse the commit action.

        Soft-deletes created ExtractedFields and reverts the proposal
        and document status.
        """
        now = timezone.now()

        # Soft-delete created fields
        field_ids = original_action.post_state.get("created_field_ids", [])
        if field_ids:
            ExtractedField.objects.filter(id__in=field_ids).update(
                is_active=False,
                deactivated_at=now,
                deactivated_by_action=self._action_record,
            )

        # Revert proposal status
        self.extraction.status = ProposalStatus.PENDING
        self.extraction.reviewed_by = None
        self.extraction.reviewed_at = None
        self.extraction.review_notes = ""
        self.extraction.committed_action = None
        self.extraction.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_notes",
                "committed_action",
                "updated_at",
            ]
        )

        # Revert document status if no other committed extractions
        has_other_committed = (
            ProposedExtraction.objects.filter(
                document=self.extraction.document,
                status=ProposalStatus.COMMITTED,
            )
            .exclude(id=self.extraction.id)
            .exists()
        )

        if not has_other_committed:
            # Check if there are other active extracted fields
            has_active_fields = (
                ExtractedField.objects.filter(
                    document=self.extraction.document,
                    is_active=True,
                )
                .exclude(id__in=field_ids)
                .exists()
            )

            if not has_active_fields:
                self.extraction.document.status = DocumentStatus.PENDING
                self.extraction.document.extraction_completed_at = None
                self.extraction.document.save(
                    update_fields=[
                        "status",
                        "extraction_completed_at",
                        "updated_at",
                    ]
                )

    def _get_metadata(self) -> dict:
        """Return additional metadata for the action record."""
        return {
            "agent_run_id": str(self.extraction.agent_run_id),
            "model_version": self.extraction.model_version,
            "field_count": len(self._created_field_ids),
            "had_overrides": bool(self.field_overrides),
            "override_count": len(self.field_overrides),
        }


class RejectExtractionAction(BaseAction):
    """
    Rejects a proposed extraction.

    This action:
    1. Updates ProposedExtraction status to REJECTED
    2. Records the rejection reason
    3. Creates an immutable Action record

    Rejection is not reversible - a new extraction must be triggered
    if the document needs to be re-processed.
    """

    action_type = ActionType.REJECT_EXTRACTION
    is_reversible = False  # Rejections cannot be undone

    def __init__(
        self,
        extraction: ProposedExtraction,
        actor_id: str,
        actor_type: str,
        trace_id: str,
        reason: str,
    ) -> None:
        """
        Initialise the reject action.

        Args:
            extraction: The ProposedExtraction to reject
            actor_id: ID of the actor performing the rejection
            actor_type: Type of actor ('user', 'system', 'celery_task')
            trace_id: Request correlation ID
            reason: Reason for rejection (required)
        """
        super().__init__(actor_id, actor_type, trace_id)
        self.extraction = extraction
        self.reason = reason

    def _get_target(self) -> tuple[str, str]:
        """Return target type and ID for the action record."""
        return ("ProposedExtraction", str(self.extraction.id))

    def _get_tenant_id(self) -> UUID:
        """Return tenant ID for the action record."""
        return self.extraction.tenant_id

    def _get_idempotency_key(self) -> str:
        """Return idempotency key to prevent duplicate rejections."""
        return f"reject-{self.extraction.id}"

    def _capture_pre_state(self) -> dict:
        """Capture state before mutation."""
        return {
            "proposal_status": self.extraction.status,
            "proposal_reviewed_by": self.extraction.reviewed_by_id,
            "proposal_reviewed_at": (
                self.extraction.reviewed_at.isoformat()
                if self.extraction.reviewed_at
                else None
            ),
            "proposal_review_notes": self.extraction.review_notes,
        }

    def _execute(self) -> None:
        """Perform the rejection mutation."""
        now = timezone.now()

        # Determine reviewed_by user ID
        reviewed_by_id = None
        if self.actor_type == "user":
            try:
                reviewed_by_id = int(self.actor_id)
            except (ValueError, TypeError):
                pass

        # Update proposal status
        self.extraction.status = ProposalStatus.REJECTED
        self.extraction.reviewed_by_id = reviewed_by_id
        self.extraction.reviewed_at = now
        self.extraction.review_notes = self.reason
        self.extraction.save(
            update_fields=[
                "status",
                "reviewed_by_id",
                "reviewed_at",
                "review_notes",
                "updated_at",
            ]
        )

    def _capture_post_state(self) -> dict:
        """Capture state after mutation."""
        return {
            "proposal_status": self.extraction.status,
            "proposal_reviewed_by": self.extraction.reviewed_by_id,
            "proposal_reviewed_at": (
                self.extraction.reviewed_at.isoformat()
                if self.extraction.reviewed_at
                else None
            ),
            "proposal_review_notes": self.extraction.review_notes,
            "rejection_reason": self.reason,
        }

    def _get_metadata(self) -> dict:
        """Return additional metadata for the action record."""
        return {
            "agent_run_id": str(self.extraction.agent_run_id),
            "model_version": self.extraction.model_version,
            "rejection_reason": self.reason,
            "document_id": str(self.extraction.document_id),
        }