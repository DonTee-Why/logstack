"""
Write-Ahead Log (WAL) system implementation.

Per-token WAL with adaptive segment rotation.
"""

import hashlib
import re
import json
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from aiofiles import open as aio_open

from ..config import WALSettings, get_settings

logger = structlog.get_logger(__name__)


@dataclass
class WALEntryMetadata:
    """Metadata for each WAL entry."""
    ingest_timestamp: float
    entry_size: int
    checksum: int
    sequence_number: int


@dataclass
class SegmentInfo:
    """Information about a WAL segment."""
    path: Path
    size_bytes: int
    creation_time: float
    last_write_time: float
    entry_count: int
    is_ready: bool


class WALManager:
    """
    Write-Ahead Log manager with per-token isolation and adaptive rotation.
    
    Features:
    - Per-token directory isolation
    - Binary segment format with checksums
    - Adaptive rotation based on ADR-002
    - Async file operations
    """
    
    def __init__(self, settings: WALSettings):
        self.settings = settings
        self.wal_root = settings.wal_root_path
        self._sequence_counters: Dict[str, int] = {}
        
        # Ensure WAL root exists
        self._ensure_wal_root()
        logger.info("WAL Manager initialized", wal_root=str(self.wal_root))
    
    def _ensure_wal_root(self) -> None:
        """Create WAL root directory if it doesn't exist."""
        try:
            self.wal_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Error creating WAL root directory", error=str(e))
            raise Exception("Error creating WAL root directory")
    
    def _sanitize_token(self, token: str) -> str:
        """
        Sanitize token for filesystem safety using hybrid approach.
        
        Format: {safe_prefix}_{hash_suffix}
        Example: logstack_1a2b3c4d_a1b2c3d4
        """

        safe_prefix = re.sub(r'[^a-zA-Z0-9_-]', '', token)
        safe_prefix = safe_prefix[:20]
        
        hash_suffix = hashlib.sha256(token.encode()).hexdigest()[:8]
        
        return f"{safe_prefix}_{hash_suffix}"
    
    def _ensure_token_directory(self, token: str) -> Path:
        """Create per-token directory if it doesn't exist."""

        sanitized_token = self._sanitize_token(token)

        token_dir = self.wal_root / sanitized_token
        token_dir.mkdir(parents=True, exist_ok=True)

        return token_dir
    
    def _get_current_segment_path(self, token_dir: Path) -> Path:
        """Get path for current active segment."""
        # TODO: Implement segment path generation
        # - Find highest numbered segment
        segment_files = sorted(token_dir.glob('segment_*.wal'), key=lambda x: int(x.stem.split('_')[-1]))
        if not segment_files:
            return token_dir / 'segment_001.wal'
        current_segment = segment_files[-1]
        current_size = current_segment.stat().st_size
        
        if current_size >= self.settings.segment_max_bytes:
            return token_dir / f'segment_{len(segment_files) + 1:03d}.wal'
        return current_segment

    def _should_rotate_segment(self, segment_path: Path) -> bool|None:
        """
        Check if segment should be rotated based on ADR-002 rules.
        
        Rules:
        - Size >= 128MB (always rotate)
        - Active (last write < 10min) + age >= 5min + size >= 64KB
        - Idle (last write >= 10min) + age >= 1hr
        - Force rotation after 6 hours
        """
        # - Get segment stats (size, creation time, last write time)
        segment_stats = segment_path.stat()
        current_size = segment_stats.st_size
        creation_time = segment_stats.st_ctime
        last_write_time = segment_stats.st_mtime
        age_seconds = time.time() - creation_time
        seconds_since_last_write = time.time() - last_write_time
        is_active = seconds_since_last_write < self.settings.idle_threshold_minutes * 60
        # - Apply rotation rules
        if current_size >= self.settings.segment_max_bytes:
            return True
        if is_active and age_seconds >= self.settings.rotation_time_active_minutes * 60 and current_size >= self.settings.min_rotation_bytes:
            return True
        if not is_active and age_seconds >= self.settings.rotation_time_idle_hours * 3600:
            return True
        if age_seconds >= self.settings.force_rotation_hours * 3600:
            return True
        return False
    
    async def _rotate_segment(self, token_dir: Path) -> None:
        """Rotate current segment to make it ready for forwarding."""
        current_segment = self._get_current_segment_path(token_dir)
        next_number = len(list(token_dir.glob('segment_*.wal'))) + 1

        current_segment.rename(current_segment.with_suffix('.ready'))

        new_segment = token_dir / f'segment_{next_number:03d}.wal'
        new_segment.touch()

    async def _write_entry_to_segment(self, segment_path: Path, entry_data: bytes, metadata: WALEntryMetadata) -> None:
        """
        Write single entry to segment file in binary format.
        Format: [4 bytes: length][entry data][4 bytes: checksum]
        """
        checksum = zlib.crc32(entry_data)
        length_prefix = struct.pack('<I', len(entry_data))
        checksum_bytes = struct.pack('<I', checksum)
        async with aio_open(segment_path, 'ab') as f:
            await f.write(length_prefix)
            await f.write(entry_data)
            await f.write(checksum_bytes)

    async def append(self, token: str, entries: List[Dict[str, Any]]) -> None:
        """
        Append log entries to WAL for given token.
        
        Main entry point for WAL writes.
        """
        token_dir = self._ensure_token_directory(token)
        current_segment = self._get_current_segment_path(token_dir)
        
        if self._should_rotate_segment(current_segment):
            await self._rotate_segment(token_dir)
            current_segment = self._get_current_segment_path(token_dir)

        for index, entry in enumerate(entries):
            entry_in_json = json.dumps(entry).encode('utf-8')
            metadata = WALEntryMetadata(
                ingest_timestamp=entry['timestamp'],
                entry_size=len(entry_in_json),
                checksum=zlib.crc32(entry_in_json),
                sequence_number=index + 1
            )
            await self._write_entry_to_segment(current_segment, entry_in_json, metadata)
        # - Update metrics (To be added later)

    def get_ready_segments(self, token: Optional[str] = None) -> List[SegmentInfo]:
        """Get segments ready for forwarding to Loki."""
        if token:
            return self._scan_for_ready_segments(self.wal_root / token)
        else:
            segments: List[SegmentInfo] = []
            for token_dir in self.wal_root.glob('*'):
                if token_dir.is_dir():
                    segments.extend(self._scan_for_ready_segments(token_dir))
            return segments

    def _scan_for_ready_segments(self, token_dir: Path) -> List[SegmentInfo]:
        """Scan for ready segments in a token directory."""
        segments: List[SegmentInfo] = []
        ready_files = token_dir.glob('segment_*.ready')

        for ready_file in ready_files:
            segments.append(SegmentInfo(
                path=ready_file,
                size_bytes=ready_file.stat().st_size,
                creation_time=ready_file.stat().st_ctime,
                last_write_time=ready_file.stat().st_mtime,
                entry_count=0,
                is_ready=True
            ))
        return segments

    def delete_segment(self, segment_path: Path) -> None:
        """Delete segment after successful forwarding."""
        if not segment_path.exists():
            return
        try:
            segment_path.unlink()
        except Exception as e:
            logger.error("Error deleting segment", segment_path=str(segment_path), error=str(e))
        logger.info("Deleted segment", segment_path=str(segment_path))

    def get_token_stats(self, token: str) -> Dict[str, Any]|None:
        """Get WAL statistics for a token."""
        token_dir = self._ensure_token_directory(token)
        active_segments = len(list(token_dir.glob('segment_*.wal')))
        ready_segments = len(list(token_dir.glob('segment_*.ready')))
        total_disk_usage = sum(segment.size_bytes for segment in self.get_ready_segments(token))

        return {
            "active_segments": active_segments,
            "ready_segments": ready_segments,
            "total_disk_usage": total_disk_usage
        }


# Global WAL manager instance
_wal_manager: Optional[WALManager] = None


def get_wal_manager() -> WALManager:
    """Get or create global WAL manager instance."""
    global _wal_manager
    
    if _wal_manager is None:
        settings = get_settings()
        _wal_manager = WALManager(settings.wal)
    
    return _wal_manager
