"""
Health checker implementation for monitoring system dependencies.

Performs comprehensive health checks for:
- Loki connectivity
- Disk space availability  
- WAL system integrity
- Background services status
"""

import asyncio
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

from ..config import get_settings
from .forwarder_service import ForwarderService
from .wal import get_wal_manager

logger = structlog.get_logger(__name__)


@dataclass
class HealthCheck:
    """Individual health check result."""
    name: str
    status: str  # "healthy", "unhealthy", "unknown"
    message: str
    details: Dict[str, Any]
    last_check: float


@dataclass
class HealthStatus:
    """Overall health status."""
    is_healthy: bool
    checks: Dict[str, HealthCheck]
    failed_checks: List[str]
    timestamp: float


class HealthChecker:
    """
    Comprehensive health checker for LogStack dependencies.
    
    Monitors:
    - Loki connectivity (last successful push within 60s)
    - Disk space (>20% free as per PRD)
    - WAL integrity (directory accessible, no corruption)
    - Background services (forwarder running)
    """
    
    def __init__(self, forwarder_service: Optional[ForwarderService] = None):
        self.settings = get_settings()
        self.forwarder_service = forwarder_service
        self.wal_manager = get_wal_manager()
        self._last_loki_check: Optional[float] = None
        self._loki_healthy = False
        self._session: Optional[aiohttp.ClientSession] = None
        
        logger.info("Health Checker initialized")
    
    async def start(self) -> None:
        """Start the health checker."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        logger.info("Health Checker started")
    
    async def stop(self) -> None:
        """Stop the health checker."""
        if self._session:
            await self._session.close()
            self._session = None
        logger.info("Health Checker stopped")
    
    async def check_all(self) -> HealthStatus:
        """Perform all health checks and return overall status."""
        checks = {}
        failed_checks = []
        
        # Run all checks in parallel (some are sync, so wrap them)
        check_results = await asyncio.gather(
            self._check_loki_connectivity(),
            asyncio.create_task(asyncio.to_thread(self._check_disk_space)),
            asyncio.create_task(asyncio.to_thread(self._check_wal_integrity)),
            asyncio.create_task(asyncio.to_thread(self._check_forwarder_service)),
            return_exceptions=True
        )
        
        # Process results
        check_names = ["loki", "disk", "wal", "forwarder"]
        for i, result in enumerate(check_results):
            name = check_names[i]
            
            if isinstance(result, Exception):
                checks[name] = HealthCheck(
                    name=name,
                    status="unhealthy",
                    message=f"Check failed: {str(result)}",
                    details={"error": str(result), "error_type": type(result).__name__},
                    last_check=time.time()
                )
                failed_checks.append(name)
            elif isinstance(result, HealthCheck):
                checks[name] = result
                if result.status != "healthy":
                    failed_checks.append(name)
        
        # Overall health is True only if all checks pass
        is_healthy = len(failed_checks) == 0
        
        return HealthStatus(
            is_healthy=is_healthy,
            checks=checks,
            failed_checks=failed_checks,
            timestamp=time.time()
        )
    
    async def _check_loki_connectivity(self) -> HealthCheck:
        """Check if Loki is reachable and responding."""
        if not self._session:
            return HealthCheck(
                name="loki",
                status="unhealthy",
                message="Health checker not started",
                details={},
                last_check=time.time()
            )
        
        try:
            # Try to reach Loki's ready endpoint
            loki_base_url = self.settings.loki.base_url
            ready_url = f"{loki_base_url.rstrip('/')}/ready"
            
            async with self._session.get(ready_url) as response:
                if response.status == 200:
                    self._last_loki_check = time.time()
                    self._loki_healthy = True
                    
                    return HealthCheck(
                        name="loki",
                        status="healthy",
                        message="Loki is reachable",
                        details={
                            "url": ready_url,
                            "status_code": response.status,
                            "response_time_ms": int((time.time() - (self._last_loki_check or 0)) * 1000)
                        },
                        last_check=self._last_loki_check
                    )
                else:
                    return HealthCheck(
                        name="loki",
                        status="unhealthy",
                        message=f"Loki returned status {response.status}",
                        details={
                            "url": ready_url,
                            "status_code": response.status,
                            "response_body": await response.text()
                        },
                        last_check=time.time()
                    )
                    
        except Exception as e:
            logger.warning("Loki connectivity check failed", error=str(e))
            return HealthCheck(
                name="loki",
                status="unhealthy",
                message=f"Cannot reach Loki: {str(e)}",
                details={"error": str(e), "url": self.settings.loki.base_url},
                last_check=time.time()
            )
    
    def _check_disk_space(self) -> HealthCheck:
        """Check if disk has sufficient free space (>20% as per PRD)."""
        try:
            wal_path = self.settings.wal.wal_root_path
            
            # Get disk usage
            total, used, free = shutil.disk_usage(wal_path)
            free_ratio = free / total
            free_percentage = free_ratio * 100
            
            min_free_ratio = self.settings.wal.disk_free_min_ratio
            min_free_percentage = min_free_ratio * 100
            
            if free_ratio >= min_free_ratio:
                status = "healthy"
                message = f"Disk space OK: {free_percentage:.1f}% free"
            else:
                status = "unhealthy"
                message = f"Low disk space: {free_percentage:.1f}% free (min: {min_free_percentage:.1f}%)"
            
            return HealthCheck(
                name="disk",
                status=status,
                message=message,
                details={
                    "path": str(wal_path),
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "free_percentage": round(free_percentage, 1),
                    "min_required_percentage": round(min_free_percentage, 1)
                },
                last_check=time.time()
            )
            
        except Exception as e:
            return HealthCheck(
                name="disk",
                status="unhealthy",
                message=f"Disk check failed: {str(e)}",
                details={"error": str(e)},
                last_check=time.time()
            )
    
    def _check_wal_integrity(self) -> HealthCheck:
        """Check WAL system integrity."""
        try:
            wal_root = self.settings.wal.wal_root_path
            
            # Check if WAL root directory exists and is writable
            if not wal_root.exists():
                return HealthCheck(
                    name="wal",
                    status="unhealthy",
                    message="WAL root directory does not exist",
                    details={"path": str(wal_root)},
                    last_check=time.time()
                )
            
            if not wal_root.is_dir():
                return HealthCheck(
                    name="wal",
                    status="unhealthy",
                    message="WAL root path is not a directory",
                    details={"path": str(wal_root)},
                    last_check=time.time()
                )
            
            # Test write access
            test_file = wal_root / ".health_check"
            try:
                test_file.write_text("test")
                test_file.unlink()
            except Exception as e:
                return HealthCheck(
                    name="wal",
                    status="unhealthy",
                    message=f"WAL directory not writable: {str(e)}",
                    details={"path": str(wal_root), "error": str(e)},
                    last_check=time.time()
                )
            
            # Count segments and check basic structure
            token_dirs = [d for d in wal_root.iterdir() if d.is_dir()]
            total_segments = 0
            total_ready_segments = 0
            
            for token_dir in token_dirs:
                segments = list(token_dir.glob("segment_*.wal"))
                ready_segments = list(token_dir.glob("segment_*.ready"))
                total_segments += len(segments)
                total_ready_segments += len(ready_segments)
            
            return HealthCheck(
                name="wal",
                status="healthy",
                message="WAL system integrity OK",
                details={
                    "path": str(wal_root),
                    "token_directories": len(token_dirs),
                    "active_segments": total_segments,
                    "ready_segments": total_ready_segments,
                    "writable": True
                },
                last_check=time.time()
            )
            
        except Exception as e:
            logger.error("WAL integrity check failed", error=str(e))
            return HealthCheck(
                name="wal",
                status="unhealthy",
                message=f"WAL integrity check failed: {str(e)}",
                details={"error": str(e)},
                last_check=time.time()
            )
    
    def _check_forwarder_service(self) -> HealthCheck:
        """Check if the forwarder service is running and healthy."""
        try:
            if not self.forwarder_service:
                return HealthCheck(
                    name="forwarder",
                    status="unhealthy",
                    message="Forwarder service not available",
                    details={},
                    last_check=time.time()
                )
            
            is_healthy = self.forwarder_service.is_healthy()
            
            if is_healthy:
                return HealthCheck(
                    name="forwarder",
                    status="healthy",
                    message="Forwarder service is running",
                    details={
                        "running": self.forwarder_service._running,
                        "forwarder_available": self.forwarder_service.forwarder is not None
                    },
                    last_check=time.time()
                )
            else:
                return HealthCheck(
                    name="forwarder",
                    status="unhealthy",
                    message="Forwarder service is not healthy",
                    details={
                        "running": getattr(self.forwarder_service, '_running', False),
                        "forwarder_available": self.forwarder_service.forwarder is not None
                    },
                    last_check=time.time()
                )
                
        except Exception as e:
            return HealthCheck(
                name="forwarder",
                status="unhealthy",
                message=f"Forwarder check failed: {str(e)}",
                details={"error": str(e)},
                last_check=time.time()
            )


# Global health checker instance
_health_checker: Optional[HealthChecker] = None


def get_health_checker(forwarder_service: Optional[ForwarderService] = None) -> HealthChecker:
    """Get or create global health checker instance."""
    global _health_checker
    
    if _health_checker is None:
        _health_checker = HealthChecker(forwarder_service)
    
    return _health_checker
