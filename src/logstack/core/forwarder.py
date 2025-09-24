"""
Async forwarder for sending WAL segments to Grafana Loki.

Features:
- Reads ready WAL segments
- Batches entries for efficient forwarding
- Retry logic with exponential backoff
- Deletes segments on successful forwarding
"""

import asyncio
import json
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

from ..config import LokiSettings, get_settings
from .wal import WALManager, get_wal_manager

logger = structlog.get_logger(__name__)


@dataclass
class ForwardingResult:
    """Result of forwarding operation."""
    success: bool
    entries_forwarded: int
    segments_processed: int
    error_message: Optional[str] = None


class LokiForwarder:
    """
    Async forwarder for sending WAL segments to Grafana Loki.
    
    Handles:
    - Reading WAL segments
    - Batching entries
    - Retry logic
    - Segment cleanup
    """
    
    def __init__(self, settings: LokiSettings, wal_manager: WALManager):
        self.settings = settings
        self.wal_manager = wal_manager
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False
        
        logger.info("Loki Forwarder initialized", loki_url=settings.push_url)
    
    async def start(self) -> None:
        """Start the forwarder service."""
        if self._running:
            return
            
        self._running = True
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.timeout_seconds)
        )
        
        logger.info("Loki Forwarder started")
    
    async def stop(self) -> None:
        """Stop the forwarder service."""
        self._running = False
        
        if self.session:
            await self.session.close()
            self.session = None
            
        logger.info("Loki Forwarder stopped")
    
    async def forward_ready_segments(self, token: Optional[str] = None) -> ForwardingResult:
        """
        Forward all ready segments to Loki.
        
        Args:
            token: Optional token to limit forwarding to specific token
            
        Returns:
            ForwardingResult with success status and metrics
        """
        if not self.session:
            return ForwardingResult(
                success=False,
                entries_forwarded=0,
                segments_processed=0,
                error_message="Forwarder not started"
            )
        
        try:
            # Get ready segments
            ready_segments = self.wal_manager.get_ready_segments(token)
            
            if not ready_segments:
                logger.debug("No ready segments to forward")
                return ForwardingResult(
                    success=True,
                    entries_forwarded=0,
                    segments_processed=0
                )
            
            logger.info(
                "Starting forward operation",
                segments_count=len(ready_segments),
                token=token[:8] + "..." if token else "all"
            )
            
            total_entries = 0
            processed_segments = 0
            
            # Process segments in batches
            for segment in ready_segments:
                try:
                    entries = await self._read_segment_entries(segment.path)
                    if not entries:
                        logger.warning("Empty segment, skipping", segment_path=str(segment.path))
                        continue
                    
                    # Forward entries to Loki
                    success = await self._forward_entries_to_loki(entries)
                    
                    if success:
                        # Delete segment on success
                        self.wal_manager.delete_segment(segment.path)
                        total_entries += len(entries)
                        processed_segments += 1
                        
                        logger.debug(
                            "Segment forwarded successfully",
                            segment_path=str(segment.path),
                            entries_count=len(entries)
                        )
                    else:
                        logger.error(
                            "Failed to forward segment",
                            segment_path=str(segment.path),
                            entries_count=len(entries)
                        )
                        
                except Exception as e:
                    logger.error(
                        "Error processing segment",
                        segment_path=str(segment.path),
                        error=str(e)
                    )
                    continue
            
            logger.info(
                "Forward operation completed",
                entries_forwarded=total_entries,
                segments_processed=processed_segments,
                success_rate=f"{processed_segments}/{len(ready_segments)}"
            )
            
            return ForwardingResult(
                success=processed_segments > 0,
                entries_forwarded=total_entries,
                segments_processed=processed_segments
            )
            
        except Exception as e:
            logger.error("Forward operation failed", error=str(e))
            return ForwardingResult(
                success=False,
                entries_forwarded=0,
                segments_processed=0,
                error_message=str(e)
            )
    
    async def _read_segment_entries(self, segment_path: Path) -> List[Dict[str, Any]]:
        """
        Read entries from a WAL segment file.
        
        Format: [4 bytes: length][entry data][4 bytes: checksum]
        """
        entries = []
        
        try:
            with open(segment_path, 'rb') as f:
                while True:
                    # Read length prefix
                    length_bytes = f.read(4)
                    if not length_bytes:
                        break
                    
                    length = struct.unpack('<I', length_bytes)[0]
                    
                    # Read entry data
                    entry_data = f.read(length)
                    if len(entry_data) != length:
                        logger.warning("Incomplete entry data", segment_path=str(segment_path))
                        break
                    
                    # Read checksum
                    checksum_bytes = f.read(4)
                    if len(checksum_bytes) != 4:
                        logger.warning("Missing checksum", segment_path=str(segment_path))
                        break
                    
                    checksum = struct.unpack('<I', checksum_bytes)[0]
                    
                    # Verify checksum
                    calculated_checksum = zlib.crc32(entry_data)
                    if checksum != calculated_checksum:
                        logger.error(
                            "Checksum mismatch",
                            segment_path=str(segment_path),
                            expected=checksum,
                            calculated=calculated_checksum
                        )
                        continue
                    
                    # Parse entry
                    try:
                        entry = json.loads(entry_data.decode('utf-8'))
                        entries.append(entry)
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Failed to parse entry JSON",
                            segment_path=str(segment_path),
                            error=str(e)
                        )
                        continue
                        
        except Exception as e:
            logger.error("Error reading segment", segment_path=str(segment_path), error=str(e))
            raise
        
        return entries
    
    async def _forward_entries_to_loki(self, entries: List[Dict[str, Any]]) -> bool:
        """
        Forward entries to Loki with retry logic.
        
        Returns:
            True if successful, False otherwise
        """
        if not entries:
            return True
        
        # Convert entries to Loki format
        loki_streams = self._convert_to_loki_format(entries)
        
        # Retry logic
        for attempt in range(self.settings.max_retries + 1):
            try:
                success = await self._send_to_loki(loki_streams)
                if success:
                    return True
                    
            except Exception as e:
                logger.warning(
                    "Loki forward attempt failed",
                    attempt=attempt + 1,
                    max_retries=self.settings.max_retries,
                    error=str(e)
                )
                
                if attempt < self.settings.max_retries:
                    # Exponential backoff
                    backoff_seconds = self.settings.backoff_seconds[min(attempt, len(self.settings.backoff_seconds) - 1)]
                    await asyncio.sleep(backoff_seconds)
                else:
                    # Park after max retries
                    logger.error("Max retries exceeded, parking", park_seconds=self.settings.backoff_park_seconds)
                    await asyncio.sleep(self.settings.backoff_park_seconds)
        
        return False
    
    def _convert_to_loki_format(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert log entries to Loki push format.
        
        Loki expects:
        {
            "streams": [
                {
                    "stream": {"label1": "value1", "label2": "value2"},
                    "values": [["timestamp_ns", "log_line"], ...]
                }
            ]
        }
        """
        # Group entries by labels (stream)
        streams: Dict[str, Dict[str, Any]] = {}
        
        for entry in entries:
            # Extract labels
            labels = {
                "service": entry.get("service", "unknown"),
                "env": entry.get("env", "unknown"),
                "level": entry.get("level", "unknown")
            }
            
            # Add additional labels if present
            if entry.get("labels"):
                labels.update(entry["labels"])
            
            # Create stream key
            stream_key = "|".join(f"{k}={v}" for k, v in sorted(labels.items()))
            
            if stream_key not in streams:
                streams[stream_key] = {
                    "stream": labels,
                    "values": []
                }
            
            # Convert timestamp to nanoseconds
            timestamp = entry.get("timestamp", "")
            if isinstance(timestamp, str):
                # Parse ISO timestamp and convert to nanoseconds
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    timestamp_ns = str(int(dt.timestamp() * 1_000_000_000))
                except:
                    timestamp_ns = str(int(time.time() * 1_000_000_000))
            elif isinstance(timestamp, (int, float)):
                timestamp_ns = str(int(timestamp * 1_000_000_000))
            else:
                timestamp_ns = str(int(time.time() * 1_000_000_000))
            
            # Create log line
            log_line = json.dumps({
                "message": entry.get("message", ""),
                "metadata": entry.get("metadata", {}),
                "trace_id": entry.get("trace_id"),
                "span_id": entry.get("span_id")
            })
            
            streams[stream_key]["values"].append([timestamp_ns, log_line])
        
        return list(streams.values())
    
    async def _send_to_loki(self, streams: List[Dict[str, Any]]) -> bool:
        """Send streams to Loki."""
        payload = {"streams": streams}
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "logstack-forwarder/1.0"
        }
        
        if not self.session:
            return False
            
        async with self.session.post(
            self.settings.push_url,
            json=payload,
            headers=headers
        ) as response:
            if response.status == 204:
                logger.debug("Successfully sent to Loki", streams_count=len(streams))
                return True
            else:
                error_text = await response.text()
                logger.error(
                    "Loki returned error",
                    status=response.status,
                    error=error_text
                )
                return False


# Global forwarder instance
_forwarder: Optional[LokiForwarder] = None


def get_forwarder() -> LokiForwarder:
    """Get or create global forwarder instance."""
    global _forwarder
    
    if _forwarder is None:
        settings = get_settings()
        wal_manager = get_wal_manager()
        _forwarder = LokiForwarder(settings.loki, wal_manager)
    
    return _forwarder