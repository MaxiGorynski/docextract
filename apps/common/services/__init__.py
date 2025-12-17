"""
==============================================================================
FILE: __init__.py
LOCATION: /docextract/apps/common/services/__init__.py
==============================================================================

PURPOSE:
    Package marker for common services module. Exports base classes for
    service layer implementation.

EXPORTS:
    - ServiceResult: Generic wrapper for service return values
    - ServiceContext: Context object passed to all service operations
    - BaseService: Base class with common utilities for services

USAGE:
    from apps.common.services import ServiceResult, ServiceContext, BaseService

==============================================================================
"""

from apps.common.services.base import BaseService, ServiceContext, ServiceResult

__all__ = [
    "BaseService",
    "ServiceContext",
    "ServiceResult",
]