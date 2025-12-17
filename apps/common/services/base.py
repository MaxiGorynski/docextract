"""
==============================================================================
FILE: base.py
LOCATION: /docextract/apps/common/services/base.py
==============================================================================

PURPOSE:
    Defines base classes and utilities for the service layer. Services are
    the primary entry point for business operations, orchestrating Selectors,
    Actions, and Agents.

CLASSES:
    - ServiceResult: Generic wrapper for service return values
    - ServiceContext: Context object passed to all service operations
    - BaseService: Base class with common utilities for services

USAGE:
    from apps.common.services.base import BaseService, ServiceResult, ServiceContext

    class MyService(BaseService):
        def my_operation(self, data: str) -> ServiceResult[MyModel]:
            self.log_operation('my_operation', data=data)
            # ... business logic ...
            return ServiceResult.ok(result)

DESIGN PRINCIPLES:
    - Stateless: All state comes from parameters or database
    - Transaction-aware: Use @transaction.atomic where needed
    - Composable: Services may call other Services
    - Testable: Dependencies injectable, no side effects in constructors

PERFORMANCE NOTES:
    - ServiceContext is lightweight and cheap to create
    - Logging uses structured format for aggregation
    - Consider caching ServiceContext per request in middleware

TESTING:
    - Create ServiceContext fixtures for test setup
    - Mock feature_flags dict for feature toggle testing
    - Use ServiceResult.success/error assertions

==============================================================================
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class ServiceResult(Generic[T]):
    """
    Standard wrapper for service return values.

    Provides a consistent interface for success/failure responses,
    avoiding exceptions for expected error conditions.

    Attributes:
        success: Whether the operation succeeded
        data: The result data (only present on success)
        error: Human-readable error message (only present on failure)
        error_code: Machine-readable error code for client handling

    Usage:
        # Success case
        return ServiceResult.ok(document)

        # Failure case
        return ServiceResult.fail("Document not found", error_code="not_found")

        # Checking result
        result = service.create_document(...)
        if result.success:
            document = result.data
        else:
            handle_error(result.error_code, result.error)
    """

    success: bool
    data: T | None = None
    error: str | None = None
    error_code: str | None = None

    @classmethod
    def ok(cls, data: T) -> ServiceResult[T]:
        """
        Create a successful result.

        Args:
            data: The result data to return

        Returns:
            ServiceResult with success=True and data populated
        """
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str, error_code: str = "error") -> ServiceResult[T]:
        """
        Create a failure result.

        Args:
            error: Human-readable error message
            error_code: Machine-readable error code for client handling

        Returns:
            ServiceResult with success=False and error details
        """
        return cls(success=False, error=error, error_code=error_code)


@dataclass
class ServiceContext:
    """
    Context passed to all service operations.

    Carries request-scoped information needed by services, including
    identity, tracing, and feature flags. Created once per request
    and passed through the service layer.

    Attributes:
        tenant_id: UUID of the current tenant for data isolation
        actor_id: Identifier of the actor (user ID or system name)
        actor_type: Category of actor ('user', 'system', 'celery_task')
        trace_id: Request correlation ID for distributed tracing
        feature_flags: Dict of feature flag states for this request

    Usage:
        context = ServiceContext(
            tenant_id=request.tenant.id,
            actor_id=str(request.user.id),
            actor_type='user',
            trace_id=request.trace_id,
            feature_flags=request.feature_flags,
        )
        service = DocumentService(context)
    """

    tenant_id: UUID
    actor_id: str
    actor_type: str  # 'user', 'system', 'celery_task'
    trace_id: str
    feature_flags: dict[str, bool]

    def __post_init__(self) -> None:
        """Validate context after initialisation."""
        if self.actor_type not in ("user", "system", "celery_task"):
            raise ValueError(
                f"Invalid actor_type: {self.actor_type}. "
                "Must be 'user', 'system', or 'celery_task'."
            )


class BaseService:
    """
    Base class for services with common utilities.

    Provides:
    - Structured logging with context injection
    - Access to ServiceContext for identity/tracing
    - Common patterns for service implementation

    Subclasses should:
    - Call super().__init__(context) in their constructor
    - Use self.log_operation() for audit logging
    - Return ServiceResult from public methods

    Usage:
        class DocumentService(BaseService):
            def __init__(self, context: ServiceContext):
                super().__init__(context)
                self.selector = DocumentSelector(context.tenant_id)

            def create_document(self, file, filename: str) -> ServiceResult[Document]:
                self.log_operation('create_document', filename=filename)
                # ... implementation ...
    """

    def __init__(self, context: ServiceContext) -> None:
        """
        Initialise the service with context.

        Args:
            context: ServiceContext with tenant, actor, and trace info
        """
        self.context = context
        self.logger = logging.getLogger(self.__class__.__name__)

    def log_operation(self, operation: str, **kwargs) -> None:
        """
        Log an operation with structured context.

        Automatically includes tenant_id, actor_id, and trace_id
        from the service context for correlation and filtering.

        Args:
            operation: Name of the operation being performed
            **kwargs: Additional key-value pairs to include in log
        """
        self.logger.info(
            operation,
            extra={
                "trace_id": self.context.trace_id,
                "actor_id": self.context.actor_id,
                "actor_type": self.context.actor_type,
                "tenant_id": str(self.context.tenant_id),
                **kwargs,
            },
        )

    def log_error(self, operation: str, error: str, **kwargs) -> None:
        """
        Log an error with structured context.

        Args:
            operation: Name of the operation that failed
            error: Error message or description
            **kwargs: Additional key-value pairs to include in log
        """
        self.logger.error(
            f"{operation}: {error}",
            extra={
                "trace_id": self.context.trace_id,
                "actor_id": self.context.actor_id,
                "actor_type": self.context.actor_type,
                "tenant_id": str(self.context.tenant_id),
                **kwargs,
            },
        )

    def is_feature_enabled(self, feature_key: str) -> bool:
        """
        Check if a feature flag is enabled.

        Args:
            feature_key: The feature flag key to check

        Returns:
            True if the feature is enabled, False otherwise
        """
        return self.context.feature_flags.get(feature_key, False)