"""
Main FastAPI application entry point.

This module sets up the FastAPI app with all middleware, routes, and lifecycle events.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import healthz, logs, metrics
from .config import get_settings
from .core.exceptions import LogStackException
from .core.forwarder import AsyncForwarder
from .core.metrics import MetricsCollector


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        # structlog.processors.StackInfoRenderer(),
        # structlog.processors.format_exc_info,
        # structlog.processors.UnicodeDecoder(),
        # structlog.processors.JSONRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    FastAPI lifespan context manager.
    
    Handles startup and shutdown of background services like the async forwarder.
    """
    settings = get_settings()
    logger.info("Starting LogStack service", version=app.version)
    
    # Initialize core components
    metrics_collector = MetricsCollector()
    app.state.metrics = metrics_collector
    
    # Start async forwarder
    forwarder = AsyncForwarder(settings=settings, metrics=metrics_collector)
    app.state.forwarder = forwarder
    
    # Start background tasks
    forwarder_task = asyncio.create_task(forwarder.start())
    
    try:
        logger.info("LogStack service started successfully")
        yield
    finally:
        logger.info("Shutting down LogStack service")
        
        # Graceful shutdown
        await forwarder.stop()
        forwarder_task.cancel()
        
        try:
            await forwarder_task
        except asyncio.CancelledError:
            logger.info("Forwarder task cancelled during shutdown")
        
        logger.info("LogStack service shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="LogStack",
    description="Log Ingestor → Grafana Loki ",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(LogStackException)
async def logstack_exception_handler(request: Request, exc: LogStackException) -> JSONResponse:
    """Handle custom LogStack exceptions."""
    logger.error(
        "LogStack exception occurred",
        error=str(exc),
        status_code=exc.status_code,
        path=request.url.path,
        method=request.method,
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": str(exc),
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.error(
        "Unexpected exception occurred",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
        method=request.method,
        exc_info=True,
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
        },
    )


# Include routers
app.include_router(logs.router, prefix="/v1", tags=["logs"])
app.include_router(metrics.router, tags=["metrics"])
app.include_router(healthz.router, tags=["health"])


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Root endpoint with service information."""
    return {
        "service": "LogStack",
        "version": app.version,
        "description": "Log Ingestor → Grafana Loki ",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "logstack.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
    )
