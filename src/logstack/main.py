"""
Main FastAPI application entry point.

This module sets up the FastAPI app with all middleware, routes, and lifecycle events.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import healthz, logs, metrics
from .config import get_settings, Settings
from .core.exceptions import LogStackException
from .core.forwarder import AsyncForwarder
from .core.metrics import MetricsCollector


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    # Configure stdlib logging but silence watchfiles spam
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
    )
    
    # Silence the verbose watchfiles logger
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    
    # Configure structlog
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


def create_lifespan_handler(settings: Settings) -> Any:
    """Create a lifespan handler with access to settings."""
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """
        FastAPI lifespan context manager.
        
        Handles startup and shutdown of background services like the async forwarder.
        """
        logger = structlog.get_logger(__name__)
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
    
    return lifespan


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    This factory function ensures all configuration is applied
    whether running via FastAPI CLI or direct execution.
    """
    # Get settings first
    settings = get_settings()
    
    # Configure logging with settings
    configure_logging(settings.log_level)
    
    # Create lifespan handler with settings
    lifespan = create_lifespan_handler(settings)
    
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
    
    return app


# Create the app instance
app = create_app()

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
    logger = structlog.get_logger(__name__)
    logger.error(
        "LogStack exception occurred",
        error=str(exc),
        status_code=exc.status_code,
        path=request.url.path,
        method=request.method,
    )
    
    # Prepare response headers
    headers = {}
    
    # Add Retry-After header for rate limit errors
    if exc.status_code == 429 and "retry_after" in exc.details:
        headers["Retry-After"] = str(exc.details["retry_after"])
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": str(exc),
            "details": exc.details,
        },
        headers=headers,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger = structlog.get_logger(__name__)
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
async def root() -> Dict[str, str]:
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
