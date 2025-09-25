"""
Admin API data models.

Contains Pydantic models for admin operations like token generation.
"""

from pydantic import BaseModel, Field


class TokenGenerationRequest(BaseModel):
    """Request model for token generation."""
    
    service_name: str = Field(
        ..., 
        description="Name of the service (alphanumeric, hyphens, underscores only)",
        pattern=r"^[a-zA-Z0-9_-]+$",
        min_length=3,
        max_length=50
    )
    description: str = Field(
        ..., 
        description="Human-readable description of the service",
        min_length=5,
        max_length=200
    )
    active: bool = Field(
        default=True, 
        description="Whether the token should be active upon creation"
    )


class TokenGenerationResponse(BaseModel):
    """Response model for token generation."""
    
    token: str = Field(..., description="Generated Bearer token")
    service_name: str = Field(..., description="Service name")
    description: str = Field(..., description="Service description")
    active: bool = Field(..., description="Token active status")
    message: str = Field(..., description="Success message")
