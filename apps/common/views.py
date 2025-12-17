"""
==============================================================================
FILE: views.py
LOCATION: /docextract/apps/common/views.py
==============================================================================

PURPOSE:
    Common views shared across the application. Currently provides the
    health check endpoint for monitoring and load balancer probes.

VIEWS:
    - health_check: Simple endpoint returning service status

USAGE:
    Included in config/urls.py:
        path("health/", health_check, name="health_check")

HEALTH CHECK:
    Returns JSON with service status and optional dependency checks.
    Used by:
    - Docker health checks
    - Kubernetes liveness/readiness probes
    - Load balancer health checks
    - Monitoring systems (Datadog, etc.)

==============================================================================
"""

from django.http import JsonResponse
from django.db import connection


def health_check(request):
    """
    Health check endpoint for monitoring.

    Returns:
        200 OK with JSON body if service is healthy
        503 Service Unavailable if critical dependencies fail

    Response format:
        {
            "status": "healthy",
            "checks": {
                "database": "ok",
                "redis": "ok"
            }
        }
    """
    checks = {}
    healthy = True

    # Check database connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        healthy = False

    # Check Redis connection
    try:
        from django.core.cache import cache
        cache.set("health_check", "ok", timeout=1)
        if cache.get("health_check") == "ok":
            checks["redis"] = "ok"
        else:
            checks["redis"] = "error: cache read failed"
            healthy = False
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
        healthy = False

    response_data = {
        "status": "healthy" if healthy else "unhealthy",
        "checks": checks,
    }

    status_code = 200 if healthy else 503
    return JsonResponse(response_data, status=status_code)