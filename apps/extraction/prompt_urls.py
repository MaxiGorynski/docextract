"""
==============================================================================
FILE: prompt_urls.py
LOCATION: /docextract/apps/extraction/prompt_urls.py
==============================================================================

PURPOSE:
    URL routing for the prompt template API. Provides endpoints for
    viewing and editing extraction prompts.

INTEGRATION:
    Add to apps/extraction/urls.py:

        from apps.extraction.prompt_urls import prompt_urlpatterns

        urlpatterns = [
            # ... existing patterns ...
        ] + prompt_urlpatterns

    Or include directly:

        path("", include("apps.extraction.prompt_urls")),

ENDPOINTS:
    GET    /api/v1/prompts/                  - List all templates
    POST   /api/v1/prompts/                  - Create new template
    GET    /api/v1/prompts/{id}/             - Get template detail
    PUT    /api/v1/prompts/{id}/             - Update template
    PATCH  /api/v1/prompts/{id}/             - Partial update
    DELETE /api/v1/prompts/{id}/             - Delete template
    POST   /api/v1/prompts/{id}/activate/    - Activate template
    POST   /api/v1/prompts/{id}/deactivate/  - Deactivate template
    POST   /api/v1/prompts/{id}/duplicate/   - Duplicate template
    GET    /api/v1/prompts/active/           - Get active prompt
    GET    /api/v1/prompts/placeholders/     - List placeholders
    GET    /api/v1/prompts/defaults/         - Get default prompts and field examples
    POST   /api/v1/prompts/create-default/   - Create from defaults

==============================================================================
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.extraction.prompt_views import (
    PromptTemplateViewSet,
    ActivePromptView,
    PromptPlaceholdersView,
    PromptDefaultsView,
    CreateDefaultPromptView,
)

# Router for ViewSet
prompt_router = DefaultRouter()
prompt_router.register(r"prompts", PromptTemplateViewSet, basename="prompt")

# URL patterns to be included
prompt_urlpatterns = [
    # Custom endpoints FIRST (before router catches them as <pk>)
    path(
        "prompts/active/",
        ActivePromptView.as_view(),
        name="prompt-active",
    ),
    path(
        "prompts/active/<str:document_type>/",
        ActivePromptView.as_view(),
        name="prompt-active-doctype",
    ),
    path(
        "prompts/placeholders/",
        PromptPlaceholdersView.as_view(),
        name="prompt-placeholders",
    ),
    path(
        "prompts/defaults/",
        PromptDefaultsView.as_view(),
        name="prompt-defaults",
    ),
    path(
        "prompts/create-default/",
        CreateDefaultPromptView.as_view(),
        name="prompt-create-default",
    ),

    # ViewSet routes (CRUD) - LAST
    path("", include(prompt_router.urls)),
]