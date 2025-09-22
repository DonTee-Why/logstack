"""
Custom exceptions for LogStack service.

Provides structured error handling with appropriate HTTP status codes
and error details for API responses.
"""

from typing import Any, Dict, Optional


class LogStackException(Exception):
    """Base exception for LogStack service."""
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "internal_error",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


class ValidationError(LogStackException):
    """Raised when request validation fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_code="validation_error",
            details=details,
        )


class AuthenticationError(LogStackException):
    """Raised when authentication fails."""
    
    def __init__(self, message: str = "Invalid or missing authentication token") -> None:
        super().__init__(
            message=message,
            status_code=401,
            error_code="authentication_error",
        )


class RateLimitError(LogStackException):
    """Raised when rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
    ) -> None:
        details = {}
        if retry_after:
            details["retry_after"] = retry_after
            
        super().__init__(
            message=message,
            status_code=429,
            error_code="rate_limit_exceeded",
            details=details,
        )


class QuotaExceededError(LogStackException):
    """Raised when WAL quota is exceeded."""
    
    def __init__(
        self,
        message: str = "WAL quota exceeded",
        quota_type: str = "unknown",
    ) -> None:
        super().__init__(
            message=message,
            status_code=429,
            error_code="quota_exceeded",
            details={"quota_type": quota_type},
        )


class WALError(LogStackException):
    """Raised when WAL operations fail."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            status_code=500,
            error_code="wal_error",
            details=details,
        )


class ForwarderError(LogStackException):
    """Raised when forwarding to Loki fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            status_code=500,
            error_code="forwarder_error",
            details=details,
        )


class MaskingError(LogStackException):
    """Raised when data masking fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(
            message=message,
            status_code=500,
            error_code="masking_error",
            details=details,
        )
