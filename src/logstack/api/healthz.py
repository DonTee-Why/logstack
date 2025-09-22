"""
Health check endpoints.

- /healthz: Liveness probe (always 200 if service alive)
- /readyz: Readiness probe (200 only if Loki reachable, disk OK, WAL integrity OK)
"""

from datetime import datetime
from typing import Dict, Any

import structlog
from fastapi import APIRouter, Request, Response, status

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/healthz",
    status_code=200,
    summary="Liveness probe",
    description="""
    Liveness probe endpoint.
    
    Always returns 200 OK if the service is running.
    Used by Kubernetes/Docker health checks to determine if container should be restarted.
    """,
)
async def liveness_check() -> Dict[str, Any]:
    """
    Liveness probe - always returns 200 if service is alive.
    """
    return {
        "status": "alive",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "logstack",
        "version": "0.1.0",
    }


@router.get(
    "/readyz",
    summary="Readiness probe", 
    description="""
    Readiness probe endpoint.
    
    Returns 200 only if all dependencies are healthy:
    - Loki reachable in last 60 seconds
    - Disk free space > 20%
    - WAL integrity OK
    
    Returns 503 Service Unavailable if any dependency is unhealthy.
    Used by load balancers to determine if instance can receive traffic.
    """,
)
async def readiness_check(request: Request, response: Response) -> Dict[str, Any]:
    """
    Readiness probe - returns 200 only if all dependencies are healthy.
    
    Returns 200 only if Loki reachable in last 60s, disk free >20%, WAL integrity OK.
    """
    try:
        # Get health checker from app state (will be implemented)
        health_checker = getattr(request.app.state, 'health_checker', None)
        
        if not health_checker:
            logger.warning("Health checker not initialized")
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "not_ready",
                "reason": "health_checker_not_initialized",
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        # Perform health checks
        health_status = await health_checker.check_all()
        
        if health_status.is_healthy:
            response.status_code = status.HTTP_200_OK
            return {
                "status": "ready",
                "timestamp": datetime.utcnow().isoformat(),
                "checks": health_status.checks,
            }
        else:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "not_ready",
                "timestamp": datetime.utcnow().isoformat(),
                "checks": health_status.checks,
                "failed_checks": health_status.failed_checks,
            }
            
    except Exception as e:
        logger.error(
            "Readiness check failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "reason": "health_check_error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
