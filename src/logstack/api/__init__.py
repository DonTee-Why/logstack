"""
API endpoints package.

Contains FastAPI routers for all service endpoints:
- /v1/logs:ingest - Main log ingestion endpoint
- /metrics - Prometheus metrics
- /healthz, /readyz - Health checks
- /v1/admin/flush - Manual WAL flush
"""
