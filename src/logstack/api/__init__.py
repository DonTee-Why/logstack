"""
API endpoints package.

Contains FastAPI routers for all service endpoints:
- /v1/logs:ingest - Main log ingestion endpoint
- /metrics - Prometheus metrics
- /healthz, /readyz - Health checks
- /v1/admin/flush - Manual WAL flush
"""
from .admin import router as admin_router
from .healthz import router as healthz_router
from .logs import router as logs_router
from .metrics import router as metrics_router

__all__ = ["admin_router", "healthz_router", "logs_router", "metrics_router"]
