"""
==============================================================================
FILE: middleware.py
LOCATION: /docextract/apps/features/middleware.py
==============================================================================

PURPOSE:
    Middleware that evaluates feature flags for each request and injects
    them into the request object for use by views and services.

MIDDLEWARE:
    - FeatureFlagMiddleware: Evaluates flags and adds request.feature_flags

USAGE:
    Add to MIDDLEWARE in settings:
        "apps.features.middleware.FeatureFlagMiddleware"

    Access in views:
        if request.feature_flags.get("ai_extraction_enabled"):
            # Feature is enabled

DESIGN DECISIONS:
    - Flags evaluated once per request for consistency
    - Settings-based flags for MVP (no database lookup)
    - Tenant-aware evaluation when tenant middleware is present

==============================================================================
"""

from django.conf import settings


class FeatureFlagMiddleware:
    """
    Middleware that injects feature flags into the request object.

    Evaluates feature flags based on:
    1. Settings-based flags (MVP implementation)
    2. Tenant overrides (if tenant is available on request)

    Adds request.feature_flags dict accessible by views and services.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Evaluate feature flags for this request
        request.feature_flags = self._evaluate_flags(request)

        response = self.get_response(request)
        return response

    def _evaluate_flags(self, request) -> dict:
        """
        Evaluate all feature flags for the current request.

        MVP implementation uses settings-based flags.
        Production would query FeatureFlag model with tenant overrides.
        """
        # Get base flags from settings
        flags = getattr(settings, "FEATURE_FLAGS", {}).copy()

        # Default flags if not configured
        if not flags:
            flags = {
                "ai_extraction_enabled": True,
            }

        # Tenant-specific overrides (if tenant middleware has run)
        tenant = getattr(request, "tenant", None)
        if tenant:
            # Could query FeatureFlag model for tenant-specific overrides
            # For MVP, just use settings
            pass

        return flags