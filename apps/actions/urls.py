"""
==============================================================================
FILE: urls.py
LOCATION: /docextract/apps/actions/urls.py
==============================================================================

PURPOSE:
    URL routing for the actions app. Maps URL patterns to views for
    accessing the audit log and performing rollback operations.

INCLUDED BY:
    config/urls.py: path("api/v1/", include("apps.actions.urls"))

URL PATTERNS:
    GET    /api/v1/actions/              - List actions (audit log)
    GET    /api/v1/actions/{id}/         - Get action details
    POST   /api/v1/actions/{id}/rollback/ - Rollback a reversible action

AUTHENTICATION:
    All endpoints require authentication.

DESIGN DECISIONS:
    - ReadOnlyModelViewSet for list/retrieve (actions are immutable)
    - Explicit path for rollback action
    - UUID path converter for action IDs
    - Comprehensive filtering support for audit trail analysis

TESTING:
    from django.urls import reverse

    url = reverse('action-list')  # /api/v1/actions/
    url = reverse('action-detail', kwargs={'id': action_id})
    url = reverse('action-rollback', kwargs={'action_id': action_id})

==============================================================================
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.actions.views import (
    ActionViewSet,
    ActionRollbackView,
)


# Router for ViewSet
router = DefaultRouter()
router.register(r"actions", ActionViewSet, basename="action")

urlpatterns = [
    # ViewSet routes (list, retrieve)
    path("", include(router.urls)),

    # Custom action routes
    path(
        "actions/<uuid:action_id>/rollback/",
        ActionRollbackView.as_view(),
        name="action-rollback",
    ),
]