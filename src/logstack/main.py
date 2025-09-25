"""
Main FastAPI application entry point.

This module sets up the FastAPI app with all middleware, routes, and lifecycle events.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.logstack.api import admin_router, healthz_router, logs_router, metrics_router
from src.logstack.config import get_settings, Settings
from src.logstack.core.exceptions import LogStackException
from src.logstack.core.forwarder_service import get_forwarder_service
from src.logstack.core.health import get_health_checker
from src.logstack.core.metrics import MetricsCollector


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
        
        # Start forwarder service
        forwarder_service = get_forwarder_service()
        app.state.forwarder_service = forwarder_service
        await forwarder_service.start()
        
        # Start health checker
        health_checker = get_health_checker(forwarder_service)
        app.state.health_checker = health_checker
        await health_checker.start()
        
        try:
            logger.info("LogStack service started successfully")
            yield
        finally:
            logger.info("Shutting down LogStack service")
            
            # Graceful shutdown
            forwarder = getattr(app.state, 'forwarder_service', None)
            if forwarder is not None:
                await forwarder.stop()
            
            # health_checker = getattr(app.state, 'health_checker', None)
            if health_checker is not None:
                await health_checker.stop()
            
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
app.include_router(logs_router, prefix="/v1", tags=["logs"])
app.include_router(admin_router, tags=["admin"])
app.include_router(metrics_router, tags=["metrics"])
app.include_router(healthz_router, tags=["health"])


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
        "src.logstack.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
    )
