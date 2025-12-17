"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/actions/__init__.py
==============================================================================

PURPOSE:
    Package initialisation for the actions app. Provides auditable state
    change tracking with pre/post state capture and rollback support.

APP CONTENTS:
    models.py      - Action model for audit logging
    admin.py       - Django admin for viewing action history
    views.py       - API views for action operations
    urls.py        - URL routing for /api/v1/actions/
    base.py        - BaseAction, ReversibleAction base classes

RESPONSIBILITIES:
    - Recording all state-changing operations
    - Capturing pre-state and post-state for debugging
    - Supporting rollback of reversible actions
    - Providing audit trail for compliance

ACTION PATTERN:
    Instead of directly mutating models, mutations go through Actions:

    # Without Actions (bad):
    extraction.status = 'committed'
    extraction.save()

    # With Actions (good):
    action = CommitExtractionAction(extraction, actor, trace_id)
    action.execute()  # Captures state, mutates, logs

STORED DATA:
    - action_type: What operation was performed
    - actor_id/actor_type: Who performed it (user, system, celery)
    - target_type/target_id: What was modified
    - pre_state: JSON snapshot before mutation
    - post_state: JSON snapshot after mutation
    - trace_id: Request correlation ID
    - is_reversible: Whether rollback is supported

DEPENDENCIES:
    - apps.common (base models)

API ENDPOINTS:
    GET    /api/v1/actions/              - List actions (audit log)
    GET    /api/v1/actions/{id}/         - Retrieve action details
    POST   /api/v1/actions/{id}/rollback/ - Rollback action

==============================================================================
"""

default_app_config = "apps.actions.apps.ActionsConfig"