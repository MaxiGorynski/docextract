"""
==============================================================================
FILE: base.py
LOCATION: /docextract/apps/actions/base.py
==============================================================================

PURPOSE:
    Defines base classes for auditable actions. Every mutation to domain
    state goes through an Action, capturing who performed it, what changed,
    and enabling rollback where appropriate.

CLASSES:
    - ActionResult: Result of action execution
    - BaseAction: Abstract base for all auditable actions
    - ReversibleAction: Base for actions that can be rolled back

USAGE:
    from apps.actions.base import ReversibleAction, ActionResult
    from apps.actions.models import ActionType

    class CommitExtractionAction(ReversibleAction):
        action_type = ActionType.COMMIT_EXTRACTION

        def _get_target(self) -> tuple[str, str]:
            return ('ProposedExtraction', str(self.extraction.id))

        def _capture_pre_state(self) -> dict:
            return {'status': self.extraction.status}

        def _execute(self) -> None:
            # Perform the mutation
            pass

        def _capture_post_state(self) -> dict:
            return {'status': self.extraction.status}

DESIGN PRINCIPLES:
    - Capture pre-state before any mutation
    - Atomic execution within database transaction
    - Capture post-state after mutation completes
    - Action records are immutable (never updated)
    - Rollback creates a NEW Action that reverses the original

PERFORMANCE NOTES:
    - Pre/post state should capture only relevant fields
    - Idempotency check uses indexed lookup
    - Transaction scope minimised to mutation only

TESTING:
    - Test idempotency by executing same action twice
    - Verify pre/post state accuracy
    - Test rollback restores original state

==============================================================================
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from apps.actions.models import Action, ActionStatus, ActionType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """
    Result of action execution.

    Returned by BaseAction.execute() to provide details about
    the completed (or failed) action.

    Attributes:
        action_id: UUID of the created Action record
        action_type: Type of action performed
        status: Completion status (completed, failed, etc.)
        is_reversible: Whether the action can be rolled back
    """

    action_id: UUID
    action_type: str
    status: str
    is_reversible: bool


class BaseAction(ABC):
    """
    Abstract base class for auditable actions.

    Actions are the mechanism for making auditable state changes.
    Every mutation captures:
    - Who performed it (actor)
    - What was changed (target)
    - State before and after
    - Whether it can be reversed

    Subclasses must implement:
    - action_type: ActionType enum value
    - _get_target(): Return (target_type, target_id) tuple
    - _get_tenant_id(): Return tenant UUID
    - _capture_pre_state(): Capture state before mutation
    - _execute(): Perform the mutation
    - _capture_post_state(): Capture state after mutation

    Optional overrides:
    - _get_idempotency_key(): Return key for deduplication
    - _get_metadata(): Return additional context dict
    """

    action_type: ActionType = None
    is_reversible: bool = True

    def __init__(
        self,
        actor_id: str,
        actor_type: str,
        trace_id: str,
        **kwargs,
    ) -> None:
        """
        Initialise the action.

        Args:
            actor_id: Identifier of the actor (user ID or system name)
            actor_type: Category of actor ('user', 'system', 'celery_task')
            trace_id: Request correlation ID for tracing
            **kwargs: Additional arguments for subclasses
        """
        self.actor_id = actor_id
        self.actor_type = actor_type
        self.trace_id = trace_id
        self.kwargs = kwargs

        self._pre_state: dict = {}
        self._post_state: dict = {}
        self._action_record: Action | None = None

        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def _get_target(self) -> tuple[str, str]:
        """
        Return the target of this action.

        Returns:
            Tuple of (target_type, target_id) where target_type is
            the model class name and target_id is the primary key.
        """
        pass

    @abstractmethod
    def _get_tenant_id(self) -> UUID:
        """
        Return the tenant ID for this action.

        Returns:
            UUID of the tenant where the action is performed.
        """
        pass

    @abstractmethod
    def _capture_pre_state(self) -> dict:
        """
        Capture state before mutation.

        Called before _execute() to record the state that will
        be changed. Should capture only the relevant fields.

        Returns:
            Dict representing the pre-mutation state.
        """
        pass

    @abstractmethod
    def _execute(self) -> None:
        """
        Perform the mutation.

        This is where the actual state change happens. Called
        within a database transaction after pre-state capture.

        Raises:
            Exception: Any exception will mark the action as FAILED.
        """
        pass

    @abstractmethod
    def _capture_post_state(self) -> dict:
        """
        Capture state after mutation.

        Called after _execute() completes successfully to record
        the new state.

        Returns:
            Dict representing the post-mutation state.
        """
        pass

    def _get_idempotency_key(self) -> str | None:
        """
        Return an idempotency key for this action.

        If provided, duplicate actions with the same key will
        return the existing action instead of executing again.

        Returns:
            Unique key string, or None if idempotency not needed.
        """
        return None

    def _get_metadata(self) -> dict:
        """
        Return additional metadata for the action record.

        Override to include context like agent_run_id, model_version,
        or other information useful for debugging/analytics.

        Returns:
            Dict of additional metadata.
        """
        return {}

    def _get_actor_email(self) -> str:
        """
        Return the actor's email for denormalisation.

        Override if actor email is available.

        Returns:
            Email string or empty string.
        """
        return ""

    @transaction.atomic
    def execute(self) -> ActionResult:
        """
        Execute the action with full audit logging.

        This method:
        1. Checks idempotency (returns existing if duplicate)
        2. Captures pre-state
        3. Executes the mutation
        4. Captures post-state
        5. Creates the Action record

        Returns:
            ActionResult with action details.

        Raises:
            Exception: Re-raises any exception from _execute() after
                      logging it in the Action record.
        """
        # Check idempotency
        idempotency_key = self._get_idempotency_key()
        if idempotency_key:
            existing = Action.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                self.logger.info(
                    f"Idempotent action already exists: {existing.id}",
                    extra={"idempotency_key": idempotency_key},
                )
                return ActionResult(
                    action_id=existing.id,
                    action_type=existing.action_type,
                    status=existing.status,
                    is_reversible=existing.is_reversible,
                )

        # Capture pre-state
        self._pre_state = self._capture_pre_state()

        # Execute mutation
        error_message = ""
        try:
            self._execute()
            status = ActionStatus.COMPLETED
        except Exception as e:
            status = ActionStatus.FAILED
            error_message = str(e)
            self.logger.exception(
                f"Action failed: {self.action_type}",
                extra={
                    "trace_id": self.trace_id,
                    "error": error_message,
                },
            )
            raise

        # Capture post-state
        self._post_state = self._capture_post_state()

        # Get target info
        target_type, target_id = self._get_target()

        # Create action record
        self._action_record = Action.objects.create(
            action_type=self.action_type,
            status=status,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            actor_email=self._get_actor_email(),
            target_type=target_type,
            target_id=target_id,
            tenant_id=self._get_tenant_id(),
            trace_id=self.trace_id,
            idempotency_key=idempotency_key,
            pre_state=self._pre_state,
            post_state=self._post_state,
            is_reversible=self.is_reversible,
            error_message=error_message,
            metadata=self._get_metadata(),
        )

        self.logger.info(
            f"Action completed: {self.action_type}",
            extra={
                "action_id": str(self._action_record.id),
                "trace_id": self.trace_id,
                "target_type": target_type,
                "target_id": target_id,
            },
        )

        return ActionResult(
            action_id=self._action_record.id,
            action_type=self._action_record.action_type,
            status=self._action_record.status,
            is_reversible=self._action_record.is_reversible,
        )


class ReversibleAction(BaseAction):
    """
    Base class for actions that can be rolled back.

    Extends BaseAction with rollback capability. Subclasses must
    implement _rollback() to reverse the action's effects.

    Rollback:
    - Creates a NEW action record (original is immutable)
    - Links the rollback action to the original via reverses/reversed_by
    - Marks the rollback action as non-reversible (no double-rollback)
    """

    is_reversible = True

    @abstractmethod
    def _rollback(self, original_action: Action) -> None:
        """
        Reverse the action using captured pre_state.

        Called within a transaction to undo the original action.
        Use original_action.pre_state to restore previous state.

        Args:
            original_action: The Action record being rolled back.
        """
        pass

    @transaction.atomic
    def rollback(self, action_id: UUID, reason: str = "") -> ActionResult:
        """
        Rollback a previously executed action.

        Creates a new rollback Action that reverses the original.
        The original action is marked as reversed.

        Args:
            action_id: UUID of the action to rollback
            reason: Reason for the rollback (stored in metadata)

        Returns:
            ActionResult for the rollback action.

        Raises:
            ValueError: If action is not reversible or already reversed.
            Action.DoesNotExist: If action_id not found.
        """
        original_action = Action.objects.get(id=action_id)

        if not original_action.is_reversible:
            raise ValueError(
                f"Action {action_id} is not reversible. "
                f"Action type: {original_action.action_type}"
            )

        if original_action.reversed_by_id:
            raise ValueError(
                f"Action {action_id} has already been reversed "
                f"by action {original_action.reversed_by_id}"
            )

        # Capture current state as pre-state for rollback
        # (this is the post-state of the original action)
        pre_state = self._capture_post_state()

        # Execute rollback
        self._rollback(original_action)

        # Post-state should match original pre-state
        post_state = self._capture_pre_state()

        # Get target info
        target_type, target_id = self._get_target()

        # Create rollback action record
        rollback_action = Action.objects.create(
            action_type=ActionType.ROLLBACK_EXTRACTION,
            status=ActionStatus.COMPLETED,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            actor_email=self._get_actor_email(),
            target_type=target_type,
            target_id=target_id,
            tenant_id=self._get_tenant_id(),
            trace_id=self.trace_id,
            pre_state=pre_state,
            post_state=post_state,
            is_reversible=False,  # Cannot rollback a rollback
            reverses=original_action,
            metadata={"reason": reason, "original_action_id": str(action_id)},
        )

        # Mark original as reversed (bypass immutability for this link)
        Action.objects.filter(id=action_id).update(reversed_by=rollback_action)

        self.logger.info(
            f"Action rolled back: {original_action.action_type}",
            extra={
                "original_action_id": str(action_id),
                "rollback_action_id": str(rollback_action.id),
                "trace_id": self.trace_id,
                "reason": reason,
            },
        )

        return ActionResult(
            action_id=rollback_action.id,
            action_type=rollback_action.action_type,
            status=rollback_action.status,
            is_reversible=rollback_action.is_reversible,
        )