"""
Log entry data models and validation.

- Required fields: timestamp, level, message, service, env
- Labels: allowlisted keys, ≤6 keys, value length ≤64 chars
- Entry size ≤ 32KB; batch size ≤ 500 entries or 1MB
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LogLevel(str, Enum):
    """Allowed log levels."""
    
    DEBUG = "DEBUG"
    INFO = "INFO" 
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class LogEntry(BaseModel):
    """
    Individual log entry model.
    
    Strict validation of log format and fields.
    """
    
    timestamp: datetime = Field(
        description="RFC3339 timestamp when the log event occurred"
    )
    level: LogLevel = Field(
        description="Log level (DEBUG, INFO, WARN, ERROR, FATAL)"
    )
    message: str = Field(
        min_length=1,
        max_length=8192,  # Reasonable message limit
        description="Log message content"
    )
    service: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        description="Service name (lowercase, alphanumeric and hyphens only)"
    )
    env: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9-]+$",
        description="Environment (e.g., dev, staging, prod)"
    )
    
    # Optional fields
    labels: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional labels (max 6 keys, values ≤64 chars)"
    )
    trace_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Distributed tracing trace ID"
    )
    span_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Distributed tracing span ID"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional structured metadata"
    )
    
    @field_validator("labels")
    def validate_labels(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Validate labels according to PRD requirements."""
        if v is None:
            return v
        
        # Allowed label keys from PRD
        allowed_keys = {"service", "env", "level", "schema_version", "region", "tenant"}
        
        # Check number of labels
        if len(v) > 6:
            raise ValueError("Labels cannot have more than 6 keys")
        
        # Check each label
        for key, value in v.items():
            if key not in allowed_keys:
                raise ValueError(f"Label key '{key}' not in allowed list: {allowed_keys}")
            
            if not isinstance(value, str):
                raise ValueError(f"Label value for '{key}' must be a string")
            
            if len(value) > 64:
                raise ValueError(f"Label value for '{key}' exceeds 64 character limit")
        
        return v
    
    @field_validator("metadata")
    def validate_metadata(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Basic metadata validation."""
        if v is None:
            return v
        
        # Prevent excessively deep nesting
        def check_depth(obj: Any, max_depth: int = 5, current_depth: int = 0) -> None:
            if current_depth > max_depth:
                raise ValueError("Metadata nesting too deep (max 5 levels)")
            
            if isinstance(obj, dict):
                for value in obj.values():
                    check_depth(value, max_depth, current_depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    check_depth(item, max_depth, current_depth + 1)
        
        check_depth(v)
        return v
    
    model_config = ConfigDict(
        # Validate assignment to catch changes after creation
        validate_assignment=True,
        # Use enum values in serialization
        use_enum_values=True,
    )


class LogBatch(BaseModel):
    """
    Batch of log entries for ingestion.
    
    Batch size ≤ 500 entries or 1MB
    """
    
    entries: List[LogEntry] = Field(
        min_length=1,
        max_length=500,
        description="List of log entries (1-500 entries)"
    )
    
    @field_validator("entries")
    def validate_batch_size(cls, v: List[LogEntry]) -> List[LogEntry]:
        """Validate batch doesn't exceed size limits."""
        if not v:
            raise ValueError("Batch must contain at least one entry")
        
        # Rough size estimation (will be validated more precisely in the handler)
        estimated_size = sum(len(entry.model_dump_json()) for entry in v)
        if estimated_size > 1_048_576:  # 1MB
            raise ValueError("Batch size exceeds 1MB limit")
        
        return v


class IngestRequest(BaseModel):
    """
    Complete ingestion request model.
    
    Wraps the log batch with any additional request-level metadata.
    """
    
    entries: List[LogEntry] = Field(
        description="Log entries to ingest"
    )
    
    # Optional request metadata
    idempotency_key: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional idempotency key for deduplication"
    )
    
    @field_validator("entries")
    def validate_entries(cls, v: List[LogEntry]) -> List[LogEntry]:
        """Validate entries using LogBatch validation."""
        # Reuse LogBatch validation logic
        LogBatch(entries=v)
        return v


class IngestResponse(BaseModel):
    """
    Response from log ingestion endpoint.
    
    202 Accepted response with acknowledgment.
    """
    
    message: str = Field(description="Response message")
    entries_accepted: int = Field(description="Number of entries accepted")
    request_id: str = Field(description="Unique request identifier")
    timestamp: datetime = Field(description="Processing timestamp")


class ErrorResponse(BaseModel):
    """
    Standard error response model.
    """
    
    error: str = Field(description="Error code")
    message: str = Field(description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional error details"
    )
