"""
==============================================================================
FILE: urls.py
LOCATION: /docextract/config/urls.py
==============================================================================

PURPOSE:
    Root URL configuration for DocExtract. Maps URL patterns to views and
    includes URL configurations from each Django app.

URL STRUCTURE:
    /admin/              - Django admin interface
    /api/v1/documents/   - Document upload and management (apps.documents)
    /api/v1/extractions/ - Extraction proposals and commits (apps.extraction)
    /api/v1/actions/     - Audit log and action history (apps.actions)
    /health/             - Health check endpoint for monitoring
    /media/              - User-uploaded files (DEBUG mode only)

API VERSIONING:
    All API endpoints are prefixed with /api/v1/. When breaking changes are
    needed, create /api/v2/ routes while maintaining v1 for backwards
    compatibility.

USAGE:
    This file is referenced by config.settings.base.ROOT_URLCONF.
    Each app defines its own urls.py which is included here.

ADDING NEW ROUTES:
    1. Create urls.py in your app with urlpatterns
    2. Include it here: path("api/v1/", include("apps.yourapp.urls"))
    3. For non-API routes, add directly to urlpatterns

PERFORMANCE NOTES:
    - URL resolution is O(n) on pattern count; keep patterns organized
    - Static/media files should be served by nginx in production

TESTING:
    - Use Django's test client: self.client.get('/api/v1/documents/')
    - Use reverse() for URL resolution: reverse('document-list')

==============================================================================
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.common.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.documents.urls")),
    path("api/v1/", include("apps.extraction.urls")),
    path("api/v1/", include("apps.actions.urls")),
    path("health/", health_check, name="health_check"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)