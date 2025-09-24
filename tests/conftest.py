"""
Pytest configuration and shared fixtures.

Contains common test fixtures and setup for all test modules.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.logstack.main import app
from src.logstack.config import get_settings, reload_settings


@pytest.fixture
def test_config() -> Dict[str, Any]:
    """Test configuration data."""
    return {
        "server": {
            "host": "0.0.0.0",
            "port": 8080,
            "debug": True,
            "log_level": "DEBUG"
        },
        "security": {
            "rate_limit_rps": 5,
            "rate_limit_burst": 10,
            "admin_token": "test_admin_token_123456789abc",
            "api_keys": {
                "test_token_valid_123456789abc": {
                    "name": "test-service",
                    "active": True,
                    "description": "Test service token"
                },
                "test_token_inactive_123456789": {
                    "name": "inactive-service", 
                    "active": False,
                    "description": "Inactive test token"
                },
                "test_admin_token_123456789abc": {
                    "name": "admin",
                    "active": True,
                    "description": "Admin test token"
                }
            }
        },
        "masking": {
            "baseline_keys": ["password", "token", "api_key", "secret", "email"],
            "partial_rules": {
                "authorization": {"keep_prefix": 5},
                "email": {"mask_email": True}
            },
            "tenant_overrides": {}
        },
        "wal": {
            "root_path": "./test_wal",
            "segment_max_bytes": 1048576,  # 1MB for testing
            "rotation_time_active_minutes": 1,  # Fast rotation for testing
            "rotation_time_idle_hours": 1,
            "idle_threshold_minutes": 2,
            "min_rotation_bytes": 1024,  # 1KB for testing
            "force_rotation_hours": 1
        }
    }


@pytest.fixture
def temp_wal_dir() -> Generator[Path, None, None]:
    """Create temporary WAL directory for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def test_client(test_config: Dict[str, Any], temp_wal_dir: Path) -> Generator[TestClient, None, None]:
    """FastAPI test client with test configuration."""
    # Clear Prometheus registry to avoid duplicates
    from prometheus_client import REGISTRY
    REGISTRY._collector_to_names.clear()
    REGISTRY._names_to_collectors.clear()
    
    # Clear rate limiter state to ensure test isolation
    import src.logstack.core.auth as auth_module
    auth_module._rate_limiter = None
    
    # Mock the config to use test values
    with patch('src.logstack.config.load_config_file') as mock_load:
        # Update WAL path to use temp directory
        test_config["wal"]["root_path"] = str(temp_wal_dir)
        mock_load.return_value = test_config
        
        # Reload settings to pick up test config
        reload_settings()
        
        # Create test client
        with TestClient(app) as client:
            yield client


@pytest.fixture
def valid_log_entry() -> Dict[str, Any]:
    """Sample valid log entry for testing."""
    return {
        "timestamp": "2025-09-22T10:30:00.000Z",
        "level": "INFO",
        "message": "Test log message",
        "service": "test-service",
        "env": "test",
        "metadata": {
            "user_id": "12345",
            "action": "login"
        }
    }


@pytest.fixture  
def sensitive_log_entry() -> Dict[str, Any]:
    """Log entry with sensitive data for masking tests."""
    return {
        "timestamp": "2025-09-22T10:30:00.000Z",
        "level": "ERROR", 
        "message": "Authentication failed",
        "service": "auth-service",
        "env": "prod",
        "metadata": {
            "user_email": "john.doe@example.com",
            "password": "super_secret_password",
            "api_key": "sk_live_dangerous_key",
            "authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "normal_field": "this should not be masked"
        }
    }


@pytest.fixture
def invalid_log_entry() -> Dict[str, Any]:
    """Invalid log entry for validation testing."""
    return {
        "timestamp": "invalid-timestamp",
        "level": "INVALID_LEVEL",
        "message": "",  # Empty message
        "service": "",  # Empty service
        "env": ""       # Empty env
    }

