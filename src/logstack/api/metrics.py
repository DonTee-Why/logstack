"""
Prometheus metrics endpoint.

Exposes metrics in Prometheus text format for scraping.
"""

import structlog
from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get(
    "/metrics",
    summary="Prometheus metrics",
    description="""
    Prometheus metrics endpoint in standard text format.
    
    **Key Metrics:**
    - logs_ingested_total{token} - Total logs processed
    - logs_rejected_total{token,reason} - Total rejections
    - wal_segments_active{token} - Current WAL segments
    - request_duration_seconds - Request latency histogram
    - wal_disk_usage_bytes{token} - WAL disk usage
    - masking_operations_total{token,field} - Masking operations
    
    This endpoint is scraped by Prometheus every 15-30 seconds.
    """,
)
async def get_metrics(request: Request) -> Response:
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus text format for scraping.
    """
    try:
        # Get metrics collector from app state
        metrics_collector = getattr(request.app.state, 'metrics', None)
        
        if not metrics_collector:
            logger.warning("Metrics collector not initialized")
            # Return empty metrics response
            return Response(
                content="# Metrics collector not initialized\n",
                media_type=CONTENT_TYPE_LATEST,
            )
        
        # Generate Prometheus format metrics
        # This will include all registered metrics from prometheus_client
        metrics_data = generate_latest()
        
        logger.debug("Metrics scraped successfully", size_bytes=len(metrics_data))
        
        return Response(
            content=metrics_data,
            media_type=CONTENT_TYPE_LATEST,
        )
        
    except Exception as e:
        logger.error(
            "Failed to generate metrics",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        
        # Return error in Prometheus format
        error_metrics = f"""# HELP logstack_metrics_error Metrics generation errors
# TYPE logstack_metrics_error counter
logstack_metrics_error{{error="{type(e).__name__}"}} 1
"""
        return Response(
            content=error_metrics,
            media_type=CONTENT_TYPE_LATEST,
        )
