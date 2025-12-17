"""
==============================================================================
FILE: urls.py
LOCATION: /docextract/apps/extraction/urls.py
==============================================================================
... (header unchanged) ...
==============================================================================
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.extraction.views import (
    ExtractionViewSet,
    ExtractionCommitView,
    ExtractionRejectView,
)
from apps.extraction.prompt_urls import prompt_urlpatterns


# Router for ViewSet
router = DefaultRouter()
router.register(r"extractions", ExtractionViewSet, basename="extraction")

urlpatterns = [
    # ViewSet routes (retrieve only)
    path("", include(router.urls)),

    # Custom action routes
    path(
        "extractions/<uuid:extraction_id>/commit/",
        ExtractionCommitView.as_view(),
        name="extraction-commit",
    ),
    path(
        "extractions/<uuid:extraction_id>/reject/",
        ExtractionRejectView.as_view(),
        name="extraction-reject",
    ),
] + prompt_urlpatterns  # Append prompt URLs at the end