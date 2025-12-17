"""
==============================================================================
FILE: models.py
LOCATION: /docextract/apps/actions/models.py
==============================================================================

PURPOSE:
    Defines the Action model for immutable audit logging of all state changes.
    Every mutation to domain state creates an Action record capturing who,
    what, when, and the before/after state.

MODELS:
    - ActionType: Enumeration of all possible action types
    - ActionStatus: Enumeration of action completion states
    - Action: Immutable audit record of a state change

USAGE:
    from apps.actions.models import Action, ActionType, ActionStatus

    action = Action.objects.create(
        action_type=ActionType.COMMIT_EXTRACTION,
        actor_type='user',
        actor_id=str(user.id),
        actor_email=user.email,
        target_type='ProposedExtraction',
        target_id=str(extraction.id),
        tenant_id=extraction.tenant_id,
        trace_id=request.trace_id,
        pre_state={'status': 'pending'},
        post_state={'status': 'committed'},
    )

DESIGN DECISIONS:
    - Actions are append-only; never updated or deleted
    - Rollback creates a NEW Action that reverses the original
    - Generic foreign key pattern (target_type + target_id) for flexibility
    - Pre/post state as JSONB enables flexible schema evolution
    - Idempotency key prevents duplicate actions from retries

PERFORMANCE NOTES:
    - Indexes on trace_id and target for correlation queries
    - Consider partitioning by created_at for large deployments
    - Pre/post state should capture only relevant fields, not full objects

TESTING:
    - Verify idempotency_key uniqueness constraint
    - Test rollback chain integrity (reversed_by / reverses)
    - Verify pre/post state accuracy for each action type

==============================================================================
"""

import uuid

from django.db import models

from apps.common.models import TimestampMixin


class ActionType(models.TextChoices):
    """
    Enumeration of all auditable action types.

    Each action type corresponds to a specific domain operation that
    mutates state and requires audit logging.
    """

    COMMIT_EXTRACTION = "commit_extraction", "Commit Extraction"
    ROLLBACK_EXTRACTION = "rollback_extraction", "Rollback Extraction"
    REJECT_EXTRACTION = "reject_extraction", "Reject Extraction"
    UPDATE_FIELD = "update_field", "Update Field"
    DELETE_FIELD = "delete_field", "Delete Field"
    DOCUMENT_UPLOAD = "document_upload", "Document Upload"
    DOCUMENT_DELETE = "document_delete", "Document Delete"


class ActionStatus(models.TextChoices):
    """
    Enumeration of action completion states.

    Actions transition through states:
    - PENDING: Action is being processed
    - COMPLETED: Action finished successfully
    - FAILED: Action encountered an error
    - ROLLED_BACK: Action was reversed by another action
    """

    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    ROLLED_BACK = "rolled_back", "Rolled Back"


class Action(TimestampMixin, models.Model):
    """
    Immutable audit record of a state change.

    Every mutation to domain state should create an Action record.
    Actions capture:
    - Who performed the action (actor)
    - What was changed (target)
    - The state before and after
    - Whether it can be reversed

    Actions are append-only; they are never updated or deleted.
    Rollback creates a NEW Action that reverses the original.

    Attributes:
        action_type: Classification of the action (commit, rollback, etc.)
        status: Current completion state of the action
        actor_type: Category of actor (user, system, celery_task)
        actor_id: Identifier of the actor (user ID or system name)
        actor_email: Denormalised email for readability in logs
        target_type: Model class name of the affected entity
        target_id: Primary key of the affected entity
        tenant_id: UUID of the tenant where action occurred
        trace_id: Request correlation ID for distributed tracing
        idempotency_key: Unique key to prevent duplicate actions
        pre_state: JSONB snapshot of state before mutation
        post_state: JSONB snapshot of state after mutation
        is_reversible: Whether this action can be rolled back
        reversed_by: Reference to the action that reversed this one
        reverses: Reference to the action this one reverses
        metadata: Additional context (agent_run_id, etc.)
        error_message: Error details if status is FAILED
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    # Classification
    action_type = models.CharField(
        max_length=50,
        choices=ActionType.choices,
        db_index=True,
        help_text="Type of action performed",
    )

    status = models.CharField(
        max_length=20,
        choices=ActionStatus.choices,
        default=ActionStatus.COMPLETED,
        help_text="Completion status of the action",
    )

    # Actor information
    actor_type = models.CharField(
        max_length=20,
        default="user",
        help_text="Category of actor: user, system, or celery_task",
    )

    actor_id = models.CharField(
        max_length=100,
        help_text="User ID or system identifier",
    )

    actor_email = models.EmailField(
        blank=True,
        help_text="Denormalised email for readability in audit logs",
    )

    # Target (generic foreign key pattern)
    target_type = models.CharField(
        max_length=100,
        help_text="Model class name of the affected entity",
    )

    target_id = models.CharField(
        max_length=100,
        help_text="Primary key of the affected entity",
    )

    # Tenant context (stored as UUID, not FK, for flexibility)
    tenant_id = models.UUIDField(
        db_index=True,
        help_text="Tenant where action occurred",
    )

    # Tracing and idempotency
    trace_id = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Request trace ID for correlation across services",
    )

    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Unique key to prevent duplicate actions from retries",
    )

    # State capture
    pre_state = models.JSONField(
        default=dict,
        help_text="JSONB snapshot of state before mutation",
    )

    post_state = models.JSONField(
        default=dict,
        help_text="JSONB snapshot of state after mutation",
    )

    # Reversibility
    is_reversible = models.BooleanField(
        default=True,
        help_text="Whether this action can be rolled back",
    )

    reversed_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reverses_set",
        help_text="The action that reversed this one",
    )

    reverses = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_by_set",
        help_text="The action that this one reverses",
    )

    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context (agent_run_id, model_version, etc.)",
    )

    error_message = models.TextField(
        blank=True,
        help_text="Error details if status is FAILED",
    )

    class Meta:
        db_table = "actions"
        indexes = [
            models.Index(
                fields=["tenant_id", "action_type"],
                name="ix_actions_tenant_type",
            ),
            models.Index(
                fields=["tenant_id", "created_at"],
                name="ix_actions_tenant_created",
            ),
            models.Index(
                fields=["target_type", "target_id"],
                name="ix_actions_target",
            ),
            models.Index(
                fields=["trace_id"],
                name="ix_actions_trace_id",
            ),
            models.Index(
                fields=["actor_id"],
                name="ix_actions_actor_id",
            ),
        ]
        ordering = ["-created_at"]
        verbose_name = "Action"
        verbose_name_plural = "Actions"

    def __str__(self) -> str:
        return f"{self.action_type} on {self.target_type}:{self.target_id}"

    def save(self, *args, **kwargs):
        """
        Override save to enforce immutability after creation.

        Actions should never be updated after initial creation.
        Updates to status should create new actions instead.
        """
        if self.pk and Action.objects.filter(pk=self.pk).exists():
            raise ValueError(
                "Actions are immutable and cannot be updated. "
                "Create a new action to record state changes."
            )
        super().save(*args, **kwargs)