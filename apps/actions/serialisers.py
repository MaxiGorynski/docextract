"""
==============================================================================
FILE: serialisers.py
LOCATION: /docextract/apps/actions/serialisers.py
==============================================================================

PURPOSE:
    DRF serialisers for the Actions API. Handles serialisation of Action
    audit records for list, retrieve, and rollback endpoints.

SERIALISERS:
    - ActorSerialiser: Actor information (user or system)
    - TargetSerialiser: Target entity reference
    - ActionListSerialiser: Compact representation for list views
    - ActionDetailSerialiser: Full representation with state snapshots
    - RollbackRequestSerialiser: Request body for action rollback
    - RollbackResponseSerialiser: Response after successful rollback

USAGE:
    from apps.actions.serialisers import (
        ActionListSerialiser,
        ActionDetailSerialiser,
        RollbackRequestSerialiser,
    )

    # In viewset
    def get_serialiser_class(self):
        if self.action == 'list':
            return ActionListSerialiser
        return ActionDetailSerialiser

DESIGN DECISIONS:
    - Actions are read-only (immutable audit log)
    - Rollback creates new action, doesn't modify existing
    - Pre/post state exposed for debugging and compliance
    - Actor/target as nested objects for clear structure

PERFORMANCE NOTES:
    - List queries should use select_related for reversed_by
    - Detail view includes full state snapshots (may be large)
    - Consider pagination for high-volume action logs

==============================================================================
"""

from rest_framework import serializers

from apps.actions.models import Action, ActionType, ActionStatus


class ActorSerialiser(serializers.Serializer):
    """
    Actor information for action audit display.

    Represents who performed the action (user, system, or Celery task).
    """

    type = serializers.CharField(source="actor_type", read_only=True)
    id = serializers.CharField(source="actor_id", read_only=True)
    email = serializers.CharField(source="actor_email", read_only=True)


class TargetSerialiser(serializers.Serializer):
    """
    Target entity reference for action audit display.

    Generic reference to the entity affected by the action.
    """

    type = serializers.CharField(source="target_type", read_only=True)
    id = serializers.CharField(source="target_id", read_only=True)


class ActionListSerialiser(serializers.ModelSerializer):
    """
    Compact action representation for list views.

    Shows essential audit information without full state snapshots.
    Suitable for audit log browsing and filtering.
    """

    actor = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    reversed_by = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = [
            "id",
            "action_type",
            "status",
            "actor",
            "target",
            "is_reversible",
            "reversed_by",
            "trace_id",
            "created_at",
        ]
        read_only_fields = fields

    def get_actor(self, obj: Action) -> dict:
        """Return actor information as nested object."""
        return {
            "type": obj.actor_type,
            "id": obj.actor_id,
            "email": obj.actor_email,
        }

    def get_target(self, obj: Action) -> dict:
        """Return target information as nested object."""
        return {
            "type": obj.target_type,
            "id": obj.target_id,
        }

    def get_reversed_by(self, obj: Action) -> str | None:
        """Return ID of reversing action if exists."""
        if obj.reversed_by_id:
            return str(obj.reversed_by_id)
        return None


class ActionDetailSerialiser(serializers.ModelSerializer):
    """
    Full action representation with state snapshots.

    Includes complete audit information:
    - Actor and target details
    - Pre and post state for debugging
    - Rollback chain references
    - Additional metadata

    Used for detailed action inspection and compliance review.
    """

    actor = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    reversed_by = serializers.SerializerMethodField()
    reverses = serializers.SerializerMethodField()
    links = serializers.SerializerMethodField()

    class Meta:
        model = Action
        fields = [
            "id",
            "action_type",
            "status",
            "actor",
            "target",
            "trace_id",
            "idempotency_key",
            "pre_state",
            "post_state",
            "is_reversible",
            "reversed_by",
            "reverses",
            "metadata",
            "error_message",
            "created_at",
            "links",
        ]
        read_only_fields = fields

    def get_actor(self, obj: Action) -> dict:
        """Return actor information as nested object."""
        return {
            "type": obj.actor_type,
            "id": obj.actor_id,
            "email": obj.actor_email,
        }

    def get_target(self, obj: Action) -> dict:
        """Return target information as nested object."""
        return {
            "type": obj.target_type,
            "id": obj.target_id,
        }

    def get_reversed_by(self, obj: Action) -> str | None:
        """Return ID of reversing action if exists."""
        if obj.reversed_by_id:
            return str(obj.reversed_by_id)
        return None

    def get_reverses(self, obj: Action) -> str | None:
        """Return ID of action this one reverses if applicable."""
        if obj.reverses_id:
            return str(obj.reverses_id)
        return None

    def get_links(self, obj: Action) -> dict:
        """Generate HATEOAS-style links for the action."""
        base = f"/api/v1/actions/{obj.id}"
        links = {
            "self": f"{base}/",
        }

        # Only include rollback link if action is reversible and not yet reversed
        if obj.is_reversible and not obj.reversed_by_id:
            links["rollback"] = f"{base}/rollback/"

        return links


class RollbackRequestSerialiser(serializers.Serializer):
    """
    Request body for rolling back an action.

    Used by POST /api/v1/actions/{id}/rollback/ endpoint.
    """

    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Reason for rollback",
    )


class RestoredStateSerialiser(serializers.Serializer):
    """
    Serialiser for restored state information in rollback response.
    """

    proposal_status = serializers.CharField(read_only=True)
    deactivated_field_count = serializers.IntegerField(read_only=True)


class RollbackActionSerialiser(serializers.Serializer):
    """
    Serialiser for the rollback action in response.
    """

    id = serializers.UUIDField(read_only=True)
    action_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    reverses = serializers.UUIDField(read_only=True)


class RollbackResponseSerialiser(serializers.Serializer):
    """
    Response after successful action rollback.

    Includes the new rollback action and restored state information.
    """

    original_action_id = serializers.UUIDField(read_only=True)
    rollback_action = RollbackActionSerialiser(read_only=True)
    restored_state = RestoredStateSerialiser(read_only=True)
    message = serializers.CharField(read_only=True)