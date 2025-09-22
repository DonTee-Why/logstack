"""
Prometheus metrics collection.

Stateless services with in-memory metrics.
Implements all key metrics from observability requirements.
"""

import time
from typing import Optional

import structlog
from prometheus_client import Counter, Gauge, Histogram, Info

logger = structlog.get_logger(__name__)


class MetricsCollector:
    """
    Centralized metrics collection for LogStack.
    
    Keep metrics simple,
    use in-memory counters, let Prometheus handle storage.
    """
    
    def __init__(self) -> None:
        # Service info
        self.service_info = Info(
            "logstack_service", 
            "LogStack service information"
        )
        self.service_info.info({
            "version": "0.1.0",
            "service": "logstack",
        })
        
        # Request metrics
        self.requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"]
        )
        
        self.request_duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        # Log ingestion metrics
        self.logs_ingested_total = Counter(
            "logs_ingested_total",
            "Total number of log entries successfully ingested",
            ["token"]
        )
        
        self.logs_rejected_total = Counter(
            "logs_rejected_total", 
            "Total number of log entries rejected",
            ["token", "reason"]
        )
        
        self.batch_size_entries = Histogram(
            "ingestion_batch_size_entries",
            "Number of entries per ingestion batch",
            buckets=[1, 5, 10, 25, 50, 100, 250, 500]
        )
        
        # WAL metrics
        self.wal_segments_active = Gauge(
            "wal_segments_active",
            "Current number of active WAL segments",
            ["token"]
        )
        
        self.wal_segments_created_total = Counter(
            "wal_segments_created_total",
            "Total WAL segments created",
            ["token"]
        )
        
        self.wal_segments_forwarded_total = Counter(
            "wal_segments_forwarded_total", 
            "Total WAL segments successfully forwarded",
            ["token"]
        )
        
        self.wal_disk_usage_bytes = Gauge(
            "wal_disk_usage_bytes",
            "Current WAL disk usage in bytes",
            ["token"]
        )
        
        self.wal_segment_size_bytes = Histogram(
            "wal_segment_size_bytes",
            "WAL segment sizes in bytes",
            ["token"],
            buckets=[1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864, 134217728]  # 1KB to 128MB
        )
        
        # Masking metrics
        self.masking_operations_total = Counter(
            "masking_operations_total",
            "Total data masking operations",
            ["token", "field"]
        )
        
        self.masking_errors_total = Counter(
            "masking_errors_total",
            "Total masking errors",
            ["token"]
        )
        
        # Forwarder metrics
        self.loki_requests_total = Counter(
            "loki_requests_total",
            "Total requests to Loki",
            ["status_code"]
        )
        
        self.loki_request_duration = Histogram(
            "loki_request_duration_seconds",
            "Loki request duration in seconds",
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
        )
        
        self.loki_entries_forwarded_total = Counter(
            "loki_entries_forwarded_total",
            "Total log entries forwarded to Loki",
            ["token"]
        )
        
        self.loki_retries_total = Counter(
            "loki_retries_total",
            "Total Loki forwarding retries",
            ["token", "attempt"]
        )
        
        # System metrics
        self.current_connections = Gauge(
            "current_connections",
            "Current number of active connections"
        )
        
        self.uptime_seconds = Gauge(
            "uptime_seconds",
            "Service uptime in seconds"
        )
        
        # Track start time for uptime calculation
        self._start_time = time.time()
    
    def record_request(
        self, 
        method: str, 
        endpoint: str, 
        status_code: int,
        duration_seconds: float
    ) -> None:
        """Record HTTP request metrics."""
        self.requests_total.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code)
        ).inc()
        
        self.request_duration.labels(
            method=method,
            endpoint=endpoint
        ).observe(duration_seconds)
    
    def record_ingestion(
        self,
        token: str,
        entries_count: int,
        batch_size: int,
        rejected_count: int = 0,
        rejection_reason: Optional[str] = None
    ) -> None:
        """Record log ingestion metrics."""
        # Mask token for metrics (first 8 chars + ...)
        token_label = token[:8] + "..." if len(token) > 8 else token
        
        self.logs_ingested_total.labels(token=token_label).inc(entries_count)
        self.batch_size_entries.observe(batch_size)
        
        if rejected_count > 0 and rejection_reason:
            self.logs_rejected_total.labels(
                token=token_label,
                reason=rejection_reason
            ).inc(rejected_count)
    
    def record_masking(self, token: str, field: str, operation_count: int = 1) -> None:
        """Record data masking operations."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        self.masking_operations_total.labels(
            token=token_label,
            field=field
        ).inc(operation_count)
    
    def record_masking_error(self, token: str) -> None:
        """Record masking error."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        self.masking_errors_total.labels(token=token_label).inc()
    
    def update_wal_metrics(
        self,
        token: str,
        active_segments: int,
        disk_usage_bytes: int
    ) -> None:
        """Update WAL-related metrics."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        
        self.wal_segments_active.labels(token=token_label).set(active_segments)
        self.wal_disk_usage_bytes.labels(token=token_label).set(disk_usage_bytes)
    
    def record_wal_segment_created(self, token: str, size_bytes: int) -> None:
        """Record WAL segment creation."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        
        self.wal_segments_created_total.labels(token=token_label).inc()
        self.wal_segment_size_bytes.labels(token=token_label).observe(size_bytes)
    
    def record_wal_segment_forwarded(self, token: str) -> None:
        """Record successful WAL segment forwarding."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        self.wal_segments_forwarded_total.labels(token=token_label).inc()
    
    def record_loki_request(
        self,
        status_code: int,
        duration_seconds: float,
        entries_count: int,
        token: str
    ) -> None:
        """Record Loki forwarding request."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        
        self.loki_requests_total.labels(status_code=str(status_code)).inc()
        self.loki_request_duration.observe(duration_seconds)
        
        if 200 <= status_code < 300:
            self.loki_entries_forwarded_total.labels(token=token_label).inc(entries_count)
    
    def record_loki_retry(self, token: str, attempt: int) -> None:
        """Record Loki retry attempt."""
        token_label = token[:8] + "..." if len(token) > 8 else token
        self.loki_retries_total.labels(
            token=token_label,
            attempt=str(attempt)
        ).inc()
    
    def update_system_metrics(self, connections: int) -> None:
        """Update system-level metrics."""
        self.current_connections.set(connections)
        self.uptime_seconds.set(time.time() - self._start_time)
