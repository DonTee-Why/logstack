"""
Log ingestion API endpoints.

Main endpoint: POST /v1/logs:ingest
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.security import HTTPBearer

from ..config import get_settings
from ..core.auth import authenticate_token, check_rate_limit
from ..core.exceptions import ValidationError
from ..core.pipeline import ProcessingPipeline
from ..models.log_entry import ErrorResponse, IngestRequest, IngestResponse

logger = structlog.get_logger(__name__)
security = HTTPBearer()

router = APIRouter()


async def get_processing_pipeline(request: Request) -> ProcessingPipeline:
    """Dependency to get the processing pipeline from app state."""
    # Get settings from config
    settings = get_settings()
    
    # Get metrics from app state (if available)
    metrics = getattr(request.app.state, 'metrics', None)
    
    return ProcessingPipeline(
        settings=settings,
        metrics=metrics,
    )


@router.post(
    "/logs:ingest",
    response_model=IngestResponse,
    status_code=202,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Ingest log entries",
    description="""
    Ingest a batch of log entries for processing and forwarding to Loki.
    
    **Processing Pipeline:**
    1. Authentication & Rate Limiting
    2. Data Masking (sensitive fields)
    3. Schema Validation
    4. Normalization for Loki
    5. WAL Persistence
    6. Acknowledgment (202 response)
    7. Async forwarding to Loki
    
    **Request Requirements:**
    - Bearer token authentication required
    - Batch size: 1-500 entries, max 1MB
    - Entry size: max 32KB each
    - Required fields: timestamp, level, message, service, env
    
    **Rate Limits:**
    - Per-token rate limiting applied
    - 429 response if limits exceeded
    """,
)
async def ingest_logs(
    request: IngestRequest,
    pipeline: ProcessingPipeline = Depends(get_processing_pipeline),
    token: str = Depends(authenticate_token),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
) -> IngestResponse:
    """
    Ingest log entries.
    
    """
    request_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)
    
    logger.info(
        "Processing log ingestion request",
        request_id=request_id,
        token=token[:8] + "...",  # Log partial token for debugging
        entries_count=len(request.entries),
        idempotency_key=x_idempotency_key,
    )
    
    try:
        # Check rate limits
        await check_rate_limit(token)
        
        # Process through pipeline
        result = await pipeline.process_batch(
            token=token,
            entries=request.entries,
            idempotency_key=x_idempotency_key,
            request_id=request_id,
        )
        
        response = IngestResponse(
            message="Logs accepted for processing",
            entries_accepted=result.entries_processed,
            request_id=request_id,
            timestamp=start_time,
        )
        
        logger.info(
            "Log ingestion completed successfully",
            request_id=request_id,
            token=token[:8] + "...",
            entries_processed=result.entries_processed,
            processing_time_ms=(datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
        )
        
        return response
        
    except Exception as e:
        logger.error(
            "Log ingestion failed",
            request_id=request_id,
            token=token[:8] + "...",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise


@router.post(
    "/admin/flush",
    responses={
        200: {"description": "Segments flushed successfully"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
    summary="Manual WAL flush",
    description="""
    Manually flush WAL segments for immediate forwarding to Loki.
    
    **Admin Operation:**
    - Requires admin token authentication
    - Can target specific token or flush all
    - Useful for immediate debugging needs
    """,
)
async def flush_wal(
    token: Optional[str] = None,
    force: bool = False,
    pipeline: ProcessingPipeline = Depends(get_processing_pipeline),
    admin_token: str = Depends(authenticate_token),  # Will validate admin token
) -> Dict[str, Any]:
    """
    Manual WAL flush endpoint.
    
    """
    request_id = str(uuid.uuid4())
    
    logger.info(
        "Processing manual flush request",
        request_id=request_id,
        target_token=token,
        force=force,
        admin_token=admin_token[:8] + "...",
    )
    
    try:
        # Perform flush operation
        result = await pipeline.flush_wal(
            target_token=token,
            force=force,
            request_id=request_id,
        )
        
        logger.info(
            "Manual flush completed",
            request_id=request_id,
            segments_flushed=len(result.flushed_segments),
        )
        
        return {
            "message": "Segments flushed and queued for forwarding",
            "flushed_segments": result.flushed_segments,
            "request_id": request_id,
        }
        
    except Exception as e:
        logger.error(
            "Manual flush failed",
            request_id=request_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise
