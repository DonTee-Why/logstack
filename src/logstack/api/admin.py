"""
Admin API endpoints for LogStack.

Provides administrative functions like manual flush operations.
"""

import secrets
import string
from typing import Dict, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.logstack.config import get_settings, reload_settings
from src.logstack.core.auth import authenticate_admin_token
from src.logstack.models import TokenGenerationRequest, TokenGenerationResponse

logger = structlog.get_logger(__name__)

router = APIRouter()


def _generate_secure_token(service_name: str) -> str:
    """Generate a secure token with logstack prefix and service identifier."""
    # Use a mix of service name and random data
    service_part = service_name.lower().replace('-', '').replace('_', '')[:10]
    
    # Generate random suffix (20 characters)
    alphabet = string.ascii_lowercase + string.digits
    random_suffix = ''.join(secrets.choice(alphabet) for _ in range(20))
    
    return f"logstack_{service_part}_{random_suffix}"


@router.post(
    "/v1/admin/tokens/generate",
    response_model=TokenGenerationResponse,
    responses={
        400: {"description": "Invalid request or service name already exists"},
        401: {"description": "Unauthorized - admin token required"},
        500: {"description": "Internal server error"},
    },
    summary="Generate API token for service",
    description="""
    Generate a new API token for a service.
    
    **Admin Operation:**
    - Requires admin token authentication
    - Generates secure token with logstack prefix
    - Automatically adds to configuration (runtime only)
    - Token format: logstack_{service}_{random20chars}
    
    **Note:** Generated tokens are added to runtime configuration only.
    For persistence, update your config.yaml or environment variables.
    """,
)
async def generate_service_token(
    request_data: TokenGenerationRequest,
    admin_token: str = Depends(authenticate_admin_token)
) -> TokenGenerationResponse:
    """
    Generate a new API token for a service.
    
    This endpoint creates a new secure token and adds it to the runtime
    configuration. The token will be valid immediately but won't persist
    across service restarts unless added to config.yaml or environment variables.
    """
    
    logger.info(
        "Token generation requested",
        service_name=request_data.service_name,
        description=request_data.description,
        active=request_data.active,
        admin_token=admin_token[:8] + "..."
    )
    
    try:
        # Check if service name already exists
        settings = get_settings()
        existing_tokens = settings.security.api_keys
        
        for existing_token, metadata in existing_tokens.items():
            if metadata.get('name', '').lower() == request_data.service_name.lower():
                logger.warning(
                    "Token generation failed: service name already exists",
                    service_name=request_data.service_name,
                    existing_token=existing_token[:8] + "..."
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Service name '{request_data.service_name}' already exists"
                )
        
        # Generate new secure token
        new_token = _generate_secure_token(request_data.service_name)
        
        # Ensure token is unique
        while new_token in existing_tokens:
            new_token = _generate_secure_token(request_data.service_name)
        
        # Add to runtime configuration
        # Note: This modifies the in-memory settings, not persistent config
        new_token_metadata = {
            'name': request_data.service_name,
            'description': request_data.description,
            'active': request_data.active,
            'generated_via_api': True  # Mark as API-generated
        }
        
        # Update the settings object (runtime only)
        settings.security.api_keys[new_token] = new_token_metadata
        
        logger.info(
            "Token generated successfully",
            service_name=request_data.service_name,
            token=new_token[:12] + "...",
            active=request_data.active
        )
        
        return TokenGenerationResponse(
            token=new_token,
            service_name=request_data.service_name,
            description=request_data.description,
            active=request_data.active,
            message=f"Token generated successfully for service '{request_data.service_name}'. "
                "Note: Token is active immediately but won't persist across restarts "
                "unless added to config.yaml or environment variables."
        )
        
    except HTTPException as e:
        # Re-raise HTTP exceptions (like duplicate service name)
        logger.error(
            "Token generation failed",
            service_name=request_data.service_name,
            error=str(e),
            error_type=type(e).__name__
        )
        raise
    except Exception as e:
        logger.error(
            "Token generation failed",
            service_name=request_data.service_name,
            error=str(e),
            error_type=type(e).__name__
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token generation failed: {str(e)}"
        )


@router.post("/v1/admin/flush")
async def flush_wal_segments(
    request: Request,
    admin_token: str = Depends(authenticate_admin_token)
) -> Dict[str, Any]:
    """
    Manually flush WAL segments to Loki.
    
    This endpoint forces an immediate forward operation of all ready segments.
    Useful for testing or manual intervention.
    """
    logger.info("Manual flush requested", admin_token=admin_token[:8] + "...")
    
    # Get forwarder service
    forwarder_service = getattr(request.app.state, 'forwarder_service', None)
    if not forwarder_service:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forwarder service not available"
        )
    
    # Check if forwarder is healthy
    if not forwarder_service.is_healthy():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forwarder service is not healthy"
        )
    
    try:
        # Force forward operation
        result = await forwarder_service.force_forward()
        
        if result["success"]:
            logger.info(
                "Manual flush completed successfully",
                entries_forwarded=result["entries_forwarded"],
                segments_processed=result["segments_processed"]
            )
            
            return {
                "message": "Flush completed successfully",
                "entries_forwarded": result["entries_forwarded"],
                "segments_processed": result["segments_processed"]
            }
        else:
            logger.warning(
                "Manual flush failed",
                error=result.get("error", "Unknown error")
            )
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Flush failed: {result.get('error', 'Unknown error')}"
            )
            
    except Exception as e:
        logger.error("Manual flush error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Flush error: {str(e)}"
        )


@router.get("/v1/admin/status")
async def get_admin_status(
    request: Request,
    admin_token: str = Depends(authenticate_admin_token)
) -> Dict[str, Any]:
    """
    Get admin status information.
    
    Returns health status of various components.
    """
    logger.debug("Admin status requested", admin_token=admin_token[:8] + "...")
    
    # Get forwarder service
    forwarder_service = getattr(request.app.state, 'forwarder_service', None)
    
    status_info = {
        "forwarder_service": {
            "available": forwarder_service is not None,
            "healthy": forwarder_service.is_healthy() if forwarder_service else False
        },
        "metrics": {
            "available": hasattr(request.app.state, 'metrics')
        }
    }
    
    return status_info
