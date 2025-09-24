"""
Admin API endpoints for LogStack.

Provides administrative functions like manual flush operations.
"""

from typing import Dict, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..core.forwarder_service import get_forwarder_service
from ..core.auth import authenticate_token

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/v1/admin/flush")
async def flush_wal_segments(
    request: Request,
    token: str = Depends(authenticate_token)
) -> Dict[str, Any]:
    """
    Manually flush WAL segments to Loki.
    
    This endpoint forces an immediate forward operation of all ready segments.
    Useful for testing or manual intervention.
    """
    logger.info("Manual flush requested", token=token[:8] + "...")
    
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
    token: str = Depends(authenticate_token)
) -> Dict[str, Any]:
    """
    Get admin status information.
    
    Returns health status of various components.
    """
    logger.debug("Admin status requested", token=token[:8] + "...")
    
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
