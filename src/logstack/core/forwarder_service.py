"""
Background service for running the Loki forwarder.

Manages the forwarder lifecycle and provides health checks.
"""

import asyncio
from typing import Any, Dict, Optional

import structlog

from .forwarder import LokiForwarder, get_forwarder

logger = structlog.get_logger(__name__)


class ForwarderService:
    """
    Background service that runs the Loki forwarder.
    
    Features:
    - Automatic startup/shutdown
    - Periodic forwarding
    - Health monitoring
    """
    
    def __init__(self, forward_interval_seconds: int = 30):
        self.forward_interval = forward_interval_seconds
        self.forwarder: Optional[LokiForwarder] = None
        self._task: Optional[asyncio.Task[None]] = None
        self._running = False
        
        logger.info("Forwarder Service initialized", interval_seconds=forward_interval_seconds)
    
    async def start(self) -> None:
        """Start the forwarder service."""
        if self._running:
            return
        
        self.forwarder = get_forwarder()
        await self.forwarder.start()
        
        self._running = True
        self._task = asyncio.create_task(self._run_forwarder_loop())
        
        logger.info("Forwarder Service started")
    
    async def stop(self) -> None:
        """Stop the forwarder service."""
        if not self._running:
            return
        
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        if self.forwarder:
            await self.forwarder.stop()
        
        logger.info("Forwarder Service stopped")
    
    async def _run_forwarder_loop(self) -> None:
        """Main forwarder loop."""
        while self._running:
            try:
                # Forward ready segments
                if not self.forwarder:
                    continue
                result = await self.forwarder.forward_ready_segments()
                
                if result.success and result.entries_forwarded > 0:
                    logger.info(
                        "Forwarder cycle completed",
                        entries_forwarded=result.entries_forwarded,
                        segments_processed=result.segments_processed
                    )
                elif result.error_message:
                    logger.warning(
                        "Forwarder cycle failed",
                        error=result.error_message
                    )
                
                # Wait for next cycle
                await asyncio.sleep(self.forward_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Forwarder loop error", error=str(e))
                await asyncio.sleep(self.forward_interval)
    
    async def force_forward(self) -> Dict[str, Any]:
        """
        Force an immediate forward operation.
        
        Returns:
            dict with forward results
        """
        if not self.forwarder:
            return {"success": False, "error": "Forwarder not started"}
        
        try:
            result = await self.forwarder.forward_ready_segments()
            return {
                "success": result.success,
                "entries_forwarded": result.entries_forwarded,
                "segments_processed": result.segments_processed,
                "error": result.error_message
            }
        except Exception as e:
            logger.error("Force forward failed", error=str(e))
            return {"success": False, "error": str(e)}
    
    def is_healthy(self) -> bool:
        """Check if the forwarder service is healthy."""
        return self._running and self.forwarder is not None


# Global service instance
_forwarder_service: Optional[ForwarderService] = None


def get_forwarder_service() -> ForwarderService:
    """Get or create global forwarder service instance."""
    global _forwarder_service
    
    if _forwarder_service is None:
        _forwarder_service = ForwarderService()
    
    return _forwarder_service
