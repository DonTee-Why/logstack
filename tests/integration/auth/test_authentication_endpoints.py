"""
Integration tests for authentication through API endpoints.

Tests authentication using FastAPI TestClient.
"""

from typing import Dict, Any
import pytest
from fastapi.testclient import TestClient


class TestAuthenticationEndpoints:
    """Test authentication through API endpoints."""
    
    def test_valid_token_authentication(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test API endpoint with valid authentication."""
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_valid_123456789abc"}
        )
        
        # Verify 202 response
        assert response.status_code == 202
        
        # Check response format matches IngestResponse model
        response_data = response.json()
        assert "message" in response_data
        assert "entries_accepted" in response_data
        assert "request_id" in response_data
        assert "timestamp" in response_data
        
        # Verify "entries_accepted" field present and correct
        assert response_data["entries_accepted"] == 1
        assert "accepted for processing" in response_data["message"]
    
    def test_invalid_token_authentication(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test API endpoint with invalid authentication."""
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer invalid_token_123"}
        )
        
        # Verify 401 response
        assert response.status_code == 401
        
        # Check error format matches ErrorResponse model
        response_data = response.json()
        assert "error" in response_data
        assert "message" in response_data
        assert "details" in response_data
        
        # Verify error code = "authentication_error"
        assert response_data["error"] == "authentication_error"
        
        # Check message mentions "Invalid"
        assert "Invalid" in response_data["message"]
    
    def test_missing_authorization_header(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test API endpoint with missing authentication."""
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]}
            # No Authorization header
        )
        
        # Verify 403 response (FastAPI returns 403 for missing auth header)
        assert response.status_code == 403
        
        # Check error format (FastAPI default format for missing auth)
        response_data = response.json()
        assert "detail" in response_data
        
        # Check error contains "Missing" or "required" or authentication-related terms
        detail = response_data["detail"].lower()
        assert "not authenticated" in detail or "missing" in detail or "required" in detail
    
    def test_inactive_token_authentication(self, test_client: TestClient, valid_log_entry: Dict[str, Any]) -> None:
        """Test authentication with inactive token."""
        response = test_client.post(
            "/v1/logs:ingest",
            json={"entries": [valid_log_entry]},
            headers={"Authorization": "Bearer test_token_inactive_123456789"}
        )
        
        # Verify 401 response
        assert response.status_code == 401
        
        # Check error format
        response_data = response.json()
        assert "error" in response_data
        assert "message" in response_data
        assert "details" in response_data
        
        # Verify error code
        assert response_data["error"] == "authentication_error"
        
        # Check error mentions "inactive"
        assert "inactive" in response_data["message"].lower()
