"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/documents/__init__.py
==============================================================================

PURPOSE:
    Package initialisation for the documents app. Handles document upload,
    storage, and lifecycle management.

APP CONTENTS:
    models.py      - Document model
    admin.py       - Django admin configuration
    views.py       - API views for document operations
    urls.py        - URL routing for /api/v1/documents/
    services.py    - Business logic (DocumentService)
    selectors.py   - Query logic (DocumentSelector)

RESPONSIBILITIES:
    - File upload with validation (type, size, hash)
    - Document metadata storage
    - Status tracking (pending → processing → extracted → failed)
    - Triggering extraction workflows

DEPENDENCIES:
    - apps.common (base models, middleware)
    - apps.extraction (triggers extraction tasks)

API ENDPOINTS:
    POST   /api/v1/documents/           - Upload document
    GET    /api/v1/documents/           - List documents
    GET    /api/v1/documents/{id}/      - Retrieve document
    POST   /api/v1/documents/{id}/extract/ - Trigger extraction
    GET    /api/v1/documents/{id}/download/ - Download file

==============================================================================
"""

default_app_config = "apps.documents.apps.DocumentsConfig"