"""
==============================================================================
FILE: urls.py
LOCATION: /docextract/apps/documents/urls.py
==============================================================================

PURPOSE:
    URL routing for the documents app. Maps URL patterns to views for
    document upload, retrieval, and extraction triggering.

INCLUDED BY:
    config/urls.py: path("api/v1/", include("apps.documents.urls"))

URL PATTERNS:
    POST   /api/v1/documents/                      - Upload new document
    GET    /api/v1/documents/                      - List documents
    GET    /api/v1/documents/{id}/                 - Get document details
    DELETE /api/v1/documents/{id}/                 - Delete document
    POST   /api/v1/documents/{id}/extract/         - Trigger AI extraction
    GET    /api/v1/documents/{id}/download/        - Download original file
    GET    /api/v1/documents/{id}/extractions/     - List document extractions

AUTHENTICATION:
    All endpoints require authentication (see REST_FRAMEWORK settings).

DESIGN DECISIONS:
    - ViewSet router for standard CRUD operations
    - Explicit paths for non-standard actions (extract, download, extractions)
    - Custom paths BEFORE router to prevent router catching them as <pk>
    - UUID path converter for document IDs

TESTING:
    from django.urls import reverse

    url = reverse('document-list')  # /api/v1/documents/
    url = reverse('document-detail', kwargs={'pk': doc_id})
    url = reverse('document-extract', kwargs={'document_id': doc_id})

==============================================================================
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.documents.views import (
    DocumentViewSet,
    DocumentExtractView,
    DocumentDownloadView,
    DocumentExtractionsView,
)


# Router for ViewSet
router = DefaultRouter()
router.register(r"documents", DocumentViewSet, basename="document")

urlpatterns = [
    # Custom action routes FIRST (before router catches them as <pk>)
    path(
        "documents/<uuid:document_id>/extract/",
        DocumentExtractView.as_view(),
        name="document-extract",
    ),
    path(
        "documents/<uuid:document_id>/download/",
        DocumentDownloadView.as_view(),
        name="document-download",
    ),
    path(
        "documents/<uuid:document_id>/extractions/",
        DocumentExtractionsView.as_view(),
        name="document-extractions",
    ),

    # ViewSet routes (list, create, retrieve, delete) - LAST
    path("", include(router.urls)),
]