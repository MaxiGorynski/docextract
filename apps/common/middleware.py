"""
==============================================================================
FILE: middleware.py
LOCATION: /docextract/apps/common/middleware.py
==============================================================================

PURPOSE:
    Common middleware components shared across the application. Middleware
    processes requests/responses globally before they reach views.

CONTAINS:
    TraceIDMiddleware - Injects unique trace_id for request correlation

MIDDLEWARE ORDER (in settings.py):
    Middleware executes top-to-bottom on request, bottom-to-top on response.
    TraceIDMiddleware should be early in the stack so trace_id is available
    to all subsequent middleware and views.

USAGE:
    Add to MIDDLEWARE in settings:
        "apps.common.middleware.TraceIDMiddleware"

    Access in views:
        request.trace_id  # e.g., "a1b2c3d4"

DISTRIBUTED TRACING:
    If a request includes X-Trace-ID header (from upstream service),
    that ID is preserved. Otherwise, a new ID is generated.

PERFORMANCE NOTES:
    - UUID generation is fast (~1μs)
    - Minimal overhead per request
    - No database or network calls

TESTING:
    from django.test import RequestFactory

    factory = RequestFactory()
    request = factory.get('/')
    middleware = TraceIDMiddleware(lambda r: HttpResponse())
    middleware(request)
    assert hasattr(request, 'trace_id')

LOGGING INTEGRATION:
    Use trace_id in log messages for request correlation:
        logger.info("Processing", extra={"trace_id": request.trace_id})

==============================================================================
"""

import uuid
import logging

logger = logging.getLogger(__name__)


class TraceIDMiddleware:
    """
    Injects a unique trace_id into each request for distributed tracing.

    The trace_id is available as request.trace_id and is included
    in all log entries for request correlation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check for existing trace ID in headers (for distributed tracing)
        trace_id = request.headers.get("X-Trace-ID")

        if not trace_id:
            trace_id = str(uuid.uuid4())[:8]  # Short ID for readability

        request.trace_id = trace_id

        response = self.get_response(request)

        # Include trace ID in response headers
        response["X-Trace-ID"] = trace_id

        return response