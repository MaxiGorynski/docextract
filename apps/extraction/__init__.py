"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/extraction/__init__.py
==============================================================================

PURPOSE:
    Package initialisation for the extraction app. Handles AI-powered field
    extraction, proposal management, and the two-phase commit workflow.

APP CONTENTS:
    models.py      - ProposedExtraction, ProposedField, ExtractedField
    admin.py       - Django admin for reviewing extractions
    views.py       - API views for extraction operations
    urls.py        - URL routing for /api/v1/extractions/
    services.py    - Business logic (ExtractionService)
    selectors.py   - Query logic (ExtractionSelector)
    tasks.py       - Celery tasks (process_extraction_task)
    agents.py      - AI orchestration (ExtractionAgent)

RESPONSIBILITIES:
    - Running AI extraction on documents
    - Creating and managing proposals (ProposedExtraction)
    - Committing approved proposals to canonical storage
    - Rejecting proposals with feedback

TWO-PHASE COMMIT FLOW:
    1. Document uploaded → status: pending
    2. Extraction triggered → Celery task runs ExtractionAgent
    3. Agent creates ProposedExtraction with ProposedFields
    4. User reviews in admin or via API
    5. Commit → ExtractedFields created, Action logged
       OR Reject → Proposal marked rejected

DEPENDENCIES:
    - apps.common (base models)
    - apps.documents (Document model)
    - apps.actions (Action logging on commit)

API ENDPOINTS:
    GET    /api/v1/extractions/           - List extractions
    GET    /api/v1/extractions/{id}/      - Retrieve extraction
    POST   /api/v1/extractions/{id}/commit/ - Commit extraction
    POST   /api/v1/extractions/{id}/reject/ - Reject extraction

==============================================================================
"""

default_app_config = "apps.extraction.apps.ExtractionConfig"