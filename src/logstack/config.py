"""
Configuration management with hot-reload capability.

Uses Pydantic Settings for environment variable handling and validation.
"""

import os
import yaml
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


def load_config_file(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        # Look for config.yaml in common locations
        possible_paths = [
            "config.yaml",  # Current directory
            "../../config.yaml",  # Project root from src/logstack
            "../../../config.yaml",  # In case we're deeper
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                config_path = path
                break
        else:
            return {}
    
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f) or {}
            return config_data
    return {}


class SecuritySettings(BaseSettings):
    """Security-related configuration."""
    
    rate_limit_rps: int = Field(default=2000, description="Rate limit requests per second per token")
    rate_limit_burst: int = Field(default=10000, description="Rate limit burst capacity per token") 
    admin_token: str = Field(default="", description="Admin token for flush endpoint")
    api_keys: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Valid API keys with metadata")
    @field_validator("api_keys", mode="before")
    def parse_api_keys(cls, v: Any) -> Dict[str, Dict[str, Any]]:
        """Parse API keys from JSON string if needed."""
        if isinstance(v, str):
            import json
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
                return {}
            except json.JSONDecodeError:
                return {}
        if isinstance(v, dict):
            return v
        return {}
    
    class Config:
        env_prefix = "LOGSTACK_SECURITY_"


class MaskingSettings(BaseSettings):
    """Data masking configuration."""
    
    baseline_keys: List[str] = Field(
        default=["password", "token", "authorization", "api_key", "secret", "card_number"],
        description="Global baseline keys to always mask"
    )
    partial_rules: Dict[str, Dict[str, Any]] = Field(
        default={"authorization": {"keep_prefix": 5}},
        description="Partial masking rules for specific keys"
    )
    tenant_overrides: Dict[str, List[str]] = Field(
        default={},
        description="Per-tenant additional masking keys"
    )
    
    class Config:
        env_prefix = "LOGSTACK_MASKING_"


class WALSettings(BaseSettings):
    """Write-Ahead Log configuration."""
    
    # Storage paths
    wal_root_path: Path = Field(default=Path("./wal"), description="Root directory for WAL storage")
    
    # Segment management
    segment_max_bytes: int = Field(default=134217728, description="Maximum segment size (128MB)")
    rotation_time_active_minutes: int = Field(default=5, description="Active segment rotation time")
    rotation_time_idle_hours: int = Field(default=1, description="Idle segment rotation time")
    idle_threshold_minutes: int = Field(default=10, description="Minutes to consider segment idle")
    min_rotation_bytes: int = Field(default=65536, description="Minimum size for time-based rotation (64KB)")
    force_rotation_hours: int = Field(default=6, description="Force rotation after hours")
    
    # Quotas
    token_wal_quota_bytes: int = Field(default=2147483648, description="Per-token WAL quota (2GB)")
    token_wal_quota_age_hours: int = Field(default=24, description="Per-token WAL age quota")
    disk_free_min_ratio: float = Field(default=0.20, description="Minimum disk free ratio")
    
    # Manual flush
    flush_endpoint_enabled: bool = Field(default=True, description="Enable manual flush endpoint")
    
    @field_validator("wal_root_path", mode="before")
    def validate_wal_path(cls, v: Path) -> Path:
        """Ensure WAL directory exists."""
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    class Config:
        env_prefix = "LOGSTACK_WAL_"


class LokiSettings(BaseSettings):
    """Grafana Loki configuration."""
    
    base_url: str = Field(default="http://localhost:3100", description="Loki base URL")
    push_endpoint: str = Field(default="/loki/api/v1/push", description="Loki push endpoint")
    timeout_seconds: int = Field(default=30, description="Request timeout")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    backoff_seconds: List[int] = Field(default=[5, 10, 20], description="Backoff intervals")
    backoff_park_seconds: int = Field(default=60, description="Park time after max retries")
    batch_max_entries: int = Field(default=1000, description="Maximum entries per batch")
    batch_max_bytes: int = Field(default=1048576, description="Maximum batch size (1MB)")
    
    @property
    def push_url(self) -> str:
        """Full Loki push URL."""
        return f"{self.base_url.rstrip('/')}{self.push_endpoint}"
    
    class Config:
        env_prefix = "LOGSTACK_LOKI_"


class ValidationSettings(BaseSettings):
    """Request validation configuration."""
    
    entry_bytes_max: int = Field(default=32768, description="Maximum entry size (32KB)")
    batch_entries_max: int = Field(default=500, description="Maximum entries per batch")
    batch_bytes_max: int = Field(default=1048576, description="Maximum batch size (1MB)")
    allowed_labels: List[str] = Field(
        default=["service", "env", "level", "schema_version", "region", "tenant"],
        description="Allowed label keys"
    )
    max_labels: int = Field(default=6, description="Maximum number of labels")
    max_label_value_length: int = Field(default=64, description="Maximum label value length")
    
    class Config:
        env_prefix = "LOGSTACK_VALIDATION_"


class Settings(BaseSettings):
    """Main application settings."""
    
    # Server configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8080, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="DEBUG", description="Log level")
    
    # Component settings
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    masking: MaskingSettings = Field(default_factory=MaskingSettings)
    wal: WALSettings = Field(default_factory=WALSettings)
    loki: LokiSettings = Field(default_factory=LokiSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    
    class Config:
        env_prefix = "LOGSTACK_"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance with config file and env support."""
    
    # Load config file data
    config_data = load_config_file()
    
    # Set environment variables from config file if they don't exist
    # This allows config file to provide defaults, env vars to override
    if config_data:
        _set_env_from_config(config_data)
    
    # Let Pydantic Settings handle the rest (env vars override config file)
    settings = Settings()
    return settings


def _set_env_from_config(config_data: Dict[str, Any]) -> None:
    """Set environment variables from config file if not already set."""
    mappings = {
        ("server", "host"): "LOGSTACK_HOST",
        ("server", "port"): "LOGSTACK_PORT", 
        ("server", "debug"): "LOGSTACK_DEBUG",
        ("server", "log_level"): "LOGSTACK_LOG_LEVEL",
        ("security", "rate_limit_rps"): "LOGSTACK_SECURITY_RATE_LIMIT_RPS",
        ("security", "rate_limit_burst"): "LOGSTACK_SECURITY_RATE_LIMIT_BURST",
        ("security", "admin_token"): "LOGSTACK_SECURITY_ADMIN_TOKEN",
        ("loki", "base_url"): "LOGSTACK_LOKI_BASE_URL",
    }
    
    for (section, key), env_var in mappings.items():
        if env_var not in os.environ:
            value = config_data.get(section, {}).get(key)
            if value is not None:
                os.environ[env_var] = str(value)
    
    # Handle api_keys specially (convert dict to JSON string)
    if "LOGSTACK_SECURITY_API_KEYS" not in os.environ:
        api_keys = config_data.get("security", {}).get("api_keys")
        if api_keys:
            import json
            os.environ["LOGSTACK_SECURITY_API_KEYS"] = json.dumps(api_keys)
    
    # Handle masking settings
    if "LOGSTACK_MASKING_BASELINE_KEYS" not in os.environ:
        baseline_keys = config_data.get("masking", {}).get("baseline_keys")
        if baseline_keys:
            import json
            os.environ["LOGSTACK_MASKING_BASELINE_KEYS"] = json.dumps(baseline_keys)
    
    if "LOGSTACK_MASKING_PARTIAL_RULES" not in os.environ:
        partial_rules = config_data.get("masking", {}).get("partial_rules")
        if partial_rules:
            import json
            os.environ["LOGSTACK_MASKING_PARTIAL_RULES"] = json.dumps(partial_rules)
    
    if "LOGSTACK_MASKING_TENANT_OVERRIDES" not in os.environ:
        tenant_overrides = config_data.get("masking", {}).get("tenant_overrides")
        if tenant_overrides:
            import json
            os.environ["LOGSTACK_MASKING_TENANT_OVERRIDES"] = json.dumps(tenant_overrides)


def reload_settings() -> Settings:
    """Reload settings (clears cache)."""
    get_settings.cache_clear()
    return get_settings()
