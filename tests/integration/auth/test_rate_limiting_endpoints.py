"""
Integration tests for rate limiting through API endpoints.

Tests rate limiting using FastAPI TestClient.
"""

import time
from typing import List, Dict, Any

from fastapi.testclient import TestClient


class TestRateLimitingEndpoints:
    """Test rate limiting through API endpoints."""
    
    def test_rate_limit_burst_capacity(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test burst capacity allows initial requests through."""
        
        for _ in range(10):
            response = test_client.post(
                "/v1/logs:ingest",
                json={"entries": [valid_log_entry]},
                headers={"Authorization": "Bearer test_token_valid_123456789abc"}
            )
            assert response.status_code == 202
        
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        assert response.status_code == 429
    
    def test_rate_limit_recovery_over_time(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test rate limit recovery after time passes."""

        # - Exhaust rate limit (get 429 responses)
        for _ in range(11):
            response = test_client.post(
                "/v1/logs:ingest",
                json={"entries": [valid_log_entry]},
                headers={"Authorization": "Bearer test_token_valid_123456789abc"}
            )
            assert response.status_code == 429 if _ >= 10 else 202
        time.sleep(1)
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        assert response.status_code == 202
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        assert response.status_code == 202
    
    def test_per_token_rate_limit_isolation(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test rate limiting is isolated per token."""
        for _ in range(11):
            response = test_client.post(
                "/v1/logs:ingest",
                json={"entries": [valid_log_entry]},
                headers={"Authorization": "Bearer test_token_valid_123456789abc"}
            )
            assert response.status_code == 429 if _ >= 10 else 202
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_admin_token_123456789abc"}
        )
        assert response.status_code == 202
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        assert response.status_code == 429
    
    def test_retry_after_header(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test 429 responses include Retry-After header."""

        for _ in range(10):
            response = test_client.post(
                "/v1/logs:ingest",
                json={"entries": [valid_log_entry]},
                headers={"Authorization": "Bearer test_token_valid_123456789abc"}
            )
            assert response.status_code == 202 if _ < 10 else 429
        
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        assert response.status_code == 429
        
        assert "Retry-After" in response.headers
        retry_after_header = int(response.headers["Retry-After"])
        assert retry_after_header > 0
        assert retry_after_header < 10

        response_data = response.json()
        assert "details" in response_data
        assert "retry_after" in response_data["details"]
        assert response_data["details"]["retry_after"] is not None
        assert response_data["details"]["retry_after"] > 0
        assert response_data["details"]["retry_after"] < 10

        assert retry_after_header == response_data["details"]["retry_after"]
    
    def test_rate_limit_error_response_format(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test rate limit error response format."""

        for _ in range(10):
            response = test_client.post(
                "/v1/logs:ingest",
                json={"entries": [valid_log_entry]},
                headers={"Authorization": "Bearer test_token_valid_123456789abc"}
            )
            assert response.status_code == 202

        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        assert response.status_code == 429

        response_data = response.json()
        assert "error" in response_data
        assert "message" in response_data  
        assert "details" in response_data
        assert "retry_after" in response_data["details"]
        assert response_data["error"] == "rate_limit_exceeded"
        assert isinstance(response_data["details"]["retry_after"], int)
