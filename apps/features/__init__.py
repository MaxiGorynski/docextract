"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/features/__init__.py
==============================================================================

PURPOSE:
    Package initialisation for the features app. Provides feature flag
    functionality for gradual rollouts, A/B testing, and kill switches.

APP CONTENTS:
    models.py      - FeatureFlag model (future: database-backed flags)
    admin.py       - Django admin for managing flags
    middleware.py  - FeatureFlagMiddleware (attaches flags to requests)

RESPONSIBILITIES:
    - Evaluating feature flags per-request
    - Supporting flag overrides per tenant/user (future)
    - Providing kill switches for features
    - Tracking flag exposure for analytics (future)

CURRENT IMPLEMENTATION (MVP):
    Flags are defined in Django settings:
        FEATURE_FLAGS = {"ai_extraction_enabled": True}

    And accessed via request:
        if request.feature_flags.get('ai_extraction_enabled'):
            ...

FUTURE ENHANCEMENTS:
    - Database-backed FeatureFlag model
    - Percentage-based rollouts
    - User/tenant targeting
    - Flag evaluation logging
    - Admin UI for flag management

DEPENDENCIES:
    - No dependencies on other project apps

USAGE IN CODE:
    # In views
    if request.feature_flags.get('new_feature'):
        return new_behavior()
    return old_behavior()

    # In services (pass flags explicitly)
    def my_service(feature_flags: dict):
        if feature_flags.get('new_feature'):
            ...

==============================================================================
"""

default_app_config = "apps.features.apps.FeaturesConfig"